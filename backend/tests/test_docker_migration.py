"""Safety boundaries for local-to-container backup and restore."""

import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/docker/migrate.py"
if not SCRIPT.exists() and Path("/opt/deploy/migrate.py").exists():
    SCRIPT = Path("/opt/deploy/migrate.py")
SPEC = importlib.util.spec_from_file_location("docker_migration", SCRIPT)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class DockerMigrationTest(unittest.TestCase):
    def test_restore_refuses_existing_data_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "original").write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                migration.restore_volume(target, io.BytesIO())
            self.assertEqual((target / "original").read_text(), "keep")

    def test_restore_rejects_path_traversal_and_links_without_partial_write(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                           ("safe/link", tarfile.SYMTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w") as archive:
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    info.linkname = "../../outside"
                    archive.addfile(info)
                stream.seek(0)
                with self.assertRaises(ValueError):
                    migration.restore_volume(Path(directory), stream)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_backup_roundtrip_verifies_hashes_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "中文.md").write_text("保留知识文档", encoding="utf-8")
            manifest = migration.file_manifest(source)
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                archive.add(source / "中文.md", arcname="中文.md")
            stream.seek(0)
            target = Path(directory) / "target"
            target.mkdir()
            migration.restore_volume(target, stream)
            self.assertEqual(migration.file_manifest(target), manifest)
            (target / "中文.md").write_text("changed", encoding="utf-8")
            self.assertNotEqual(migration.file_manifest(target), manifest)
