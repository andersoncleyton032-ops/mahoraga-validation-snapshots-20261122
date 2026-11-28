"""Reproducible, GitHub-independent validation pipeline for Mahoraga.

Run with:
    python scripts/validate_project.py --profile ci
    python scripts/validate_project.py --profile device
    python scripts/validate_project.py --profile visual

The pipeline uses a fixed command allowlist, runs sequentially, applies time
budgets, preserves bounded logs, and writes an atomic machine-readable report.
It does not install dependencies, contact remote services, or modify production
memory/checkpoints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import signal
from collections import deque
from threading import Lock, Thread
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
MAX_LOG_CHARS = 16_000
PIPE_DRAIN_GRACE_SECONDS = 2.0
PIPE_CLEANUP_GRACE_SECONDS = 1.0
VISUAL_TEST_FILES = (
    "tests/test_visual_creation.py",
    "tests/test_visual_document_store.py",
    "tests/test_visual_scene_compiler.py",
    "tests/test_visual_document_lab.py",
    "tests/test_visual_document_lab_integration.py",
    "tests/test_image_task_executor.py",
    "tests/test_image_generation.py",
)
FIXTURES = (
    "tests/fixtures/language_training_seed_v1.json",
    "tests/fixtures/language_training_seed_v2.json",
    "tests/fixtures/language_regression_v2.json",
    "tests/fixtures/language_regression_v3.json",
    "tests/fixtures/knowledge_retrieval_v1.json",
)


def _python() -> str:
    return sys.executable


def build_plan(profile: str, junit_path: Path) -> list[dict[str, Any]]:
    """Return the immutable, sequential validation plan."""
    if profile not in {"ci", "device", "visual", "full-core"}:
        raise ValueError("profile precisa ser 'ci', 'device', 'visual' ou 'full-core'.")
    eval_timeout = 240 if profile == "ci" else 600
    test_timeout = 600 if profile == "ci" else 1200 if profile == "full-core" else 1800
    plan = [
        {
            "id": "compile",
            "purpose": "Verificar sintaxe e compilabilidade dos módulos e testes.",
            "command": [_python(), "-m", "compileall", "-q", "agent", "tests", "scripts"],
            "timeout_seconds": 120,
        },
        {
            "id": "language_v1",
            "purpose": "Baseline linguístico com treinamento temporário isolado.",
            "command": [
                _python(), "scripts/evaluate_language_regression.py",
                "--training-seed", "tests/fixtures/language_training_seed_v1.json",
                "--min-decision-accuracy", "0.95",
                "--min-action-precision", "0.95",
                "--min-action-recall", "0.80",
                "--min-safe-nonexecution-rate", "0.95",
                "--max-false-positives", "0",
                "--max-future-action-leakage", "0",
            ],
            "timeout_seconds": eval_timeout,
        },
        {
            "id": "language_v2",
            "purpose": "Holdout independente de linguagem v2.",
            "command": [
                _python(), "scripts/evaluate_language_regression.py",
                "--cases", "tests/fixtures/language_regression_v2.json",
                "--training-seed", "tests/fixtures/language_training_seed_v2.json",
                "--min-decision-accuracy", "0.95",
                "--min-action-precision", "0.95",
                "--min-action-recall", "0.80",
                "--min-safe-nonexecution-rate", "0.95",
                "--max-false-positives", "0",
                "--max-future-action-leakage", "0",
            ],
            "timeout_seconds": eval_timeout,
        },
        {
            "id": "language_v3",
            "purpose": "Holdout adversarial expandido v3.",
            "command": [
                _python(), "scripts/evaluate_language_regression.py",
                "--cases", "tests/fixtures/language_regression_v3.json",
                "--training-seed", "tests/fixtures/language_training_seed_v2.json",
                "--min-decision-accuracy", "0.95",
                "--min-action-precision", "0.95",
                "--min-action-recall", "0.80",
                "--min-safe-nonexecution-rate", "0.95",
                "--max-false-positives", "0",
                "--max-future-action-leakage", "0",
            ],
            "timeout_seconds": eval_timeout,
        },
        {
            "id": "knowledge_retrieval",
            "purpose": "Baseline de recuperação lexical e métricas de lacunas.",
            "command": [
                _python(), "scripts/evaluate_knowledge_retrieval.py",
                "--suite", "tests/fixtures/knowledge_retrieval_v1.json",
                "--k", "3", "--min-lexical-recall", "0.95",
                "--min-lexical-mrr", "0.95",
            ],
            "timeout_seconds": eval_timeout,
        },
        {
            "id": "prototype_plasticity",
            "purpose": "Adaptação, retenção, novidade e replay em fixture sintética.",
            "command": [_python(), "-m", "scripts.evaluate_prototype_plasticity"],
            "timeout_seconds": eval_timeout,
        },
        {
            "id": "continuity",
            "purpose": "Consistência dos registros canônicos de continuidade.",
            "command": [_python(), "scripts/validate_continuity.py"],
            "timeout_seconds": 60,
        },
        {
            "id": "pytest",
            "purpose": "Suíte integral de testes unitários, integração e regressão.",
            "command": [
                _python(), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                f"--junitxml={junit_path}",
            ],
            "timeout_seconds": test_timeout,
        },
    ]

    collection_stage = {
        "id": "pytest_collect_only",
        "purpose": (
            "Coletar os casos reais do pytest sem executar testes; "
            "a contagem é registrada separadamente do inventário estático."
        ),
        "command": [
            _python(), "-m", "pytest", "--collect-only", "-q",
            "-p", "no:cacheprovider",
            *(VISUAL_TEST_FILES if profile == "visual" else []),
        ],
        "timeout_seconds": 300 if profile == "ci" else 600,
        "collection_scope": "visual_suite" if profile == "visual" else "full_repository",
    }
    if profile == "visual":
        visual_stage = {
            "id": "pytest_visual",
            "purpose": (
                "Executar a cadeia visual headless, incluindo persistência, "
                "compilador, selector, executor e integração full-core."
            ),
            "command": [
                _python(), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                *VISUAL_TEST_FILES, f"--junitxml={junit_path}",
            ],
            "timeout_seconds": 1200,
        }
        return [plan[0], collection_stage, visual_stage]

    plan.insert(-1, collection_stage)
    return plan


def _pytest_collected_count(stdout: str, stderr: str = "") -> int | None:
    """Extract pytest's own collection summary; never infer from source declarations."""
    output = (stdout or "") + "\n" + (stderr or "")
    match = re.search(r"(?m)^\s*(\d+)\s+tests?\s+collected\b", output)
    if match:
        return int(match.group(1))
    if re.search(r"(?m)^\s*no tests (?:collected|ran)\b", output):
        return 0
    return None


