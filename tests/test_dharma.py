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
        created_by_test = False
        try:
            link.symlink_to(
                Path("agent").resolve(),
                target_is_directory=True
            )
            created_by_test = True
            result = self.dharma.evaluate(
                "create_sandbox_file",
                "sandbox/workspace/link_to_agent/main.py"
            )
            self.assertFalse(result.allowed)
        finally:
            if created_by_test and link.is_symlink():
                link.unlink()

    def test_sensitive_action_requires_approval(self):
        result = self.dharma.evaluate("install_package")
        self.assertFalse(result.allowed)
        self.assertTrue(result.requires_approval)

    def test_protected_action_requires_human_review(self):
        result = self.dharma.evaluate("modify_policy")
        self.assertFalse(result.allowed)
        self.assertTrue(result.requires_approval)


    def test_blender_python_rejects_caller_supplied_boolean(self):
        result = self.dharma.evaluate(
            "blender_python_execute",
            context={
                "human_approved": True,
                "scope": "blender_python",
                "approval_payload": {"script": "print('hello')"},
            },
        )
        self.assertFalse(result.allowed)
        self.assertTrue(result.requires_approval)

    def test_blender_python_requires_one_shot_verified_attestation(self):
        class FakeApprovalVerifier:
            def __init__(self):
                self.used = set()

            def consume_attestation(self, *, attestation, action, subject_sha256):
                if not isinstance(attestation, dict) or attestation.get("approved") is not True:
                    return False
                nonce = attestation.get("nonce")
                if not isinstance(nonce, str) or not nonce or nonce in self.used:
                    return False
                self.used.add(nonce)
                return True

        verifier = FakeApprovalVerifier()
        dharma = Dharma(approval_verifier=verifier)
        context = {
            "approval_attestation": {"approved": True, "nonce": "one-shot"},
            "scope": "blender_python",
            "approval_payload": {"script": "print('hello')"},
        }
        first = dharma.evaluate("blender_python_execute", context=context)
        replay = dharma.evaluate("blender_python_execute", context=context)
        self.assertTrue(first.allowed)
        self.assertFalse(replay.allowed)

    def test_unknown_action_is_blocked(self):
        result = self.dharma.evaluate("unknown_action")
        self.assertFalse(result.allowed)
        self.assertFalse(result.requires_approval)


if __name__ == "__main__":
    unittest.main()



def test_sandbox_symlink_escape_is_rejected(tmp_path):
    sandbox_workspace = Path(__file__).resolve().parents[1] / "sandbox" / "workspace"
    sandbox_workspace.mkdir(parents=True, exist_ok=True)
    link = sandbox_workspace / f"escape-{tmp_path.name}"
    link.symlink_to(tmp_path, target_is_directory=True)
    try:
        result = Dharma().evaluate(
            "create_sandbox_file", f"sandbox/workspace/{link.name}/payload.py"
        )
        assert not result.allowed
        assert result.requires_approval
    finally:
        link.unlink(missing_ok=True)
