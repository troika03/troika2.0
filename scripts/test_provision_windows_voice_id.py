"""Safety checks for build-time Windows voice asset provisioning."""
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location("windows_voice_provision", Path(__file__).with_name("provision_windows_voice_id.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProvisionTests(unittest.TestCase):
    def archive(self, names):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as output:
            for name in names:
                # ZipInfo normally normalizes Windows separators when constructed.
                # Assign after construction to model a hostile on-disk ZIP entry.
                entry = zipfile.ZipInfo()
                entry.filename = name
                output.writestr(entry, b"fixture")
        data.seek(0)
        return zipfile.ZipFile(data)

    def test_traversal_and_windows_paths_rejected(self):
        item = {"archive_root": "model", "output": "model"}
        for name in ["model/../outside", "/outside", "model\\outside", "C:/outside"]:
            with self.subTest(name=name), self.archive([name]) as archive:
                with self.assertRaises(ValueError):
                    MODULE.entries(archive, item)

    def test_duplicate_case_folded_paths_rejected(self):
        with self.archive(["model/one", "model/ONE"]) as archive:
            with self.assertRaises(ValueError):
                MODULE.entries(archive, {"archive_root": "model", "output": "model"})

    def test_link_entry_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            entry = zipfile.ZipInfo("model/linked")
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, "outside")
        data.seek(0)
        with zipfile.ZipFile(data) as archive:
            with self.assertRaises(ValueError):
                MODULE.entries(archive, {"archive_root": "model", "output": "model"})

    def test_required_native_files_cannot_be_missing(self):
        with self.archive(["vosk/libvosk.dll"]) as archive:
            with self.assertRaises(ValueError):
                MODULE.entries(archive, {"archive_root": "vosk", "output": "native", "selected_files": ["libvosk.dll", "libwinpthread-1.dll"]})

    def test_invalid_existing_cache_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            target = cache / "model.zip"
            target.write_bytes(b"old")
            with self.assertRaises(ValueError):
                MODULE.obtain({"filename": target.name, "size": 4, "sha256": "0" * 64}, cache, True)
            self.assertEqual(target.read_bytes(), b"old")

    def test_existing_output_rejects_corruption_and_unexpected_file(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "model.bin"
            fixture.write_bytes(b"expected")
            manifest = json.dumps({"files": [{"path": "model.bin", "size": fixture.stat().st_size, "sha256": MODULE.digest(fixture)}]}).encode()
            (root / "manifest.json").write_bytes(manifest)
            checksum = hashlib.sha256(manifest).hexdigest()
            MODULE.verify(root, checksum)
            (root / "unexpected.bin").write_bytes(b"x")
            with self.assertRaises(ValueError):
                MODULE.verify(root, checksum)
            (root / "unexpected.bin").unlink()
            fixture.write_bytes(b"corrupt!")
            with self.assertRaises(ValueError):
                MODULE.verify(root, checksum)


if __name__ == "__main__":
    unittest.main()
