import tempfile
import unittest
from pathlib import Path
from agent.hardware_intelligence import HardwareIntelligence


class TestHardwareIntelligence(unittest.TestCase):
    def test_snapshot_is_read_only_and_structured(self):
        report = HardwareIntelligence().snapshot()
        self.assertEqual(report["mode"], "read_only")
        for key in ("android", "cpu", "memory", "storage", "battery", "thermal", "gpu", "access_map"):
            self.assertIn(key, report)

    def test_memory_parser_handles_missing_proc(self):
        collector = HardwareIntelligence()
        result = collector.memory()
        self.assertIn("status", result)
        self.assertIn("values", result)


if __name__ == "__main__":
    unittest.main()
