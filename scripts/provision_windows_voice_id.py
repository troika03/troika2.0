#!/usr/bin/env python3
"""Provision pinned offline speaker verification assets for the WPF client.

Only build-time downloads are permitted. Installed applications use local files.
Archives and every extracted file are verified; existing invalid output is never
silently overwritten. Python's standard library is sufficient.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "troika-desktop" / "voice-id.lock.json"


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def linked(path: Path) -> bool:
    return path.is_symlink() or (path.exists() and bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400))


def safe_directory(path: Path) -> None:
    for entry in [path, *path.parents]:
        if linked(entry) or (entry.exists() and not entry.is_dir()):
            raise ValueError(f"Expected a plain build directory: {entry}")
    path.mkdir(parents=True, exist_ok=True)


def valid(path: Path, item: dict) -> bool:
    return path.is_file() and not linked(path) and path.stat().st_size == item["size"] and digest(path) == item["sha256"]


def obtain(item: dict, cache: Path, offline: bool) -> Path:
    target = cache / item["filename"]
    if target.exists() or linked(target):
        if not valid(target, item):
            raise ValueError(f"Cached artifact differs from the lock: {target}")
        return target
    if offline:
        raise FileNotFoundError(f"Missing pinned artifact: {target}")
    url = urllib.parse.urlparse(item["url"])
    if url.scheme != "https" or url.hostname not in {"files.pythonhosted.org", "alphacephei.com"}:
        raise ValueError("Only official HTTPS artifact sources are permitted")
    descriptor, name = tempfile.mkstemp(prefix=".troika-download-", dir=cache)
    os.close(descriptor)
    temporary = Path(name)
    try:
        try:
            request = urllib.request.Request(item["url"], headers={"User-Agent": "Troika-build/1.0"})
            with urllib.request.urlopen(request, timeout=20) as response, temporary.open("wb") as output:
                final = urllib.parse.urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != url.hostname:
                    raise ValueError("Unexpected artifact download redirect")
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > item["size"]:
                        raise ValueError("Artifact exceeds pinned length")
                    output.write(block)
        except OSError:
            # curl is bundled with modern Windows and honors system proxy rules.
            curl = shutil.which("curl.exe") if os.name == "nt" else None
            if not curl:
                raise
            subprocess.run([curl, "--fail", "--silent", "--show-error", "--location", "--proto", "=https", "--connect-timeout", "15", "--max-time", "180", "--max-filesize", str(item["size"]), "--output", str(temporary), item["url"]], check=True)
        if not valid(temporary, item):
            raise ValueError(f"Artifact failed SHA-256/length verification: {item['filename']}")
        if target.exists():
            if not valid(target, item):
                raise ValueError("A different artifact appeared during provisioning")
        else:
            temporary.replace(target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def entries(archive: zipfile.ZipFile, item: dict) -> list[tuple[zipfile.ZipInfo, str]]:
    if len(archive.infolist()) > 512:
        raise ValueError("Too many archive entries")
    result = []
    seen = set()
    total = 0
    for entry in archive.infolist():
        path = PurePosixPath(entry.filename)
        mode = entry.external_attr >> 16
        if (path.is_absolute() or ".." in path.parts or "\\" in entry.orig_filename or ":" in entry.filename
                or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
            raise ValueError(f"Unsafe archive entry: {entry.filename}")
        if entry.is_dir() or not path.parts or path.parts[0] != item["archive_root"]:
            continue
        relative = PurePosixPath(*path.parts[1:]).as_posix()
        if item.get("selected_files") and relative not in item["selected_files"]:
            continue
        output = str(PurePosixPath(item["output"]) / relative)
        total += entry.file_size
        if relative in {"", "."} or output.casefold() in seen or entry.flag_bits & 1 or entry.file_size > 128 * 1024 * 1024 or total > 256 * 1024 * 1024:
            raise ValueError("Duplicate, oversized or encrypted archive entry")
        seen.add(output.casefold())
        result.append((entry, output))
    if not result or (item.get("selected_files") and len(result) != len(item["selected_files"])):
        raise ValueError("Archive lacks required runtime files")
    return result


def manifest_for(archives: list[tuple[Path, dict]]) -> bytes:
    files = []
    for path, item in archives:
        with zipfile.ZipFile(path) as archive:
            for entry, output in entries(archive, item):
                with archive.open(entry) as source:
                    checksum = hashlib.file_digest(source, "sha256").hexdigest()
                files.append({"path": output, "sha256": checksum, "size": entry.file_size})
    return (json.dumps({"schema": 1, "speaker_model": "vosk-model-spk-0.4", "files": sorted(files, key=lambda x: x["path"])}, indent=2) + "\n").encode("utf-8")


def verify(directory: Path, expected_hash: str) -> None:
    if linked(directory) or not directory.is_dir():
        raise ValueError("Voice identity output is not a plain directory")
    marker = directory / "manifest.json"
    if not marker.is_file() or linked(marker) or digest(marker) != expected_hash:
        raise ValueError("Voice identity manifest failed verification")
    expected = {"manifest.json"}
    for item in json.loads(marker.read_text(encoding="utf-8"))["files"]:
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
            raise ValueError("Unsafe manifest path")
        target = directory.joinpath(*relative.parts)
        if not valid(target, item):
            raise ValueError(f"Voice identity file failed verification: {target}")
        expected.add(item["path"])
    actual = set()
    for entry in directory.rglob("*"):
        if linked(entry):
            raise ValueError("Voice identity output contains a link")
        if entry.is_file():
            actual.add(entry.relative_to(directory).as_posix())
    if actual != expected:
        raise ValueError("Voice identity output contains unexpected files")


def provision(output: Path, cache: Path, offline: bool = False) -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    safe_directory(output.parent)
    if output.exists() or linked(output):
        verify(output, lock["manifest_sha256"])
        print("Verified pinned Windows voice identity assets.")
        return
    safe_directory(cache)
    archives = [(obtain(item, cache, offline), item) for item in lock["artifacts"]]
    manifest = manifest_for(archives)
    if hashlib.sha256(manifest).hexdigest() != lock["manifest_sha256"]:
        raise ValueError("Extracted manifest differs from the lock")
    stage = Path(tempfile.mkdtemp(prefix=".voice-identity-", dir=output.parent))
    try:
        for path, item in archives:
            with zipfile.ZipFile(path) as archive:
                for entry, relative in entries(archive, item):
                    target = stage / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open("xb") as destination:
                        shutil.copyfileobj(source, destination, 1024 * 1024)
        (stage / "manifest.json").write_bytes(manifest)
        verify(stage, lock["manifest_sha256"])
        if output.exists() or linked(output):
            raise ValueError("Output appeared during provisioning")
        stage.rename(output)
        stage = None
    finally:
        if stage is not None:
            shutil.rmtree(stage)
    print("Provisioned pinned Windows voice identity assets.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "troika-desktop" / "assets" / "voice-id")
    parser.add_argument("--cache", type=Path, default=ROOT / "troika-desktop" / ".voice-id-cache")
    parser.add_argument("--offline", action="store_true")
    arguments = parser.parse_args()
    provision(arguments.output.resolve(), arguments.cache.resolve(), arguments.offline)


if __name__ == "__main__":
    main()
