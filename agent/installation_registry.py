"""Auditable registry of installed software and acquisition provenance."""
from __future__ import annotations
from .memory import get_store


class InstallationRegistry:
    def __init__(self, store=None):
        self.store = store or get_store()

    def record(self, *, installation_id: str, name: str, version: str | None,
               method: str, purpose: str, source_url: str | None = None,
               source_ref: str | None = None, installed_at: str | None = None,
               verification: str = "not_verified", license: str | None = None,
               notes: dict | None = None) -> bool:
        return self.store.record_installation(installation_id, name, version, method,
            source_url, source_ref, installed_at, purpose, verification, license, notes)

    def list_all(self) -> list[dict]:
        return self.store.list_installations()
