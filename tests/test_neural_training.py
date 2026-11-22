import numpy as np
import pytest

from agent.neural_core import build_mlp, Adam, MSELoss
from agent.neural_training import Trainer, TrainingError


def make_trainer(batch_size=2, learning_rate=0.03, seed=42):
    network = build_mlp(2, [4], 1, seed=seed)
    optimizer = Adam(learning_rate=learning_rate)
    loss = MSELoss()

    trainer = Trainer(
        network,
        optimizer,
        loss,
        batch_size=batch_size,
        shuffle=True,
        seed=seed,
    )

    return network, optimizer, trainer


def xor_data():
    x = np.array([
        [0.0, 0.0],
        [0.0, 1.0],
        [1.0, 0.0],
        [1.0, 1.0],
    ], dtype=np.float32)

    y = np.array([[0.0], [1.0], [1.0], [0.0]], dtype=np.float32)

    return x, y


def test_rejects_empty_dataset():
    _, _, trainer = make_trainer()

    with pytest.raises(TrainingError):
        trainer.fit(
            np.empty((0, 2)),
            np.empty((0, 1)),
            epochs=1,
        )


def test_rejects_mismatched_dataset():
    _, _, trainer = make_trainer()

    with pytest.raises(TrainingError):
        trainer.fit(
            np.zeros((3, 2)),
            np.zeros((2, 1)),
            epochs=1,
        )


def test_minibatches_process_all_samples():
    x, y = xor_data()
    _, optimizer, trainer = make_trainer(batch_size=3)

    result = trainer.fit(x, y, epochs=2)

    assert result["epochs_completed"] == 2
    assert result["history"][0]["samples"] == 4
    assert result["history"][1]["samples"] == 4

    # Dois lotes por época: 3 exemplos + 1 exemplo.
    assert optimizer.step_count == 4


def test_evaluation_does_not_change_weights():
    x, y = xor_data()
    network, _, trainer = make_trainer()

    before = [
        parameter.data.copy()
        for parameter in network.parameters()
    ]

    value = trainer.evaluate(x, y)

    after = network.parameters()

    assert np.isfinite(value)

    for old, parameter in zip(before, after):
        assert np.array_equal(old, parameter.data)


def test_early_stopping():
    x, y = xor_data()
    _, _, trainer = make_trainer(learning_rate=1e-12)

    result = trainer.fit(
        x,
        y,
        epochs=20,
        validation_data=(x, y),
        patience=2,
        min_delta=1.0,
    )

    assert result["stopped_early"] is True
    assert result["epochs_completed"] == 3
    assert result["best_validation_loss"] is not None


def test_training_records_finite_metrics():
    x, y = xor_data()
    _, _, trainer = make_trainer()

    result = trainer.fit(
        x,
        y,
        epochs=5,
        validation_data=(x, y),
    )

    assert len(result["history"]) == 5

    for record in result["history"]:
        assert np.isfinite(record["loss"])
        assert np.isfinite(record["gradient_norm"])
        assert np.isfinite(record["validation_loss"])
