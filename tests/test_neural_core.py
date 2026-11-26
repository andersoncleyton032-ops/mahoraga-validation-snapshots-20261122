import numpy as np
import pytest

from agent.neural_core import (
    matrix, Dense, Activation, MSELoss,
    Sequential, SGD, Adam, NeuralError, build_mlp,
)


def test_matrix_converts_vector_to_row():
    result = matrix([1, 2, 3])
    assert result.shape == (1, 3)
    assert result.dtype == np.float32


def test_matrix_rejects_non_finite_values():
    with pytest.raises(ValueError):
        matrix([[1.0, np.nan]])


def test_dense_forward_and_backward_shapes():
    layer = Dense(2, 3, seed=1)
    x = np.array([[1, 2], [3, 4]], dtype=np.float32)
    output = layer.forward(x)
    gradient = layer.backward(np.ones_like(output))

    assert output.shape == (2, 3)
    assert gradient.shape == (2, 2)
    assert layer.weights.grad.shape == (2, 3)
    assert layer.bias.grad.shape == (1, 3)


@pytest.mark.parametrize("name", ["relu", "tanh", "sigmoid", "softmax"])
def test_activation_outputs_are_finite(name):
    layer = Activation(name)
    x = np.array([[-2, 0, 2]], dtype=np.float32)
    output = layer.forward(x)

    assert output.shape == x.shape
    assert np.all(np.isfinite(output))

    if name == "softmax":
        np.testing.assert_allclose(
            output.sum(axis=1), [1.0], atol=1e-6
        )


def test_softmax_backward_gradient_sums_to_zero():
    layer = Activation("softmax")
    output = layer.forward(np.array([[1, 2, 3]], dtype=np.float32))
    gradient = layer.backward(np.ones_like(output))

    np.testing.assert_allclose(gradient, 0.0, atol=1e-6)


def test_mse_loss_value_and_gradient():
    prediction = np.array([[1, 3]], dtype=np.float32)
    target = np.array([[0, 1]], dtype=np.float32)

    value, gradient = MSELoss().forward_backward(prediction, target)

    assert value == pytest.approx(2.5)
    np.testing.assert_allclose(
        gradient, [[1.0, 2.0]], atol=1e-6
    )


def test_sequential_backward_accumulates_gradients():
    network = Sequential([
        Dense(2, 2, seed=1),
        Activation("tanh"),
        Dense(2, 1, seed=2),
    ])

    x = np.array([[1, 2], [3, 4]], dtype=np.float32)
    output = network.forward(x)
    network.backward(np.ones_like(output))

    assert all(
        np.all(np.isfinite(p.grad))
        for p in network.parameters()
    )
    assert network.ready is False


def test_sgd_updates_parameters():
    parameter = Dense(1, 1, seed=1).weights
    original = parameter.data.copy()
    parameter.grad.fill(2.0)

    SGD(learning_rate=0.1).step([parameter])

    np.testing.assert_allclose(
        parameter.data, original - 0.2, atol=1e-6
    )


def test_adam_updates_parameters_and_step_count():
    parameter = Dense(1, 1, seed=1).weights
    original = parameter.data.copy()
    parameter.grad.fill(1.0)
    optimizer = Adam(learning_rate=0.01)

    optimizer.step([parameter])

    assert optimizer.step_count == 1
    assert id(parameter) in optimizer.state
    assert not np.array_equal(parameter.data, original)


def test_build_mlp_parameter_count():
    network = build_mlp(2, [4], 1, seed=42)

    assert network.parameter_count() == 17
    assert len(network.config()) == 4


def test_backward_requires_forward():
    network = Sequential([Dense(2, 1, seed=1)])

    with pytest.raises(NeuralError):
        network.backward(np.ones((1, 1), dtype=np.float32))


@pytest.mark.parametrize("rate", [0, -0.1, np.nan, np.inf])
def test_sgd_rejects_invalid_learning_rate(rate):
    with pytest.raises(ValueError):
        SGD(learning_rate=rate)


@pytest.mark.parametrize("rate", [0, -0.1, np.nan, np.inf])
def test_adam_rejects_invalid_learning_rate(rate):
    with pytest.raises(ValueError):
        Adam(learning_rate=rate)


@pytest.mark.parametrize("epsilon", [0, -1, np.nan, np.inf])
def test_adam_rejects_invalid_epsilon(epsilon):
    with pytest.raises(ValueError):
        Adam(epsilon=epsilon)


def test_sgd_invalid_gradient_does_not_partially_update():
    first = Dense(1, 1, seed=1).weights
    second = Dense(1, 1, seed=2).weights

    first.grad.fill(1.0)
    second.grad.fill(np.nan)

    first_before = first.data.copy()
    second_before = second.data.copy()

    with pytest.raises(NeuralError):
        SGD(learning_rate=0.1).step([first, second])

    np.testing.assert_array_equal(first.data, first_before)
    np.testing.assert_array_equal(second.data, second_before)


def test_adam_invalid_gradient_does_not_change_state_or_parameters():
    first = Dense(1, 1, seed=1).weights
    second = Dense(1, 1, seed=2).weights

    first.grad.fill(1.0)
    second.grad.fill(np.inf)

    first_before = first.data.copy()
    second_before = second.data.copy()

    optimizer = Adam(learning_rate=0.01)

    with pytest.raises(NeuralError):
        optimizer.step([first, second])

    np.testing.assert_array_equal(first.data, first_before)
    np.testing.assert_array_equal(second.data, second_before)
    assert optimizer.step_count == 0
    assert optimizer.state == {}


@pytest.mark.parametrize("clip", [0, -1, np.nan, np.inf])
def test_train_step_rejects_invalid_clip(clip):
    network = build_mlp(2, [3], 1, seed=1)
    x = np.array([[0, 1]], dtype=np.float32)
    target = np.array([[1]], dtype=np.float32)

    with pytest.raises(ValueError):
        network.train_step(x, target, MSELoss(), SGD(), clip=clip)


def test_train_step_rejects_non_finite_loss_without_updating():
    class InvalidLoss:
        def forward_backward(self, prediction, target):
            return float("nan"), np.ones_like(prediction)

    network = build_mlp(2, [3], 1, seed=1)
    optimizer = SGD(learning_rate=0.1)
    x = np.array([[0, 1]], dtype=np.float32)
    target = np.array([[1]], dtype=np.float32)
    before = [p.data.copy() for p in network.parameters()]

    with pytest.raises(NeuralError):
        network.train_step(x, target, InvalidLoss(), optimizer)

    for parameter, original in zip(network.parameters(), before):
        np.testing.assert_array_equal(parameter.data, original)
