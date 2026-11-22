import json
import numpy as np
import pytest

from agent.neural_core import (
    build_mlp, Adam, MSELoss, NeuralError, Sequential, Activation,
)
from agent.neural_checkpoint import (
    save_training_checkpoint,
    load_training_checkpoint,
)


def make_network():
    return build_mlp(2, [4], 1, seed=42)


def make_data():
    x = np.array(
        [[0, 0], [0, 1], [1, 0], [1, 1]],
        dtype=np.float32,
    )
    y = np.array(
        [[0], [1], [1], [0]],
        dtype=np.float32,
    )
    return x, y


def test_checkpoint_restores_weights_and_adam(tmp_path):
    x, y = make_data()
    net_a = make_network()
    opt_a = Adam(learning_rate=0.03)
    loss = MSELoss()

    for _ in range(30):
        net_a.train_step(x, y, loss, opt_a)

    path = tmp_path / "training.npz"
    save_training_checkpoint(net_a, opt_a, path)

    net_b = make_network()
    opt_b = Adam(learning_rate=0.03)

    assert load_training_checkpoint(net_b, opt_b, path)

    for a, b in zip(net_a.parameters(), net_b.parameters()):
        np.testing.assert_array_equal(a.data, b.data)
        np.testing.assert_array_equal(
            opt_a.state[id(a)]["m"],
            opt_b.state[id(b)]["m"],
        )
        np.testing.assert_array_equal(
            opt_a.state[id(a)]["v"],
            opt_b.state[id(b)]["v"],
        )

    assert opt_a.step_count == opt_b.step_count

    net_a.train_step(x, y, loss, opt_a)
    net_b.train_step(x, y, loss, opt_b)

    for a, b in zip(net_a.parameters(), net_b.parameters()):
        np.testing.assert_array_equal(a.data, b.data)


def test_checkpoint_rejects_incompatible_architecture(tmp_path):
    net_a = make_network()
    opt_a = Adam(learning_rate=0.03)
    x, y = make_data()

    net_a.train_step(x, y, MSELoss(), opt_a)

    path = tmp_path / "training.npz"
    save_training_checkpoint(net_a, opt_a, path)

    net_b = build_mlp(2, [5], 1, seed=42)
    opt_b = Adam(learning_rate=0.03)
    before = [p.data.copy() for p in net_b.parameters()]

    with pytest.raises(NeuralError):
        load_training_checkpoint(net_b, opt_b, path)

    for old, current in zip(before, net_b.parameters()):
        np.testing.assert_array_equal(old, current.data)

    assert opt_b.step_count == 0
    assert opt_b.state == {}


def test_checkpoint_rejects_corrupted_weights_without_mutation(tmp_path):
    net_a = make_network()
    opt_a = Adam(learning_rate=0.03)
    x, y = make_data()

    net_a.train_step(x, y, MSELoss(), opt_a)

    path = tmp_path / "training.npz"
    save_training_checkpoint(net_a, opt_a, path)

    with np.load(path, allow_pickle=False) as archive:
        arrays = {key: archive[key].copy() for key in archive.files}

    metadata = json.loads(arrays["metadata"].tobytes())
    weight_key = metadata["parameters"][0]["keys"]["weight"]
    arrays[weight_key].flat[0] += 1.0

    corrupted = tmp_path / "corrupted.npz"
    np.savez_compressed(corrupted, **arrays)

    net_b = make_network()
    opt_b = Adam(learning_rate=0.03)
    before = [p.data.copy() for p in net_b.parameters()]

    with pytest.raises(NeuralError):
        load_training_checkpoint(net_b, opt_b, corrupted)

    for old, current in zip(before, net_b.parameters()):
        np.testing.assert_array_equal(old, current.data)

    assert opt_b.step_count == 0
    assert opt_b.state == {}


def _rewrite_training_archive(source, destination, transform):
    with np.load(source, allow_pickle=False) as archive:
        arrays = {key: archive[key].copy() for key in archive.files}
    transform(arrays)
    np.savez_compressed(destination, **arrays)


