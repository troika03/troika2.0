"""Integrity and refusal checks for the offline wake asset provisioner."""
from pathlib import Path
import hashlib
import io
import stat
import tempfile
import unittest
import zipfile

import prepare_offline_wake as provision


class OfflineWakeProvisionTest(unittest.TestCase):
    def test_speaker_model_requires_its_own_files_and_verifies_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "speaker.zip"
            required = ["mfcc.conf", "final.ext.raw", "mean.vec", "transform.mat"]
            with zipfile.ZipFile(source, "w") as archive:
                for name in required:
                    archive.writestr("speaker/" + name, name.encode())
            model = {"version": "test-speaker", "archive_root": "speaker", "required_files": required}
            with zipfile.ZipFile(source) as archive:
                entries = provision.model_entries(archive, "speaker", required)
                manifest = provision.model_manifest(archive, entries, model)
            model["manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
            target = base / "assets/model-owner-voice"
            self.assertEqual(provision.install_model(source, model, target), "installed")
            self.assertEqual(provision.install_model(source, model, target), "verified")
            (target / "mean.vec").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "failed verification"):
                provision.install_model(source, model, target)

    def test_offline_cache_rejects_corruption_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            target = cache / "dependency.aar"
            target.write_bytes(b"corrupt")
            item = {"filename": target.name, "size": 4,
                    "sha256": hashlib.sha256(b"good").hexdigest()}
            with self.assertRaisesRegex(ValueError, "refusing overwrite"):
                provision.download(item, cache, offline=True)
            self.assertEqual(target.read_bytes(), b"corrupt")

    def test_offline_cache_requires_exact_existing_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            target = cache / "dependency.aar"
            item = {"filename": target.name, "size": 4,
                    "sha256": hashlib.sha256(b"good").hexdigest()}
            with self.assertRaises(FileNotFoundError):
                provision.download(item, cache, offline=True)
            target.write_bytes(b"good")
            self.assertEqual(provision.download(item, cache, offline=True), target)

    def test_archive_rejects_traversal_absolute_and_link_entries(self):
        cases = ["model/../outside", "/outside", "model\\outside"]
        for name in cases:
            with self.subTest(name=name), io.BytesIO() as content:
                with zipfile.ZipFile(content, "w") as output:
                    output.writestr(name, b"unsafe")
                content.seek(0)
                with zipfile.ZipFile(content) as archive:
                    with self.assertRaises(ValueError):
                        provision.model_entries(archive, "model")
        with io.BytesIO() as content:
            entry = zipfile.ZipInfo("model/link")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(content, "w") as output:
                output.writestr(entry, "../outside")
            content.seek(0)
            with zipfile.ZipFile(content) as archive:
                with self.assertRaisesRegex(ValueError, "Non-regular"):
                    provision.model_entries(archive, "model")

    def test_archive_rejects_case_collisions_on_all_platforms(self):
        with io.BytesIO() as content:
            with zipfile.ZipFile(content, "w") as output:
                output.writestr("model/am/final.mdl", b"one")
                output.writestr("model/AM/FINAL.MDL", b"two")
            content.seek(0)
            with zipfile.ZipFile(content) as archive:
                with self.assertRaisesRegex(ValueError, "Duplicate"):
                    provision.model_entries(archive, "model")

    def test_model_install_is_verified_and_refuses_modified_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "model.zip"
            required = ["am/final.mdl", "conf/model.conf", "conf/mfcc.conf",
                        "graph/HCLr.fst", "graph/Gr.fst"]
            with zipfile.ZipFile(source, "w") as archive:
                for name in required:
                    archive.writestr("model/" + name, name.encode())
            model = {"version": "test-model", "archive_root": "model"}
            with zipfile.ZipFile(source) as archive:
                entries = provision.model_entries(archive, "model")
                manifest = provision.model_manifest(archive, entries, model)
            model["manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
            target = base / "assets/model-wake-ru"
            self.assertEqual(provision.install_model(source, model, target), "installed")
            self.assertEqual(provision.install_model(source, model, target), "verified")
            modified = target / "am/final.mdl"
            modified.write_bytes(b"user change")
            with self.assertRaisesRegex(ValueError, "failed verification"):
                provision.install_model(source, model, target)
            self.assertEqual(modified.read_bytes(), b"user change")
            self.assertFalse(any(path.name.startswith(".troika-model-")
                                 for path in target.parent.iterdir()))

    def test_existing_unknown_library_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "dependency.aar"
            source.write_bytes(b"verified")
            destination = base / "libraries"
            destination.mkdir()
            existing = destination / source.name
            existing.write_bytes(b"unknown")
            item = {"filename": source.name, "size": source.stat().st_size,
                    "sha256": provision.digest(source)}
            with self.assertRaisesRegex(ValueError, "refusing overwrite"):
                provision.install_library(source, item, destination)
            self.assertEqual(existing.read_bytes(), b"unknown")


if __name__ == "__main__":
    unittest.main()
