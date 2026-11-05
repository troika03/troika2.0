#!/usr/bin/env python3
"""Provision the pinned offline wake model and native libraries before a build.

The application never downloads these assets at runtime. Existing output is
verified, never silently replaced. Only Python's standard library is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

TOOL_DIRECTORY = Path(__file__).resolve().parent
LOCK_PATH = TOOL_DIRECTORY / "offline-wake.lock.json"
MAX_FILES = 256
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 128 * 1024 * 1024


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def linked(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        # Junctions are reparse points, but Path.is_symlink() on Python 3.11
        # does not identify every kind of Windows directory link.
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def regular_file(path: Path) -> bool:
    return path.is_file() and not linked(path)


def validate_file(path: Path, item: dict) -> bool:
    return (regular_file(path) and path.stat().st_size == item["size"]
            and digest(path) == item["sha256"])


def ensure_safe_directory(path: Path) -> None:
    """Reject links in the complete destination chain before creating files."""
    for entry in [path, *path.parents]:
        if linked(entry):
            raise ValueError(f"Symbolic link is not a build output directory: {entry}")
        if entry.exists() and not entry.is_dir():
            raise ValueError(f"Expected a directory: {entry}")
    path.mkdir(parents=True, exist_ok=True)


def download(item: dict, cache: Path, offline: bool) -> Path:
    target = cache / item["filename"]
    if target.exists():
        if not validate_file(target, item):
            raise ValueError(f"Cached file differs from the lock; refusing overwrite: {target}")
        return target
    if linked(target):
        raise ValueError(f"Refusing symbolic link: {target}")
    if offline:
        raise FileNotFoundError(f"Missing pinned cache file in offline mode: {target}")
    parsed = urllib.parse.urlparse(item["url"])
    if parsed.scheme != "https" or parsed.hostname not in {"repo.maven.apache.org", "alphacephei.com"}:
        raise ValueError("The lock must refer to an official HTTPS source")
    last_error = None
    for attempt in range(3):
        temporary = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=".troika-download-", dir=cache)
            temporary = Path(name)
            request = urllib.request.Request(item["url"], headers={"User-Agent": "Troika-build/1.0"})
            with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(request, timeout=60) as response:
                final_url = urllib.parse.urlparse(response.geturl())
                if final_url.scheme != "https" or final_url.hostname != parsed.hostname:
                    raise ValueError("Unexpected download redirect")
                received = 0
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > item["size"]:
                        raise ValueError("Download exceeds its pinned byte length")
                    output.write(block)
            if not validate_file(temporary, item):
                raise ValueError(f"Downloaded file failed SHA-256/length verification: {item['filename']}")
            # A concurrent provisioner cannot cause an unverified replacement.
            if target.exists() or linked(target):
                if not validate_file(target, item):
                    raise ValueError(f"Output appeared during download: {target}")
                return target
            temporary.replace(target)
            temporary = None
            return target
        except (OSError, ValueError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(1 + attempt)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    raise RuntimeError(f"Unable to obtain pinned {item['filename']}: {last_error}") from last_error


def model_entries(archive: zipfile.ZipFile, root: str,
                  required_files: list[str] | None = None) -> list[tuple[zipfile.ZipInfo, str]]:
    entries = archive.infolist()
    if len(entries) > MAX_FILES:
        raise ValueError("Model archive contains too many entries")
    result = []
    seen = set()
    total = 0
    for entry in entries:
        name = entry.filename
        path = PurePosixPath(name)
        if ("\\" in name or ":" in name or path.is_absolute()
                or ".." in path.parts or not path.parts or path.parts[0] != root):
            raise ValueError(f"Unsafe model archive path: {name}")
        relative = PurePosixPath(*path.parts[1:]).as_posix()
        mode = entry.external_attr >> 16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
            raise ValueError(f"Non-regular model archive entry: {name}")
        if entry.is_dir():
            continue
        if relative in {"", ".", "manifest.json"} or relative.casefold() in seen:
            raise ValueError(f"Duplicate or reserved model path: {name}")
        seen.add(relative.casefold())
        total += entry.file_size
        if entry.file_size > MAX_FILE_BYTES or total > MAX_EXPANDED_BYTES or entry.flag_bits & 1:
            raise ValueError("Model archive exceeds bounded extraction limits")
        result.append((entry, relative))
    required = set(required_files) if required_files is not None else {
        "am/final.mdl", "conf/model.conf", "conf/mfcc.conf", "graph/HCLr.fst", "graph/Gr.fst"}
    if not required.issubset({name for _, name in result}):
        raise ValueError("Model archive is missing required Russian model files")
    return sorted(result, key=lambda pair: pair[1])


def model_manifest(archive: zipfile.ZipFile, entries: list, model: dict) -> bytes:
    files = []
    for entry, path in entries:
        with archive.open(entry) as source:
            checksum = hashlib.file_digest(source, "sha256").hexdigest()
        files.append({"path": path, "sha256": checksum, "size": entry.file_size})
    result = {"version": model["version"], "files": files}
    return (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def verify_model(directory: Path, manifest: bytes) -> None:
    if linked(directory) or not directory.is_dir():
        raise ValueError(f"Existing model output is not a plain directory: {directory}")
    marker = directory / "manifest.json"
    if not regular_file(marker) or marker.read_bytes() != manifest:
        raise ValueError(f"Existing model has a different manifest; refusing overwrite: {directory}")
    expected = {"manifest.json"}
    for item in json.loads(manifest)["files"]:
        target = directory / item["path"]
        if not validate_file(target, item):
            raise ValueError(f"Existing model file failed verification: {target}")
        expected.add(item["path"])
    actual = set()
    for entry in directory.rglob("*"):
        if linked(entry):
            raise ValueError(f"Model output contains a symbolic link: {entry}")
        if entry.is_file():
            actual.add(entry.relative_to(directory).as_posix())
    if actual != expected:
        raise ValueError(f"Existing model contains unexpected files: {directory}")


def install_model(archive_path: Path, model: dict, destination: Path) -> str:
    ensure_safe_directory(destination.parent)
    with zipfile.ZipFile(archive_path) as archive:
        entries = model_entries(archive, model["archive_root"], model.get("required_files"))
        manifest = model_manifest(archive, entries, model)
        if hashlib.sha256(manifest).hexdigest() != model["manifest_sha256"]:
            raise ValueError("Model manifest differs from the pinned manifest digest")
        if destination.exists() or linked(destination):
            verify_model(destination, manifest)
            return "verified"
        stage = Path(tempfile.mkdtemp(prefix=".troika-model-", dir=destination.parent))
        try:
            for entry, relative in entries:
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            (stage / "manifest.json").write_bytes(manifest)
            verify_model(stage, manifest)
            if destination.exists() or linked(destination):
                raise ValueError(f"Model output appeared during provisioning: {destination}")
            stage.rename(destination)
            stage = None
            return "installed"
        finally:
            if stage is not None:
                # Only the freshly created directory under the verified output parent.
                assert (stage.is_absolute() and stage.resolve().parent == destination.parent.resolve()
                        and not linked(stage) and stage.name.startswith(".troika-model-"))
                shutil.rmtree(stage)


def install_library(source: Path, item: dict, directory: Path) -> str:
    ensure_safe_directory(directory)
    target = directory / item["filename"]
    if target.exists() or linked(target):
        if not validate_file(target, item):
            raise ValueError(f"Existing library differs from the lock; refusing overwrite: {target}")
        return "verified"
    descriptor, name = tempfile.mkstemp(prefix=".troika-library-", dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, output)
        if not validate_file(temporary, item):
            raise ValueError("Copied library failed verification")
        if target.exists() or linked(target):
            raise ValueError(f"Library output appeared during provisioning: {target}")
        temporary.rename(target)
        temporary = None
        return "installed"
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=TOOL_DIRECTORY.parent,
                        help="Flutter project containing android/app (default: this project)")
    parser.add_argument("--cache", type=Path, default=TOOL_DIRECTORY.parent / ".offline-wake-cache",
                        help="Build download cache; every cached file is verified against the lock")
    parser.add_argument("--offline", action="store_true", help="Require all three pinned cache files locally")
    args = parser.parse_args()
    project = args.project.absolute()
    if not (project / "android/app/build.gradle").is_file():
        parser.error("--project must identify an existing Flutter Android project")
    ensure_safe_directory(project)
    cache = args.cache.absolute()
    ensure_safe_directory(cache)
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock["schema_version"] != 1:
        raise ValueError("Unsupported dependency lock version")
    libraries = []
    for item in lock["libraries"]:
        source = download(item, cache, args.offline)
        libraries.append({"filename": item["filename"],
                          "status": install_library(source, item, project / "android/app/wake-dependencies")})
    model = lock["model"]
    source = download(model, cache, args.offline)
    status = install_model(source, model, project / "android/app/src/main/assets/model-wake-ru")
    speaker = lock["speaker_model"]
    speaker_source = download(speaker, cache, args.offline)
    speaker_status = install_model(speaker_source, speaker, project / "android/app/src/main/assets/model-owner-voice")
    print(json.dumps({"project": str(project), "libraries": libraries, "model": status,
                      "speaker_model": speaker_status,
                      "model_manifest_sha256": model["manifest_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
