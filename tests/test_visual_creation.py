from __future__ import annotations

import json

import pytest

from agent.visual_creation import (
    TransformSpec,
    VisualConstructionStepSpec,
    VisualDocumentError,
    VisualDocumentSpec,
    VisualElementSpec,
    VisualLayerSpec,
    VisualReferenceSpec,
    VisualStyleSpec,
)


def sample_document() -> VisualDocumentSpec:
    return VisualDocumentSpec(
        document_id="scene.study.001",
        title="Personagem — estudos de pose",
        coordinate_space="mixed",
        canvas_width=1200,
        canvas_height=900,
        layers=(
            VisualLayerSpec("layer.guides", "Guias", 0, "guide", opacity=0.4),
            VisualLayerSpec("layer.art", "Arte", 1, "vector"),
            VisualLayerSpec("layer.refs", "Referências", 2, "reference", locked=True),
        ),
        elements=(
            VisualElementSpec(
                "element.character", "group", "layer.art", name="Personagem",
                role="main_subject",
            ),
            VisualElementSpec(
                "element.torso", "shape", "layer.art", name="Torso",
                role="anatomy.volume", parent_id="element.character",
                transform=TransformSpec(translation=(0.0, 1.2, 0.0)),
                data={"primitive": "ellipsoid", "proportion": 0.31},
            ),
            VisualElementSpec(
                "element.pose", "pose", "layer.guides", name="Pose-chave",
                role="pose.keyframe", data={"pose_index": 0, "balance": "centered"},
            ),
        ),
        references=(
            VisualReferenceSpec("reference.model_sheet", "asset:sha256:abc123", "identity"),
        ),
        construction_steps=(
            VisualConstructionStepSpec(
                "step.gesture", "gesture", "Definir linha de ação",
                target_element_ids=("element.pose",),
            ),
            VisualConstructionStepSpec(
                "step.block", "geometric_blocking", "Construir volumes principais",
                target_element_ids=("element.character", "element.torso"),
                depends_on=("step.gesture",),
            ),
            VisualConstructionStepSpec(
                "step.anatomy", "anatomy", "Revisar proporções e equilíbrio",
                target_element_ids=("element.torso",),
                depends_on=("step.block",),
            ),
        ),
        style=VisualStyleSpec(
            style_id="style.concept-sketch",
            medium="concept_art",
            description="Estudo estrutural com guias visíveis",
            parameters={"line_weight": 1.4, "palette": ["warm_gray", "charcoal"]},
        ),
        metadata={"authoring_mode": "incremental", "learning_level": "guided"},
    )


def test_document_round_trip_and_canonical_hash_are_stable() -> None:
    document = sample_document()
    restored = VisualDocumentSpec.from_json(document.to_json())

    assert restored.to_dict() == document.to_dict()
    assert restored.sha256() == document.sha256()
    assert len(document.sha256()) == 64


def test_document_schema_is_versioned_and_not_executable() -> None:
    payload = json.loads(sample_document().to_json())

    assert payload["schema"] == "mahoraga.visual_document.v1"
    assert "layers" in payload
    assert "construction_steps" in payload
    assert "asset:sha256:abc123" in payload["references"][0]["asset_id"]
    assert not any(key in payload for key in ("script", "command", "executable"))


def test_construction_methods_cover_multiple_artistic_approaches() -> None:
    methods = {step.method for step in sample_document().construction_steps}

    assert {"gesture", "geometric_blocking", "anatomy"} <= methods


def test_document_rejects_unknown_top_level_fields() -> None:
    payload = json.loads(sample_document().to_json())
    payload["backend_command"] = "run something"

    with pytest.raises(VisualDocumentError, match="campos desconhecidos"):
        VisualDocumentSpec.from_mapping(payload)


def test_document_rejects_unsupported_schema() -> None:
    payload = json.loads(sample_document().to_json())
    payload["schema"] = "mahoraga.visual_document.v2"

    with pytest.raises(VisualDocumentError, match="schema ausente ou incompatível"):
        VisualDocumentSpec.from_mapping(payload)


