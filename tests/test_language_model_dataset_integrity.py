import json
import pytest

from agent.language_engine import LanguageEngine


class NullCognitive:
    def record_observation(self, **kwargs):
        return {"status": "ignored"}

    def record_learning(self, **kwargs):
        return {"status": "ignored"}


def _seed_examples():
    return [
        {"text": "mostre o estado do sistema", "intent": "status"},
        {"text": "qual é a condição atual", "intent": "status"},
        {"text": "inspecione a cena do blender", "intent": "blender.inspect"},
        {"text": "analise os objetos da cena", "intent": "blender.inspect"},
    ]


def test_checkpoint_loads_only_when_training_dataset_hash_matches(tmp_path):
    root = tmp_path / "mahoraga"
    first = LanguageEngine(root=root, cognitive=NullCognitive())
    first.add_examples(_seed_examples(), source="isolated_test")
    trained = first.train(epochs=2)

    assert trained["status"] == "trained"
    assert trained["dataset_sha256"] == first._dataset_sha256()
    metadata = json.loads(first.metadata_path.read_text(encoding="utf-8"))
    assert metadata["provenance_schema_version"] == 1
    assert metadata["provenance_sha256"] == first._provenance_sha256()
    assert metadata["provenance_records"] == len(first.provenance_records)
    assert first.metadata_path.exists()
    assert first.model_path.exists()

    reloaded = LanguageEngine(root=root, cognitive=NullCognitive())
    assert reloaded.status()["trained"] is True

    # Adding a new example invalidates the in-memory model but intentionally
    # leaves the old checkpoint files intact for recovery/audit.
    reloaded.add_examples(
        [{"text": "verifique a situação do núcleo", "intent": "status"}],
        source="isolated_test",
    )
    assert reloaded.model_path.exists()
    assert reloaded.metadata_path.exists()

    fresh = LanguageEngine(root=root, cognitive=NullCognitive())
    status = fresh.status()

    assert status["examples"] == 5
    assert status["trained"] is False
    assert fresh.network is None


def test_legacy_checkpoint_without_dataset_fingerprint_is_not_trusted(tmp_path):
    root = tmp_path / "mahoraga"
    engine = LanguageEngine(root=root, cognitive=NullCognitive())
    engine.add_examples(_seed_examples(), source="isolated_test")
    engine.train(epochs=1)

    metadata = json.loads(engine.metadata_path.read_text(encoding="utf-8"))
    metadata.pop("dataset_sha256")
    engine.metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )

    reloaded = LanguageEngine(root=root, cognitive=NullCognitive())
    assert reloaded.status()["trained"] is False
    assert reloaded.model_path.exists()
    assert reloaded.metadata_path.exists()



def test_corrupted_neural_checkpoint_is_treated_as_unavailable_not_crash(
    tmp_path
):
    root = tmp_path / "mahoraga"
    engine = LanguageEngine(root=root, cognitive=NullCognitive())
    engine.add_examples(_seed_examples(), source="isolated_test")
    engine.train(epochs=1)

    # Valid metadata + malformed NPZ bytes exercises the NeuralError boundary.
    engine.model_path.write_bytes(b"not-an-npz-checkpoint")

    reloaded = LanguageEngine(root=root, cognitive=NullCognitive())
    status = reloaded.status()

    assert status["trained"] is False
    assert reloaded.network is None
    assert reloaded.ready is False



def test_checkpoint_requires_the_original_training_seed(tmp_path):
    root = tmp_path / "mahoraga"
    first = LanguageEngine(
        root=root,
        cognitive=NullCognitive(),
        seed=42,
    )
    first.add_examples(_seed_examples(), source="isolated_test")
    first.train(epochs=1)

    metadata = json.loads(first.metadata_path.read_text(encoding="utf-8"))
    assert metadata["seed"] == 42

    same_seed = LanguageEngine(
        root=root,
        cognitive=NullCognitive(),
        seed=42,
    )
    assert same_seed.status()["trained"] is True

    different_seed = LanguageEngine(
        root=root,
        cognitive=NullCognitive(),
        seed=43,
    )
    assert different_seed.status()["trained"] is False
    assert different_seed.network is None
    assert different_seed.ready is False
    # Rejection does not delete or rewrite the previous checkpoint.
    assert different_seed.model_path.exists()
    assert different_seed.metadata_path.exists()


def test_checkpoint_without_seed_metadata_is_not_trusted(tmp_path):
    root = tmp_path / "mahoraga"
    engine = LanguageEngine(root=root, cognitive=NullCognitive(), seed=42)
    engine.add_examples(_seed_examples(), source="isolated_test")
    engine.train(epochs=1)

    metadata = json.loads(engine.metadata_path.read_text(encoding="utf-8"))
    metadata.pop("seed")
    engine.metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False),
        encoding="utf-8",
    )

    reloaded = LanguageEngine(root=root, cognitive=NullCognitive(), seed=42)
    assert reloaded.status()["trained"] is False
    assert reloaded.network is None
    assert reloaded.model_path.exists()
    assert reloaded.metadata_path.exists()


@pytest.mark.parametrize("seed", [True, -1, "42", 1.5])
def test_language_engine_rejects_invalid_training_seed(tmp_path, seed):
    with pytest.raises(ValueError, match="seed deve ser"):
        LanguageEngine(
            root=tmp_path / "mahoraga",
            cognitive=NullCognitive(),
            seed=seed,
        )


def test_checkpoint_rejects_provenance_changes_even_when_examples_are_unchanged(tmp_path):
    root = tmp_path / "mahoraga"
    engine = LanguageEngine(root=root, cognitive=NullCognitive())
    examples = _seed_examples()
    engine.add_examples(examples, source="source-a")
    engine.train(epochs=1)
    trained_dataset_hash = engine._dataset_sha256()

    updater = LanguageEngine(root=root, cognitive=NullCognitive())
    result = updater.add_examples([examples[0]], source="source-b")
    assert result["added"] == 0
    assert result["provenance_added"] == 1
    assert updater._dataset_sha256() == trained_dataset_hash

    fresh = LanguageEngine(root=root, cognitive=NullCognitive())
    assert fresh._load_model() is False
    assert fresh.ready is False


def test_checkpoint_without_provenance_fingerprint_is_not_trusted(tmp_path):
    root = tmp_path / "mahoraga"
    engine = LanguageEngine(root=root, cognitive=NullCognitive())
    engine.add_examples(_seed_examples(), source="isolated_test")
    engine.train(epochs=1)
    metadata = json.loads(engine.metadata_path.read_text(encoding="utf-8"))
    metadata.pop("provenance_sha256")
    engine.metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    fresh = LanguageEngine(root=root, cognitive=NullCognitive())
    assert fresh._load_model() is False