def test_training_checkpoint_rejects_oversized_file_before_numpy_load(
    tmp_path, monkeypatch
):
    from agent.checkpoint_safety import MAX_CHECKPOINT_FILE_BYTES

    network = make_network()
    optimizer = Adam(learning_rate=0.03)
    path = tmp_path / "oversized.npz"
    with path.open("wb") as handle:
        handle.truncate(MAX_CHECKPOINT_FILE_BYTES + 1)

    before = [parameter.data.copy() for parameter in network.parameters()]

    def unexpected_load(*args, **kwargs):
        pytest.fail("numpy.load não deveria ser chamado antes do preflight")

    monkeypatch.setattr(np, "load", unexpected_load)
    with pytest.raises(NeuralError):
        load_training_checkpoint(network, optimizer, path)

    for original, parameter in zip(before, network.parameters()):
        np.testing.assert_array_equal(original, parameter.data)
    assert optimizer.step_count == 0
    assert optimizer.state == {}


def test_training_checkpoint_rejects_undeclared_zip_member_before_numpy_load(
    tmp_path, monkeypatch
):
    network = make_network()
    optimizer = Adam(learning_rate=0.03)
    source = tmp_path / "source.npz"
    save_training_checkpoint(network, optimizer, source)
    corrupted = tmp_path / "extra-member.npz"

    def add_extra(arrays):
        arrays["undeclared"] = np.zeros((1,), dtype=np.float32)

    _rewrite_training_archive(source, corrupted, add_extra)
    before = [parameter.data.copy() for parameter in network.parameters()]

    def unexpected_load(*args, **kwargs):
        pytest.fail("numpy.load não deveria materializar arquivo com membro extra")

    monkeypatch.setattr(np, "load", unexpected_load)
    with pytest.raises(NeuralError):
        load_training_checkpoint(network, optimizer, corrupted)

    for original, parameter in zip(before, network.parameters()):
        np.testing.assert_array_equal(original, parameter.data)
    assert optimizer.step_count == 0
    assert optimizer.state == {}


def test_training_checkpoint_normalizes_malformed_metadata_and_preserves_state(
    tmp_path
):
    network = make_network()
    optimizer = Adam(learning_rate=0.03)
    source = tmp_path / "source.npz"
    save_training_checkpoint(network, optimizer, source)
    corrupted = tmp_path / "bad-metadata.npz"

    def corrupt_metadata(arrays):
        arrays["metadata"] = np.frombuffer(
            b"{not-json", dtype=np.uint8
        ).copy()

    _rewrite_training_archive(source, corrupted, corrupt_metadata)
    before = [parameter.data.copy() for parameter in network.parameters()]

    with pytest.raises(NeuralError):
        load_training_checkpoint(network, optimizer, corrupted)

    for original, parameter in zip(before, network.parameters()):
        np.testing.assert_array_equal(original, parameter.data)
    assert optimizer.step_count == 0
    assert optimizer.state == {}


def test_core_checkpoint_uses_preflight_and_preserves_weights(
    tmp_path, monkeypatch
):
    source_network = make_network()
    source = tmp_path / "source-core.npz"
    source_network.save_checkpoint(source)
    corrupted = tmp_path / "extra-core.npz"

    def add_extra(arrays):
        arrays["unexpected"] = np.zeros((1,), dtype=np.float32)

    _rewrite_training_archive(source, corrupted, add_extra)
    target = make_network()
    before = [parameter.data.copy() for parameter in target.parameters()]

    def unexpected_load(*args, **kwargs):
        pytest.fail("numpy.load não deveria materializar membro não declarado")

    monkeypatch.setattr(np, "load", unexpected_load)
    with pytest.raises(NeuralError):
        target.load_checkpoint(corrupted)

    for original, parameter in zip(before, target.parameters()):
        np.testing.assert_array_equal(original, parameter.data)


def test_core_checkpoint_round_trip_remains_compatible(tmp_path):
    original = make_network()
    path = tmp_path / "core.npz"
    original.save_checkpoint(path)

    restored = make_network()
    assert restored.load_checkpoint(path)

    for expected, actual in zip(original.parameters(), restored.parameters()):
        np.testing.assert_array_equal(expected.data, actual.data)



