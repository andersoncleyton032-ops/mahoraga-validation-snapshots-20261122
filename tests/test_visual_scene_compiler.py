from __future__ import annotations

import pytest

from agent.visual_creation import (
    TransformSpec,
    VisualDocumentSpec,
    VisualElementSpec,
    VisualLayerSpec,
    VisualReferenceSpec,
    VisualStyleSpec,
)
from agent.visual_scene_compiler import VisualSceneCompiler


def camera(element_id: str = "camera.main", *, transform: TransformSpec | None = None):
    return VisualElementSpec(
        element_id=element_id,
        kind="camera",
        layer_id="layer.main",
        transform=transform or TransformSpec(),
        data={"origin": [0.0, 0.0, 5.0], "target": [0.0, 0.0, 0.0]},
    )


def scene_document(*elements: VisualElementSpec, **kwargs) -> VisualDocumentSpec:
    return VisualDocumentSpec(
        document_id="scene.compiler-test",
        title="Compiler test",
        coordinate_space="3d",
        layers=(VisualLayerSpec("layer.main", "Main", 0),),
        elements=tuple(elements),
        **kwargs,
    )


def test_compiler_maps_camera_sphere_and_point_light_with_provenance() -> None:
    sphere = VisualElementSpec(
        "element.sphere", "shape", "layer.main",
        transform=TransformSpec(translation=(1.0, 0.0, 0.0)),
        data={"primitive": "sphere", "radius": 1.5, "albedo": [0.2, 0.3, 0.4]},
    )
    light = VisualElementSpec(
        "light.key", "light", "layer.main",
        transform=TransformSpec(translation=(2.0, 3.0, 4.0)),
        data={"intensity": [5.0, 5.0, 5.0]},
    )
    document = scene_document(camera(), sphere, light)

    result = VisualSceneCompiler.compile(document)

    assert result.status == "compiled"
    assert result.scene is not None
    assert result.scene.scene_id == document.document_id
    assert result.scene.spheres[0].center == (1.0, 0.0, 0.0)
    assert result.scene.spheres[0].radius == 1.5
    assert result.scene.point_lights[0].position == (2.0, 3.0, 4.0)
    assert result.source_document_sha256 == document.sha256()
    assert result.scene_spec_sha256 == result.scene.sha256()
    assert ("camera", "camera.main") in result.element_bindings
    assert ("spheres[0]", "element.sphere") in result.element_bindings
    assert ("point_lights[0]", "light.key") in result.element_bindings


def test_compiler_maps_axis_aligned_and_oriented_boxes() -> None:
    axis_box = VisualElementSpec(
        "box.axis", "shape", "layer.main",
        data={"primitive": "box", "half_extents": [1.0, 2.0, 3.0]},
    )
    rotated_box = VisualElementSpec(
        "box.rotated", "shape", "layer.main",
        transform=TransformSpec(
            translation=(1.0, 2.0, 3.0),
            rotation_degrees=(0.0, 25.0, 0.0),
            scale=(2.0, 1.0, 1.0),
        ),
        data={"primitive": "box", "half_extents": [0.5, 0.5, 0.5]},
    )

    result = VisualSceneCompiler.compile(scene_document(camera(), axis_box, rotated_box))

    assert result.status == "compiled"
    assert result.scene is not None
    assert len(result.scene.boxes) == 1
    assert result.scene.boxes[0].minimum == (-1.0, -2.0, -3.0)
    assert len(result.scene.oriented_boxes) == 1
    assert result.scene.oriented_boxes[0].center == (1.0, 2.0, 3.0)
    assert result.scene.oriented_boxes[0].half_extents == (1.0, 0.5, 0.5)


def test_compiler_maps_plane_normal_and_camera_transform() -> None:
    plane = VisualElementSpec(
        "plane.floor", "shape", "layer.main",
        data={"primitive": "plane", "normal": [0.0, 1.0, 0.0]},
    )
    camera_element = camera(
        transform=TransformSpec(
            translation=(1.0, 0.0, 0.0),
            rotation_degrees=(0.0, 90.0, 0.0),
        )
    )

    result = VisualSceneCompiler.compile(scene_document(camera_element, plane))

    assert result.status == "compiled"
    assert result.scene is not None
    assert result.scene.planes[0].point == (0.0, 0.0, 0.0)
    assert result.scene.planes[0].normal == (0.0, 1.0, 0.0)
    assert result.scene.camera.origin == (6.0, 0.0, 0.0)
    assert result.scene.camera.target == (1.0, 0.0, 0.0)


