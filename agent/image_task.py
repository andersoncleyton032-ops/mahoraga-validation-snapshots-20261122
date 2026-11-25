"""Versioned, backend-neutral contract for visual generation tasks.

The specification describes intent and bounded inputs. It does not select a
backend, authorize external access, execute work, or prove resource availability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Any, ClassVar, Mapping


class ImageTaskContractError(ValueError):
    """Raised when a visual task request violates its versioned contract."""


@dataclass(frozen=True)
class VisualResourceBudget:
    """Caller-declared upper bounds; these are not resource-admission evidence."""

    max_runtime_seconds: int = 900
    max_peak_memory_mb: int = 2048
    max_output_bytes: int = 32 * 1024 * 1024

    MAX_RUNTIME_SECONDS: ClassVar[int] = 7200
    MAX_PEAK_MEMORY_MB: ClassVar[int] = 16 * 1024
    MAX_OUTPUT_BYTES: ClassVar[int] = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        _bounded_int(self.max_runtime_seconds, "max_runtime_seconds", 1, self.MAX_RUNTIME_SECONDS)
        _bounded_int(self.max_peak_memory_mb, "max_peak_memory_mb", 64, self.MAX_PEAK_MEMORY_MB)
        _bounded_int(self.max_output_bytes, "max_output_bytes", 1024, self.MAX_OUTPUT_BYTES)

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualResourceBudget":
        if not isinstance(value, Mapping):
            raise ImageTaskContractError("resource_budget deve ser um objeto.")
        allowed = {"max_runtime_seconds", "max_peak_memory_mb", "max_output_bytes"}
        unknown = set(value) - allowed
        if unknown:
            raise ImageTaskContractError(f"Campos desconhecidos em resource_budget: {sorted(unknown)}")
        try:
            return cls(**dict(value))
        except TypeError as exc:
            raise ImageTaskContractError("resource_budget contém campos ausentes ou inválidos.") from exc

    def to_dict(self) -> dict[str, int]:
        return {
            "max_runtime_seconds": self.max_runtime_seconds,
            "max_peak_memory_mb": self.max_peak_memory_mb,
            "max_output_bytes": self.max_output_bytes,
        }


def _bounded_int(value: Any, field_name: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ImageTaskContractError(f"{field_name} deve ser um inteiro.")
    if not minimum <= value <= maximum:
        raise ImageTaskContractError(f"{field_name} deve estar entre {minimum} e {maximum}.")


def _optional_text(value: Any, field_name: str, *, maximum: int, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ImageTaskContractError(f"{field_name} é obrigatório.")
        return None
    if not isinstance(value, str):
        raise ImageTaskContractError(f"{field_name} deve ser texto.")
    normalized = value.strip()
    if not normalized:
        raise ImageTaskContractError(f"{field_name} não pode ser vazio.")
    if len(normalized) > maximum:
        raise ImageTaskContractError(f"{field_name} excede o limite de {maximum} caracteres.")
    if any(ord(char) < 32 and char not in "\t\n" for char in normalized):
        raise ImageTaskContractError(f"{field_name} contém caracteres de controle inválidos.")
    return normalized


def _identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is None:
        raise ImageTaskContractError(f"{field_name} inválido.")
    return value


def _optional_identifier(value: Any, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _finite_number(value: Any, field_name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ImageTaskContractError(f"{field_name} deve ser numérico.")
    numeric = float(value)
    if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
        raise ImageTaskContractError(f"{field_name} deve ser finito e estar entre {minimum} e {maximum}.")
    return numeric


@dataclass(frozen=True)
class ImageTaskSpec:
    """Portable visual request; it carries no execution or authorization authority."""

    task_id: str
    operation: str
    prompt: str | None = None
    negative_prompt: str | None = None
    source_asset_id: str | None = None
    reference_asset_ids: tuple[str, ...] = ()
    mask_asset_id: str | None = None
    scene_id: str | None = None
    scene_spec_sha256: str | None = None
    width: int = 512
    height: int = 512
    seed: int = 0
    steps: int | None = None
    guidance_scale: float | None = None
    strength: float | None = None
    backend_preference: str = "auto"
    output_mime_type: str = "image/png"
    resource_budget: VisualResourceBudget = field(default_factory=VisualResourceBudget)

    SCHEMA: ClassVar[str] = "mahoraga.image_task.v1"
    OPERATIONS: ClassVar[frozenset[str]] = frozenset({
        "text_to_image", "image_to_image", "inpainting", "outpainting",
        "variation", "refinement", "scene_composition", "procedural_render", "path_trace",
    })
    NEURAL_OPERATIONS: ClassVar[frozenset[str]] = frozenset({
        "text_to_image", "image_to_image", "inpainting", "outpainting", "variation", "refinement",
    })
    SOURCE_OPERATIONS: ClassVar[frozenset[str]] = frozenset({
        "image_to_image", "inpainting", "outpainting", "variation", "refinement",
    })
    SCENE_OPERATIONS: ClassVar[frozenset[str]] = frozenset({
        "scene_composition", "procedural_render", "path_trace",
    })
    BACKENDS: ClassVar[frozenset[str]] = frozenset({
        "auto", "procedural", "cpu.pathtracer", "litert", "mnn", "blender", "remote",
    })
    MAX_DIMENSION: ClassVar[int] = 4096
    MAX_PIXELS: ClassVar[int] = 16_777_216
    MAX_REFERENCE_ASSETS: ClassVar[int] = 8
    MAX_PROMPT_CHARS: ClassVar[int] = 12_000
    MAX_NEGATIVE_PROMPT_CHARS: ClassVar[int] = 4_000
    MAX_SEED: ClassVar[int] = (2**63) - 1
    MAX_STEPS: ClassVar[int] = 100

    def __post_init__(self) -> None:
        _identifier(self.task_id, "task_id")
        if not isinstance(self.operation, str) or self.operation not in self.OPERATIONS:
            raise ImageTaskContractError("operation não suportada.")

        prompt_required = self.operation in {
            "text_to_image", "image_to_image", "inpainting", "outpainting",
            "refinement", "scene_composition",
        }
        prompt = _optional_text(self.prompt, "prompt", maximum=self.MAX_PROMPT_CHARS, required=prompt_required)
        negative_prompt = _optional_text(
            self.negative_prompt, "negative_prompt", maximum=self.MAX_NEGATIVE_PROMPT_CHARS,
        )
        if negative_prompt is not None and self.operation not in self.NEURAL_OPERATIONS:
            raise ImageTaskContractError("negative_prompt só é válido para operações neurais.")

        source_asset_id = _optional_identifier(self.source_asset_id, "source_asset_id")
        if self.operation in self.SOURCE_OPERATIONS and source_asset_id is None:
            raise ImageTaskContractError(f"{self.operation} exige source_asset_id.")
        if self.operation not in self.SOURCE_OPERATIONS and source_asset_id is not None:
            raise ImageTaskContractError(f"{self.operation} não aceita source_asset_id.")

        if not isinstance(self.reference_asset_ids, (tuple, list)):
            raise ImageTaskContractError("reference_asset_ids deve ser uma lista.")
        references = tuple(_identifier(item, "reference_asset_ids[]") for item in self.reference_asset_ids)
        if len(references) > self.MAX_REFERENCE_ASSETS:
            raise ImageTaskContractError(f"São permitidas no máximo {self.MAX_REFERENCE_ASSETS} referências.")
        if len(set(references)) != len(references):
            raise ImageTaskContractError("reference_asset_ids contém duplicatas.")

        mask_asset_id = _optional_identifier(self.mask_asset_id, "mask_asset_id")
        if self.operation == "inpainting" and mask_asset_id is None:
            raise ImageTaskContractError("inpainting exige mask_asset_id.")
        if mask_asset_id is not None and self.operation not in {"inpainting", "outpainting"}:
            raise ImageTaskContractError("mask_asset_id só é válido para inpainting e outpainting.")
        all_asset_ids = [item for item in (source_asset_id, *references, mask_asset_id) if item is not None]
        if len(set(all_asset_ids)) != len(all_asset_ids):
            raise ImageTaskContractError("source, mask e referências devem possuir IDs distintos.")

        scene_id = _optional_identifier(self.scene_id, "scene_id")
        scene_sha = self.scene_spec_sha256
        if scene_sha is not None:
            if not isinstance(scene_sha, str) or re.fullmatch(r"[0-9a-fA-F]{64}", scene_sha) is None:
                raise ImageTaskContractError("scene_spec_sha256 deve conter 64 dígitos hexadecimais.")
            scene_sha = scene_sha.lower()
        if self.operation in self.SCENE_OPERATIONS:
            if scene_id is None or scene_sha is None:
                raise ImageTaskContractError(f"{self.operation} exige scene_id e scene_spec_sha256.")
        elif scene_id is not None or scene_sha is not None:
            raise ImageTaskContractError("scene_id e scene_spec_sha256 só são válidos para operações de cena.")

        _bounded_int(self.width, "width", 1, self.MAX_DIMENSION)
        _bounded_int(self.height, "height", 1, self.MAX_DIMENSION)
        if self.width * self.height > self.MAX_PIXELS:
            raise ImageTaskContractError(f"A imagem excede {self.MAX_PIXELS} pixels.")
        _bounded_int(self.seed, "seed", 0, self.MAX_SEED)

        neural = self.operation in self.NEURAL_OPERATIONS
        steps, guidance, strength = self.steps, self.guidance_scale, self.strength
        if neural:
            # These are model/backend parameters, not universal task defaults.
            # Keep omitted values unset so an adapter must apply its declared profile.
            if steps is not None:
                _bounded_int(steps, "steps", 1, self.MAX_STEPS)
            if guidance is not None:
                guidance = _finite_number(guidance, "guidance_scale", 0.0, 30.0)
            if self.operation in self.SOURCE_OPERATIONS:
                if strength is not None:
                    strength = _finite_number(strength, "strength", 0.0, 1.0)
            elif strength is not None:
                raise ImageTaskContractError("strength só é válido para operações com imagem de origem.")
        elif steps is not None or guidance is not None or strength is not None:
            raise ImageTaskContractError("steps, guidance_scale e strength não se aplicam a renderização de cena.")

        if not isinstance(self.backend_preference, str) or self.backend_preference not in self.BACKENDS:
            raise ImageTaskContractError("backend_preference não suportado.")
        if not isinstance(self.output_mime_type, str) or self.output_mime_type != "image/png":
            raise ImageTaskContractError("A versão 1 aceita somente image/png como formato de saída.")
        if not isinstance(self.resource_budget, VisualResourceBudget):
            raise ImageTaskContractError("resource_budget deve ser um VisualResourceBudget validado.")

        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "negative_prompt", negative_prompt)
        object.__setattr__(self, "source_asset_id", source_asset_id)
        object.__setattr__(self, "reference_asset_ids", references)
        object.__setattr__(self, "mask_asset_id", mask_asset_id)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "scene_spec_sha256", scene_sha)
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "guidance_scale", guidance)
        object.__setattr__(self, "strength", strength)

    @property
    def input_asset_ids(self) -> tuple[str, ...]:
        """Return IDs in deterministic source/reference/mask order."""
        return tuple(
            item for item in (self.source_asset_id, *self.reference_asset_ids, self.mask_asset_id)
            if item is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "task_id": self.task_id,
            "operation": self.operation,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "source_asset_id": self.source_asset_id,
            "reference_asset_ids": list(self.reference_asset_ids),
            "mask_asset_id": self.mask_asset_id,
            "scene_id": self.scene_id,
            "scene_spec_sha256": self.scene_spec_sha256,
            "width": self.width,
            "height": self.height,
            "seed": self.seed,
            "steps": self.steps,
            "guidance_scale": self.guidance_scale,
            "strength": self.strength,
            "backend_preference": self.backend_preference,
            "output_mime_type": self.output_mime_type,
            "resource_budget": self.resource_budget.to_dict(),
        }

    def sha256(self) -> str:
        encoded = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_mapping(cls, value: Any) -> "ImageTaskSpec":
        if not isinstance(value, Mapping):
            raise ImageTaskContractError("ImageTaskSpec deve ser um objeto.")
        data = dict(value)
        schema = data.pop("schema", None)
        if schema != cls.SCHEMA:
            raise ImageTaskContractError(f"Schema incompatível: esperado {cls.SCHEMA}.")
        allowed = {
            "task_id", "operation", "prompt", "negative_prompt", "source_asset_id",
            "reference_asset_ids", "mask_asset_id", "scene_id", "scene_spec_sha256",
            "width", "height", "seed", "steps", "guidance_scale", "strength",
            "backend_preference", "output_mime_type", "resource_budget",
        }
        unknown = set(data) - allowed
        if unknown:
            raise ImageTaskContractError(f"Campos desconhecidos: {sorted(unknown)}")
        if "task_id" not in data or "operation" not in data:
            raise ImageTaskContractError("task_id e operation são obrigatórios.")
        if "resource_budget" in data:
            data["resource_budget"] = VisualResourceBudget.from_mapping(data["resource_budget"])
        try:
            return cls(**data)
        except TypeError as exc:
            raise ImageTaskContractError("ImageTaskSpec contém campos ausentes ou inválidos.") from exc
