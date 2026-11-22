from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lab_documents_define_isolation_and_non_promotion():
    charter = (ROOT / "docs" / "LAB_CHARTER.md").read_text(encoding="utf-8")
    contract = (ROOT / "docs" / "AUTONOMOUS_EVOLUTION_CONTRACT.md").read_text(encoding="utf-8")
    assert "private source repository" in charter
    assert "no automatic" in charter.lower()
    assert "does not discover new candidates" in contract
    assert "does not" in contract and "persist its state" in contract
    assert "No automatic production promotion" in contract


def test_source_manifest_documents_private_state_exclusions():
    manifest = (ROOT / "docs" / "SOURCE_MANIFEST.md").read_text(encoding="utf-8")
    assert "memory/data.json" in manifest
    assert "logs/activity.log" in manifest
    assert "curated baseline" in manifest


def test_local_memory_and_activity_files_are_ignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "memory/data.json" in ignored
    assert "logs/activity.log" in ignored
