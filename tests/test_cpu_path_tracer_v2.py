import hashlib
import json
import struct
from pathlib import Path

import pytest

from agent.cpu_path_tracer import (
    CPUPathTracerBackend, CameraSpec, PathTracingError, PointLightSpec,
    SceneSpec, TriangleSpec,
)
from agent.image_generation import ImageGenerationEngine


def scene_v1():
    return {
        "schema": "mahoraga.scene.v1",
        "scene_id": "mahoraga-visual-lab-v1",
        "camera": {
            "origin": [0.0, 1.9, 4.8],
            "target": [0.0, 0.85, 0.0],
            "up": [0.0, 1.0, 0.0],
            "vertical_fov_degrees": 42.0,
        },
        "spheres": [
            {"center": [-0.85, 0.88, 0.0], "radius": 0.88,
             "albedo": [0.18, 0.34, 0.72]},
            {"center": [0.92, 0.52, -0.35], "radius": 0.52,
             "albedo": [0.72, 0.31, 0.12]},
            {"center": [0.0, 3.5, 0.4], "radius": 0.28,
             "albedo": [0.0, 0.0, 0.0], "emission": [3.5, 3.1, 2.5]},
        ],
        "triangles": [
            {"a": [-5.0, 0.0, -5.0], "b": [5.0, 0.0, -5.0],
             "c": [5.0, 0.0, 5.0], "albedo": [0.42, 0.46, 0.50]},
            {"a": [-5.0, 0.0, -5.0], "b": [5.0, 0.0, 5.0],
             "c": [-5.0, 0.0, 5.0], "albedo": [0.42, 0.46, 0.50]},
        ],
        "point_lights": [
            {"position": [-2.5, 4.2, 3.0], "intensity": [420.0, 385.0, 330.0]}
        ],
        "background_top": [0.16, 0.22, 0.34],
        "background_bottom": [0.52, 0.58, 0.67],
    }


def test_legacy_scene_schema_remains_compatible():
    legacy = {
        "camera": {"origin": [0, 0, 5], "target": [0, 0, 0]},
        "spheres": [{"center": [0, 0, 0], "radius": 1, "albedo": [0.5, 0.5, 0.5]}],
    }
    parsed = SceneSpec.from_mapping(legacy)
    assert len(parsed.spheres) == 1
    assert parsed.triangles == ()
    assert parsed.point_lights == ()


def test_scene_v1_adds_triangles_and_point_lights():
    parsed = SceneSpec.from_mapping(scene_v1())
    assert parsed.scene_id == "mahoraga-visual-lab-v1"
    assert len(parsed.spheres) == 3
    assert len(parsed.triangles) == 2
    assert len(parsed.point_lights) == 1


def test_scene_rejects_unknown_fields_degenerate_triangles_and_invalid_vectors():
    value = scene_v1()
    value["triangles"][0] = {
        "a": [0, 0, 0], "b": [1, 1, 1], "c": [2, 2, 2],
        "albedo": [0.5, 0.5, 0.5],
    }
    with pytest.raises(PathTracingError, match="área nula"):
        SceneSpec.from_mapping(value)
    value = scene_v1()
    value["untrusted_code"] = "do_not_execute"
    with pytest.raises(PathTracingError, match="campos desconhecidos"):
        SceneSpec.from_mapping(value)


def test_triangle_and_point_light_render_are_deterministic_and_effective():
    scene = scene_v1()
    first = CPUPathTracerBackend.render_rgb(
        48, 32, scene=scene, seed=41, samples_per_pixel=2, max_depth=3
    )
    repeated = CPUPathTracerBackend.render_rgb(
        48, 32, scene=scene, seed=41, samples_per_pixel=2, max_depth=3
    )
    changed_seed = CPUPathTracerBackend.render_rgb(
        48, 32, scene=scene, seed=42, samples_per_pixel=2, max_depth=3
    )
    without_light = dict(scene)
    without_light["point_lights"] = []
    no_light = CPUPathTracerBackend.render_rgb(
        48, 32, scene=without_light, seed=41, samples_per_pixel=2, max_depth=3
    )
    without_floor = dict(scene)
    without_floor["triangles"] = []
    no_floor = CPUPathTracerBackend.render_rgb(
        48, 32, scene=without_floor, seed=41, samples_per_pixel=2, max_depth=3
    )
    assert len(first) == 48 * 32 * 3
    assert first == repeated
    assert first != changed_seed
    assert first != no_light
    assert first != no_floor


