import hashlib
import os
import stat
import pytest

from agent.artifact_store import ArtifactStore, ArtifactStoreError
from agent.image_generation import ProceduralImageBackend


def make_png():
    return ProceduralImageBackend.render(16, 12, seed=37)


def test_artifact_store_round_trips_verified_png_without_serializing_bytes(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    content = make_png()
    stored = store.put_png(
        content,
        source_kind="user_upload",
        source_ref="upload://session/image-001",
        license_status="user_supplied",
    )

    assert stored.content == content
    assert stored.asset.descriptor.mime_type == "image/png"
    assert stored.asset.descriptor.content_sha256 == hashlib.sha256(content).hexdigest()
    assert stored.asset.verification["sha256_verified"] is True
    assert stored.to_dict()["content_included"] is False

    restored = store.get_png(stored.asset.descriptor.asset_id)
    assert restored.content == content
    assert restored.asset.descriptor.to_dict() == stored.asset.descriptor.to_dict()
    assert restored.asset.verification["pixel_decode_verified"] is True


def test_artifact_store_put_is_idempotent_for_same_bytes_and_provenance(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    content = make_png()
    first = store.put_png(content, source_kind="generated", source_ref="artifact://local/one")
    second = store.put_png(content, source_kind="generated", source_ref="artifact://local/one")

    assert first.asset.descriptor.asset_id == second.asset.descriptor.asset_id
    assert store.get_png(first.asset.descriptor.asset_id).content == content


def test_identical_bytes_with_distinct_provenance_get_distinct_asset_ids(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    content = make_png()
    first = store.put_png(content, source_kind="user_upload", source_ref="upload://a")
    second = store.put_png(content, source_kind="generated", source_ref="artifact://b")

    assert first.asset.descriptor.content_sha256 == second.asset.descriptor.content_sha256
    assert first.asset.descriptor.asset_id != second.asset.descriptor.asset_id
    blob = store._blob_path(store.root, hashlib.sha256(content).hexdigest())
    assert blob.is_file()


def test_artifact_store_rejects_tampered_blob_on_read(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    stored = store.put_png(
        make_png(), source_kind="generated", source_ref="artifact://tamper-test"
    )
    digest = stored.asset.descriptor.content_sha256
    blob = store._blob_path(store.root, digest)
    blob.write_bytes(b"tampered")

    with pytest.raises(ArtifactStoreError):
        store.get_png(stored.asset.descriptor.asset_id)


def test_artifact_store_rejects_tampered_descriptor_on_read(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    stored = store.put_png(
        make_png(), source_kind="generated", source_ref="artifact://descriptor-test"
    )
    descriptor_path = store._descriptor_path(stored.asset.descriptor.asset_id)
    descriptor_path.write_text('{"schema":"mahoraga.image_asset.v1","asset_id":"forged"}')

    with pytest.raises(ArtifactStoreError):
        store.get_png(stored.asset.descriptor.asset_id)


def test_artifact_store_rejects_invalid_asset_ids_without_path_traversal(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    for asset_id in ("../outside", "/tmp/file", "asset-" + "z" * 48, ""):
        with pytest.raises(ArtifactStoreError):
            store.get_png(asset_id)


def test_artifact_store_rejects_mismatched_declared_digest(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ArtifactStoreError):
        store.put_png(
            make_png(),
            source_kind="user_upload",
            source_ref="upload://mismatch",
            declared_sha256="0" * 64,
        )


def test_artifact_store_does_not_follow_blob_symlinks(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    stored = store.put_png(
        make_png(), source_kind="generated", source_ref="artifact://symlink-test"
    )
    digest = stored.asset.descriptor.content_sha256
    blob = store._blob_path(store.root, digest)
    outside = tmp_path / "outside.png"
    outside.write_bytes(stored.content)
    blob.unlink()
    os.symlink(outside, blob)

    with pytest.raises(ArtifactStoreError):
        store.get_png(stored.asset.descriptor.asset_id)


def test_artifact_store_rejects_symlink_root(tmp_path):
    real_root = tmp_path / "real-artifacts"
    real_root.mkdir(mode=0o700)
    link_root = tmp_path / "linked-artifacts"
    os.symlink(real_root, link_root)

    with pytest.raises(ArtifactStoreError):
        ArtifactStore(link_root)


def test_artifact_store_does_not_change_permissions_of_existing_root(tmp_path):
    root = tmp_path / "shared-artifacts"
    root.mkdir()
    root.chmod(0o755)

    with pytest.raises(ArtifactStoreError, match="privado"):
        ArtifactStore(root)

    assert root.stat().st_mode & 0o777 == 0o755



def test_artifact_store_initializes_private_blob_and_descriptor_directories(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")

    for directory in (store.root, store.blob_root, store.descriptor_root):
        assert directory.is_dir()
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
