import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import zipfile
import zlib
import struct

from agent.checkpoint_safety import (
    MAX_NPY_HEADER_BYTES,
    CheckpointPreflightError,
    open_checkpoint_file,
    decode_metadata_array,
    preflight_npz,
)

FORMAT_VERSION = 1
DTYPE = np.float32


class NeuralError(Exception):
    pass


def matrix(value):
    result = np.asarray(value, dtype=DTYPE)
    if result.ndim == 1:
        result = result.reshape(1, -1)
    if result.ndim != 2 or not np.all(np.isfinite(result)):
        raise ValueError("Matriz inválida.")
    return result


class Parameter:
    def __init__(self, data, name):
        self.data = np.asarray(data, dtype=DTYPE).copy()
        self.grad = np.zeros_like(self.data)
        self.name = name

    def zero_grad(self):
        self.grad.fill(0)


class Layer:
    def parameters(self):
        return []

    def config(self):
        raise NotImplementedError


class Dense(Layer):
    def __init__(self, input_size, output_size, seed=None):
        if input_size < 1 or output_size < 1:
            raise ValueError("Dimensões inválidas.")

        rng = np.random.default_rng(seed)
        scale = np.sqrt(2.0 / (input_size + output_size))

        self.weights = Parameter(
            rng.normal(0, scale, (input_size, output_size)),
            "weights"
        )
        self.bias = Parameter(
            np.zeros((1, output_size)),
            "bias"
        )
        self.input_size = input_size
        self.output_size = output_size
        self.last_input = None

    def forward(self, x):
        x = matrix(x)
        if x.shape[1] != self.input_size:
            raise ValueError("Entrada incompatível.")
        self.last_input = x
        return x @ self.weights.data + self.bias.data

    def backward(self, grad):
        grad = matrix(grad)
        if self.last_input is None:
            raise NeuralError("Forward não executado.")
        if grad.shape != (self.last_input.shape[0], self.output_size):
            raise ValueError("Gradiente incompatível.")

        self.weights.grad += self.last_input.T @ grad
        self.bias.grad += np.sum(grad, axis=0, keepdims=True)
        return grad @ self.weights.data.T

    def parameters(self):
        return [self.weights, self.bias]

    def config(self):
        return {
            "type": "dense",
            "input_size": self.input_size,
            "output_size": self.output_size
        }


class Activation(Layer):
    def __init__(self, name):
        if name not in ("relu", "tanh", "sigmoid", "softmax"):
            raise ValueError("Ativação inválida.")
        self.name = name
        self.output = None

    def forward(self, x):
        x = matrix(x)

        if self.name == "relu":
            y = np.maximum(x, 0)
        elif self.name == "tanh":
            y = np.tanh(x)
        elif self.name == "sigmoid":
            y = np.empty_like(x)
            positive = x >= 0
            y[positive] = 1 / (1 + np.exp(-x[positive]))
            exp_x = np.exp(x[~positive])
            y[~positive] = exp_x / (1 + exp_x)
        else:
            shifted = x - np.max(x, axis=1, keepdims=True)
            exp_x = np.exp(shifted)
            y = exp_x / np.sum(exp_x, axis=1, keepdims=True)

        self.output = y
        return y

    def backward(self, grad):
        grad = matrix(grad)
        if self.output is None or grad.shape != self.output.shape:
            raise NeuralError("Gradiente incompatível.")

        if self.name == "relu":
            return grad * (self.output > 0)
        if self.name == "tanh":
            return grad * (1 - self.output ** 2)
        if self.name == "sigmoid":
            return grad * self.output * (1 - self.output)

        dot = np.sum(grad * self.output, axis=1, keepdims=True)
        return self.output * (grad - dot)

    def config(self):
        return {"type": "activation", "name": self.name}


class MSELoss:
    def forward_backward(self, prediction, target):
        difference = prediction - target
        loss = np.mean(difference ** 2)
        grad = 2 * difference / difference.size
        return float(loss), grad