_PYTEST_SUMMARY_LINE = re.compile(
    r"^\s*(?:=+\s*)?(?P<body>.*?)\s+in\s+\d+(?:\.\d+)?s(?:\s*=+)?\s*$"
)


def _pytest_terminal_counts(output: str) -> dict[str, int] | None:
    """Parse both pytest -q and verbose terminal summaries."""
    for line in reversed((output or "").splitlines()):
        match = _PYTEST_SUMMARY_LINE.match(line)
        if not match:
            continue
        counts = {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "xfailed": 0,
            "xpassed": 0,
            "deselected": 0,
        }
        found = False
        for raw_count, raw_label in re.findall(
            r"(?<!\w)(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b",
            match.group("body"),
            flags=re.IGNORECASE,
        ):
            label = raw_label.lower()
            label = "errors" if label in {"error", "errors"} else label
            counts[label] += int(raw_count)
            found = True
        if found:
            return counts
    return None


def _pytest_execution_evidence(result: dict[str, Any]) -> tuple[str, dict[str, int] | None]:
    """A zero exit code is insufficient without a real passing pytest summary."""
    if result.get("status") != "passed":
        return str(result.get("status", "execution_error")), None
    output = (result.get("stdout_tail") or "") + "\n" + (result.get("stderr_tail") or "")
    counts = _pytest_terminal_counts(output)
    if counts is None:
        return "inconclusive", None
    if counts["failed"] or counts["errors"] or counts["xpassed"]:
        return "failed", counts
    if counts["passed"] <= 0:
        return "inconclusive", counts
    return "passed", counts


