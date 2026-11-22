from pathlib import Path

from agent import actions, lab, memory, main


def test_package_entrypoint_imports_without_ambiguous_top_level_imports():
    assert main.Mahoraga.__name__ == "Mahoraga"


def test_persistent_paths_are_scoped_to_the_checked_out_lab():
    root = Path(__file__).resolve().parents[1]
    for target in (actions.LOG_FILE, lab.LAB_FILE, memory.MEMORY_FILE):
        assert Path(target).resolve().is_relative_to(root)
