import unittest
from pathlib import Path
from agent.dharma import Dharma


class TestDharma(unittest.TestCase):
    def setUp(self):
        self.dharma = Dharma()

    def test_safe_action_is_allowed(self):
        result = self.dharma.evaluate("read_project")
        self.assertTrue(result.allowed)
        self.assertFalse(result.requires_approval)

    def test_valid_sandbox_action_is_allowed(self):
        result = self.dharma.evaluate(
            "create_sandbox_file", "sandbox/workspace/test.py"
        )
        self.assertTrue(result.allowed)

    def test_invalid_sandbox_path_is_rejected(self):
        paths = [
            "../agent/main.py",
            "/agent/main.py",
            "sandbox/../agent/main.py",
            "",
            None,
            123,
            "sandbox/.",
            "sandbox",
            "sandbox//file.py",
        ]
        for path in paths:
            with self.subTest(path=path):
                result = self.dharma.evaluate(
                    "create_sandbox_file", path
                )
                self.assertFalse(result.allowed)


    def test_symbolic_link_is_rejected(self):
        link = Path("sandbox/workspace/link_to_agent")
        try:
            link.symlink_to(
                Path("agent").resolve(),
                target_is_directory=True
            )
            result = self.dharma.evaluate(
                "create_sandbox_file",
                "sandbox/workspace/link_to_agent/main.py"
            )
            self.assertFalse(result.allowed)
        finally:
            if link.is_symlink():
                link.unlink()

    def test_sensitive_action_requires_approval(self):
        result = self.dharma.evaluate("install_package")
        self.assertFalse(result.allowed)
        self.assertTrue(result.requires_approval)

    def test_protected_action_requires_human_review(self):
        result = self.dharma.evaluate("modify_policy")
        self.assertFalse(result.allowed)
        self.assertTrue(result.requires_approval)

    def test_unknown_action_is_blocked(self):
        result = self.dharma.evaluate("unknown_action")
        self.assertFalse(result.allowed)
        self.assertFalse(result.requires_approval)


if __name__ == "__main__":
    unittest.main()
