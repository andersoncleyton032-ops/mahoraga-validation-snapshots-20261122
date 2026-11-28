import json
import os
import re
import sys
from pathlib import Path

import pytest

from scripts import validate_project

ROOT = Path(__file__).resolve().parents[1]


def test_build_plan_is_fixed_sequential_and_contains_all_quality_gates(tmp_path):
    plan = validate_project.build_plan("ci", tmp_path / "tests.xml")
    ids = [item["id"] for item in plan]

    assert ids == [
        "compile",
        "language_v1",
        "language_v2",
        "language_v3",
        "knowledge_retrieval",
        "prototype_plasticity",
        "continuity",
        "pytest_collect_only",
        "pytest",
    ]
    assert all(isinstance(item["command"], list) for item in plan)
    assert all(item["timeout_seconds"] > 0 for item in plan)
    for item in plan:
        if item["id"].startswith("language_"):
            command = item["command"]
            assert "--min-decision-accuracy" in command
            assert "--min-action-precision" in command
            assert "--min-action-recall" in command
            assert "--min-safe-nonexecution-rate" in command
            assert "--max-false-positives" in command
            assert "--max-future-action-leakage" in command
    assert "--collect-only" in plan[-2]["command"]
    assert plan[-2]["collection_scope"] == "full_repository"
    assert plan[-1]["command"][-1] == f"--junitxml={tmp_path / 'tests.xml'}"



def test_build_plan_visual_profile_collects_and_executes_only_governed_visual_suite(tmp_path):
    plan = validate_project.build_plan("visual", tmp_path / "visual.junit.xml")
    assert [item["id"] for item in plan] == [
        "compile", "pytest_collect_only", "pytest_visual",
    ]
    collection = plan[1]
    execution = plan[2]
    assert collection["collection_scope"] == "visual_suite"
    assert "--collect-only" in collection["command"]
    assert all(path in collection["command"] for path in validate_project.VISUAL_TEST_FILES)
    assert all(path in execution["command"] for path in validate_project.VISUAL_TEST_FILES)
    assert execution["command"][-1] == "--junitxml=" + str(tmp_path / "visual.junit.xml")


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("86 tests collected in 0.42s", 86),
        ("1 test collected in 0.01s", 1),
        ("no tests collected", 0),
        ("ERROR: collection failed", None),
    ],
)
def test_pytest_collection_count_uses_pytest_summary(output, expected):
    assert validate_project._pytest_collected_count(output) == expected


def test_build_plan_rejects_unknown_profile(tmp_path):
    with pytest.raises(ValueError, match="profile"):
        validate_project.build_plan("unbounded", tmp_path / "tests.xml")


def test_run_stage_reports_success_and_failure():
    success = validate_project._run_stage(
        [sys.executable, "-c", "print('ok')"], 5
    )
    failure = validate_project._run_stage(
        [sys.executable, "-c", "raise SystemExit(7)"], 5
    )

    assert success["status"] == "passed"
    assert "ok" in success["stdout_tail"]
    assert failure["status"] == "failed"
    assert failure["returncode"] == 7


def test_run_stage_bounds_time_and_output():
    timeout = validate_project._run_stage(
        [sys.executable, "-c", "import time; time.sleep(2)"], 1
    )
    output = validate_project._run_stage(
        [sys.executable, "-c", "print('x' * 20000)"], 5
    )

    assert timeout["status"] == "timeout"
    assert timeout["timed_out"] is True
    assert len(output["stdout_tail"]) <= validate_project.MAX_LOG_CHARS


def test_report_write_is_valid_json_and_replaces_atomically(tmp_path):
    destination = tmp_path / "reports" / "validation.json"
    report = {"schema": "mahoraga.validation_report", "summary": {"overall": "passed"}}

    validate_project.write_report(destination, report)

    assert json.loads(destination.read_text(encoding="utf-8")) == report
    assert list(destination.parent.glob("*.tmp")) == []


def test_report_write_rejects_symlink_destination(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="link simbólico"):
        validate_project.write_report(link, {"safe": True})


def test_fixture_fingerprints_are_stable_sha256_or_explicitly_missing():
    fingerprints = validate_project._fixture_fingerprints()

    assert set(fingerprints) == set(validate_project.FIXTURES)
    assert all(
        value is None or (
            isinstance(value, str) and len(value) == 64
        )
        for value in fingerprints.values()
    )


