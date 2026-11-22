import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent.deep_diagnostics import HardwareDeepDiagnostics
from agent.store import KnowledgeStore


class TestHardwareDeepDiagnostics(unittest.TestCase):
    def test_run_is_read_only_and_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = HardwareDeepDiagnostics(tmp).run(save=False)
            self.assertEqual(report["schema"], "mahoraga.hardware.deep.v1")
            self.assertEqual(report["mode"], "read_only")
            self.assertFalse(report["safety"]["writes_performed"])
            self.assertFalse(report["safety"]["device_writes_performed"])
            self.assertFalse(report["local_persistence"]["requested"])
            self.assertEqual(report["local_persistence"]["targets"], [])
            self.assertIn("thermal", report)
            self.assertIn("gpu", report)
            self.assertIn("shizuku", report)

    def test_shizuku_command_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            diag = HardwareDeepDiagnostics(tmp)
            self.assertEqual(
                diag._run_shizuku("rm -rf /", 2)["status"],
                "not_allowlisted",
            )

    def test_report_files_are_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "memory.sqlite3"
            store = KnowledgeStore(db_path)

            report = HardwareDeepDiagnostics(
                project_root=tmp,
                store=store,
            ).run(save=True)

            self.assertTrue(Path(report["saved_reports"]["json"]).is_file())
            self.assertTrue(Path(report["saved_reports"]["markdown"]).is_file())
            self.assertNotIn("persistence_warning", report)
            self.assertTrue(report["local_persistence"]["requested"])
            self.assertEqual(
                report["local_persistence"]["scope"], "project_storage"
            )
            self.assertCountEqual(
                report["local_persistence"]["targets"],
                ["json_report", "markdown_report", "knowledge_store"],
            )
            self.assertFalse(report["safety"]["device_writes_performed"])

            with sqlite3.connect(db_path) as db:
                observations = db.execute(
                    "SELECT COUNT(*) FROM observations "
                    "WHERE category = ? AND subject = ?",
                    ("deep_hardware_diagnostics", "android_device"),
                ).fetchone()[0]

                events = db.execute(
                    "SELECT COUNT(*) FROM events "
                    "WHERE event_type = ?",
                    ("hardware.deep_diagnostics",),
                ).fetchone()[0]

            self.assertEqual(observations, 1)
            self.assertEqual(events, 1)