def test_document_rejects_element_with_missing_layer() -> None:
    with pytest.raises(VisualDocumentError, match="camada inexistente"):
        VisualDocumentSpec(
            document_id="scene.invalid",
            title="Invalid",
            elements=(VisualElementSpec("element.one", "shape", "layer.missing"),),
        )


def test_document_rejects_non_group_parent() -> None:
    with pytest.raises(VisualDocumentError, match="elemento group existente"):
        VisualDocumentSpec(
            document_id="scene.invalid",
            title="Invalid",
            layers=(VisualLayerSpec("layer.one", "One", 0),),
            elements=(
                VisualElementSpec("element.parent", "shape", "layer.one"),
                VisualElementSpec(
                    "element.child", "shape", "layer.one",
                    parent_id="element.parent",
                ),
            ),
        )


def test_document_rejects_parent_cycles() -> None:
    with pytest.raises(VisualDocumentError, match="contém ciclo"):
        VisualDocumentSpec(
            document_id="scene.invalid",
            title="Invalid",
            layers=(VisualLayerSpec("layer.one", "One", 0),),
            elements=(
                VisualElementSpec(
                    "element.a", "group", "layer.one", parent_id="element.b",
                ),
                VisualElementSpec(
                    "element.b", "group", "layer.one", parent_id="element.a",
                ),
            ),
        )


def test_document_rejects_missing_step_target() -> None:
    with pytest.raises(VisualDocumentError, match="elemento inexistente"):
        VisualDocumentSpec(
            document_id="scene.invalid",
            title="Invalid",
            layers=(VisualLayerSpec("layer.one", "One", 0),),
            construction_steps=(
                VisualConstructionStepSpec(
                    "step.one", "gesture", "Gesture",
                    target_element_ids=("element.missing",),
                ),
            ),
        )


def test_document_rejects_missing_step_dependency() -> None:
    with pytest.raises(VisualDocumentError, match="etapa inexistente"):
        VisualDocumentSpec(
            document_id="scene.invalid",
            title="Invalid",
            construction_steps=(
                VisualConstructionStepSpec(
                    "step.one", "gesture", "Gesture",
                    depends_on=("step.missing",),
                ),
            ),
        )


def test_document_rejects_construction_dependency_cycle() -> None:
    with pytest.raises(VisualDocumentError, match="contém ciclo"):
        VisualDocumentSpec(
            document_id="scene.invalid",
            title="Invalid",
            construction_steps=(
                VisualConstructionStepSpec(
                    "step.one", "gesture", "Gesture", depends_on=("step.two",),
                ),
                VisualConstructionStepSpec(
                    "step.two", "pose", "Pose", depends_on=("step.one",),
                ),
            ),
        )


def test_document_rejects_duplicate_ids_across_collections() -> None:
    with pytest.raises(VisualDocumentError, match="IDs devem ser únicos"):
        VisualDocumentSpec(
            document_id="scene.invalid",
            title="Invalid",
            layers=(VisualLayerSpec("shared.id", "Layer", 0),),
            references=(
                VisualReferenceSpec("shared.id", "asset:one", "reference"),
            ),
        )


def test_document_rejects_non_finite_transform_values() -> None:
    with pytest.raises(VisualDocumentError, match="finito"):
        TransformSpec(translation=(float("nan"), 0.0, 0.0))


def test_document_rejects_zero_scale() -> None:
    with pytest.raises(VisualDocumentError, match="escala zero"):
        TransformSpec(scale=(1.0, 0.0, 1.0))


def test_document_rejects_non_json_data() -> None:
    with pytest.raises(VisualDocumentError, match="tipo que não pertence ao JSON"):
        VisualElementSpec(
            "element.invalid", "custom", "layer.any",
            data={"object": object()},
        )


