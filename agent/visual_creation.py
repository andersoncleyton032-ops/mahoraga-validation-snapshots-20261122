"""Editable, backend-neutral visual document model for Mahoraga.

This module stores authoring intent and structure. It does not render, execute
scripts, load models, access the filesystem, authorize tools, or store media
bytes. Large inputs remain referenced by ArtifactStore asset IDs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, ClassVar
from collections.abc import Mapping


class VisualDocumentError(ValueError):
    """A visual document violates the versioned authoring contract."""


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_ALLOWED_BLEND_MODES = frozenset({"normal", "multiply", "screen", "overlay", "add"})
_ALLOWED_LAYER_TYPES = frozenset({
    "raster", "vector", "geometry", "guide", "reference",
    "annotation", "mask", "skeleton",
})
_ALLOWED_ELEMENT_KINDS = frozenset({
    "stroke", "shape", "text", "image", "mesh", "group",
    "skeleton", "pose", "light", "camera", "mask", "custom",
})
_ALLOWED_COORDINATE_SPACES = frozenset({"2d", "3d", "mixed"})
_ALLOWED_STEP_STATES = frozenset({
    "planned", "prepared", "applied", "reviewed", "blocked",
})
ALLOWED_CONSTRUCTION_METHODS = frozenset({
    "gesture", "thumbnail", "silhouette", "geometric_blocking",
    "anatomy", "pose", "perspective", "composition",
    "value_study", "color_study", "line_art", "painting",
    "pixel_art", "vector_art", "3d_blockout", "materials",
    "lighting", "procedural_render", "neural_generation",
    "image_editing", "inpainting", "outpainting", "refinement",
    "interpolation", "custom",
})


def _identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise VisualDocumentError(f"{field_name} inválido.")
    return value


def _text(value: Any, field_name: str, maximum: int, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str):
        raise VisualDocumentError(f"{field_name} deve ser texto.")
    normalized = value.strip()
    if not normalized and not optional:
        raise VisualDocumentError(f"{field_name} não pode ser vazio.")
    if len(normalized) > maximum:
        raise VisualDocumentError(f"{field_name} excede {maximum} caracteres.")
    if any(ord(char) < 32 and char not in "\t\n" for char in normalized):
        raise VisualDocumentError(f"{field_name} contém caracteres de controle.")
    return normalized


def _integer(value: Any, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VisualDocumentError(f"{field_name} deve ser inteiro.")
    if not minimum <= value <= maximum:
        raise VisualDocumentError(f"{field_name} fora dos limites.")
    return value


def _number(value: Any, field_name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VisualDocumentError(f"{field_name} deve ser numérico.")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise VisualDocumentError(f"{field_name} deve ser finito e estar nos limites.") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise VisualDocumentError(f"{field_name} deve ser finito e estar nos limites.")
    return result


def _vector3(value: Any, field_name: str, *, allow_zero: bool = True) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise VisualDocumentError(f"{field_name} deve conter três números.")
    result = tuple(
        _number(component, f"{field_name}[{index}]", -1_000_000.0, 1_000_000.0)
        for index, component in enumerate(value)
    )
    if not allow_zero and any(abs(component) <= 1e-12 for component in result):
        raise VisualDocumentError(f"{field_name} não pode conter escala zero.")
    return result  # type: ignore[return-value]


def _validate_json_tree(value: Any, field_name: str, depth: int = 0, budget: list[int] | None = None) -> None:
    if budget is None:
        budget = [0]
    budget[0] += 1
    if depth > 16 or budget[0] > 20_000:
        raise VisualDocumentError(f"{field_name} excede a complexidade JSON permitida.")
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise VisualDocumentError(f"{field_name} contém número não finito.")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise VisualDocumentError(f"{field_name} contém chave JSON que não é texto.")
            _validate_json_tree(item, field_name, depth + 1, budget)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_tree(item, field_name, depth + 1, budget)
        return
    raise VisualDocumentError(f"{field_name} contém tipo que não pertence ao JSON.")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _json_object(value: Any, field_name: str, *, max_bytes: int = 262_144) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VisualDocumentError(f"{field_name} deve ser um objeto JSON.")
    _validate_json_tree(value, field_name)
    try:
        encoded = json.dumps(
            _thaw_json(value), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > max_bytes:
            raise VisualDocumentError(f"{field_name} excede o limite de bytes.")
        copied = json.loads(encoded)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, VisualDocumentError):
            raise
        raise VisualDocumentError(f"{field_name} contém valor não serializável.") from exc
    if not isinstance(copied, dict):
        raise VisualDocumentError(f"{field_name} deve ser um objeto JSON.")
    return _freeze_json(copied)


def _unique(values: tuple[str, ...], field_name: str, maximum: int) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise VisualDocumentError(f"{field_name} deve ser uma sequência.")
    if len(values) > maximum:
        raise VisualDocumentError(f"{field_name} excede {maximum} itens.")
    normalized = tuple(_identifier(value, field_name) for value in values)
    if len(set(normalized)) != len(normalized):
        raise VisualDocumentError(f"{field_name} contém IDs duplicados.")
    return normalized


def _assert_acyclic(edges: dict[str, tuple[str, ...]], field_name: str) -> None:
    # Kahn's algorithm avoids recursion-depth failures on long but valid plans.
    indegree = {node: 0 for node in edges}
    dependents: dict[str, list[str]] = {node: [] for node in edges}
    for node, dependencies in edges.items():
        for dependency in dependencies:
            if dependency in edges:
                indegree[node] += 1
                dependents[dependency].append(node)
    ready = [node for node, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        node = ready.pop()
        visited += 1
        for dependent in dependents[node]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    if visited != len(edges):
        raise VisualDocumentError(f"{field_name} contém ciclo.")


@dataclass(frozen=True)
class TransformSpec:
    """Backend-neutral translation, Euler rotation (degrees), and scale."""

    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_degrees: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "translation", _vector3(self.translation, "translation"))
        object.__setattr__(
            self, "rotation_degrees",
            _vector3(self.rotation_degrees, "rotation_degrees"),
        )
        object.__setattr__(self, "scale", _vector3(self.scale, "scale", allow_zero=False))

    @classmethod
    def from_mapping(cls, value: Any) -> "TransformSpec":
        if not isinstance(value, Mapping):
            raise VisualDocumentError("transform deve ser um objeto.")
        allowed = {"translation", "rotation_degrees", "scale"}
        if set(value) - allowed:
            raise VisualDocumentError("transform contém campos desconhecidos.")
        return cls(
            translation=value.get("translation", (0.0, 0.0, 0.0)),
            rotation_degrees=value.get("rotation_degrees", (0.0, 0.0, 0.0)),
            scale=value.get("scale", (1.0, 1.0, 1.0)),
        )

    def to_dict(self) -> dict[str, list[float]]:
        return {
            "translation": list(self.translation),
            "rotation_degrees": list(self.rotation_degrees),
            "scale": list(self.scale),
        }


@dataclass(frozen=True)
class VisualLayerSpec:
    layer_id: str
    name: str
    order: int
    layer_type: str = "raster"
    visible: bool = True
    locked: bool = False
    opacity: float = 1.0
    blend_mode: str = "normal"

    def __post_init__(self) -> None:
        _identifier(self.layer_id, "layer_id")
        _text(self.name, "layer.name", 160)
        _integer(self.order, "layer.order", -100_000, 100_000)
        if not isinstance(self.layer_type, str) or self.layer_type not in _ALLOWED_LAYER_TYPES:
            raise VisualDocumentError("layer_type não suportado.")
        if not isinstance(self.visible, bool) or not isinstance(self.locked, bool):
            raise VisualDocumentError("visible e locked devem ser booleanos.")
        object.__setattr__(self, "opacity", _number(self.opacity, "opacity", 0.0, 1.0))
        if not isinstance(self.blend_mode, str) or self.blend_mode not in _ALLOWED_BLEND_MODES:
            raise VisualDocumentError("blend_mode não suportado.")

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualLayerSpec":
        if not isinstance(value, Mapping):
            raise VisualDocumentError("layer deve ser um objeto.")
        allowed = {
            "layer_id", "name", "order", "layer_type", "visible",
            "locked", "opacity", "blend_mode",
        }
        if set(value) - allowed or not {"layer_id", "name", "order"}.issubset(value):
            raise VisualDocumentError("layer contém campos desconhecidos ou obrigatórios ausentes.")
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_id": self.layer_id, "name": self.name, "order": self.order,
            "layer_type": self.layer_type, "visible": self.visible,
            "locked": self.locked, "opacity": self.opacity,
            "blend_mode": self.blend_mode,
        }


@dataclass(frozen=True)
class VisualElementSpec:
    element_id: str
    kind: str
    layer_id: str
    name: str = ""
    role: str = ""
    parent_id: str | None = None
    asset_id: str | None = None
    transform: TransformSpec = field(default_factory=TransformSpec)
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.element_id, "element_id")
        if not isinstance(self.kind, str) or self.kind not in _ALLOWED_ELEMENT_KINDS:
            raise VisualDocumentError("kind de elemento não suportado.")
        _identifier(self.layer_id, "element.layer_id")
        object.__setattr__(self, "name", _text(self.name, "element.name", 160, optional=True))
        object.__setattr__(self, "role", _text(self.role, "element.role", 160, optional=True))
        if self.parent_id is not None:
            _identifier(self.parent_id, "parent_id")
        if self.asset_id is not None:
            _identifier(self.asset_id, "asset_id")
        if not isinstance(self.transform, TransformSpec):
            raise VisualDocumentError("element.transform deve ser TransformSpec.")
        object.__setattr__(self, "data", _json_object(self.data, "element.data"))

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualElementSpec":
        if not isinstance(value, Mapping):
            raise VisualDocumentError("element deve ser um objeto.")
        allowed = {
            "element_id", "kind", "layer_id", "name", "role",
            "parent_id", "asset_id", "transform", "data",
        }
        required = {"element_id", "kind", "layer_id"}
        if set(value) - allowed or not required.issubset(value):
            raise VisualDocumentError("element contém campos desconhecidos ou obrigatórios ausentes.")
        data = dict(value)
        data["transform"] = TransformSpec.from_mapping(data.get("transform", {}))
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id, "kind": self.kind,
            "layer_id": self.layer_id, "name": self.name, "role": self.role,
            "parent_id": self.parent_id, "asset_id": self.asset_id,
            "transform": self.transform.to_dict(), "data": _thaw_json(self.data),
        }


@dataclass(frozen=True)
class VisualReferenceSpec:
    reference_id: str
    asset_id: str
    purpose: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        _identifier(self.reference_id, "reference_id")
        _identifier(self.asset_id, "reference.asset_id")
        object.__setattr__(self, "purpose", _text(self.purpose, "reference.purpose", 240))
        object.__setattr__(self, "weight", _number(self.weight, "reference.weight", 0.0, 1.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualReferenceSpec":
        if not isinstance(value, Mapping):
            raise VisualDocumentError("reference deve ser um objeto.")
        allowed = {"reference_id", "asset_id", "purpose", "weight"}
        if set(value) - allowed or not {"reference_id", "asset_id", "purpose"}.issubset(value):
            raise VisualDocumentError("reference contém campos desconhecidos ou ausentes.")
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id, "asset_id": self.asset_id,
            "purpose": self.purpose, "weight": self.weight,
        }


@dataclass(frozen=True)
class VisualConstructionStepSpec:
    step_id: str
    method: str
    intent: str
    target_element_ids: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    status: str = "planned"
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.step_id, "step_id")
        if not isinstance(self.method, str) or self.method not in ALLOWED_CONSTRUCTION_METHODS:
            raise VisualDocumentError("method de construção não suportado.")
        object.__setattr__(self, "intent", _text(self.intent, "step.intent", 2000))
        object.__setattr__(
            self, "target_element_ids",
            _unique(self.target_element_ids, "target_element_ids", 512),
        )
        object.__setattr__(self, "depends_on", _unique(self.depends_on, "depends_on", 1024))
        if self.step_id in self.depends_on:
            raise VisualDocumentError("Uma etapa não pode depender de si mesma.")
        if not isinstance(self.status, str) or self.status not in _ALLOWED_STEP_STATES:
            raise VisualDocumentError("status de etapa não suportado.")
        object.__setattr__(
            self, "parameters", _json_object(self.parameters, "step.parameters"),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualConstructionStepSpec":
        if not isinstance(value, Mapping):
            raise VisualDocumentError("construction_step deve ser um objeto.")
        allowed = {
            "step_id", "method", "intent", "target_element_ids",
            "depends_on", "status", "parameters",
        }
        required = {"step_id", "method", "intent"}
        if set(value) - allowed or not required.issubset(value):
            raise VisualDocumentError("construction_step contém campos desconhecidos ou ausentes.")
        data = dict(value)
        for key in ("target_element_ids", "depends_on"):
            if key in data and not isinstance(data[key], (list, tuple)):
                raise VisualDocumentError(f"{key} deve ser uma lista.")
        data["target_element_ids"] = tuple(data.get("target_element_ids", ()))
        data["depends_on"] = tuple(data.get("depends_on", ()))
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id, "method": self.method, "intent": self.intent,
            "target_element_ids": list(self.target_element_ids),
            "depends_on": list(self.depends_on), "status": self.status,
            "parameters": _thaw_json(self.parameters),
        }


@dataclass(frozen=True)
class VisualStyleSpec:
    style_id: str = "style.default"
    medium: str = "unspecified"
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.style_id, "style_id")
        object.__setattr__(self, "medium", _text(self.medium, "style.medium", 120))
        object.__setattr__(
            self, "description",
            _text(self.description, "style.description", 2000, optional=True),
        )
        object.__setattr__(
            self, "parameters", _json_object(self.parameters, "style.parameters"),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualStyleSpec":
        if not isinstance(value, Mapping):
            raise VisualDocumentError("style deve ser um objeto.")
        allowed = {"style_id", "medium", "description", "parameters"}
        if set(value) - allowed:
            raise VisualDocumentError("style contém campos desconhecidos.")
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "style_id": self.style_id, "medium": self.medium,
            "description": self.description, "parameters": _thaw_json(self.parameters),
        }


@dataclass(frozen=True)
class VisualDocumentSpec:
    """Persistent editable source for a visual work; not an image or renderer."""

    document_id: str
    title: str
    coordinate_space: str = "2d"
    canvas_width: int = 1024
    canvas_height: int = 1024
    revision: int = 1
    layers: tuple[VisualLayerSpec, ...] = ()
    elements: tuple[VisualElementSpec, ...] = ()
    references: tuple[VisualReferenceSpec, ...] = ()
    construction_steps: tuple[VisualConstructionStepSpec, ...] = ()
    style: VisualStyleSpec = field(default_factory=VisualStyleSpec)
    metadata: dict[str, Any] = field(default_factory=dict)

    SCHEMA: ClassVar[str] = "mahoraga.visual_document.v1"
    MAX_LAYERS: ClassVar[int] = 128
    MAX_ELEMENTS: ClassVar[int] = 4096
    MAX_REFERENCES: ClassVar[int] = 128
    MAX_STEPS: ClassVar[int] = 1024
    MAX_SERIALIZED_BYTES: ClassVar[int] = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        _identifier(self.document_id, "document_id")
        object.__setattr__(self, "title", _text(self.title, "title", 240))
        if not isinstance(self.coordinate_space, str) or self.coordinate_space not in _ALLOWED_COORDINATE_SPACES:
            raise VisualDocumentError("coordinate_space deve ser 2d, 3d ou mixed.")
        _integer(self.canvas_width, "canvas_width", 1, 16384)
        _integer(self.canvas_height, "canvas_height", 1, 16384)
        _integer(self.revision, "revision", 1, 2**31 - 1)
        for field_name, values, expected, maximum in (
            ("layers", self.layers, VisualLayerSpec, self.MAX_LAYERS),
            ("elements", self.elements, VisualElementSpec, self.MAX_ELEMENTS),
            ("references", self.references, VisualReferenceSpec, self.MAX_REFERENCES),
            ("construction_steps", self.construction_steps,
             VisualConstructionStepSpec, self.MAX_STEPS),
        ):
            if not isinstance(values, (tuple, list)) or len(values) > maximum:
                raise VisualDocumentError(f"{field_name} inválido ou acima do limite.")
            if any(not isinstance(item, expected) for item in values):
                raise VisualDocumentError(f"{field_name} contém item de tipo inválido.")
            object.__setattr__(self, field_name, tuple(values))
        if not isinstance(self.style, VisualStyleSpec):
            raise VisualDocumentError("style deve ser VisualStyleSpec.")
        object.__setattr__(self, "metadata", _json_object(self.metadata, "metadata"))

        layer_ids = [item.layer_id for item in self.layers]
        layer_orders = [item.order for item in self.layers]
        if len(layer_orders) != len(set(layer_orders)):
            raise VisualDocumentError("Cada camada deve possuir ordem de composição única.")
        element_ids = [item.element_id for item in self.elements]
        reference_ids = [item.reference_id for item in self.references]
        step_ids = [item.step_id for item in self.construction_steps]
        all_ids = layer_ids + element_ids + reference_ids + step_ids
        if len(all_ids) != len(set(all_ids)):
            raise VisualDocumentError("IDs devem ser únicos em todo o documento.")

        layer_id_set = set(layer_ids)
        element_map = {item.element_id: item for item in self.elements}
        for element in self.elements:
            if element.layer_id not in layer_id_set:
                raise VisualDocumentError(
                    f"Elemento {element.element_id} referencia camada inexistente."
                )
            if element.parent_id is not None:
                parent = element_map.get(element.parent_id)
                if parent is None or parent.kind != "group":
                    raise VisualDocumentError("parent_id deve referenciar elemento group existente.")
                if parent.element_id == element.element_id:
                    raise VisualDocumentError("Elemento não pode ser pai de si mesmo.")
        _assert_acyclic(
            {item.element_id: ((item.parent_id,) if item.parent_id else ())
             for item in self.elements},
            "Hierarquia de elementos",
        )

        element_id_set = set(element_ids)
        step_map = {item.step_id: item for item in self.construction_steps}
        for step in self.construction_steps:
            missing_targets = set(step.target_element_ids) - element_id_set
            if missing_targets:
                raise VisualDocumentError(
                    f"Etapa {step.step_id} referencia elemento inexistente."
                )
            missing_dependencies = set(step.depends_on) - set(step_map)
            if missing_dependencies:
                raise VisualDocumentError(
                    f"Etapa {step.step_id} depende de etapa inexistente."
                )
        _assert_acyclic(
            {item.step_id: item.depends_on for item in self.construction_steps},
            "Dependências de construção",
        )
        # Ensure the complete document is bounded and JSON serializable.
        encoded = self.to_json()
        if len(encoded.encode("utf-8")) > self.MAX_SERIALIZED_BYTES:
            raise VisualDocumentError("Documento visual excede o limite serializado.")

    @classmethod
    def from_mapping(cls, value: Any) -> "VisualDocumentSpec":
        if not isinstance(value, Mapping):
            raise VisualDocumentError("Documento visual deve ser um objeto.")
        allowed = {
            "schema", "document_id", "title", "coordinate_space",
            "canvas_width", "canvas_height", "revision", "layers",
            "elements", "references", "construction_steps", "style", "metadata",
        }
        if set(value) - allowed:
            raise VisualDocumentError("Documento visual contém campos desconhecidos.")
        if value.get("schema") != cls.SCHEMA:
            raise VisualDocumentError("schema ausente ou incompatível.")
        required = {"document_id", "title"}
        if not required.issubset(value):
            raise VisualDocumentError("Documento visual sem campos obrigatórios.")
        for key in ("layers", "elements", "references", "construction_steps"):
            if key in value and not isinstance(value[key], (list, tuple)):
                raise VisualDocumentError(f"{key} deve ser uma lista.")
        return cls(
            document_id=value["document_id"],
            title=value["title"],
            coordinate_space=value.get("coordinate_space", "2d"),
            canvas_width=value.get("canvas_width", 1024),
            canvas_height=value.get("canvas_height", 1024),
            revision=value.get("revision", 1),
            layers=tuple(VisualLayerSpec.from_mapping(v) for v in value.get("layers", ())),
            elements=tuple(VisualElementSpec.from_mapping(v) for v in value.get("elements", ())),
            references=tuple(VisualReferenceSpec.from_mapping(v) for v in value.get("references", ())),
            construction_steps=tuple(
                VisualConstructionStepSpec.from_mapping(v)
                for v in value.get("construction_steps", ())
            ),
            style=VisualStyleSpec.from_mapping(value.get("style", {})),
            metadata=_json_object(value.get("metadata", {}), "metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "document_id": self.document_id,
            "title": self.title,
            "coordinate_space": self.coordinate_space,
            "canvas_width": self.canvas_width,
            "canvas_height": self.canvas_height,
            "revision": self.revision,
            "layers": [item.to_dict() for item in self.layers],
            "elements": [item.to_dict() for item in self.elements],
            "references": [item.to_dict() for item in self.references],
            "construction_steps": [item.to_dict() for item in self.construction_steps],
            "style": self.style.to_dict(),
            "metadata": _thaw_json(self.metadata),
        }

    def to_json(self) -> str:
        try:
            return json.dumps(
                self.to_dict(), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise VisualDocumentError("Documento visual não pode ser serializado.") from exc

    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, value: str) -> "VisualDocumentSpec":
        if not isinstance(value, str):
            raise VisualDocumentError("JSON do documento deve ser texto.")
        if len(value.encode("utf-8")) > cls.MAX_SERIALIZED_BYTES:
            raise VisualDocumentError("JSON do documento excede o limite.")
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise VisualDocumentError("JSON do documento é inválido.") from exc
        return cls.from_mapping(decoded)


class VisualDocumentEditor:
    """Pure, revisioned edits; previous document instances remain unchanged."""

    @staticmethod
    def _require_editable_element(
        document: VisualDocumentSpec, element: VisualElementSpec,
    ) -> None:
        layer_map = {layer.layer_id: layer for layer in document.layers}
        element_map = {item.element_id: item for item in document.elements}
        current: VisualElementSpec | None = element
        visited: set[str] = set()
        while current is not None:
            if current.element_id in visited:
                raise VisualDocumentError("Hierarquia de elementos contém ciclo.")
            visited.add(current.element_id)
            layer = layer_map.get(current.layer_id)
            if layer is None:
                raise VisualDocumentError("Camada do elemento não existe.")
            if layer.locked:
                raise VisualDocumentError(
                    f"Camada bloqueada impede a edição do elemento {current.element_id}."
                )
            current = (
                element_map.get(current.parent_id)
                if current.parent_id is not None else None
            )

    @staticmethod
    def _require_document(document: Any) -> VisualDocumentSpec:
        if not isinstance(document, VisualDocumentSpec):
            raise VisualDocumentError("document deve ser VisualDocumentSpec.")
        if document.revision >= 2**31 - 1:
            raise VisualDocumentError("revision atingiu o limite.")
        return document

    @classmethod
    def add_layer(
        cls, document: VisualDocumentSpec, layer: VisualLayerSpec,
    ) -> VisualDocumentSpec:
        current = cls._require_document(document)
        if not isinstance(layer, VisualLayerSpec):
            raise VisualDocumentError("layer deve ser VisualLayerSpec.")
        return replace(current, revision=current.revision + 1, layers=current.layers + (layer,))

    @classmethod
    def add_element(
        cls, document: VisualDocumentSpec, element: VisualElementSpec,
    ) -> VisualDocumentSpec:
        current = cls._require_document(document)
        if not isinstance(element, VisualElementSpec):
            raise VisualDocumentError("element deve ser VisualElementSpec.")
        VisualDocumentEditor._require_editable_element(current, element)
        return replace(
            current, revision=current.revision + 1,
            elements=current.elements + (element,),
        )

    @classmethod
    def replace_element(
        cls, document: VisualDocumentSpec, element: VisualElementSpec,
    ) -> VisualDocumentSpec:
        current = cls._require_document(document)
        if not isinstance(element, VisualElementSpec):
            raise VisualDocumentError("element deve ser VisualElementSpec.")
        existing = next(
            (item for item in current.elements if item.element_id == element.element_id),
            None,
        )
        if existing is None:
            raise VisualDocumentError("elemento a substituir não existe.")
        cls._require_editable_element(current, existing)
        cls._require_editable_element(current, element)
        updated = tuple(
            element if item.element_id == element.element_id else item
            for item in current.elements
        )
        return replace(current, revision=current.revision + 1, elements=updated)

    @classmethod
    def set_element_transform(
        cls, document: VisualDocumentSpec, element_id: str, transform: TransformSpec,
    ) -> VisualDocumentSpec:
        current = cls._require_document(document)
        _identifier(element_id, "element_id")
        if not isinstance(transform, TransformSpec):
            raise VisualDocumentError("transform deve ser TransformSpec.")
        element = next((item for item in current.elements if item.element_id == element_id), None)
        if element is None:
            raise VisualDocumentError("elemento a transformar não existe.")
        return cls.replace_element(current, replace(element, transform=transform))

    @classmethod
    def set_layer_visibility(
        cls, document: VisualDocumentSpec, layer_id: str, visible: bool,
    ) -> VisualDocumentSpec:
        current = cls._require_document(document)
        _identifier(layer_id, "layer_id")
        if not isinstance(visible, bool):
            raise VisualDocumentError("visible deve ser booleano.")
        layer = next((item for item in current.layers if item.layer_id == layer_id), None)
        if layer is None:
            raise VisualDocumentError("camada a alterar não existe.")
        updated = tuple(
            replace(item, visible=visible) if item.layer_id == layer_id else item
            for item in current.layers
        )
        return replace(current, revision=current.revision + 1, layers=updated)

    @classmethod
    def append_construction_step(
        cls, document: VisualDocumentSpec, step: VisualConstructionStepSpec,
    ) -> VisualDocumentSpec:
        current = cls._require_document(document)
        if not isinstance(step, VisualConstructionStepSpec):
            raise VisualDocumentError("step deve ser VisualConstructionStepSpec.")
        return replace(
            current, revision=current.revision + 1,
            construction_steps=current.construction_steps + (step,),
        )

    @classmethod
    def set_style(
        cls, document: VisualDocumentSpec, style: VisualStyleSpec,
    ) -> VisualDocumentSpec:
        current = cls._require_document(document)
        if not isinstance(style, VisualStyleSpec):
            raise VisualDocumentError("style deve ser VisualStyleSpec.")
        return replace(current, revision=current.revision + 1, style=style)

    @classmethod
    def remove_element(
        cls, document: VisualDocumentSpec, element_id: str,
    ) -> VisualDocumentSpec:
        """Remove only an unreferenced leaf; dependent data must be edited first."""
        current = cls._require_document(document)
        _identifier(element_id, "element_id")
        existing = next(
            (item for item in current.elements if item.element_id == element_id),
            None,
        )
        if existing is None:
            raise VisualDocumentError("elemento a remover não existe.")
        cls._require_editable_element(current, existing)
        if any(item.parent_id == element_id for item in current.elements):
            raise VisualDocumentError("elemento possui filhos; remova/reassocie os filhos primeiro.")
        if any(element_id in step.target_element_ids for step in current.construction_steps):
            raise VisualDocumentError("elemento ainda é alvo de uma etapa de construção.")
        updated = tuple(item for item in current.elements if item.element_id != element_id)
        return replace(current, revision=current.revision + 1, elements=updated)