def test_checkpoint_preflight_rejects_truncated_npy_header(tmp_path):
    import io
    import zipfile

    from agent.checkpoint_safety import (
        CheckpointPreflightError,
        preflight_npz,
    )

    metadata_buffer = io.BytesIO()
    np.lib.format.write_array(
        metadata_buffer,
        np.array([1], dtype=np.uint8),
        allow_pickle=False,
    )
    path = tmp_path / "truncated-header.npz"
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        # Magic + versão 1.0 + apenas um byte do comprimento do cabeçalho.
        archive.writestr("weight.npy", bytes([0x93]) + b"NUMPY" + bytes([1, 0, 0]))
        archive.writestr("metadata.npy", metadata_buffer.getvalue())

    with path.open("rb") as checkpoint_file:
        with pytest.raises(CheckpointPreflightError):
            preflight_npz(
                checkpoint_file,
                {"weight": ((1,), np.float32)},
            )



@pytest.mark.parametrize(
    "limit_name",
    ["MAX_CHECKPOINT_FILE_BYTES", "MAX_CHECKPOINT_UNCOMPRESSED_BYTES"],
)
@pytest.mark.parametrize("save_kind", ["training", "core"])
def test_checkpoint_savers_refuse_archives_the_loaders_would_reject(
    tmp_path, monkeypatch, limit_name, save_kind
):
    import agent.checkpoint_safety as checkpoint_safety

    monkeypatch.setattr(checkpoint_safety, limit_name, 1)
    network = make_network()
    path = tmp_path / f"{save_kind}-{limit_name}.npz"
    original = b"previous-valid-checkpoint-placeholder"
    path.write_bytes(original)

    with pytest.raises(NeuralError, match="limites"):
        if save_kind == "training":
            save_training_checkpoint(
                network, Adam(learning_rate=0.03), path
            )
        else:
            network.save_checkpoint(path)

    assert path.read_bytes() == original



def test_training_checkpoint_refuses_invalid_adam_step_count_without_replacing_file(
    tmp_path
):
    network = make_network()
    optimizer = Adam(learning_rate=0.03)
    path = tmp_path / "existing.npz"
    save_training_checkpoint(network, optimizer, path)
    original = path.read_bytes()

    optimizer.step_count = -1
    with pytest.raises(NeuralError, match="Contador de passos"):
        save_training_checkpoint(network, optimizer, path)

    assert path.read_bytes() == original



def test_core_checkpoint_refuses_non_finite_weights_without_creating_file(
    tmp_path
):
    network = make_network()
    network.parameters()[0].data.flat[0] = np.nan
    path = tmp_path / "non-finite.npz"

    with pytest.raises(NeuralError, match="dtype ou valores inválidos"):
        network.save_checkpoint(path)

    assert not path.exists()


def test_parameter_free_sequential_checkpoint_round_trip(tmp_path):
    original = Sequential([Activation("relu")])
    path = tmp_path / "activation-only.npz"

    assert original.save_checkpoint(path)

    restored = Sequential([Activation("relu")])
    assert restored.load_checkpoint(path)

    sample = np.array([[-1.0, 2.0]], dtype=np.float32)
    np.testing.assert_array_equal(
        original.predict(sample),
        restored.predict(sample),
    )



def test_checkpoint_open_rejects_symlink_path(tmp_path):
    from agent.checkpoint_safety import (
        CheckpointPreflightError,
        open_checkpoint_file,
    )

    target = tmp_path / "real.npz"
    target.write_bytes(b"not-used")
    link = tmp_path / "linked.npz"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(CheckpointPreflightError, match="regular"):
        open_checkpoint_file(link)


@pytest.mark.skipif(not hasattr(__import__("os"), "mkfifo"), reason="FIFO unavailable")
def test_checkpoint_open_rejects_fifo_without_blocking(tmp_path):
    import os
    from agent.checkpoint_safety import (
        CheckpointPreflightError,
        open_checkpoint_file,
    )

    fifo = tmp_path / "checkpoint.fifo"
    os.mkfifo(fifo)

    with pytest.raises(CheckpointPreflightError, match="regular"):
        open_checkpoint_file(fifo)



def test_checkpoint_metadata_rejects_deeply_nested_json():
    from agent.checkpoint_safety import (
        CheckpointPreflightError,
        decode_metadata_array,
    )

    payload = b'{"nested":' + b"[" * 64 + b"0" + b"]" * 64 + b"}"
    metadata = np.frombuffer(payload, dtype=np.uint8)

    with pytest.raises(CheckpointPreflightError, match="Profundidade excessiva"):
        decode_metadata_array(metadata)



