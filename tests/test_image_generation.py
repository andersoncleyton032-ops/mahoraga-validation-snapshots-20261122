import hashlib
import struct
import zlib
from pathlib import Path

import pytest

from agent.image_generation import (
    ImageGenerationEngine,
    ImageGenerationError,
    ProceduralImageBackend,
)
from agent.integration_core import IntegratedCore
from agent.store import KnowledgeStore


class FakeHardware:
    def snapshot(self):
        return {"android": {"model": "test-device"}, "available_tools": {}}


def _png_dimensions(data):
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_procedural_backend_generates_valid_deterministic_png(tmp_path):
    engine = ImageGenerationEngine(tmp_path / "images")
    first = engine.generate_procedural(64, 48, seed=42)
    second = engine.generate_procedural(64, 48, seed=42)

    data = Path(first["artifact_path"]).read_bytes()
    assert _png_dimensions(data) == (64, 48)
    assert data[-12:] == b"\x00\x00\x00\x00IEND\xaeB\x60\x82"
    decompressed = zlib.decompress(data[41:-16])
    assert len(decompressed) == 48 * (1 + 64 * 3)
    assert first["sha256"] == second["sha256"]
    assert first["artifact_path"] == second["artifact_path"]
    assert first["validated"] is True
    assert hashlib.sha256(data).hexdigest() == first["sha256"]


def test_seed_changes_procedural_output(tmp_path):
    backend = ProceduralImageBackend()
    assert backend.render(32, 32, 1) != backend.render(32, 32, 2)


@pytest.mark.parametrize(
    "width,height,seed",
    [
        (0, 10, 1),
        (1025, 10, 1),
        (1024, 1024, 1),
        (True, 10, 1),
        (10, 10, False),
        (10, 10, 2**63),
    ],
)
def test_invalid_or_over_budget_requests_are_rejected(width, height, seed):
    with pytest.raises(ImageGenerationError):
        ProceduralImageBackend.render(width, height, seed)


def test_integrated_core_exposes_one_shared_image_generation_engine_without_init_writes(tmp_path):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    core = IntegratedCore(root=tmp_path, store=store, hardware=FakeHardware())

    assert not (tmp_path / "artifacts").exists()
    assert core.image_generation.status()["component"] == "ImageGenerationEngine"
    assert core.image_generation.artifact_root == (
        tmp_path / "artifacts" / "images"
    ).resolve()
    assert core.store is store
    assert core.build_report()["status"] == "healthy"


def test_generation_does_not_write_to_the_canonical_sqlite_store(tmp_path):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    core = IntegratedCore(root=tmp_path, store=store, hardware=FakeHardware())
    before_counts = store.counts()
    before_events = store.list_events(limit=1000)

    result = core.image_generation.generate_procedural(24, 24, seed=7)

    assert result["validated"] is True
    assert store.counts() == before_counts
    assert store.list_events(limit=1000) == before_events


from agent.cpu_path_tracer import (CameraSpec, CPUPathTracerBackend, PathTracingError, SceneSpec, SphereSpec)


def test_cpu_path_tracer_is_deterministic_and_seed_sensitive():
    first = CPUPathTracerBackend.render_rgb(24, 18, seed=23, samples_per_pixel=2)
    repeated = CPUPathTracerBackend.render_rgb(24, 18, seed=23, samples_per_pixel=2)
    changed = CPUPathTracerBackend.render_rgb(24, 18, seed=24, samples_per_pixel=2)
    assert len(first) == 24 * 18 * 3
    assert first == repeated
    assert first != changed


def test_cpu_path_tracer_rejects_excessive_or_invalid_work():
    with pytest.raises(PathTracingError):
        CPUPathTracerBackend.render_rgb(129, 128)
    with pytest.raises(PathTracingError):
        CPUPathTracerBackend.render_rgb(True, 10)
    with pytest.raises(PathTracingError):
        CPUPathTracerBackend.render_rgb(10, 10, samples_per_pixel=9)

    sphere = {"center": [0, 0, 0], "radius": 1, "albedo": [0.5, 0.5, 0.5]}
    scene = {
        "camera": {"origin": [0, 0, 5], "target": [0, 0, 0]},
        "spheres": [sphere] * 32,
    }
    with pytest.raises(PathTracingError):
        CPUPathTracerBackend.render_rgb(
            128, 128, scene=scene, samples_per_pixel=8, max_depth=4
        )