def _git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _validate_validation_checkout(
    output: Path, junit_path: Path, source_snapshot: dict[str, Any],
) -> None:
    """Require an identified, clean checkout and report files outside it."""
    commit = source_snapshot.get("git_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Visual/full-core exige HEAD Git válido e identificado.")
    if source_snapshot.get("git_root") != str(ROOT.resolve()):
        raise ValueError("Visual/full-core exige a raiz real do repositório Git.")
    working_tree = source_snapshot.get("working_tree")
    if not isinstance(working_tree, str) or working_tree:
        raise ValueError("Visual/full-core exige working tree limpa.")
    repository_root = ROOT.resolve()
    for path in (output, junit_path):
        if path.is_symlink():
            raise ValueError("Relatórios de validação não podem ser links simbólicos.")
        resolved = path.parent.resolve() / path.name
        if resolved.is_relative_to(repository_root):
            raise ValueError("Relatórios visual/full-core devem ficar fora do checkout.")


def _fixture_fingerprints() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for relative in FIXTURES:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            result[relative] = None
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65_536), b""):
                digest.update(chunk)
        result[relative] = digest.hexdigest()
    return result


def _resource_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
    }
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        try:
            for line in meminfo.read_text(encoding="ascii").splitlines():
                if line.startswith(("MemTotal:", "MemAvailable:")):
                    key, value = line.split(":", 1)
                    snapshot[key] = value.strip()
        except (OSError, UnicodeError):
            snapshot["proc_meminfo_readable"] = False
    return snapshot



class _BoundedByteTail:
    """Thread-safe byte tail whose memory use never exceeds its configured cap."""

    def __init__(self, max_bytes: int):
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("max_bytes deve ser inteiro positivo.")
        self.max_bytes = max_bytes
        self._parts: deque[bytes] = deque()
        self._size = 0
        self._lock = Lock()

    def append(self, chunk: bytes) -> None:
        if not isinstance(chunk, bytes):
            raise TypeError("O buffer aceita somente bytes.")
        if not chunk:
            return
        with self._lock:
            if len(chunk) >= self.max_bytes:
                self._parts.clear()
                self._parts.append(chunk[-self.max_bytes:])
                self._size = self.max_bytes
                return
            self._parts.append(chunk)
            self._size += len(chunk)
            while self._size > self.max_bytes and self._parts:
                excess = self._size - self.max_bytes
                first = self._parts[0]
                if len(first) <= excess:
                    self._parts.popleft()
                    self._size -= len(first)
                else:
                    self._parts[0] = first[excess:]
                    self._size -= excess

    def render(self, max_chars: int = MAX_LOG_CHARS) -> str:
        with self._lock:
            raw = b"".join(self._parts)
        return raw.decode("utf-8", errors="replace")[-max_chars:]


