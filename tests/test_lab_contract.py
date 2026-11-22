from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lab_documents_define_isolation_and_non_promotion():
    charter = (ROOT / "docs" / "LAB_CHARTER.md").read_text(encoding="utf-8")
    contract = (ROOT / "docs" / "AUTONOMOUS_EVOLUTION_CONTRACT.md").read_text(encoding="utf-8")
    assert "private source repository" in charter
    assert "no automatic" in charter.lower()
    assert "does not discover candidates" in contract
    assert "persist state" in contract
    assert "Never promote automatically to production" in contract


def test_source_manifest_documents_private_state_exclusions():
    manifest = (ROOT / "docs" / "SOURCE_MANIFEST.md").read_text(encoding="utf-8")
    assert "memory/data.json" in manifest
    assert "logs/activity.log" in manifest
    assert "reviewed allowlist" in manifest
    assert "blender_python_executor.py" in manifest


def test_publication_policy_excludes_private_runtime_data_and_execution_surface():
    policy = (ROOT / "docs" / "PUBLICATION_POLICY.md").read_text(encoding="utf-8")
    assert "local databases" in policy
    assert "credentials" in policy
    assert "arbitrary code execution" in policy


def test_local_memory_and_activity_files_are_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "memory/data.json" in ignored
    assert "logs/activity.log" in ignored
