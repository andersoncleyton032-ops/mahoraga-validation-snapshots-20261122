from concurrent.futures import ThreadPoolExecutor
from threading import Event

from agent.language_engine import LanguageEngine
from agent.neural_training import Trainer


class NullCognitive:
    def record_observation(self, **kwargs):
        return {"status": "ignored"}

    def record_learning(self, **kwargs):
        return {"status": "ignored"}


def _examples():
    return [
        {"text": "mostre o estado do sistema", "intent": "status"},
        {"text": "qual é a condição atual", "intent": "status"},
        {"text": "inspecione a cena do blender", "intent": "blender.inspect"},
        {"text": "analise os objetos da cena", "intent": "blender.inspect"},
    ]


def test_training_and_example_updates_are_serialized_on_shared_instance(
    tmp_path, monkeypatch
):
    engine = LanguageEngine(root=tmp_path / "mahoraga", cognitive=NullCognitive())
    engine.add_examples(_examples(), source="isolated_test")

    training_started = Event()
    release_training = Event()
    add_attempted = Event()

    def controlled_fit(self, inputs, targets, epochs):
        training_started.set()
        assert release_training.wait(timeout=5)
        return {
            "epochs_completed": epochs,
            "history": [{"loss": 0.125}],
        }

    monkeypatch.setattr(Trainer, "fit", controlled_fit)

    def add_after_training_starts():
        add_attempted.set()
        return engine.add_examples(
            [{"text": "verifique a situação do núcleo", "intent": "status"}],
            source="isolated_test",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        training = executor.submit(engine.train, epochs=1)
        assert training_started.wait(timeout=5)

        addition = executor.submit(add_after_training_starts)
        try:
            assert add_attempted.wait(timeout=5)
            # The add operation has started but cannot mutate the dataset while
            # training owns the same instance lock.
            assert not addition.done()
        finally:
            release_training.set()

        trained = training.result(timeout=5)
        added = addition.result(timeout=5)

    assert trained["status"] == "trained"
    assert added["status"] == "recorded"
    assert added["added"] == 1
    assert added["provenance_added"] == 1
    assert engine.ready is False
    assert engine.network is None

    # The checkpoint produced by the completed training is now stale, and a
    # fresh instance must reject it against the newly persisted dataset.
    fresh = LanguageEngine(root=tmp_path / "mahoraga", cognitive=NullCognitive())
    assert fresh.status()["examples"] == 5
    assert fresh.status()["trained"] is False


def test_status_and_classification_wait_for_in_progress_state_transition(tmp_path):
    engine = LanguageEngine(root=tmp_path / "mahoraga", cognitive=NullCognitive())
    status_started = Event()
    classify_started = Event()

    def read_status():
        status_started.set()
        return engine.status()

    def classify():
        classify_started.set()
        return engine.classify("mostre o estado do sistema")

    with ThreadPoolExecutor(max_workers=2) as executor:
        engine._state_lock.acquire()
        try:
            status_future = executor.submit(read_status)
            classify_future = executor.submit(classify)
            assert status_started.wait(timeout=5)
            assert classify_started.wait(timeout=5)
            assert not status_future.done()
            assert not classify_future.done()
        finally:
            engine._state_lock.release()

        assert status_future.result(timeout=5)["component"] == "LanguageEngine"
        assert classify_future.result(timeout=5)["decision"] in {
            "abstain", "clarify", "defer"
        }