def test_document_rejects_invalid_boolean_flags() -> None:
    with pytest.raises(VisualDocumentError, match="booleanos"):
        VisualLayerSpec("layer.invalid", "Invalid", 0, visible=1)  # type: ignore[arg-type]


def test_document_rejects_unknown_construction_method() -> None:
    with pytest.raises(VisualDocumentError, match="method de construção"):
        VisualConstructionStepSpec(
            "step.invalid", "execute_python", "This must never be a method",
        )


def test_document_rejects_oversized_canvas_and_serialized_input() -> None:
    with pytest.raises(VisualDocumentError, match="canvas_width"):
        VisualDocumentSpec(
            document_id="scene.invalid",
            title="Invalid",
            canvas_width=16385,
        )

    oversized = " " * (VisualDocumentSpec.MAX_SERIALIZED_BYTES + 1)
    with pytest.raises(VisualDocumentError, match="excede o limite"):
        VisualDocumentSpec.from_json(oversized)


def test_transform_rejects_unknown_fields() -> None:
    with pytest.raises(VisualDocumentError, match="campos desconhecidos"):
        TransformSpec.from_mapping({"scale": [1, 1, 1], "script": "not allowed"})


def test_editor_updates_one_transform_without_mutating_previous_revision() -> None:
    from agent.visual_creation import VisualDocumentEditor

    original = sample_document()
    original_torso = next(item for item in original.elements if item.element_id == "element.torso")
    updated = VisualDocumentEditor.set_element_transform(
        original,
        "element.torso",
        TransformSpec(
            translation=(0.5, 1.4, 0.0),
            rotation_degrees=(0.0, 12.0, 0.0),
        ),
    )
    updated_torso = next(item for item in updated.elements if item.element_id == "element.torso")

    assert original.revision == 1
    assert updated.revision == 2
    assert original_torso.transform.translation == (0.0, 1.2, 0.0)
    assert updated_torso.transform.translation == (0.5, 1.4, 0.0)
    assert updated.sha256() != original.sha256()
    assert updated.references == original.references
    assert updated.elements[0] is original.elements[0]


def test_editor_can_hide_a_guide_layer_without_changing_other_layers() -> None:
    from agent.visual_creation import VisualDocumentEditor

    original = sample_document()
    updated = VisualDocumentEditor.set_layer_visibility(
        original, "layer.guides", False,
    )

    assert updated.revision == original.revision + 1
    assert updated.layers[0].visible is False
    assert original.layers[0].visible is True
    assert updated.layers[1:] == original.layers[1:]


def test_editor_can_append_a_construction_step_incrementally() -> None:
    from agent.visual_creation import VisualDocumentEditor

    original = sample_document()
    step = VisualConstructionStepSpec(
        "step.color", "color_study", "Definir temperatura e paleta",
        target_element_ids=("element.character",),
        depends_on=("step.anatomy",),
        parameters={"palette": "warm_cool"},
    )
    updated = VisualDocumentEditor.append_construction_step(original, step)

    assert updated.revision == original.revision + 1
    assert len(updated.construction_steps) == len(original.construction_steps) + 1
    assert updated.construction_steps[-1] == step
    assert len(original.construction_steps) == 3


def test_editor_rejects_removing_an_element_still_used_by_a_step() -> None:
    from agent.visual_creation import VisualDocumentEditor

    with pytest.raises(VisualDocumentError, match="alvo de uma etapa"):
        VisualDocumentEditor.remove_element(sample_document(), "element.torso")


def test_editor_rejects_removing_a_group_with_children() -> None:
    from agent.visual_creation import VisualDocumentEditor

    with pytest.raises(VisualDocumentError, match="possui filhos"):
        VisualDocumentEditor.remove_element(sample_document(), "element.character")