def test_renderer_rejects_geometry_and_work_budget_overruns():
    scene = scene_v1()
    scene["point_lights"] = [
        {"position": [i + 1.0, 4.0, 2.0], "intensity": [1.0, 1.0, 1.0]}
        for i in range(8)
    ]
    with pytest.raises(PathTracingError, match="orçamento"):
        CPUPathTracerBackend.render_rgb(
            128, 128, scene=scene, samples_per_pixel=8, max_depth=4
        )
    scene = scene_v1()
    scene["triangles"] = scene["triangles"] * 33
    with pytest.raises(PathTracingError):
        SceneSpec.from_mapping(scene)


def test_scene_seed_and_dimension_types_are_strict():
    with pytest.raises(PathTracingError):
        CPUPathTracerBackend.render_rgb(True, 10)
    with pytest.raises(PathTracingError):
        CPUPathTracerBackend.render_rgb(10, 10, seed=True)
    with pytest.raises(PathTracingError):
        CPUPathTracerBackend.render_rgb(10, 10, samples_per_pixel=9)
    with pytest.raises(PathTracingError):
        CPUPathTracerBackend.render_rgb(10, 10, max_depth=5)


def test_facade_writes_png_and_reports_scene_provenance(tmp_path):
    engine = ImageGenerationEngine(tmp_path / "artifacts")
    result = engine.generate_path_traced(
        64, 48, scene=scene_v1(), seed=2026, samples_per_pixel=2
    )
    data = Path(result["artifact_path"]).read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", data[16:24]) == (64, 48)
    assert hashlib.sha256(data).hexdigest() == result["sha256"]
    assert result["backend"] == "cpu.pathtracer"
    assert result["path_tracing"] is True
    assert result["validated"] is True
    assert engine.status()["runtime_dispatch_enabled"] is False


def test_backend_status_matches_extended_contract():
    status = CPUPathTracerBackend.status()
    assert status["supported_geometry"] == ["sphere", "triangle"]
    assert status["direct_light_sampling"] is True
    assert status["max_triangles"] == 64
    assert status["max_point_lights"] == 8
    assert status["real_device_validation"] is False


def test_scene_dataclasses_validate_direct_construction_and_limits():
    with pytest.raises(PathTracingError, match="área nula"):
        TriangleSpec(
            (0, 0, 0), (1, 1, 1), (2, 2, 2), (0.5, 0.5, 0.5)
        )
    with pytest.raises(PathTracingError):
        PointLightSpec((0, 0, 0), (1001, 0, 0))

    valid_triangle = TriangleSpec(
        (0, 0, 0), (1, 0, 0), (0, 1, 0), (0.5, 0.5, 0.5)
    )
    camera = CameraSpec((0, 0, 5), (0, 0, 0))
    with pytest.raises(PathTracingError, match="triangles"):
        SceneSpec(camera, (), triangles=(valid_triangle,) * 65)
    with pytest.raises(PathTracingError, match="background_top"):
        SceneSpec(camera, (), background_top=(0.5, 0.5, 1.1))
    with pytest.raises(PathTracingError, match="spheres"):
        SceneSpec(camera, ({"center": [0, 0, 0]},))


def test_scene_spec_round_trip_uses_one_canonical_schema():
    scene = SceneSpec.from_mapping(scene_v1())
    encoded = scene.to_dict()
    assert encoded["schema"] == SceneSpec.SCHEMA
    restored = SceneSpec.from_mapping(encoded)
    assert restored.to_dict() == encoded
    assert restored.sha256() == scene.sha256()

    legacy = dict(scene_v1())
    legacy["schema"] = "mahoraga.scene.v1"
    assert SceneSpec.from_mapping(legacy).sha256() == scene.sha256()
