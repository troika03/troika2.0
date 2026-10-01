"""Owner-scoped persistent workspace for hosted Troika tools."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Iterator


MAX_FILE_BYTES = 1024 * 1024
MAX_WORKSPACE_BYTES = 25 * 1024 * 1024
MAX_WORKSPACE_FILES = 2_000
MAX_LIST_RESULTS = 250
MAX_SEARCH_RESULTS = 50
_OWNER_ID = re.compile(r"^usr_[0-9a-f]{32}$")


class WorkspaceError(ValueError):
    """Safe user-facing workspace failure."""


@dataclass(frozen=True)
class WorkspaceEntry:
    path: str
    kind: str
    size: int
    modified_at: float

    def to_dict(self) -> dict[str, str | int | float]:
        return {
            "path": self.path,
            "kind": self.kind,
            "size": self.size,
            "modified_at": self.modified_at,
        }


class WorkspaceStore:
    """Filesystem workspace whose paths never escape one account bucket."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _clean_owner(user_id: str) -> str:
        value = str(user_id or "").strip()
        if not _OWNER_ID.fullmatch(value):
            raise WorkspaceError("invalid workspace owner")
        return value

    @classmethod
    def _bucket(cls, user_id: str) -> str:
        owner = cls._clean_owner(user_id)
        return sha256(owner.encode("utf-8")).hexdigest()[:32]

    def _owner_root(self, user_id: str, *, create: bool = True) -> Path:
        target = (self.root / self._bucket(user_id)).resolve()
        if self.root not in target.parents:
            raise WorkspaceError("workspace owner escaped storage root")
        if create:
            target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _clean_relative(value: str | None, *, allow_root: bool = True) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        if raw in {"", "."}:
            if allow_root:
                return ""
            raise WorkspaceError("path is required")
        if len(raw) > 512 or "\x00" in raw or re.match(r"^[A-Za-z]:", raw):
            raise WorkspaceError("invalid workspace path")
        path = PurePosixPath(raw)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise WorkspaceError("path must stay inside the private workspace")
        return path.as_posix()

    def _resolve(
        self,
        user_id: str,
        value: str | None,
        *,
        allow_root: bool = True,
    ) -> tuple[Path, str]:
        owner_root = self._owner_root(user_id)
        relative = self._clean_relative(value, allow_root=allow_root)
        target = (owner_root / relative).resolve(strict=False)
        if target != owner_root and owner_root not in target.parents:
            raise WorkspaceError("path must stay inside the private workspace")
        current = owner_root
        for part in PurePosixPath(relative).parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise WorkspaceError("symbolic links are not supported")
        return target, relative

    @staticmethod
    def _entry(owner_root: Path, target: Path) -> WorkspaceEntry:
        stat = target.stat()
        return WorkspaceEntry(
            path=target.relative_to(owner_root).as_posix() or ".",
            kind="folder" if target.is_dir() else "file",
            size=0 if target.is_dir() else stat.st_size,
            modified_at=stat.st_mtime,
        )

    def _iter_files(self, owner_root: Path) -> Iterator[Path]:
        count = 0
        for directory, names, filenames in os.walk(owner_root, followlinks=False):
            names[:] = sorted(
                name for name in names if not (Path(directory) / name).is_symlink()
            )
            for filename in sorted(filenames):
                target = Path(directory) / filename
                if target.is_symlink() or not target.is_file():
                    continue
                count += 1
                if count > MAX_WORKSPACE_FILES:
                    raise WorkspaceError("workspace contains too many files")
                yield target

    def _usage(self, user_id: str) -> tuple[int, int]:
        owner_root = self._owner_root(user_id)
        files = list(self._iter_files(owner_root))
        return len(files), sum(path.stat().st_size for path in files)

    def list(self, user_id: str, path: str = "") -> list[WorkspaceEntry]:
        owner_root = self._owner_root(user_id)
        target, _ = self._resolve(user_id, path)
        if not target.exists():
            raise WorkspaceError("path does not exist")
        if not target.is_dir():
            return [self._entry(owner_root, target)]
        entries = []
        for child in sorted(
            target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
        ):
            if child.is_symlink():
                continue
            entries.append(self._entry(owner_root, child))
            if len(entries) >= MAX_LIST_RESULTS:
                break
        return entries

    def stat(self, user_id: str, path: str) -> WorkspaceEntry:
        owner_root = self._owner_root(user_id)
        target, _ = self._resolve(user_id, path, allow_root=False)
        if not target.exists() or target.is_symlink():
            raise WorkspaceError("path does not exist")
        return self._entry(owner_root, target)

    def read_text(self, user_id: str, path: str) -> str:
        target, _ = self._resolve(user_id, path, allow_root=False)
        if not target.is_file() or target.is_symlink():
            raise WorkspaceError("file does not exist")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError("file exceeds the workspace read limit")
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError("only UTF-8 text files can be read") from exc

    def write_text(
        self,
        user_id: str,
        path: str,
        content: str,
        *,
        overwrite: bool = True,
    ) -> WorkspaceEntry:
        target, _ = self._resolve(user_id, path, allow_root=False)
        encoded = str(content).encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise WorkspaceError("file exceeds the workspace write limit")
        if target.exists() and (target.is_dir() or target.is_symlink()):
            raise WorkspaceError("target is not a regular file")
        if target.exists() and not overwrite:
            raise WorkspaceError("file already exists")
        files, total = self._usage(user_id)
        previous = target.stat().st_size if target.exists() else 0
        if not target.exists() and files >= MAX_WORKSPACE_FILES:
            raise WorkspaceError("workspace file limit reached")
        if total - previous + len(encoded) > MAX_WORKSPACE_BYTES:
            raise WorkspaceError("workspace storage limit reached")
        target.parent.mkdir(parents=True, exist_ok=True)
        owner_root = self._owner_root(user_id)
        if (
            owner_root not in target.parent.resolve().parents
            and target.parent.resolve() != owner_root
        ):
            raise WorkspaceError("target escaped the private workspace")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".pending-", dir=target.parent, delete=False
            ) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return self._entry(owner_root, target)

    def replace_text(
        self,
        user_id: str,
        path: str,
        old: str,
        new: str,
        *,
        replace_all: bool = False,
    ) -> WorkspaceEntry:
        if not old:
            raise WorkspaceError("old text must not be empty")
        content = self.read_text(user_id, path)
        count = content.count(old)
        if count == 0:
            raise WorkspaceError("old text was not found")
        if count > 1 and not replace_all:
            raise WorkspaceError("old text is not unique; use replace_all explicitly")
        updated = (
            content.replace(old, new) if replace_all else content.replace(old, new, 1)
        )
        return self.write_text(user_id, path, updated)

    def mkdir(self, user_id: str, path: str) -> WorkspaceEntry:
        owner_root = self._owner_root(user_id)
        target, _ = self._resolve(user_id, path, allow_root=False)
        if target.exists() and not target.is_dir():
            raise WorkspaceError("a file already exists at that path")
        target.mkdir(parents=True, exist_ok=True)
        return self._entry(owner_root, target)

    def copy(self, user_id: str, source: str, destination: str) -> WorkspaceEntry:
        owner_root = self._owner_root(user_id)
        src, _ = self._resolve(user_id, source, allow_root=False)
        dst, _ = self._resolve(user_id, destination, allow_root=False)
        if not src.is_file() or src.is_symlink():
            raise WorkspaceError("source file does not exist")
        if dst.exists():
            raise WorkspaceError("destination already exists")
        content = self.read_text(user_id, source)
        return self.write_text(user_id, destination, content, overwrite=False)

    def move(self, user_id: str, source: str, destination: str) -> WorkspaceEntry:
        owner_root = self._owner_root(user_id)
        src, _ = self._resolve(user_id, source, allow_root=False)
        dst, _ = self._resolve(user_id, destination, allow_root=False)
        if not src.exists() or src.is_symlink():
            raise WorkspaceError("source path does not exist")
        if dst.exists():
            raise WorkspaceError("destination already exists")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        return self._entry(owner_root, dst)

    def delete(self, user_id: str, path: str, *, recursive: bool = False) -> None:
        target, _ = self._resolve(user_id, path, allow_root=False)
        if not target.exists() or target.is_symlink():
            raise WorkspaceError("path does not exist")
        if target.is_dir():
            if recursive:
                shutil.rmtree(target)
            else:
                target.rmdir()
        else:
            target.unlink()

    def search(
        self,
        user_id: str,
        query: str,
        *,
        path: str = "",
    ) -> list[dict[str, str | int]]:
        needle = str(query or "").strip()
        if not needle or len(needle) > 200:
            raise WorkspaceError("search query must contain 1 to 200 characters")
        owner_root = self._owner_root(user_id)
        target, _ = self._resolve(user_id, path)
        if not target.exists():
            raise WorkspaceError("search path does not exist")
        candidates = [target] if target.is_file() else self._iter_files(target)
        lowered = needle.casefold()
        results: list[dict[str, str | int]] = []
        for candidate in candidates:
            relative = candidate.relative_to(owner_root).as_posix()
            if lowered in candidate.name.casefold():
                results.append({"path": relative, "line": 0, "excerpt": candidate.name})
            if candidate.stat().st_size <= MAX_FILE_BYTES:
                try:
                    lines = candidate.read_text(encoding="utf-8").splitlines()
                except UnicodeDecodeError:
                    lines = []
                for index, line in enumerate(lines, start=1):
                    if lowered in line.casefold():
                        results.append({
                            "path": relative,
                            "line": index,
                            "excerpt": line[:300],
                        })
                        if len(results) >= MAX_SEARCH_RESULTS:
                            return results
            if len(results) >= MAX_SEARCH_RESULTS:
                break
        return results

    def export_files(self, user_id: str) -> list[tuple[str, bytes]]:
        owner_root = self._owner_root(user_id, create=False)
        if not owner_root.exists():
            return []
        exported = []
        for target in self._iter_files(owner_root):
            if target.stat().st_size > MAX_FILE_BYTES:
                raise WorkspaceError("workspace contains an oversized file")
            exported.append((
                target.relative_to(owner_root).as_posix(),
                target.read_bytes(),
            ))
        return exported

    def delete_all_for_user(self, user_id: str) -> None:
        owner_root = self._owner_root(user_id, create=False)
        if owner_root.exists():
            shutil.rmtree(owner_root)
