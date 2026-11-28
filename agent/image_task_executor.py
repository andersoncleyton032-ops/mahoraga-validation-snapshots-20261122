"""Governed executor for the first supported ImageTaskSpec backend.

Only the bounded CPU path-tracing operation is executable in this slice.
Neural, remote, Blender and non-executable scene operations remain deferred.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Mapping

from .cancellation import CancellationToken
from .cpu_path_tracer import CPUPathTracerBackend, SceneSpec
from .image_generation import ImageGenerationEngine
from .image_task import ImageTaskSpec


class ImageTaskExecutionError(ValueError):
    """An image task could not be safely admitted or executed."""


class ProceduralImageTaskExecutor:
    VERSION = "0.1.2"

    def __init__(
        self,
        image_generation: ImageGenerationEngine,
        reserve_resources: Callable[..., dict[str, Any]],
        release_resources: Callable[[dict[str, Any]], dict[str, Any]],
        backend_selector: Any = None,
    ):
        if not isinstance(image_generation, ImageGenerationEngine):
            raise ImageTaskExecutionError("ImageGenerationEngine compartilhado é obrigatório.")
        if not callable(reserve_resources) or not callable(release_resources):
            raise ImageTaskExecutionError("Callbacks de admissão e liberação são obrigatórios.")
        self.image_generation = image_generation
        self._reserve_resources = reserve_resources
        self._release_resources = release_resources
        if backend_selector is not None and not callable(getattr(backend_selector, "select", None)):
            raise ImageTaskExecutionError("VisualBackendSelector compatível é obrigatório.")
        self.backend_selector = backend_selector

    @staticmethod
    def _estimate(value: Any, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ImageTaskExecutionError(f"{field} deve ser uma estimativa numérica explícita.")
        result = float(value)
        if not math.isfinite(result) or result <= 0:
            raise ImageTaskExecutionError(f"{field} deve ser finito e positivo.")
        return result

    @staticmethod
    def _worst_case_png_bytes(width: int, height: int) -> int:
        raw_scanlines = width * height * 3 + height
        deflate_bound = (
            raw_scanlines + (raw_scanlines >> 12)
            + (raw_scanlines >> 14) + (raw_scanlines >> 25) + 13
        )
        return 128 + deflate_bound

    def execute(
        self,
        task_spec: ImageTaskSpec | Mapping[str, Any],
        scene: SceneSpec | Mapping[str, Any],
        *,
        estimated_ram_mb: float,
        estimated_seconds: float,
        texture_catalog: Any = None,
        cancellation_token: CancellationToken | None = None,
        runtime_context: dict[str, Any] | None = None,
        visual_provenance: Any = None,
    ) -> dict[str, Any]:
        """Validate, admit, execute and release one bounded path-tracing task."""
        if isinstance(task_spec, ImageTaskSpec):
            spec = task_spec
        elif isinstance(task_spec, Mapping):
            spec = ImageTaskSpec.from_mapping(task_spec)
        else:
            raise ImageTaskExecutionError("task_spec deve ser ImageTaskSpec ou Mapping.")
        if spec.operation != "path_trace":
            return {
                "status": "unsupported_operation",
                "reason": "procedural_executor_supports_path_trace_only",
                "operation": spec.operation,
                "execution_performed": False,
            }
        if spec.backend_preference not in {"auto", "cpu.pathtracer"}:
            return {
                "status": "unsupported_backend",
                "reason": "requested_backend_is_not_enabled",
                "backend_preference": spec.backend_preference,
                "execution_performed": False,
            }
        if self.backend_selector is None:
            return {
                "status": "backend_not_governed",
                "reason": "backend_selector_required",
                "backend_selection": None,
                "execution_performed": False,
            }
        backend_selection = self.backend_selector.select(spec)
        if not isinstance(backend_selection, dict) or backend_selection.get("status") != "selected":
            return {
                "status": "backend_not_governed",
                "reason": (
                    backend_selection.get("reason", "backend_selection_denied")
                    if isinstance(backend_selection, dict)
                    else "backend_selection_invalid"
                ),
                "backend_selection": backend_selection,
                "execution_performed": False,
            }
        if (
            backend_selection.get("capability_id") != "image.cpu_path_trace"
            or backend_selection.get("backend_selected") != "cpu.pathtracer"
            or backend_selection.get("reasons") != []
            or backend_selection.get("execution_performed") is not False
        ):
            return {
                "status": "backend_not_governed",
                "reason": "backend_selection_mismatch",
                "backend_selection": backend_selection,
                "execution_performed": False,
            }
        try:
            resolved_scene = (
                scene if isinstance(scene, SceneSpec) else SceneSpec.from_mapping(dict(scene))
            )
        except (TypeError, ValueError) as exc:
            raise ImageTaskExecutionError("SceneSpec inválido.") from exc
        if resolved_scene.scene_id != spec.scene_id:
            raise ImageTaskExecutionError("scene_id não corresponde ao SceneSpec fornecido.")
        scene_digest = resolved_scene.sha256()
        if scene_digest != spec.scene_spec_sha256:
            raise ImageTaskExecutionError("scene_spec_sha256 diverge do SceneSpec fornecido.")
        visual_provenance_payload = None
        if visual_provenance is not None:
            from .visual_scene_compiler import VisualRenderProvenance
            if not isinstance(visual_provenance, VisualRenderProvenance):
                raise ImageTaskExecutionError("visual_provenance precisa ser VisualRenderProvenance.")
            if (
                visual_provenance.task_id != spec.task_id
                or visual_provenance.task_sha256 != spec.sha256()
                or visual_provenance.scene_spec_sha256 != scene_digest
            ):
                raise ImageTaskExecutionError(
                    "Proveniência visual não corresponde à tarefa e à cena fornecidas."
                )
            visual_provenance_payload = visual_provenance.to_dict()
        if (
            spec.width > CPUPathTracerBackend.MAX_DIMENSION
            or spec.height > CPUPathTracerBackend.MAX_DIMENSION
            or spec.width * spec.height > CPUPathTracerBackend.MAX_PIXELS
        ):
            return {
                "status": "unsupported_dimensions",
                "reason": "image_task_exceeds_cpu_pathtracer_capability",
                "max_dimension": CPUPathTracerBackend.MAX_DIMENSION,
                "max_pixels": CPUPathTracerBackend.MAX_PIXELS,
                "execution_performed": False,
            }
        ram = self._estimate(estimated_ram_mb, "estimated_ram_mb")
        seconds = self._estimate(estimated_seconds, "estimated_seconds")
        budget = spec.resource_budget
        if ram > budget.max_peak_memory_mb or seconds > budget.max_runtime_seconds:
            return {
                "status": "deferred",
                "reason": "caller_estimate_exceeds_image_task_budget",
                "execution_performed": False,
            }
        output_bound = self._worst_case_png_bytes(spec.width, spec.height)
        if output_bound > budget.max_output_bytes:
            return {
                "status": "deferred",
                "reason": "worst_case_output_exceeds_image_task_budget",
                "estimated_output_upper_bound_bytes": output_bound,
                "max_output_bytes": budget.max_output_bytes,
                "execution_performed": False,
            }
        if cancellation_token is None:
            cancellation_token = CancellationToken()
        elif not isinstance(cancellation_token, CancellationToken):
            raise ImageTaskExecutionError("cancellation_token inválido.")
        cancellation_token.raise_if_cancelled()

        from .image_asset_verifier import ImageTextureCatalog
        if texture_catalog is None:
            texture_catalog = ImageTextureCatalog(assets=())
        elif not isinstance(texture_catalog, ImageTextureCatalog):
            raise ImageTaskExecutionError("texture_catalog precisa ser verificado.")
        admission = self._reserve_resources(
            {
                "task_id": spec.task_id,
                "workload": "image_generation",
                "estimated_ram_mb": ram,
                "estimated_seconds": seconds,
            },
            runtime_context,
        )
        if not isinstance(admission, dict) or admission.get("allowed") is not True:
            return {
                "status": "deferred",
                "reason": (
                    admission.get("reason", "resource_admission_denied")
                    if isinstance(admission, dict) else "resource_admission_invalid"
                ),
                "execution_performed": False,
            }
        lease = admission.get("reservation")
        if not isinstance(lease, dict):
            return {
                "status": "deferred_with_resource_warning",
                "reason": "resource_lease_missing",
                "execution_performed": False,
                "resource_admission": {
                    "status": "admitted_lease_unavailable",
                    "reservation_id": None,
                    "release": {
                        "released": False,
                        "reason": "resource_lease_missing",
                    },
                },
            }
        release_result: dict[str, Any] = {
            "released": False,
            "reason": "release_not_attempted",
        }
        execution_error: BaseException | None = None
        execution_traceback = None
        try:
            result = self.image_generation.generate_path_traced_with_catalog(
                spec.width, spec.height, scene=resolved_scene,
                texture_catalog=texture_catalog, seed=spec.seed,
                cancellation_token=cancellation_token,
                visual_provenance=visual_provenance,
            )
            if result.get("byte_size", output_bound + 1) > budget.max_output_bytes:
                raise ImageTaskExecutionError("PNG committed but exceeded declared output budget.")
            artifact_verification = self.image_generation.verify_stored_render_artifact(
                result["asset_id"],
                result["manifest_path"],
                expected_scene_sha256=scene_digest,
                expected_visual_provenance=visual_provenance,
            )
        except BaseException as exc:
            execution_error = exc
            execution_traceback = exc.__traceback__
        finally:
            try:
                candidate_release_result = self._release_resources(lease)
                if isinstance(candidate_release_result, dict):
                    # Normalize subclasses to a plain dict before interpreting evidence.
                    release_result = dict(candidate_release_result)
                else:
                    release_result = {
                        "released": False,
                        "reason": "resource_release_result_invalid",
                    }
            except Exception:
                release_result = {
                    "released": False,
                    "reason": "resource_release_callback_failed",
                }
        release_confirmed = release_result.get("released") is True
        if execution_error is not None:
            if not release_confirmed:
                release_evidence = dict(release_result)
                try:
                    setattr(execution_error, "resource_release", release_evidence)
                except Exception:
                    pass
                try:
                    add_note = getattr(execution_error, "add_note", None)
                    if callable(add_note):
                        reason = release_evidence.get("reason", "unknown")
                        try:
                            reason_text = str(reason)
                        except Exception:
                            reason_text = "unavailable"
                        add_note(
                            "Mahoraga: a liberação da reserva de recursos não foi confirmada: "
                            + reason_text
                        )
                except Exception:
                    # Cleanup diagnostics must never replace the primary execution error.
                    pass
            raise execution_error.with_traceback(execution_traceback)
        return {
            **result,
            "status": (
                result.get("status", "completed")
                if release_confirmed
                else "completed_with_resource_warning"
            ),
            "task_execution": {
                "status": (
                    "completed_and_verified"
                    if release_confirmed
                    else "completed_and_verified_with_resource_warning"
                ),
                "executor": "ProceduralImageTaskExecutor",
                "executor_version": self.VERSION,
                "task_contract_schema": spec.SCHEMA,
                "task_id": spec.task_id,
                "task_sha256": spec.sha256(),
                "operation": spec.operation,
                "backend_selected": result.get("backend"),
                "scene_id": resolved_scene.scene_id,
                "scene_spec_sha256": scene_digest,
                "source_document_sha256": (
                    visual_provenance.source_document_sha256
                    if visual_provenance is not None else None
                ),
                "visual_document_provenance": visual_provenance_payload,
                "estimated_ram_mb": ram,
                "estimated_seconds": seconds,
                "output_upper_bound_bytes": output_bound,
                "visual_quality_assessed": False,
                "neural_model_used": False,
                "remote_accessed": False,
            },
            "artifact_verification": artifact_verification["verification"],
            "visual_signal": artifact_verification["visual_signal"],
            "backend_selection": backend_selection,
            "resource_admission": {
                "status": (
                    "admitted_and_released"
                    if release_confirmed
                    else "admitted_release_unconfirmed"
                ),
                "reservation_id": lease.get("reservation_id"),
                "release": release_result,
            },
        }