class Sequential:
    def __init__(self, layers):
        self.layers = list(layers)
        if not self.layers:
            raise ValueError("Rede vazia.")
        self.ready = False

    def forward(self, x):
        result = matrix(x)
        for layer in self.layers:
            result = layer.forward(result)
        self.ready = True
        return result

    def predict(self, x):
        return self.forward(x)

    def backward(self, grad):
        if not self.ready:
            raise NeuralError("Execute forward primeiro.")
        result = matrix(grad)
        for layer in reversed(self.layers):
            result = layer.backward(result)
        self.ready = False
        return result

    def parameters(self):
        result = []
        for layer in self.layers:
            result.extend(layer.parameters())
        return result

    def zero_grad(self):
        for parameter in self.parameters():
            parameter.zero_grad()

    def config(self):
        return [layer.config() for layer in self.layers]

    def parameter_count(self):
        return sum(p.data.size for p in self.parameters())

    def train_step(self, x, target, loss, optimizer, clip=5.0):
        try:
            valid_clip = (
                np.isscalar(clip)
                and not isinstance(clip, (bool, np.bool_))
                and np.isfinite(clip)
                and clip > 0
            )
        except (TypeError, ValueError):
            valid_clip = False

        if not valid_clip:
            raise ValueError("Limite de gradiente inválido.")

        self.zero_grad()
        prediction = self.forward(x)
        target = matrix(target)

        if prediction.shape != target.shape:
            raise ValueError("Target incompatível.")

        if not np.all(np.isfinite(prediction)):
            raise NeuralError("Previsão inválida.")

        loss_value, grad = loss.forward_backward(prediction, target)

        if not np.isscalar(loss_value) or not np.isfinite(loss_value):
            raise NeuralError("Valor da perda inválido.")

        grad = matrix(grad)
        if grad.shape != prediction.shape:
            raise NeuralError("Gradiente da perda incompatível.")

        if not np.all(np.isfinite(grad)):
            raise NeuralError("Gradiente da perda inválido.")

        self.backward(grad)

        norm = np.sqrt(sum(
            np.sum(p.grad.astype(np.float64) ** 2)
            for p in self.parameters()
        ))

        if not np.isfinite(norm):
            raise NeuralError("Gradiente inválido.")

        if norm > clip:
            factor = clip / (norm + 1e-12)
            for p in self.parameters():
                p.grad *= factor

        optimizer.step(self.parameters())

        return {
            "loss": float(loss_value),
            "gradient_norm": float(norm),
            "parameters": self.parameter_count()
        }

    def save_checkpoint(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        arrays = {}
        entries = []
        parameters = self.parameters()
        save_expected_arrays = {}

        for i, p in enumerate(parameters):
            if (
                not isinstance(p.data, np.ndarray)
                or p.data.dtype != np.dtype(DTYPE)
                or not np.all(np.isfinite(p.data))
            ):
                raise NeuralError(
                    f"Parâmetro {i} contém dtype ou valores inválidos."
                )
            save_expected_arrays[f"p{i}"] = (p.data.shape, DTYPE)
            key = f"p{i}"
            arrays[key] = p.data.copy()
            entries.append({
                "key": key,
                "shape": list(p.data.shape),
                "hash": hashlib.sha256(p.data.tobytes()).hexdigest()
            })

        metadata = {
            "version": FORMAT_VERSION,
            "architecture": self.config(),
            "parameters": entries
        }

        arrays["metadata"] = np.frombuffer(
            json.dumps(metadata, allow_nan=False).encode(), dtype=np.uint8
        )

        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, suffix=".tmp", delete=False
            ) as f:
                temporary = Path(f.name)
                np.savez_compressed(f, **arrays)
                f.flush()
                os.fsync(f.fileno())

            try:
                with temporary.open("rb") as checkpoint_file:
                    preflight_npz(checkpoint_file, save_expected_arrays)
            except CheckpointPreflightError as exc:
                raise NeuralError(
                    "Checkpoint gerado excede os limites ou o contrato de leitura."
                ) from exc

            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

        return str(path)

    def load_checkpoint(self, path):
        parameters = self.parameters()
        expected_arrays = {
            f"p{index}": (parameter.data.shape, DTYPE)
            for index, parameter in enumerate(parameters)
        }
        loaded = []

        try:
            with open_checkpoint_file(path) as checkpoint_file:
                preflight_npz(checkpoint_file, expected_arrays)
                with np.load(
                    checkpoint_file,
                    allow_pickle=False,
                    max_header_size=MAX_NPY_HEADER_BYTES,
                ) as archive:
                    metadata = decode_metadata_array(archive["metadata"])
                    if set(metadata) != {
                        "version", "architecture", "parameters",
                    }:
                        raise NeuralError("Schema de metadados incompatível.")

                    version = metadata["version"]
                    if (
                        not isinstance(version, int)
                        or isinstance(version, bool)
                        or version != FORMAT_VERSION
                    ):
                        raise NeuralError("Versão incompatível.")
                    if metadata["architecture"] != self.config():
                        raise NeuralError("Arquitetura incompatível.")

                    entries = metadata["parameters"]
                    if (
                        not isinstance(entries, list)
                        or len(parameters) != len(entries)
                    ):
                        raise NeuralError("Quantidade incompatível.")

                    for index, (parameter, entry) in enumerate(
                        zip(parameters, entries)
                    ):
                        if not isinstance(entry, dict) or set(entry) != {
                            "key", "shape", "hash",
                        }:
                            raise NeuralError("Entrada de parâmetro inválida.")

                        expected_key = f"p{index}"
                        digest = entry["hash"]
                        if (
                            entry["key"] != expected_key
                            or entry["shape"] != list(parameter.data.shape)
                            or not isinstance(digest, str)
                            or len(digest) != 64
                            or any(
                                char not in "0123456789abcdef"
                                for char in digest
                            )
                        ):
                            raise NeuralError(
                                "Identidade/dimensão de parâmetro inválida."
                            )

                        data = archive[expected_key]
                        if (
                            data.dtype != np.dtype(DTYPE)
                            or data.shape != parameter.data.shape
                            or not np.all(np.isfinite(data))
                        ):
                            raise NeuralError("Peso incompatível.")
                        if hashlib.sha256(
                            np.ascontiguousarray(data).tobytes()
                        ).hexdigest() != digest:
                            raise NeuralError("Integridade do peso inválida.")

                        loaded.append(data.copy())
        except NeuralError:
            raise
        except (
            OSError, EOFError, ValueError, TypeError, KeyError,
            OverflowError, UnicodeError, zipfile.BadZipFile, zlib.error, struct.error,
        ) as exc:
            raise NeuralError(
                "Checkpoint inválido ou corrompido."
            ) from exc

        # A rede só é modificada depois de todos os arrays/metadados validados.
        for parameter, data in zip(parameters, loaded):
            parameter.data[...] = data
        return True



