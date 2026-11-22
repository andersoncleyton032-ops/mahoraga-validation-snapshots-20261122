import pytest

from agent.store import KnowledgeStore


def definition(**overrides):
    data = {
        "name": "Processamento matemático",
        "purpose": "Executar operações matemáticas locais.",
        "version": "1.0.0",
        "risk": "local_compute",
        "maturity_state": "implemented",
        "source_module": "agent.math_tools",
        "operations": ["add", "multiply"],
        "inputs": {"a": "number", "b": "number"},
        "outputs": {"result": "number"},
        "dependencies": ["python"],
        "tools": [],
        "limitations": ["Somente operações numéricas."],
        "resource_requirements": {"network": False},
        "validation": {"unit_tests": False, "integration_tests": False},
        "enabled": True,
        "metadata": {"origin": "unit_test"},
    }
    data.update(overrides)
    return data


def test_capability_catalog_migration_is_registered(tmp_path):
    store = KnowledgeStore(tmp_path / "catalog.sqlite3")

    with store._reader() as db:
        versions = [
            row["version"]
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        table = db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='capabilities'"
        ).fetchone()

    assert versions == [1, 2, 3, 4, 5, 6]
    assert table is not None


def test_capability_catalog_round_trip(tmp_path):
    store = KnowledgeStore(tmp_path / "catalog.sqlite3")
    record = definition()

    assert store.upsert_capability("math.basic", record) is True

    items = store.list_capabilities()
    assert len(items) == 1

    saved = items[0]
    assert saved["capability_id"] == "math.basic"
    assert saved["name"] == record["name"]
    assert saved["purpose"] == record["purpose"]
    assert saved["operations"] == record["operations"]
    assert saved["inputs"] == record["inputs"]
    assert saved["outputs"] == record["outputs"]
    assert saved["dependencies"] == record["dependencies"]
    assert saved["resource_requirements"] == record["resource_requirements"]
    assert saved["validation"] == record["validation"]
    assert saved["maturity_state"] == "implemented"
    assert saved["enabled"] is True


def test_capability_catalog_update_preserves_single_record(tmp_path):
    store = KnowledgeStore(tmp_path / "catalog.sqlite3")

    assert store.upsert_capability("math.basic", definition()) is True

    updated = definition(
        version="1.1.0",
        description="Atualização de metadados.",
        maturity_state="tested_individually",
    )
    assert store.upsert_capability("math.basic", updated) is False

    items = store.list_capabilities()
    assert len(items) == 1
    assert items[0]["version"] == "1.1.0"
    assert items[0]["maturity_state"] == "tested_individually"


@pytest.mark.parametrize("capability_id", ["", "   ", None, 123, "../invalid"])
def test_capability_catalog_rejects_invalid_identifier(tmp_path, capability_id):
    store = KnowledgeStore(tmp_path / "catalog.sqlite3")

    with pytest.raises(ValueError):
        store.upsert_capability(capability_id, definition())


@pytest.mark.parametrize(
    "state",
    [
        "planned",
        "in_development",
        "implemented",
        "tested_individually",
        "tested_integration",
        "validated_real",
    ],
)
def test_capability_catalog_accepts_defined_maturity_states(tmp_path, state):
    store = KnowledgeStore(tmp_path / f"{state}.sqlite3")

    assert store.upsert_capability(
        f"test.{state}",
        definition(maturity_state=state),
    ) is True


def test_capability_catalog_rejects_unknown_maturity_state(tmp_path):
    store = KnowledgeStore(tmp_path / "catalog.sqlite3")

    with pytest.raises(ValueError):
        store.upsert_capability(
            "test.invalid",
            definition(maturity_state="proven_without_evidence"),
        )


def test_capability_catalog_rejects_non_dictionary_definition(tmp_path):
    store = KnowledgeStore(tmp_path / "catalog.sqlite3")

    with pytest.raises(ValueError):
        store.upsert_capability("test.invalid", ["not", "a", "dictionary"])


def test_capability_catalog_rejects_invalid_json_values(tmp_path):
    store = KnowledgeStore(tmp_path / "catalog.sqlite3")

    with pytest.raises(ValueError):
        store.upsert_capability(
            "test.invalid",
            definition(resource_requirements={"invalid": object()}),
        )
