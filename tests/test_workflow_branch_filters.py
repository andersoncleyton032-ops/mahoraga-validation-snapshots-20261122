"""Guard workflow branch filters for stacked pull requests."""

from fnmatch import fnmatchcase
from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    REPOSITORY_ROOT / ".github" / "workflows" / "physics-tests.yml",
    REPOSITORY_ROOT / ".github" / "workflows" / "core-regression.yml",
)
ACTIVE_STACKED_BASE = "feat/visual-document-model-20261125-rebased"


def _pull_request_branch_patterns(workflow_path: Path) -> tuple[str, ...]:
    source = workflow_path.read_text(encoding="utf-8")
    section = re.search(
        r"(?ms)^  pull_request:\s*\n(?P<body>.*?)(?=^[A-Za-z_][A-Za-z0-9_-]*:|\Z)",
        source,
    )
    assert section is not None, f"pull_request block missing in {workflow_path.name}"
    branches = re.search(
        r"(?m)^    branches:\s*\[(?P<items>[^\]]*)\]",
        section.group("body"),
    )
    assert branches is not None, f"inline pull_request.branches missing in {workflow_path.name}"
    return tuple(
        item.strip().strip("\"'")
        for item in branches.group("items").split(",")
        if item.strip()
    )


def test_stacked_visual_feature_base_is_covered_by_both_ci_workflows():
    for workflow_path in WORKFLOWS:
        patterns = _pull_request_branch_patterns(workflow_path)
        assert any(fnmatchcase(ACTIVE_STACKED_BASE, pattern) for pattern in patterns), (
            f"{workflow_path.name} will not run for pull requests targeting "
            f"{ACTIVE_STACKED_BASE!r}; pull_request.branches filters the base branch"
        )
