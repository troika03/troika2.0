"""Bounded, expiring RAM handoffs; generated files never enter ArtifactStore."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import threading
import time
import uuid

from troika_product.artifacts import safe_artifact_filename


@dataclass(frozen=True)
class Delivery:
    user_id: str
    device_id: str
    filename: str
    kind: str
    mime_type: str
    data: bytes
    expires_at: float
    created_at: float

    def metadata(self, item_id: str) -> dict:
        return {"id": item_id, "filename": self.filename, "kind": self.kind,
                "mime_type": self.mime_type, "size": len(self.data),
                "sha256": hashlib.sha256(self.data).hexdigest(), "created_at": self.created_at,
                "storage": "device", "status": "awaiting_device", "expires_at": self.expires_at,
                "download_url": f"/v1/device-files/{item_id}"}


class DeviceDeliveryStore:
    def __init__(self, *, ttl: float = 600, max_bytes: int = 100 * 1024 * 1024):
        self.ttl = ttl
        self.max_bytes = max_bytes
        self._lock = threading.RLock()
        self._items: dict[str, Delivery] = {}
        self._timers: dict[str, threading.Timer] = {}

    def create(self, user_id: str, device_id: str, filename: str, kind: str,
               mime_type: str, data: bytes) -> dict:
        if not data or len(data) > 50 * 1024 * 1024:
            raise ValueError("invalid delivery size")
        # Project names use the same filename normalization as documents.
        filename = (safe_artifact_filename(filename.removesuffix(".zip"), "json")[:-5] + ".zip"
                    if kind == "zip" else safe_artifact_filename(filename, kind))
        item_id = "delivery_" + uuid.uuid4().hex
        expires = time.time() + self.ttl
        with self._lock:
            self._purge()
            if sum(len(item.data) for item in self._items.values()) + len(data) > self.max_bytes:
                raise ValueError("delivery capacity exceeded; retry after downloading files")
            item = Delivery(user_id, device_id, filename, kind, mime_type, data, expires, time.time())
            self._items[item_id] = item
            timer = threading.Timer(self.ttl, self._remove, args=(item_id,))
            timer.daemon = True
            self._timers[item_id] = timer
            timer.start()
        return item.metadata(item_id)

    def list_pending(self, user_id: str, device_id: str) -> list[dict]:
        with self._lock:
            self._purge()
            return [item.metadata(item_id) for item_id, item in self._items.items()
                    if (item.user_id, item.device_id) == (user_id, device_id)]

    def _remove(self, item_id: str) -> None:
        with self._lock:
            self._items.pop(item_id, None)
            timer = self._timers.pop(item_id, None)
            if timer:
                timer.cancel()

    def _purge(self) -> None:
        for item_id, item in list(self._items.items()):
            if item.expires_at <= time.time():
                self._remove(item_id)

    def get(self, item_id: str, user_id: str, device_id: str) -> Delivery | None:
        with self._lock:
            self._purge()
            item = self._items.get(item_id)
            return item if item and (item.user_id, item.device_id) == (user_id, device_id) else None

    def acknowledge(self, item_id: str, user_id: str, device_id: str) -> bool:
        with self._lock:
            if self.get(item_id, user_id, device_id) is None:
                return False
            self._remove(item_id)
            return True

    def purge_owner(self, user_id: str, device_id: str | None = None) -> None:
        with self._lock:
            for item_id, item in list(self._items.items()):
                if item.user_id == user_id and (device_id is None or item.device_id == device_id):
                    self._remove(item_id)


device_deliveries = DeviceDeliveryStore()
