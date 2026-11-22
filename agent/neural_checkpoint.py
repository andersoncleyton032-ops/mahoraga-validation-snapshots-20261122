import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np

from agent.neural_core import Adam, NeuralError, DTYPE
from agent.checkpoint_safety import (
    MAX_NPY_HEADER_BYTES,
    CheckpointPreflightError,
    open_checkpoint_file,
    decode_metadata_array,
    preflight_npz,
)
import zipfile
import zlib
import struct


FORMAT_VERSION = 1


def _hash(array):
    return hashlib.sha256(
        np.ascontiguousarray(array).tobytes()
    ).hexdigest()


def _optimizer_config(optimizer):
    return {
        "type": "Adam",
        "learning_rate": optimizer.learning_rate,
        "beta1": optimizer.beta1,
        "beta2": optimizer.beta2,
        "epsilon": optimizer.epsilon,
    }


def save_training_checkpoint(network, optimizer, path):
    if not isinstance(optimizer, Adam):
        raise TypeError("Este checkpoint exige o otimizador Adam.")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    parameters = network.parameters()
    if (
        not isinstance(optimizer.step_count, int)
        or isinstance(optimizer.step_count, bool)
        or optimizer.step_count < 0
    ):
        raise NeuralError("Contador de passos do Adam inválido.")
    if not isinstance(optimizer.state, dict):
        raise NeuralError("Estado do Adam incompatível.")

    optimizer_config = _optimizer_config(optimizer)
    for key in ("learning_rate", "epsilon"):
        value = optimizer_config[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not np.isfinite(value)
            or value <= 0
        ):
            raise NeuralError(f"Parâmetro Adam inválido: {key}.")
    for key in ("beta1", "beta2"):
        value = optimizer_config[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not np.isfinite(value)
            or not 0 <= value < 1
        ):
            raise NeuralError(f"Parâmetro Adam inválido: {key}.")

    parameter_ids = {id(parameter) for parameter in parameters}
    state_parameter_ids = set(optimizer.state)
    if not state_parameter_ids.issubset(parameter_ids):
        raise NeuralError(
            "O estado do Adam contém parâmetros que não pertencem à rede."
        )
    if optimizer.step_count == 0 and state_parameter_ids:
        raise NeuralError(
            "O Adam não pode possuir momentos antes do primeiro passo."
        )
    if optimizer.step_count > 0 and state_parameter_ids != parameter_ids:
        raise NeuralError(
            "O estado do Adam está incompleto para os parâmetros da rede."
        )

    arrays = {}
    entries = []

    for index, parameter in enumerate(parameters):
        weight = np.asarray(parameter.data, dtype=DTYPE).copy()

        state = optimizer.state.get(id(parameter))
        if state is None:
            moment_m = np.zeros_like(weight)
            moment_v = np.zeros_like(weight)
        else:
            if not isinstance(state, dict) or set(state) != {"m", "v"}:
                raise NeuralError(
                    "Estado do Adam deve conter exatamente os momentos m e v."
                )
            moment_m = np.asarray(state["m"], dtype=DTYPE).copy()
            moment_v = np.asarray(state["v"], dtype=DTYPE).copy()

        if (
            weight.shape != moment_m.shape
            or weight.shape != moment_v.shape
            or not np.all(np.isfinite(weight))
            or not np.all(np.isfinite(moment_m))
            or not np.all(np.isfinite(moment_v))
        ):
            raise NeuralError("Estado inválido no parâmetro.")

        keys = {
            "weight": f"weight_{index}",
            "m": f"moment_m_{index}",
            "v": f"moment_v_{index}",
        }

        arrays[keys["weight"]] = weight
        arrays[keys["m"]] = moment_m
        arrays[keys["v"]] = moment_v

        entries.append({
            "index": index,
            "name": parameter.name,
            "shape": list(weight.shape),
            "keys": keys,
            "hashes": {
                "weight": _hash(weight),
                "m": _hash(moment_m),
                "v": _hash(moment_v),
            },
        })

    metadata = {
        "version": FORMAT_VERSION,
        "architecture": network.config(),
        "optimizer": optimizer_config,
        "step_count": optimizer.step_count,
        "parameters": entries,
    }

    arrays["metadata"] = np.frombuffer(
        json.dumps(metadata, allow_nan=False).encode("utf-8"),
        dtype=np.uint8,
    )

    save_expected_arrays = {}
    for index in range(len(parameters)):
        save_expected_arrays[f"weight_{index}"] = (parameters[index].data.shape, DTYPE)
        save_expected_arrays[f"moment_m_{index}"] = (parameters[index].data.shape, DTYPE)
        save_expected_arrays[f"moment_v_{index}"] = (parameters[index].data.shape, DTYPE)

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            np.savez_compressed(file, **arrays)
            file.flush()
            os.fsync(file.fileno())

        try:
            with temporary.open("rb") as checkpoint_file:
                preflight_npz(checkpoint_file, save_expected_arrays)
        except CheckpointPreflightError as exc:
            raise NeuralError(
                "Checkpoint gerado excede os limites ou o contrato de leitura."
            ) from exc

        os.replace(temporary, path)
        temporary = None

    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

    return str(path)