def test_editor_removes_an_unreferenced_leaf_as_a_new_revision() -> None:
    from agent.visual_creation import VisualDocumentEditor

    document = VisualDocumentSpec(
        document_id="scene.remove",
        title="Leaf removal",
        layers=(VisualLayerSpec("layer.one", "One", 0),),
        elements=(VisualElementSpec("element.leaf", "shape", "layer.one"),),
    )
    updated = VisualDocumentEditor.remove_element(document, "element.leaf")

    assert updated.revision == 2
    assert updated.elements == ()
    assert len(document.elements) == 1


def test_editor_rejects_unknown_element_and_invalid_visibility() -> None:
    from agent.visual_creation import VisualDocumentEditor

    with pytest.raises(VisualDocumentError, match="não existe"):
        VisualDocumentEditor.set_element_transform(
            sample_document(), "element.unknown", TransformSpec(),
        )
    with pytest.raises(VisualDocumentError, match="booleano"):
        VisualDocumentEditor.set_layer_visibility(
            sample_document(), "layer.guides", 0,  # type: ignore[arg-type]
        )


def test_json_payloads_are_deeply_immutable_and_export_as_plain_json() -> None:
    document = VisualDocumentSpec(
        document_id="scene.immutable",
        title="Immutable",
        layers=(VisualLayerSpec("layer.one", "One", 0),),
        elements=(
            VisualElementSpec(
                "element.one", "shape", "layer.one",
                data={"nested": {"values": [1, 2, 3]}},
            ),
        ),
    )

    with pytest.raises(TypeError):
        document.elements[0].data["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        document.elements[0].data["nested"]["new"] = "value"  # type: ignore[index]
    assert json.loads(document.to_json())["elements"][0]["data"]["nested"]["values"] == [1, 2, 3]


def test_json_payload_rejects_non_string_nested_keys() -> None:
    with pytest.raises(VisualDocumentError, match="chave JSON que não é texto"):
        VisualElementSpec(
            "element.invalid", "custom", "layer.any",
            data={"nested": {1: "not a JSON object key"}},
        )


def test_json_payload_rejects_excessive_nesting() -> None:
    nested: object = "leaf"
    for _ in range(18):
        nested = {"node": nested}
    with pytest.raises(VisualDocumentError, match="complexidade JSON"):
        VisualElementSpec(
            "element.invalid", "custom", "layer.any",
            data={"nested": nested},
        )


def test_step_mapping_rejects_strings_instead_of_id_lists() -> None:
    with pytest.raises(VisualDocumentError, match="target_element_ids deve ser uma lista"):
        VisualConstructionStepSpec.from_mapping({
            "step_id": "step.invalid",
            "method": "gesture",
            "intent": "Gesture",
            "target_element_ids": "element.one",
        })


def test_long_valid_step_chain_does_not_depend_on_python_recursion_depth() -> None:
    steps = []
    for index in range(1000):
        dependencies = (f"step.{index - 1}",) if index else ()
        steps.append(
            VisualConstructionStepSpec(
                step_id=f"step.{index}",
                method="gesture",
                intent=f"Construction stage {index}",
                depends_on=dependencies,
            )
        )
    document = VisualDocumentSpec(
        document_id="scene.long-plan",
        title="Long incremental plan",
        construction_steps=tuple(steps),
    )

    assert len(document.construction_steps) == 1000
    assert len(document.sha256()) == 64


def test_editor_adds_a_new_layer_and_element_as_separate_revisions() -> None:
    from agent.visual_creation import VisualDocumentEditor

    original = VisualDocumentSpec(document_id="scene.edit", title="Edit")
    with_layer = VisualDocumentEditor.add_layer(
        original, VisualLayerSpec("layer.base", "Base", 0),
    )
    with_element = VisualDocumentEditor.add_element(
        with_layer, VisualElementSpec("element.circle", "shape", "layer.base"),
    )

    assert original.revision == 1
    assert with_layer.revision == 2
    assert with_element.revision == 3
    assert original.layers == ()
    assert with_layer.elements == ()
    assert with_element.elements[0].element_id == "element.circle"


def test_editor_rejects_replacement_with_different_nonexistent_id() -> None:
    from agent.visual_creation import VisualDocumentEditor

    with pytest.raises(VisualDocumentError, match="não existe"):
        VisualDocumentEditor.replace_element(
            sample_document(),
            VisualElementSpec("element.not-present", "shape", "layer.art"),
        )


def test_style_payload_is_deeply_immutable_too() -> None:
    document = VisualDocumentSpec(
        document_id="scene.style-immutable",
        title="Style immutable",
        style=VisualStyleSpec(parameters={"color": {"palette": ["red", "blue"]}}),
    )
    with pytest.raises(TypeError):
        document.style.parameters["color"]["name"] = "changed"  # type: ignore[index]
    assert json.loads(document.to_json())["style"]["parameters"]["color"]["palette"] == ["red", "blue"]


def test_editor_can_update_transform_when_element_has_nested_immutable_data() -> None:
    from agent.visual_creation import VisualDocumentEditor

    document = VisualDocumentSpec(
        document_id="scene.nested-edit",
        title="Nested data",
        layers=(VisualLayerSpec("layer.one", "One", 0),),
        elements=(
            VisualElementSpec(
                "element.one", "shape", "layer.one",
                data={"geometry": {"control_points": [[0, 0, 0], [1, 1, 1]]}},
            ),
        ),
    )

    updated = VisualDocumentEditor.set_element_transform(
        document, "element.one",
        TransformSpec(translation=(2.0, 0.0, 0.0)),
    )

    assert updated.revision == 2
    assert updated.elements[0].data["geometry"]["control_points"][1] == (1, 1, 1)
    assert document.elements[0].transform.translation == (0.0, 0.0, 0.0)


def test_document_rejects_ambiguous_duplicate_layer_order() -> None:
    with pytest.raises(VisualDocumentError, match="ordem de composição única"):
        VisualDocumentSpec(
            document_id="scene.duplicate-order",
            title="Duplicate order",
            layers=(
                VisualLayerSpec("layer.one", "One", 0),
                VisualLayerSpec("layer.two", "Two", 0),
            ),
        )


def test_editor_cannot_add_element_to_locked_layer() -> None:
    from agent.visual_creation import VisualDocumentEditor

    document = VisualDocumentSpec(
        document_id="scene.locked-add",
        title="Locked add",
        layers=(VisualLayerSpec("layer.locked", "Locked", 0, locked=True),),
    )

    with pytest.raises(VisualDocumentError, match="Camada bloqueada"):
        VisualDocumentEditor.add_element(
            document, VisualElementSpec("element.new", "shape", "layer.locked"),
        )


def test_editor_cannot_modify_child_inside_locked_parent_group() -> None:
    from agent.visual_creation import VisualDocumentEditor

    document = VisualDocumentSpec(
        document_id="scene.locked-parent",
        title="Locked parent",
        layers=(
            VisualLayerSpec("layer.main", "Main", 0),
            VisualLayerSpec("layer.group", "Group", 1, locked=True),
        ),
        elements=(
            VisualElementSpec("group.character", "group", "layer.group"),
            VisualElementSpec(
                "element.body", "shape", "layer.main",
                parent_id="group.character",
            ),
        ),
    )

    with pytest.raises(VisualDocumentError, match="Camada bloqueada"):
        VisualDocumentEditor.set_element_transform(
            document, "element.body", TransformSpec(translation=(1.0, 0.0, 0.0)),
        )


def test_editor_cannot_remove_element_from_locked_layer() -> None:
    from agent.visual_creation import VisualDocumentEditor

    document = VisualDocumentSpec(
        document_id="scene.locked-remove",
        title="Locked remove",
        layers=(VisualLayerSpec("layer.locked", "Locked", 0, locked=True),),
        elements=(VisualElementSpec("element.leaf", "shape", "layer.locked"),),
    )

    with pytest.raises(VisualDocumentError, match="Camada bloqueada"):
        VisualDocumentEditor.remove_element(document, "element.leaf")