def test_scene_spec_rejects_unknown_fields_and_more_than_32_spheres():
    with pytest.raises(PathTracingError):
        SceneSpec.from_mapping({"camera": {"origin": [0, 0, 4], "target": [0, 0, 0]},
                                "spheres": [], "script": "not allowed"})
    sphere = {"center": [0, 0, 0], "radius": 1, "albedo": [0.5, 0.5, 0.5]}
    with pytest.raises(PathTracingError):
        SceneSpec.from_mapping({"camera": {"origin": [0, 0, 4], "target": [0, 0, 0]},
                                "spheres": [sphere] * 33})


def test_image_engine_stores_path_traced_png_and_preserves_sqlite(tmp_path):
    store = KnowledgeStore(tmp_path / "memory.sqlite3")
    core = IntegratedCore(root=tmp_path, store=store, hardware=FakeHardware())
    assert not (tmp_path / "artifacts").exists()
    assert core.image_generation.status()["runtime_dispatch_enabled"] is False
    before_counts = store.counts()
    before_events = store.list_events(limit=1000)
    result = core.image_generation.generate_path_traced(16, 12, seed=7, samples_per_pixel=2)
    data = Path(result["artifact_path"]).read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", data[16:24]) == (16, 12)
    assert result["backend"] == "cpu.pathtracer"
    assert result["path_tracing"] is True
    assert hashlib.sha256(data).hexdigest() == result["sha256"]
    assert store.counts() == before_counts
    assert store.list_events(limit=1000) == before_events


def test_direct_scene_dataclasses_validate_values_not_only_mapping_input():
    with pytest.raises(PathTracingError):
        CameraSpec((0, 0, 0), (0, 0, 0))
    with pytest.raises(PathTracingError):
        CameraSpec((0, 0, 0), (0, 0, -1), up=(0, 0, 1))
    with pytest.raises(PathTracingError):
        SphereSpec((0, 0, 0), 0, (0.5, 0.5, 0.5))
    with pytest.raises(PathTracingError):
        SceneSpec(CameraSpec((0, 0, 4), (0, 0, 0)), [object()])
    with pytest.raises(PathTracingError):
        SceneSpec(CameraSpec((0, 0, 4), (0, 0, 0)), [SphereSpec((0, 0, 0), 1, (0.5, 0.5, 0.5))] * 33)


def test_path_tracer_rejects_huge_numeric_scene_fields():
    with pytest.raises(PathTracingError):
        SphereSpec((10**1000, 0, 0), 1, (0.5, 0.5, 0.5))
    with pytest.raises(PathTracingError):
        CameraSpec((0, 0, 4), (0, 0, 0), vertical_fov_degrees=10**1000)


def test_scene_spec_has_stable_canonical_hash_and_round_trips():
    scene = SceneSpec.default()
    encoded = scene.to_dict()
    restored = SceneSpec.from_mapping(encoded)
    assert restored.to_dict() == encoded
    assert restored.sha256() == scene.sha256()
    assert len(scene.sha256()) == 64
    changed = SceneSpec.from_mapping({
        "schema": "mahoraga.scene_spec.v1",
        "camera": encoded["camera"],
        "spheres": encoded["spheres"][:-1],
    })
    assert changed.sha256() != scene.sha256()


def test_scene_spec_rejects_unknown_versions():
    data = SceneSpec.default().to_dict()
    data["schema"] = "mahoraga.scene_spec.v99"
    with pytest.raises(PathTracingError):
        SceneSpec.from_mapping(data)


def test_path_trace_metadata_contains_scene_identity(tmp_path):
    engine = ImageGenerationEngine(tmp_path / "images")
    scene = SceneSpec.default()
    result = engine.generate_path_traced(12, 12, scene=scene, seed=9)
    assert result["scene_sha256"] == scene.sha256()
    assert result["scene"] == scene.to_dict()