def test_run_validation_checkpoints_each_stage_and_marks_completion(monkeypatch, tmp_path):
    plan = validate_project.build_plan("ci", tmp_path / "out.junit.xml")
    calls = []

    def fake_stage(command, timeout):
        calls.append((command, timeout))
        stdout = ""
        if "--collect-only" in command:
            stdout = "1 test collected in 0.1s"
        elif "pytest" in command:
            stdout = "1 passed in 0.1s"
        return {
            "status": "passed",
            "returncode": 0,
            "duration_seconds": 0.001,
            "stdout_tail": stdout,
            "stderr_tail": "",
            "timed_out": False,
        }

    monkeypatch.setattr(validate_project, "_run_stage", fake_stage)
    monkeypatch.setattr(validate_project, "_git_value", lambda *args: "fixture")
    monkeypatch.setattr(validate_project, "_fixture_fingerprints", lambda: {})
    monkeypatch.setattr(validate_project, "_resource_snapshot", lambda: {})
    output = tmp_path / "reports" / "result.json"

    report = validate_project.run_validation("ci", output)

    assert len(calls) == len(plan)
    assert report["state"] == "completed"
    assert report["summary"]["overall"] == "passed"
    assert report["summary"]["stages_recorded"] == len(plan)
    assert report["summary"]["pytest_collection_status"] == "passed"
    assert report["summary"]["pytest_collected_cases"] == 1
    assert json.loads(output.read_text(encoding="utf-8"))["state"] == "completed"



def test_bounded_byte_tail_keeps_only_the_newest_bytes():
    tail = validate_project._BoundedByteTail(5)
    tail.append(b"abc")
    tail.append(b"def")

    assert tail.render(5) == "bcdef"
    assert tail._size == 5
    assert sum(len(part) for part in tail._parts) == 5


def test_run_stage_bounds_stdout_and_stderr_independently():
    script = (
        "import sys; "
        "sys.stdout.write('A' * 200000); sys.stdout.flush(); "
        "sys.stderr.write('B' * 200000); sys.stderr.flush()"
    )
    result = validate_project._run_stage([sys.executable, "-c", script], 10)

    assert result["status"] == "passed"
    assert len(result["stdout_tail"]) <= validate_project.MAX_LOG_CHARS
    assert len(result["stderr_tail"]) <= validate_project.MAX_LOG_CHARS
    assert result["stdout_tail"].endswith("A" * 100)
    assert result["stderr_tail"].endswith("B" * 100)
    assert result["output_capture"]["mode"] == "concurrent_pipe_drain_bounded_tail"
    assert result["output_capture"]["ram_buffer_bytes_per_stream"] == (
        validate_project.MAX_LOG_CHARS * 4
    )


def test_run_stage_handles_timeout_after_streaming_output():
    script = (
        "import sys, time; "
        "sys.stdout.write('progress' * 10000); sys.stdout.flush(); "
        "time.sleep(5)"
    )
    result = validate_project._run_stage([sys.executable, "-c", script], 1)

    assert result["status"] == "timeout"
    assert result["timed_out"] is True
    assert result["returncode"] is None
    assert len(result["stdout_tail"]) <= validate_project.MAX_LOG_CHARS



@pytest.mark.skipif(os.name != "posix", reason="process-group termination is POSIX-specific")
def test_run_stage_kills_descendant_that_keeps_pipes_open_after_parent_exit():
    child = "import time; time.sleep(30)"
    script = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "print('parent-exited', flush=True)"
    )

    result = validate_project._run_stage([sys.executable, "-c", script], 10)

    assert result["status"] == "passed"
    assert "parent-exited" in result["stdout_tail"]
    assert result["timed_out"] is False
    assert result["duration_seconds"] < 5
    assert result["output_capture"]["reader_threads_stopped"] is True



def test_ci_workflow_covers_stacked_fix_and_research_pr_bases():
    workflow = (ROOT / ".github" / "workflows" / "physics-tests.yml").read_text(
        encoding="utf-8"
    )
    pull_request = workflow.split("  pull_request:", 1)[1].split(
        "  paths:", 1
    )[0]
    assert '"fix/**"' in pull_request
    assert '"research/**"' in pull_request
    assert '"work/**"' in pull_request
    assert "timeout-minutes: 45" in workflow


def test_ci_job_timeout_covers_declared_sequential_stage_budgets():
    workflow = (ROOT / ".github" / "workflows" / "physics-tests.yml").read_text(
        encoding="utf-8"
    )
    test_job = workflow.split("  test:", 1)[1]
    timeout_match = re.search(r"timeout-minutes:\s*(\d+)", test_job)
    assert timeout_match is not None
    job_budget = int(timeout_match.group(1)) * 60

    from scripts.validate_project import build_plan

    plan = build_plan("ci", ROOT / "validation.junit.xml")
    declared_budget = sum(stage["timeout_seconds"] for stage in plan)
    assert job_budget >= declared_budget



def test_pytest_terminal_counts_accepts_quiet_and_verbose_summaries():
    assert validate_project._pytest_terminal_counts("149 passed in 1.03s")["passed"] == 149
    verbose = validate_project._pytest_terminal_counts(
        "=== 9 passed, 1 skipped in 0.50s ==="
    )
    assert verbose == {
        "passed": 9, "failed": 0, "errors": 0, "skipped": 1,
        "xfailed": 0, "xpassed": 0, "deselected": 0,
    }


