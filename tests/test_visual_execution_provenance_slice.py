from __future__ import annotations

import pytest

from agent.cancellation import CancellationToken
from agent.image_generation import ImageGenerationEngine, ImageGenerationError
from agent.image_task import VisualResourceBudget
from agent.image_task_executor import ImageTaskExecutionError, ProceduralImageTaskExecutor
from agent.visual_creation import VisualDocumentSpec, VisualElementSpec, VisualLayerSpec
from agent.visual_scene_compiler import VisualRenderProvenance, compile_visual_image_task


class Admission:
    def __init__(self):
        self.requests = []
        self.releases = []

    def reserve(self, request, runtime_context=None):
        self.requests.append((request, runtime_context))
        return {
            "allowed": True,
            "reservation": {"reservation_id": "lease-001", "proof": "opaque"},
        }

    def release(self, lease):
        self.releases.append(lease)
        return {"released": True, "reason": "reservation_released"}


class SelectedSelector:
    def select(self, spec):
        return {
            "status": "selected",
            "reason": "test_backend_selected",
            "capability_id": "image.cpu_path_trace",
            "backend_selected": "cpu.pathtracer",
            "reasons": [],
            "execution_performed": False,
        }


def build_executor(tmp_path, admission=None, engine=None):
    admission = admission or Admission()
    engine = engine or ImageGenerationEngine(tmp_path / "images")
    executor = ProceduralImageTaskExecutor(
        engine,
        admission.reserve,
        admission.release,
        backend_selector=SelectedSelector(),
    )
    return executor, admission


def prepared_visual_task():
    document = VisualDocumentSpec(
        document_id="scene.executor-provenance",
        title="Executor provenance",
        coordinate_space="3d",
        layers=(VisualLayerSpec("layer.main", "Main", 0),),
        elements=(
            VisualElementSpec(
                "camera.main", "camera", "layer.main",
                data={"origin": [0.0, 0.0, 5.0], "target": [0.0, 0.0, 0.0]},
            ),
            VisualElementSpec(
                "element.sphere", "shape", "layer.main",
                data={"primitive": "sphere", "radius": 0.8},
            ),
        ),
    )
    prepared = compile_visual_image_task(
        document,
        task_id="task.executor.provenance",
        width=32,
        height=24,
        resource_budget=VisualResourceBudget(
            max_runtime_seconds=20,
            max_peak_memory_mb=128,
            max_output_bytes=1024 * 1024,
        ),
    )
    assert prepared.status == "ready_for_governed_executor"
    return document, prepared


def test_executor_persists_and_reverifies_visual_document_provenance(tmp_path):
    document, prepared = prepared_visual_task()
    engine = ImageGenerationEngine(tmp_path / "images")
    executor, admission = build_executor(tmp_path, engine=engine)

    result = executor.execute(
        prepared.task_spec,
        prepared.scene,
        estimated_ram_mb=64,
        estimated_seconds=5,
        visual_provenance=prepared.render_provenance(),
    )

    provenance = prepared.render_provenance().to_dict()
    assert result["status"] == "completed"
    assert result["lineage_manifest"]["schema"] == "mahoraga.image_render_manifest.v2"
    assert result["lineage_manifest"]["visual_document"] == provenance
    assert result["visual_document_provenance"] == provenance
    assert result["task_execution"]["visual_document_provenance"] == provenance
    assert result["task_execution"]["source_document_sha256"] == document.sha256()
    stored = engine.artifact_store.get_png(result["asset_id"])
    assert stored.asset.descriptor.source_ref == (
        f"mahoraga://visual-document/{document.sha256()}"
    )
    assert result["artifact_verification"]["manifest_schema_and_digest_verified"] is True
    assert len(admission.releases) == 1


def test_executor_rejects_visual_provenance_for_another_task_before_admission(tmp_path):
    _, prepared = prepared_visual_task()
    original = prepared.render_provenance()
    mismatched = VisualRenderProvenance(
        source_document_sha256=original.source_document_sha256,
        scene_spec_sha256=original.scene_spec_sha256,
        task_id=original.task_id,
        task_sha256="f" * 64,
        element_bindings=original.element_bindings,
        skipped_hidden_element_ids=original.skipped_hidden_element_ids,
    )
    executor, admission = build_executor(tmp_path)

    with pytest.raises(ImageTaskExecutionError, match="não corresponde"):
        executor.execute(
            prepared.task_spec,
            prepared.scene,
            estimated_ram_mb=64,
            estimated_seconds=5,
            visual_provenance=mismatched,
        )

    assert admission.requests == []
    assert admission.releases == []
    assert not (tmp_path / "images").exists()


def test_stored_render_verifier_rejects_different_expected_visual_provenance(tmp_path):
    _, prepared = prepared_visual_task()
    engine = ImageGenerationEngine(tmp_path / "images")
    executor, _ = build_executor(tmp_path, engine=engine)
    original = prepared.render_provenance()
    result = executor.execute(
        prepared.task_spec,
        prepared.scene,
        estimated_ram_mb=64,
        estimated_seconds=5,
        visual_provenance=original,
    )
    mismatched = VisualRenderProvenance(
        source_document_sha256=original.source_document_sha256,
        scene_spec_sha256=original.scene_spec_sha256,
        task_id=original.task_id,
        task_sha256=original.task_sha256,
        element_bindings=(("camera", "camera.main"),),
        skipped_hidden_element_ids=original.skipped_hidden_element_ids,
    )

    with pytest.raises(ImageGenerationError, match="diverge do registro esperado"):
        engine.verify_stored_render_artifact(
            result["asset_id"],
            result["manifest_path"],
            expected_scene_sha256=prepared.scene.sha256(),
            expected_visual_provenance=mismatched,
        )


def test_visual_document_provenance_validator_accepts_matching_record():
    digest = "c" * 64
    provenance = VisualRenderProvenance(
        source_document_sha256=digest,
        scene_spec_sha256=digest,
        task_id="task.manifest.valid",
        task_sha256=digest,
        element_bindings=(("camera", "camera.main"),),
    )

    normalized = ImageGenerationEngine._validate_visual_document_provenance(
        provenance,
        scene_sha256=digest,
        expected=provenance,
    )

    assert normalized == provenance.to_dict()


def test_visual_document_provenance_validator_rejects_scene_or_authentication_mismatch():
    digest = "d" * 64
    provenance = VisualRenderProvenance(
        source_document_sha256=digest,
        scene_spec_sha256=digest,
        task_id="task.manifest.invalid",
        task_sha256=digest,
        element_bindings=(("camera", "camera.main"),),
    )
    payload = provenance.to_dict()

    with pytest.raises(ImageGenerationError, match="diverge do SceneSpec"):
        ImageGenerationEngine._validate_visual_document_provenance(
            payload, scene_sha256="e" * 64,
        )

    payload["source_provenance_authenticated"] = True
    with pytest.raises(ImageGenerationError, match="não pode alegar autenticação"):
        ImageGenerationEngine._validate_visual_document_provenance(
            payload, scene_sha256=digest,
        )
