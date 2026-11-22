"""Backward-compatible memory API backed by the unified SQLite store."""
from __future__ import annotations
from pathlib import Path
from .store import KnowledgeStore

_ROOT = Path(__file__).resolve().parent.parent
_STORE: KnowledgeStore | None = None


def get_store() -> KnowledgeStore:
    global _STORE
    if _STORE is None:
        _STORE = KnowledgeStore()
        _STORE.import_legacy_file(_ROOT / "memory" / "data.json", "memory")
        _STORE.import_legacy_file(_ROOT / "experiments" / "experiments.json", "experiments")
    return _STORE


def save_memory(key, value, metadata=None):
    return get_store().save_memory(key, value, metadata)


def load_memory():
    return get_store().load_memories()


def record_learning(topic: str, learning, source: str = "internal"):
    store = get_store()
    store.save_memory(f"learning:{topic}", learning, {"source": source})
    return store.record_event("learning.recorded", {"topic": topic, "source": source})