def load_training_checkpoint(network, optimizer, path):
    if not isinstance(optimizer, Adam):
        raise TypeError("Este checkpoint exige o otimizador Adam.")

    parameters = network.parameters()
    expected_arrays = {}
    for index, parameter in enumerate(parameters):
        expected_arrays[f"weight_{index}"] = (parameter.data.shape, DTYPE)
        expected_arrays[f"moment_m_{index}"] = (parameter.data.shape, DTYPE)
        expected_arrays[f"moment_v_{index}"] = (parameter.data.shape, DTYPE)

    loaded_weights = []
    loaded_states = []

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
                    "version", "architecture", "optimizer",
                    "step_count", "parameters",
                }:
                    raise NeuralError("Schema de metadados incompatível.")

                version = metadata["version"]
                if (
                    not isinstance(version, int)
                    or isinstance(version, bool)
                    or version != FORMAT_VERSION
                ):
                    raise NeuralError("Versão incompatível.")

                if metadata["architecture"] != network.config():
                    raise NeuralError("Arquitetura incompatível.")

                if metadata["optimizer"] != _optimizer_config(optimizer):
                    raise NeuralError("Configuração do Adam incompatível.")

                step_count = metadata["step_count"]
                if (
                    not isinstance(step_count, int)
                    or isinstance(step_count, bool)
                    or step_count < 0
                ):
                    raise NeuralError("Contador de passos inválido.")

                entries = metadata["parameters"]
                if (
                    not isinstance(entries, list)
                    or len(entries) != len(parameters)
                ):
                    raise NeuralError("Quantidade de parâmetros incompatível.")

                for index, (parameter, entry) in enumerate(
                    zip(parameters, entries)
                ):
                    if not isinstance(entry, dict) or set(entry) != {
                        "index", "name", "shape", "keys", "hashes",
                    }:
                        raise NeuralError("Entrada de parâmetro inválida.")

                    if (
                        not isinstance(entry["index"], int)
                        or isinstance(entry["index"], bool)
                        or entry["index"] != index
                        or entry["name"] != parameter.name
                        or entry["shape"] != list(parameter.data.shape)
                    ):
                        raise NeuralError(
                            "Identidade/dimensão de parâmetro incompatível."
                        )

                    expected_keys = {
                        "weight": f"weight_{index}",
                        "m": f"moment_m_{index}",
                        "v": f"moment_v_{index}",
                    }
                    if entry["keys"] != expected_keys:
                        raise NeuralError("Mapa de arrays incompatível.")

                    hashes = entry["hashes"]
                    if (
                        not isinstance(hashes, dict)
                        or set(hashes) != {"weight", "m", "v"}
                        or any(
                            not isinstance(value, str)
                            or len(value) != 64
                            or any(
                                char not in "0123456789abcdef"
                                for char in value
                            )
                            for value in hashes.values()
                        )
                    ):
                        raise NeuralError("Hashes do parâmetro inválidos.")

                    arrays = {
                        "weight": archive[expected_keys["weight"]],
                        "m": archive[expected_keys["m"]],
                        "v": archive[expected_keys["v"]],
                    }
                    for label, array in arrays.items():
                        if (
                            array.dtype != np.dtype(DTYPE)
                            or array.shape != parameter.data.shape
                            or not np.all(np.isfinite(array))
                        ):
                            raise NeuralError(
                                f"Array {label} incompatível no checkpoint."
                            )
                        if _hash(array) != hashes[label]:
                            raise NeuralError(
                                "Falha na integridade do checkpoint."
                            )

                    loaded_weights.append(arrays["weight"].copy())
                    loaded_states.append({
                        "m": arrays["m"].copy(),
                        "v": arrays["v"].copy(),
                    })
    except NeuralError:
        raise
    except (
        OSError, EOFError, ValueError, TypeError, KeyError,
        OverflowError, UnicodeError, zipfile.BadZipFile, zlib.error, struct.error,
    ) as exc:
        raise NeuralError(
            "Checkpoint de treinamento inválido ou corrompido."
        ) from exc

    # Só altera rede e otimizador depois de validar todos os arrays.
    for parameter, weight in zip(parameters, loaded_weights):
        parameter.data[...] = weight

    optimizer.state = {
        id(parameter): state
        for parameter, state in zip(parameters, loaded_states)
    }
    optimizer.step_count = step_count
    return True
