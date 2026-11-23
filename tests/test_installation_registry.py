import tempfile
import unittest
from pathlib import Path
from agent.store import KnowledgeStore
from agent.installation_registry import InstallationRegistry


class TestInstallationRegistry(unittest.TestCase):
    def test_record_and_list_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "db.sqlite3")
            registry = InstallationRegistry(store)
            record = {"installation_id": "demo:1", "name": "Demo", "version": "1",
                      "method": "direct_link", "source_url": "https://example.invalid/demo",
                      "source_ref": "test", "purpose": "unit test", "verification": "sha256_verified"}
            self.assertTrue(registry.record(**record))
            self.assertFalse(registry.record(**record))
            self.assertEqual(registry.list_all()[0]["method"], "direct_link")


if __name__ == "__main__":
    unittest.main()