@pytest.mark.parametrize(
    "invalid_state",
    [
        {"m": np.zeros((1,), dtype=np.float32)},
        {"v": np.zeros((1,), dtype=np.float32)},
        {
            "m": np.zeros((1,), dtype=np.float32),
            "v": np.zeros((1,), dtype=np.float32),
            "extra": np.zeros((1,), dtype=np.float32),
        },
    ],
)
def test_training_checkpoint_rejects_partial_or_extra_adam_moments(
    tmp_path, invalid_state
):
    network = make_network()
    optimizer = Adam(learning_rate=0.03)
    optimizer.step_count = 1
    for parameter in network.parameters():
        optimizer.state[id(parameter)] = {
            "m": np.zeros_like(parameter.data),
            "v": np.zeros_like(parameter.data),
        }
    parameter = network.parameters()[0]
    optimizer.state[id(parameter)] = invalid_state
    path = tmp_path / "existing-valid.npz"
    save_training_checkpoint(
        network,
        Adam(learning_rate=0.03),
        path,
    )
    original = path.read_bytes()

    with pytest.raises(NeuralError, match="exatamente os momentos"):
        save_training_checkpoint(network, optimizer, path)

    assert path.read_bytes() == original


def test_training_checkpoint_rejects_stale_adam_parameter_state(tmp_path):
    network = make_network()
    optimizer = Adam(learning_rate=0.03)
    optimizer.state[123456789] = {
        "m": np.zeros((1,), dtype=np.float32),
        "v": np.zeros((1,), dtype=np.float32),
    }
    path = tmp_path / "existing-valid.npz"
    save_training_checkpoint(
        network,
        Adam(learning_rate=0.03),
        path,
    )
    original = path.read_bytes()

    with pytest.raises(NeuralError, match="não pertencem à rede"):
        save_training_checkpoint(network, optimizer, path)

    assert path.read_bytes() == original



def test_training_checkpoint_rejects_missing_adam_state_after_updates(
    tmp_path
):
    network = make_network()
    optimizer = Adam(learning_rate=0.03)
    x, y = make_data()
    network.train_step(x, y, MSELoss(), optimizer)
    parameter = network.parameters()[0]
    del optimizer.state[id(parameter)]

    path = tmp_path / "previous.npz"
    path.write_bytes(b"previous-checkpoint")
    original = path.read_bytes()

    with pytest.raises(NeuralError, match="incompleto"):
        save_training_checkpoint(network, optimizer, path)

    assert path.read_bytes() == original


def test_training_checkpoint_rejects_adam_state_before_first_step(tmp_path):
    network = make_network()
    optimizer = Adam(learning_rate=0.03)
    parameter = network.parameters()[0]
    optimizer.state[id(parameter)] = {
        "m": np.zeros_like(parameter.data),
        "v": np.zeros_like(parameter.data),
    }

    with pytest.raises(NeuralError, match="antes do primeiro passo"):
        save_training_checkpoint(
            network, optimizer, tmp_path / "invalid.npz"
        )



def test_checkpoint_rejects_zip_member_count_before_zipfile_materialization(
    tmp_path, monkeypatch
):
    import zipfile
    import agent.checkpoint_safety as checkpoint_safety

    network = make_network()
    optimizer = Adam(learning_rate=0.03)
    path = tmp_path / "too-many-members.npz"
    save_training_checkpoint(network, optimizer, path)

    with zipfile.ZipFile(path, mode="a") as archive:
        archive.writestr("undeclared-extra.npy", b"extra")

    def unexpected_zipfile(*args, **kwargs):
        pytest.fail("ZipFile não deveria construir entradas antes da checagem EOCD")

    monkeypatch.setattr(checkpoint_safety.zipfile, "ZipFile", unexpected_zipfile)
    with path.open("rb") as checkpoint_file:
        with pytest.raises(
            checkpoint_safety.CheckpointPreflightError,
            match="Contagem de membros ZIP",
        ):
            checkpoint_safety.preflight_npz(
                checkpoint_file,
                {
                    "weight_0": (network.parameters()[0].data.shape, np.float32),
                    "moment_m_0": (network.parameters()[0].data.shape, np.float32),
                    "moment_v_0": (network.parameters()[0].data.shape, np.float32),
                },
            )