def test_compiler_refuses_2d_documents_without_claiming_renderability() -> None:
    document = VisualDocumentSpec(
        document_id="scene.2d",
        title="2D drawing",
        coordinate_space="2d",
    )

    result = VisualSceneCompiler.compile(document)

    assert result.status == "unsupported_coordinate_space"
    assert result.scene is None
    assert result.source_document_sha256 == document.sha256()


def test_compiler_requires_exactly_one_visible_camera() -> None:
    missing = scene_document()
    duplicate = scene_document(camera(), camera("camera.other"))

    assert VisualSceneCompiler.compile(missing).status == "camera_required"
    result = VisualSceneCompiler.compile(duplicate)
    assert result.status == "camera_required"
    assert set(result.unsupported_element_ids) == {"camera.main", "camera.other"}


def test_compiler_reports_unsupported_elements_instead_of_dropping_them() -> None:
    unknown = VisualElementSpec(
        "element.stroke", "stroke", "layer.main",
        data={"points": [[0, 0], [1, 1]]},
    )

    result = VisualSceneCompiler.compile(scene_document(camera(), unknown))

    assert result.status == "unsupported_elements"
    assert result.scene is None
    assert result.unsupported_element_ids == ("element.stroke",)


def test_compiler_rejects_unknown_primitive_fields() -> None:
    invalid_shape = VisualElementSpec(
        "element.sphere", "shape", "layer.main",
        data={
            "primitive": "sphere",
            "radius": 1.0,
            "half_extents": [1.0, 1.0, 1.0],
        },
    )

    result = VisualSceneCompiler.compile(scene_document(camera(), invalid_shape))

    assert result.status == "unsupported_elements"
    assert result.unsupported_element_ids == ("element.sphere",)


def test_compiler_skips_hidden_layers_and_tracks_the_skipped_ids() -> None:
    hidden_layer = VisualLayerSpec("layer.hidden", "Hidden", 1, visible=False)
    hidden_shape = VisualElementSpec(
        "element.hidden", "shape", "layer.hidden",
        data={"primitive": "sphere", "radius": 2.0},
    )
    document = VisualDocumentSpec(
        document_id="scene.hidden",
        title="Hidden layers",
        coordinate_space="3d",
        layers=(VisualLayerSpec("layer.main", "Main", 0), hidden_layer),
        elements=(camera(), hidden_shape),
    )

    result = VisualSceneCompiler.compile(document)

    assert result.status == "compiled"
    assert result.scene is not None
    assert result.scene.spheres == ()
    assert result.skipped_hidden_element_ids == ("element.hidden",)


def test_hidden_group_hides_descendants_even_when_child_layer_is_visible() -> None:
    group_layer = VisualLayerSpec("layer.group", "Group", 0, visible=False)
    group = VisualElementSpec("group.character", "group", "layer.group")
    child = VisualElementSpec(
        "element.body", "shape", "layer.main",
        parent_id="group.character",
        data={"primitive": "sphere", "radius": 1.0},
    )
    document = VisualDocumentSpec(
        document_id="scene.hidden-parent",
        title="Hidden parent",
        coordinate_space="3d",
        layers=(VisualLayerSpec("layer.main", "Main", 1), group_layer),
        elements=(camera(), group, child),
    )

    result = VisualSceneCompiler.compile(document)

    assert result.status == "compiled"
    assert result.scene is not None
    assert result.scene.spheres == ()
    assert set(result.skipped_hidden_element_ids) == {"group.character", "element.body"}


def test_compiler_blocks_document_references_it_cannot_preserve() -> None:
    document = scene_document(
        camera(),
        references=(VisualReferenceSpec("ref.one", "asset.one", "character identity"),),
    )

    result = VisualSceneCompiler.compile(document)

    assert result.status == "unsupported_references"
    assert result.scene is None
    assert result.unsupported_element_ids == ("ref.one",)


def test_compiler_blocks_style_features_not_represented_by_scene_spec() -> None:
    document = scene_document(
        camera(),
        style=VisualStyleSpec(style_id="style.ink", medium="ink", parameters={"line": "brush"}),
    )

    result = VisualSceneCompiler.compile(document)

    assert result.status == "unsupported_style_profile"
    assert result.scene is None


def test_compiler_blocks_layer_compositing_instead_of_ignoring_it() -> None:
    document = VisualDocumentSpec(
        document_id="scene.opacity",
        title="Opacity",
        coordinate_space="3d",
        layers=(VisualLayerSpec("layer.main", "Main", 0, opacity=0.5),),
        elements=(
            VisualElementSpec(
                "camera.main", "camera", "layer.main",
                data={"origin": [0, 0, 5], "target": [0, 0, 0]},
            ),
        ),
    )

    result = VisualSceneCompiler.compile(document)

    assert result.status == "unsupported_layer_compositing"
    assert result.scene is None
    assert result.unsupported_element_ids == ("camera.main",)