def test_pytest_execution_does_not_promote_all_skipped_or_missing_summary():
    skipped = {
        "status": "passed", "stdout_tail": "12 skipped in 0.20s", "stderr_tail": "",
    }
    missing = {"status": "passed", "stdout_tail": "quiet output only", "stderr_tail": ""}
    failed = {
        "status": "passed", "stdout_tail": "1 failed, 2 passed in 0.30s",
        "stderr_tail": "",
    }
    assert validate_project._pytest_execution_evidence(skipped)[0] == "inconclusive"
    assert validate_project._pytest_execution_evidence(missing)[0] == "inconclusive"
    assert validate_project._pytest_execution_evidence(failed)[0] == "failed"


def test_full_core_profile_collects_the_entire_repository_with_extended_budget(tmp_path):
    plan = validate_project.build_plan("full-core", tmp_path / "full-core.junit.xml")
    collection, execution = plan[-2], plan[-1]
    assert collection["collection_scope"] == "full_repository"
    assert "--collect-only" in collection["command"]
    assert not any(path in collection["command"] for path in validate_project.VISUAL_TEST_FILES)
    assert execution["timeout_seconds"] == 1200


def test_run_validation_blocks_visual_execution_when_collection_fails(monkeypatch, tmp_path):
    calls = []

    def fake_stage(command, timeout):
        calls.append(command)
        if "--collect-only" in command:
            return {
                "status": "failed", "returncode": 2, "duration_seconds": 0.1,
                "stdout_tail": "", "stderr_tail": "collection failed", "timed_out": False,
            }
        return {
            "status": "passed", "returncode": 0, "duration_seconds": 0.1,
            "stdout_tail": "1 passed in 0.1s", "stderr_tail": "", "timed_out": False,
        }

    monkeypatch.setattr(validate_project, "_run_stage", fake_stage)
    monkeypatch.setattr(validate_project, "_git_value", lambda *args: "fixture")
    monkeypatch.setattr(validate_project, "_fixture_fingerprints", lambda: {})
    monkeypatch.setattr(validate_project, "_resource_snapshot", lambda: {})
    report = validate_project.run_validation("visual", tmp_path / "blocked.json")

    assert len(calls) == 2
    assert report["summary"]["pytest_collection_status"] == "failed"
    assert report["summary"]["overall"] == "failed"
    assert report["stages"][-1]["id"] == "pytest_visual"
    assert report["stages"][-1]["status"] == "blocked"


def test_run_validation_blocks_visual_execution_when_collection_count_is_unknown(
    monkeypatch, tmp_path,
):
    calls = []

    def fake_stage(command, timeout):
        calls.append(command)
        output = "" if "--collect-only" in command else "1 passed in 0.1s"
        return {
            "status": "passed", "returncode": 0, "duration_seconds": 0.1,
            "stdout_tail": output, "stderr_tail": "", "timed_out": False,
        }

    monkeypatch.setattr(validate_project, "_run_stage", fake_stage)
    monkeypatch.setattr(validate_project, "_git_value", lambda *args: "fixture")
    monkeypatch.setattr(validate_project, "_fixture_fingerprints", lambda: {})
    monkeypatch.setattr(validate_project, "_resource_snapshot", lambda: {})
    report = validate_project.run_validation("visual", tmp_path / "unknown.json")

    assert len(calls) == 2
    assert report["summary"]["pytest_collection_status"] == "inconclusive"
    assert report["summary"]["overall"] == "inconclusive"
    assert report["stages"][-1]["status"] == "blocked"


def test_run_validation_marks_all_skipped_visual_suite_inconclusive(monkeypatch, tmp_path):
    def fake_stage(command, timeout):
        if "--collect-only" in command:
            output, status = "1 test collected in 0.1s", "passed"
        elif "pytest" in command:
            output, status = "1 skipped in 0.1s", "passed"
        else:
            output, status = "", "passed"
        return {
            "status": status, "returncode": 0, "duration_seconds": 0.1,
            "stdout_tail": output, "stderr_tail": "", "timed_out": False,
        }

    monkeypatch.setattr(validate_project, "_run_stage", fake_stage)
    monkeypatch.setattr(validate_project, "_git_value", lambda *args: "fixture")
    monkeypatch.setattr(validate_project, "_fixture_fingerprints", lambda: {})
    monkeypatch.setattr(validate_project, "_resource_snapshot", lambda: {})
    report = validate_project.run_validation("visual", tmp_path / "skipped.json")

    assert report["stages"][-1]["status"] == "inconclusive"
    assert report["summary"]["overall"] == "inconclusive"


def test_pytest_terminal_counts_normalizes_error_and_rejects_unexpected_passes():
    counts = validate_project._pytest_terminal_counts(
        "1 error, 2 xpassed in 0.2s"
    )
    assert counts is not None
    assert counts["errors"] == 1
    assert counts["xpassed"] == 2
    assert validate_project._pytest_execution_evidence({
        "status": "passed",
        "stdout_tail": "1 error, 2 xpassed in 0.2s",
        "stderr_tail": "",
    })[0] == "failed"