def _drain_pipe(stream, tail: _BoundedByteTail) -> None:
    """Continuously drain a child pipe while retaining only a bounded tail."""
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            tail.append(chunk)
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _kill_process_tree(process: subprocess.Popen) -> None:
    """Terminate the validation process group, even if its leader already exited.

    A descendant may inherit stdout/stderr and keep a reader thread blocked
    after the immediate child has exited. On POSIX the process group remains
    addressable by the original PID while any member is alive, so do not use
    process.poll() as a reason to skip group termination.
    """
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
    elif process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def _run_stage(
    command: Sequence[str],
    timeout_seconds: int,
    *,
    cwd: Path = ROOT,
) -> dict[str, Any]:
    """Run one allowlisted stage with bounded RAM for captured output."""
    started = time.monotonic()
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["MAHORAGA_VALIDATION_SUITE"] = "1"
    stdout_tail = _BoundedByteTail(MAX_LOG_CHARS * 4)
    stderr_tail = _BoundedByteTail(MAX_LOG_CHARS * 4)
    process = None
    readers: list[Thread] = []

    try:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=(os.name == "posix"),
        )
        if process.stdout is None or process.stderr is None:
            raise OSError("Não foi possível criar os canais de saída do processo.")

        readers = [
            Thread(target=_drain_pipe, args=(process.stdout, stdout_tail), daemon=True),
            Thread(target=_drain_pipe, args=(process.stderr, stderr_tail), daemon=True),
        ]
        for reader in readers:
            reader.start()

        timed_out = False
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(process)
            returncode = process.wait()

        drain_deadline = time.monotonic() + PIPE_DRAIN_GRACE_SECONDS
        for reader in readers:
            reader.join(timeout=max(0.0, drain_deadline - time.monotonic()))

        if any(reader.is_alive() for reader in readers):
            _kill_process_tree(process)
            for stream in (process.stdout, process.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
            cleanup_deadline = time.monotonic() + PIPE_CLEANUP_GRACE_SECONDS
            for reader in readers:
                reader.join(timeout=max(0.0, cleanup_deadline - time.monotonic()))

        readers_stopped = not any(reader.is_alive() for reader in readers)
        stdout = stdout_tail.render()
        stderr = stderr_tail.render()
        if timed_out:
            status = "timeout"
        elif not readers_stopped:
            status = "execution_error"
            stderr = (stderr + "\\n" if stderr else "") + (
                "Os canais de saída não foram encerrados após o limite de limpeza."
            )
        else:
            status = "passed" if returncode == 0 else "failed"
        return {
            "status": status,
            "returncode": None if timed_out else returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": stdout,
            "stderr_tail": stderr,
            "timed_out": timed_out,
            "output_capture": {
                "reader_threads_stopped": readers_stopped,
                "mode": "concurrent_pipe_drain_bounded_tail",
                "max_chars_per_stream": MAX_LOG_CHARS,
                "ram_buffer_bytes_per_stream": MAX_LOG_CHARS * 4,
            },
        }
    except OSError as exc:
        if process is not None:
            _kill_process_tree(process)
            try:
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for stream in (
            process.stdout if process is not None else None,
            process.stderr if process is not None else None,
        ):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        for reader in readers:
            reader.join(timeout=1)
        return {
            "status": "execution_error",
            "returncode": None,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": stdout_tail.render(),
            "stderr_tail": stderr_tail.render(),
            "timed_out": False,
            "output_capture": {
                "mode": "concurrent_pipe_drain_bounded_tail",
                "max_chars_per_stream": MAX_LOG_CHARS,
                "ram_buffer_bytes_per_stream": MAX_LOG_CHARS * 4,
            },
            "error": f"{type(exc).__name__}: {exc}",
        }


def write_report(path: Path, report: dict[str, Any]) -> None:
    """Write a report atomically without following a final-component symlink."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Destino do relatório não pode ser link simbólico.")
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def run_validation(profile: str, output: Path) -> dict[str, Any]:
    output = Path(output).expanduser()
    if not output.is_absolute():
        output = Path.cwd() / output
    junit_path = output.with_suffix(".junit.xml")
    plan = build_plan(profile, junit_path)
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    stages: list[dict[str, Any]] = []
    current_stage: str | None = None
    current_stage_started_at: str | None = None
    source_snapshot = {
        "git_root": _git_value("rev-parse", "--show-toplevel"),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_branch": _git_value("branch", "--show-current"),
        "working_tree": _git_value("status", "--short", "--untracked-files=all"),
        "fixture_sha256": _fixture_fingerprints(),
    }
    if profile in {"visual", "full-core"}:
        _validate_validation_checkout(output, junit_path, source_snapshot)
    output.parent.mkdir(parents=True, exist_ok=True)
    environment_snapshot = _resource_snapshot()

    def snapshot(final: bool) -> dict[str, Any]:
        non_passed = [item["id"] for item in stages if item["status"] != "passed"]
        hard_failed = any(
            item["status"] in {"failed", "timeout", "execution_error"}
            for item in stages
        )
        overall = (
            "passed" if final and not non_passed
            else "failed" if final and hard_failed
            else "inconclusive" if final
            else "running"
        )
        collection_stage = next(
            (item for item in stages if item["id"] == "pytest_collect_only"),
            None,
        )
        collection_status = (
            collection_stage["status"] if collection_stage is not None else "pending"
        )
        collected_cases = (
            collection_stage.get("collected_cases")
            if collection_stage is not None else None
        )
        return {
            "schema": "mahoraga.validation_report",
            "schema_version": 1,
            "profile": profile,
            "state": "completed" if final else "running",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat() if final else None,
            "duration_seconds": round(time.monotonic() - started, 3),
            "current_stage": current_stage,
            "current_stage_started_at": current_stage_started_at,
            "source": source_snapshot,
            "environment": environment_snapshot,
            "summary": {
                "stage_count": len(plan) + (
                    1 if profile in {"visual", "full-core"} else 0
                ),
                "stages_recorded": len(stages),
                "passed": sum(item["status"] == "passed" for item in stages),
                "failed": sum(item["status"] == "failed" for item in stages),
                "timed_out": sum(item["status"] == "timeout" for item in stages),
                "execution_errors": sum(item["status"] == "execution_error" for item in stages),
                "inconclusive": sum(item["status"] == "inconclusive" for item in stages),
                "blocked": sum(item["status"] == "blocked" for item in stages),
                "pytest_collection_status": collection_status,
                "pytest_collected_cases": collected_cases,
                "failed_stage_ids": non_passed,
                "overall": overall,
            },
            "stages": list(stages),
            "interpretation": [
                "A successful run demonstrates only the tested commit, environment, fixtures and checks.",
                "Synthetic benchmarks do not establish generalization to unseen real-world data.",
                "A test pass is evidence, not proof of absence of defects.",
                "Device validation must be run on the target Android/Termux environment separately.",
            ],
            "artifacts": {
                "junit_xml": str(junit_path),
                "report_json": str(output),
            },
        }

    # Persist a checkpoint before the first process and after every stage. If
    # Android kills the process or power is lost, the last completed evidence
    # remains available and is explicitly marked as an incomplete run.
    write_report(output, snapshot(final=False))
    collection_gate_passed = False
    collection_gate_reason = "pytest collection has not completed"
    for item in plan:
        current_stage = item["id"]
        current_stage_started_at = datetime.now(timezone.utc).isoformat()
        write_report(output, snapshot(final=False))

        is_pytest_execution = item["id"] in {"pytest", "pytest_visual"}
        if is_pytest_execution and not collection_gate_passed:
            result = {
                "status": "blocked",
                "returncode": None,
                "duration_seconds": 0.0,
                "stdout_tail": "",
                "stderr_tail": "",
                "timed_out": False,
                "blocked_by": "pytest_collect_only",
                "reason": collection_gate_reason,
            }
        else:
            result = _run_stage(item["command"], item["timeout_seconds"])

        if item["id"] == "pytest_collect_only":
            count = _pytest_collected_count(
                result.get("stdout_tail", ""),
                result.get("stderr_tail", ""),
            )
            result["collected_cases"] = count
            result["collection_scope"] = item["collection_scope"]
            if result.get("status") == "passed" and count is not None and count > 0:
                collection_gate_passed = True
                result["collection_gate"] = "open"
            else:
                if result.get("status") == "passed":
                    result["status"] = "inconclusive"
                    result["error"] = "pytest did not report a positive collected-case count"
                collection_gate_reason = (
                    "pytest collection failed or did not produce a positive, parseable count"
                )
                result["collection_gate"] = "closed"

        if is_pytest_execution and result.get("status") == "passed":
            pytest_status, pytest_counts = _pytest_execution_evidence(result)
            result["status"] = pytest_status
            result["pytest_counts"] = pytest_counts

        stages.append({
            "id": item["id"],
            "purpose": item["purpose"],
            "command": item["command"],
            "timeout_seconds": item["timeout_seconds"],
            **result,
        })
        current_stage = None
        current_stage_started_at = None
        write_report(output, snapshot(final=False))

    if profile in {"visual", "full-core"}:
        try:
            commit_after = _git_value("rev-parse", "HEAD")
            working_tree_after = _git_value(
                "status", "--short", "--untracked-files=all"
            )
            source_snapshot["git_commit_after"] = commit_after
            source_snapshot["working_tree_after"] = working_tree_after
            integrity_ok = (
                commit_after == source_snapshot["git_commit"]
                and working_tree_after == ""
            )
            stages.append({
                "id": "checkout_integrity",
                "status": "passed" if integrity_ok else "failed",
                "reason": None if integrity_ok else (
                    "HEAD mudou ou working tree foi alterada durante a validação."
                ),
                "git_commit_after": commit_after,
                "working_tree_after": working_tree_after,
            })
        except Exception as exc:
            source_snapshot["git_commit_after"] = None
            source_snapshot["working_tree_after"] = None
            stages.append({
                "id": "checkout_integrity",
                "status": "execution_error",
                "reason": str(exc),
            })

    report = snapshot(final=True)
    write_report(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("ci", "device", "visual", "full-core"), default="ci")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.output is None:
        if args.profile in {"visual", "full-core"}:
            args.output = (
                Path(tempfile.gettempdir()) / "mahoraga-validation"
                / f"{args.profile}.json"
            )
        else:
            args.output = ROOT / "sandbox" / "validation" / "latest.json"
    report = run_validation(args.profile, args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Relatório: {args.output}")
    print(f"JUnit: {args.output.with_suffix('.junit.xml')}")
    return 0 if report["summary"]["overall"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
