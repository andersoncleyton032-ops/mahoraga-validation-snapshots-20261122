from pathlib import Path

from agent import actions, main, memory


def test_package_entrypoint_imports_integrated_core():
    assert main.Mahoraga.__name__ == "Mahoraga"
    assert main.IntegratedCore.__name__ == "IntegratedCore"


def test_persistent_paths_are_scoped_to_the_checked_out_lab(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(memory, "_STORE", None)
    store = memory.get_store()

    assert Path(actions.LOG_FILE).resolve().is_relative_to(root)
    assert store.db_path.resolve().is_relative_to(root)
