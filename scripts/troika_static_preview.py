"""Serve only explicitly selected static project pages to a browser lab."""

import os
from pathlib import Path, PureWindowsPath
import stat
from urllib.parse import quote, unquote, urlsplit

from troika_product.computer_control import ComputerControlError


ORIGIN = "http://troika-browser.test/"
_HTML = {".html", ".htm"}
_TYPES = {
    ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon",
    ".svg": "image/svg+xml", ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
}
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_BYTES = 16 * 1024 * 1024
_MAX_FILES = 128
_CSP = (
    "default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self'; form-action 'none'; base-uri 'none'"
)


def _parts(name):
    if not name or len(name) > 240 or any(ord(character) < 32 for character in name):
        raise ValueError("invalid preview path")
    parts = name.split("/")
    if any(not part or part.startswith(".") or part.endswith((".", " "))
           or "\\" in part or ":" in part or PureWindowsPath(part).is_reserved() for part in parts):
        raise ValueError("invalid preview path")
    return parts


def _plain(info):
    return not (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _identity(info):
    return (info.st_dev, info.st_ino)


class StaticProjectPreview:
    def __init__(self, directory, entry, second_entry=None):
        try:
            root = Path(directory)
            if root.drive.startswith("\\\\") or not _plain(root.lstat()) or not root.is_dir():
                raise ValueError("invalid preview directory")
            self.root = root.resolve(strict=True)
            if self.root.drive.startswith("\\\\"):
                raise ValueError("preview directory must be local")
            self.root_id = _identity(self.root.lstat())
            self.entries = {"overview": entry}
            if second_entry is not None:
                if entry.casefold() == second_entry.casefold():
                    raise ValueError("duplicate preview pages")
                self.entries["details"] = second_entry
            self.files = {}
            self.total_bytes = 0
            for name in self.entries.values():
                if Path(name).suffix.lower() not in _HTML:
                    raise ValueError("preview entry must be HTML")
                self._read(name)
            self.pages = {key: ORIGIN + quote(name, safe="/") for key, name in self.entries.items()}
        except (OSError, RuntimeError, ValueError):
            raise ComputerControlError("project_preview_unavailable") from None

    def _read(self, name):
        if name in self.files:
            return self.files[name]
        if len(self.files) >= _MAX_FILES or _identity(self.root.lstat()) != self.root_id:
            raise ValueError("preview limit or directory changed")
        parts = _parts(name)
        path = self.root
        for part in parts:
            path /= part
            info = path.lstat()
            if not _plain(info):
                raise ValueError("links cannot be served")
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink > 1
                or not path.resolve(strict=True).is_relative_to(self.root)):
            raise ValueError("not a project file")
        remaining = min(_MAX_FILE_BYTES, _MAX_TOTAL_BYTES - self.total_bytes)
        if not 0 <= info.st_size <= remaining:
            raise ValueError("preview file exceeds limit")
        with path.open("rb") as file:
            opened = os.fstat(file.fileno())
            if _identity(opened) != _identity(info) or opened.st_size != info.st_size:
                raise ValueError("preview file changed")
            data = file.read(remaining + 1)
            if len(data) != opened.st_size or os.fstat(file.fileno()).st_mtime_ns != opened.st_mtime_ns:
                raise ValueError("preview file changed")
        self.files[name] = data
        self.total_bytes += len(data)
        return data

    def route(self, route):
        request = route.request
        try:
            address = urlsplit(request.url)
            if request.method != "GET" or not request.url.startswith(ORIGIN) or len(request.url) > 1000:
                raise ValueError("unexpected preview request")
            name = unquote(address.path[1:], errors="strict")
            extension = Path(name).suffix.lower()
            if request.is_navigation_request():
                if request.url not in self.pages.values():
                    raise ValueError("page not selected for preview")
            elif extension in _HTML:
                raise ValueError("unexpected document request")
            content_type = _TYPES.get(extension)
            if content_type is None:
                raise ValueError("unsupported preview asset")
            data = self._read(name)
        except (OSError, RuntimeError, ValueError):
            route.abort()
            return
        route.fulfill(status=200, content_type=content_type, body=data, headers={
            "Content-Security-Policy": _CSP, "X-Content-Type-Options": "nosniff",
        })
