import tempfile
import unittest
from pathlib import Path
from agent.store import KnowledgeStore
from agent.tool_intelligence import ToolIntelligence


class TestToolIntelligence(unittest.TestCase):
    def test_discovery_registers_detected_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "db.sqlite3")
            report = ToolIntelligence(store).discover(include_python_packages=False)
            self.assertIn("commands", report)
            catalog_ids = {item["tool_id"] for item in store.list_tools()}
            command_ids = {item["tool_id"] for item in report["commands"]}
            package_ids = {item["tool_id"] for item in report["termux_packages"]}
            self.assertTrue(command_ids.issubset(catalog_ids))
            self.assertTrue(package_ids.issubset(catalog_ids))
            self.assertEqual(len(command_ids), len(report["commands"]))

    def test_presence_is_not_operational_competence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "db.sqlite3")
            store.upsert_tool("command:demo", "demo", "/bin/demo")
            with self.assertRaises(ValueError):
                store.update_tool_competence("command:demo", "operational", ["installed"])
            store.update_tool_competence("command:demo", "operational", ["test 1 passed", "test 2 passed"])
            self.assertEqual(store.list_tools()[0]["competence"], "operational")


    def test_specialized_and_improver_levels_require_store_evidence_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "db.sqlite3")
            tools = ToolIntelligence(store)
            store.upsert_tool(
                "command:demo", "demo", "/bin/demo",
                source="test", competence="identified",
            )

            with self.assertRaisesRegex(ValueError, "specialized exige"):
                tools.register_specialized("command:demo", ["evidence 1", "evidence 2"])
            tools.register_specialized(
                "command:demo",
                ["test A passed", "test B passed", "test C passed"],
            )
            self.assertEqual(store.list_tools()[0]["competence"], "specialized")

            with self.assertRaisesRegex(ValueError, "improver exige"):
                tools.register_improver(
                    "command:demo",
                    ["evidence 1", "evidence 2", "evidence 3"],
                )
            tools.register_improver(
                "command:demo",
                ["baseline recorded", "change tested", "regression checked", "result reviewed"],
            )
            saved = store.list_tools()[0]
            self.assertEqual(saved["competence"], "improver")
            self.assertEqual(len(saved["evidence"]), 7)

    def test_competence_registration_does_not_execute_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / "db.sqlite3")
            tools = ToolIntelligence(store)
            store.upsert_tool("command:demo", "demo", "/bin/demo")
            tools.register_specialized(
                "command:demo",
                ["test 1 passed", "test 2 passed", "test 3 passed"],
            )
            assert store.list_tools()[0]["competence"] == "specialized"


if __name__ == "__main__":
    unittest.main()
