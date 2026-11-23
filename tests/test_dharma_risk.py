import unittest
from pathlib import Path
from agent.dharma import Dharma


class TestDharma(unittest.TestCase):
    def setUp(self):
        self.dharma = Dharma()

    def test_read_only_action_allowed(self):
        result = self.dharma.evaluate("inspect_hardware")
        self.assertTrue(result.allowed)
        self.assertFalse(result.requires_approval)

    def test_context_can_escalate_risk(self):
        result = self.dharma.evaluate("read_project", context={"writes_project": True})
        self.assertFalse(result.allowed)
        self.assertTrue(result.requires_approval)

    def test_unknown_action_stays_blocked(self):
        result = self.dharma.evaluate("unregistered_action")
        self.assertFalse(result.allowed)
        self.assertFalse(result.requires_approval)

    def test_sandbox_rejects_traversal(self):
        self.assertFalse(self.dharma.evaluate("create_sandbox_file", "sandbox/../agent/main.py").allowed)


if __name__ == "__main__":
    unittest.main()
