from pathlib import Path


def test_snapshot_workflow_requires_android_and_shizuku_junit_evidence():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "snapshot-tests.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("raise SystemExit(1)") >= 2
    assert workflow.count('totals["tests"] == 0') >= 2
    assert workflow.count('totals["skipped"] == totals["tests"]') >= 2
    assert workflow.count("if-no-files-found: error") >= 2