def test_compiler_blocks_transformed_groups_until_group_transforms_are_supported() -> None:
    group = VisualElementSpec(
        "group.character", "group", "layer.main",
        transform=TransformSpec(translation=(1.0, 0.0, 0.0)),
    )

    result = VisualSceneCompiler.compile(scene_document(camera(), group))

    assert result.status == "unsupported_elements"
    assert result.unsupported_element_ids == ("group.character",)


def test_compiler_blocks_asset_backed_shapes_until_asset_adaptation_exists() -> None:
    image_backed_shape = VisualElementSpec(
        "element.texture", "shape", "layer.main", asset_id="asset.texture",
        data={"primitive": "sphere", "radius": 1.0},
    )

    result = VisualSceneCompiler.compile(scene_document(camera(), image_backed_shape))

    assert result.status == "unsupported_elements"
    assert result.unsupported_element_ids == ("element.texture",)


def test_compiler_rejects_nonuniform_sphere_scale() -> None:
    sphere = VisualElementSpec(
        "element.ellipsoid", "shape", "layer.main",
        transform=TransformSpec(scale=(1.0, 2.0, 1.0)),
        data={"primitive": "sphere", "radius": 1.0},
    )

    result = VisualSceneCompiler.compile(scene_document(camera(), sphere))

    assert result.status == "unsupported_elements"
    assert result.unsupported_element_ids == ("element.ellipsoid",)


def test_image_task_bridge_prepares_path_trace_spec_without_execution() -> None:
    from agent.visual_scene_compiler import compile_visual_image_task

    document = scene_document(camera(), VisualElementSpec(
        "element.sphere", "shape", "layer.main",
        data={"primitive": "sphere", "radius": 0.8},
    ))

    result = compile_visual_image_task(document, task_id="task.visual.001")

    assert result.status == "ready_for_governed_executor"
    assert result.task_spec is not None
    assert result.task_spec.operation == "path_trace"
    assert result.task_spec.scene_id == document.document_id
    assert result.task_spec.scene_spec_sha256 == result.scene_spec_sha256
    assert result.source_document_sha256 == document.sha256()
    assert result.scene is not None
    assert result.task_spec.backend_preference == "cpu.pathtracer"
    assert result.task_spec.width == 64
    assert result.task_spec.height == 64
    assert result.execution_started is False
    assert ("spheres[0]", "element.sphere") in result.element_bindings


def test_image_task_bridge_rejects_dimensions_above_cpu_backend_limits() -> None:
    from agent.visual_scene_compiler import compile_visual_image_task

    result = compile_visual_image_task(
        scene_document(camera()), task_id="task.visual.large", width=129, height=64,
    )

    assert result.status == "unsupported_render_dimensions"
    assert result.task_spec is None
    assert result.scene is not None
    assert result.execution_started is False


def test_image_task_bridge_rejects_invalid_task_contract_inputs() -> None:
    from agent.visual_scene_compiler import compile_visual_image_task

    result = compile_visual_image_task(
        scene_document(camera()), task_id="invalid task id", seed=-1,
    )

    assert result.status == "invalid_task_spec"
    assert result.task_spec is None
    assert result.scene is not None
    assert result.execution_started is False


def test_image_task_bridge_reuses_compiler_fail_closed_result() -> None:
    from agent.visual_scene_compiler import compile_visual_image_task

    unsupported = VisualElementSpec(
        "element.stroke", "stroke", "layer.main",
        data={"points": [[0, 0, 0], [1, 1, 1]]},
    )
    result = compile_visual_image_task(
        scene_document(camera(), unsupported), task_id="task.visual.unsupported",
    )

    assert result.status == "unsupported_elements"
    assert result.task_spec is None
    assert result.scene is None
    assert result.source_document_sha256 is not None
    assert result.unsupported_element_ids == ("element.stroke",)
    assert result.execution_started is False


def test_image_task_bridge_rejects_unvalidated_resource_budget_object() -> None:
    from agent.visual_scene_compiler import compile_visual_image_task

    result = compile_visual_image_task(
        scene_document(camera()),
        task_id="task.visual.invalid-budget",
        resource_budget=object(),  # type: ignore[arg-type]
    )

    assert result.status == "invalid_task_spec"
    assert result.task_spec is None
    assert result.execution_started is False