class SGD:
    def __init__(self, learning_rate=0.01):
        try:
            valid_rate = np.isscalar(learning_rate) and np.isfinite(learning_rate) and learning_rate > 0
        except (TypeError, ValueError):
            valid_rate = False
        if not valid_rate:
            raise ValueError("Taxa inválida.")
        self.learning_rate = float(learning_rate)

    def step(self, parameters):
        updates = [
            p.data - self.learning_rate * p.grad
            for p in parameters
        ]

        if not all(np.all(np.isfinite(x)) for x in updates):
            raise NeuralError("Atualização inválida.")

        for p, update in zip(parameters, updates):
            p.data[...] = update


class Adam:
    def __init__(self, learning_rate=0.001, beta1=0.9,
                 beta2=0.999, epsilon=1e-8):
        try:
            valid_rate = np.isscalar(learning_rate) and np.isfinite(learning_rate) and learning_rate > 0
            valid_epsilon = np.isscalar(epsilon) and np.isfinite(epsilon) and epsilon > 0
            valid_beta1 = np.isscalar(beta1) and np.isfinite(beta1) and 0 <= beta1 < 1
            valid_beta2 = np.isscalar(beta2) and np.isfinite(beta2) and 0 <= beta2 < 1
        except (TypeError, ValueError):
            valid_rate = valid_epsilon = False
            valid_beta1 = valid_beta2 = False

        if not valid_rate or not valid_epsilon:
            raise ValueError("Parâmetros inválidos.")
        if not valid_beta1 or not valid_beta2:
            raise ValueError("Betas inválidos.")

        self.learning_rate = float(learning_rate)
        self.beta1 = float(beta1)
        self.beta2 = float(beta2)
        self.epsilon = float(epsilon)
        self.step_count = 0
        self.state = {}

    def step(self, parameters):
        t = self.step_count + 1
        updates = []

        for p in parameters:
            if p.data.shape != p.grad.shape:
                raise NeuralError("Dimensão do gradiente incompatível.")
            if not np.all(np.isfinite(p.data)) or not np.all(np.isfinite(p.grad)):
                raise NeuralError("Parâmetro ou gradiente inválido.")

            key = id(p)
            state = self.state.get(key)

            if state is None:
                old_m = np.zeros_like(p.data)
                old_v = np.zeros_like(p.data)
            else:
                old_m = state["m"]
                old_v = state["v"]

            if (old_m.shape != p.data.shape or old_v.shape != p.data.shape
                    or not np.all(np.isfinite(old_m))
                    or not np.all(np.isfinite(old_v))):
                raise NeuralError("Estado Adam inválido.")

            m = self.beta1 * old_m + (1 - self.beta1) * p.grad
            v = self.beta2 * old_v + (1 - self.beta2) * p.grad ** 2

            mh = m / (1 - self.beta1 ** t)
            vh = v / (1 - self.beta2 ** t)

            new_data = p.data - self.learning_rate * mh / (
                np.sqrt(vh) + self.epsilon
            )

            if (not np.all(np.isfinite(m))
                    or not np.all(np.isfinite(v))
                    or not np.all(np.isfinite(new_data))):
                raise NeuralError("Atualização Adam inválida.")

            updates.append((p, key, m, v, new_data))

        for p, key, m, v, new_data in updates:
            self.state[key] = {"m": m, "v": v}
            p.data[...] = new_data

        self.step_count = t


def build_mlp(input_size, hidden_sizes, output_size,
              activation="tanh", output_activation="sigmoid",
              seed=42):
    if input_size < 1 or output_size < 1 or not hidden_sizes:
        raise ValueError("Dimensões inválidas.")

    layers = []
    current = input_size

    for i, size in enumerate(hidden_sizes):
        if size < 1:
            raise ValueError("Camada inválida.")
        layers.append(Dense(current, size, seed + i))
        layers.append(Activation(activation))
        current = size

    layers.append(Dense(current, output_size, seed + len(hidden_sizes)))

    if output_activation is not None:
        layers.append(Activation(output_activation))

    return Sequential(layers)