def test_compiler_rejects_camera_with_asset_reference() -> None:
    invalid_camera = VisualElementSpec(
        "camera.main", "camera", "layer.main",
        asset_id="asset.camera",
        data={"origin": [0, 0, 5], "target": [0, 0, 0]},
    )

    result = VisualSceneCompiler.compile(scene_document(invalid_camera))

    assert result.status == "invalid_camera"
    assert result.scene is None
    assert result.unsupported_element_ids == ("camera.main",)


def test_compiler_rejects_group_payloads_it_cannot_interpret() -> None:
    group = VisualElementSpec(
        "group.character", "group", "layer.main",
        data={"blend_children": "multiply"},
    )

    result = VisualSceneCompiler.compile(scene_document(camera(), group))

    assert result.status == "unsupported_elements"
    assert result.scene is None
    assert result.unsupported_element_ids == ("group.character",)


def test_prepared_image_task_builds_immutable_document_to_task_provenance() -> None:
    from agent.visual_scene_compiler import compile_visual_image_task

    document = scene_document(
        camera(),
        VisualElementSpec(
            "element.sphere", "shape", "layer.main",
            data={"primitive": "sphere", "radius": 0.8},
        ),
    )
    prepared = compile_visual_image_task(document, task_id="task.provenance.001")

    provenance = prepared.render_provenance()

    assert provenance.source_document_sha256 == document.sha256()
    assert provenance.scene_spec_sha256 == prepared.scene.sha256()
    assert provenance.task_id == prepared.task_spec.task_id
    assert provenance.task_sha256 == prepared.task_spec.sha256()
    assert ("camera", "camera.main") in provenance.element_bindings
    assert ("spheres[0]", "element.sphere") in provenance.element_bindings
    assert provenance.to_dict()["source_provenance_authenticated"] is False


def test_failed_visual_compile_cannot_create_render_provenance() -> None:
    from agent.visual_scene_compiler import (
        VisualSceneCompilationError,
        compile_visual_image_task,
    )

    failed = compile_visual_image_task(
        scene_document(camera(), VisualElementSpec(
            "element.stroke", "stroke", "layer.main",
            data={"points": [[0, 0, 0], [1, 1, 1]]},
        )),
        task_id="task.provenance.failed",
    )

    with pytest.raises(VisualSceneCompilationError, match="Somente uma tarefa preparada"):
        failed.render_provenance()


def test_visual_render_provenance_rejects_duplicate_scene_paths() -> None:
    from agent.visual_scene_compiler import (
        VisualRenderProvenance,
        VisualSceneCompilationError,
    )

    digest = "a" * 64
    with pytest.raises(VisualSceneCompilationError, match="únicos"):
        VisualRenderProvenance(
            source_document_sha256=digest,
            scene_spec_sha256=digest,
            task_id="task.duplicate.path",
            task_sha256=digest,
            element_bindings=(
                ("spheres[0]", "element.one"),
                ("spheres[0]", "element.two"),
            ),
        )


def test_visual_render_provenance_rejects_invalid_digest_and_hidden_overlap() -> None:
    from agent.visual_scene_compiler import (
        VisualRenderProvenance,
        VisualSceneCompilationError,
    )

    digest = "b" * 64
    with pytest.raises(VisualSceneCompilationError, match="SHA-256"):
        VisualRenderProvenance(
            source_document_sha256="not-a-digest",
            scene_spec_sha256=digest,
            task_id="task.invalid.digest",
            task_sha256=digest,
            element_bindings=(),
        )
    with pytest.raises(VisualSceneCompilationError, match="visível e oculto"):
        VisualRenderProvenance(
            source_document_sha256=digest,
            scene_spec_sha256=digest,
            task_id="task.hidden.overlap",
            task_sha256=digest,
            element_bindings=(("camera", "camera.main"),),
            skipped_hidden_element_ids=("camera.main",),
        )


def test_visual_render_provenance_accepts_historical_semver() -> None:
    from agent.visual_scene_compiler import VisualRenderProvenance

    digest = "e" * 64
    record = VisualRenderProvenance(
        source_document_sha256=digest,
        scene_spec_sha256=digest,
        task_id="task.historical.compiler",
        task_sha256=digest,
        element_bindings=(),
        compiler_version="0.0.9",
    )

    assert record.compiler_version == "0.0.9"


def test_visual_render_provenance_rejects_malformed_compiler_version() -> None:
    from agent.visual_scene_compiler import (
        VisualRenderProvenance,
        VisualSceneCompilationError,
    )

    digest = "f" * 64
    with pytest.raises(VisualSceneCompilationError, match="(?i)versão do compilador"):
        VisualRenderProvenance(
            source_document_sha256=digest,
            scene_spec_sha256=digest,
            task_id="task.bad.compiler.version",
            task_sha256=digest,
            element_bindings=(),
            compiler_version="current",
        )
