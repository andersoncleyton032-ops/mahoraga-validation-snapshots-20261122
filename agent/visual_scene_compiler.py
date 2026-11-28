"""Compile a bounded visual authoring document into the existing CPU SceneSpec.

The compiler is deliberately a one-way adapter. It never renders, reserves
resources, reads assets, or enables a backend. Unsupported authoring elements
are reported rather than silently omitted.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any
from collections.abc import Mapping

from .cpu_path_tracer import (
    BoxSpec,
    CameraSpec,
    OrientedBoxSpec,
    PlaneSpec,
    PointLightSpec,
    SceneSpec,
    SphereSpec,
    CPUPathTracerBackend,
)
from .image_task import ImageTaskContractError, ImageTaskSpec, VisualResourceBudget
from .visual_creation import VisualDocumentSpec, VisualElementSpec


class VisualSceneCompilationError(ValueError):
    """The editable visual document cannot be compiled safely."""


@dataclass(frozen=True)
class VisualSceneCompileResult:
    status: str
    scene: SceneSpec | None
    scene_spec_sha256: str | None
    source_document_sha256: str | None = None
    unsupported_element_ids: tuple[str, ...] = ()
    skipped_hidden_element_ids: tuple[str, ...] = ()
    element_bindings: tuple[tuple[str, str], ...] = ()
    reason: str | None = None


def _finite(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VisualSceneCompilationError(f"{field} deve ser numérico.")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise VisualSceneCompilationError(f"{field} deve ser finito.") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise VisualSceneCompilationError(f"{field} está fora dos limites.")
    return result


def _vec3(value: Any, field: str, low: float, high: float) -> tuple[float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise VisualSceneCompilationError(f"{field} deve conter três números.")
    return tuple(
        _finite(component, f"{field}[{index}]", low, high)
        for index, component in enumerate(value)
    )  # type: ignore[return-value]


def _rotate(vector: tuple[float, float, float], rotation: tuple[float, float, float]) -> tuple[float, float, float]:
    """Apply fixed-axis X, then Y, then Z rotations, in degrees."""
    x, y, z = (math.radians(component) for component in rotation)
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    vx, vy, vz = vector
    # X, then Y, then Z. The convention is explicit and backend-neutral.
    vy, vz = vy * cx - vz * sx, vy * sx + vz * cx
    vx, vz = vx * cy + vz * sy, -vx * sy + vz * cy
    vx, vy = vx * cz - vy * sz, vx * sz + vy * cz
    # Canonicalize floating-point residue from right-angle rotations for stable scene hashes.
    return (
        0.0 if abs(vx) < 1e-12 else vx,
        0.0 if abs(vy) < 1e-12 else vy,
        0.0 if abs(vz) < 1e-12 else vz,
    )


def _quaternion_from_euler(rotation: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """Quaternion matching the fixed-axis X/Y/Z convention, as w, x, y, z."""
    x, y, z = (math.radians(component) / 2.0 for component in rotation)
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    return (
        cx * cy * cz + sx * sy * sz,
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
    )


def _material(data: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "albedo", "emission", "metallic", "roughness",
        "texture_pattern", "texture_color_a", "texture_color_b", "texture_scale",
    }
    if set(data) - allowed:
        raise VisualSceneCompilationError("Material contém campos não suportados pelo CPUPathTracer.")
    result: dict[str, Any] = {
        "albedo": _vec3(data.get("albedo", (0.7, 0.7, 0.7)), "material.albedo", 0.0, 1.0),
        "emission": _vec3(data.get("emission", (0.0, 0.0, 0.0)), "material.emission", 0.0, 100.0),
        "metallic": _finite(data.get("metallic", 0.0), "material.metallic", 0.0, 1.0),
        "roughness": _finite(data.get("roughness", 0.7), "material.roughness", 0.02, 1.0),
    }
    texture_pattern = data.get("texture_pattern", "solid")
    if texture_pattern not in {"solid", "checker"}:
        raise VisualSceneCompilationError("Apenas texturas solid/checker estão mapeadas nesta versão.")
    result["texture_pattern"] = texture_pattern
    result["texture_scale"] = _finite(data.get("texture_scale", 8.0), "material.texture_scale", 0.1, 256.0)
    if texture_pattern == "checker":
        result["texture_color_a"] = _vec3(
            data.get("texture_color_a"), "material.texture_color_a", 0.0, 1.0,
        )
        result["texture_color_b"] = _vec3(
            data.get("texture_color_b"), "material.texture_color_b", 0.0, 1.0,
        )
    elif "texture_color_a" in data or "texture_color_b" in data:
        raise VisualSceneCompilationError("Cores checker exigem texture_pattern=checker.")
    return result


def _camera(element: VisualElementSpec) -> CameraSpec:
    data = element.data
    allowed = {
        "origin", "target", "up", "vertical_fov_degrees",
        "aperture", "focus_distance",
    }
    if set(data) - allowed or not {"origin", "target"}.issubset(data):
        raise VisualSceneCompilationError("Camera exige origin e target e não aceita campos extras.")
    local_origin = _vec3(data["origin"], "camera.origin", -10000.0, 10000.0)
    local_target = _vec3(data["target"], "camera.target", -10000.0, 10000.0)
    up = _vec3(data.get("up", (0.0, 1.0, 0.0)), "camera.up", -1.0, 1.0)
    if any(abs(value - 1.0) > 1e-9 for value in element.transform.scale):
        raise VisualSceneCompilationError("Escala de câmera diferente de 1 ainda não está mapeada.")
    translation = element.transform.translation
    rotation = element.transform.rotation_degrees
    local_direction = tuple(local_target[i] - local_origin[i] for i in range(3))
    world_origin_offset = _rotate(local_origin, rotation)
    world_direction = _rotate(local_direction, rotation)
    world_up = _rotate(up, rotation)
    origin = tuple(translation[i] + world_origin_offset[i] for i in range(3))
    target = tuple(origin[i] + world_direction[i] for i in range(3))
    up = world_up
    return CameraSpec(
        origin=origin,
        target=target,
        up=up,
        vertical_fov_degrees=_finite(
            data.get("vertical_fov_degrees", 42.0), "camera.vertical_fov_degrees", 5.0, 120.0,
        ),
        aperture=_finite(data.get("aperture", 0.0), "camera.aperture", 0.0, 1.0),
        focus_distance=_finite(data.get("focus_distance", 5.0), "camera.focus_distance", 0.1, 10000.0),
    )


class VisualSceneCompiler:
    """Compile the currently supported subset without losing unsupported IDs."""

    VERSION = "0.1.0"

    @classmethod
    def compile(cls, document: VisualDocumentSpec) -> VisualSceneCompileResult:
        if not isinstance(document, VisualDocumentSpec):
            raise VisualSceneCompilationError("document deve ser VisualDocumentSpec.")
        if document.coordinate_space == "2d":
            return VisualSceneCompileResult(
                status="unsupported_coordinate_space",
                scene=None,
                scene_spec_sha256=None,
                source_document_sha256=document.sha256(),
                reason="O CPUPathTracer requer coordenadas 3D.",
            )
        if len(document.document_id) > 96:
            return VisualSceneCompileResult(
                status="unsupported_document_id",
                scene=None,
                scene_spec_sha256=None,
                source_document_sha256=document.sha256(),
                reason="SceneSpec limita scene_id a 96 caracteres.",
            )

        visible_layers = {layer.layer_id for layer in document.layers if layer.visible}
        element_map = {element.element_id: element for element in document.elements}

        def ancestry_is_visible(element: VisualElementSpec) -> bool:
            current: VisualElementSpec | None = element
            while current is not None:
                if current.layer_id not in visible_layers:
                    return False
                current = element_map.get(current.parent_id) if current.parent_id else None
            return True

        hidden_ids = tuple(
            element.element_id for element in document.elements
            if not ancestry_is_visible(element)
        )
        active_elements = tuple(
            element for element in document.elements
            if ancestry_is_visible(element)
        )
        cameras = [element for element in active_elements if element.kind == "camera"]
        unsupported: set[str] = set()
        if len(cameras) != 1:
            unsupported.update(element.element_id for element in cameras)
            return VisualSceneCompileResult(
                status="camera_required",
                scene=None,
                scene_spec_sha256=None,
                source_document_sha256=document.sha256(),
                unsupported_element_ids=tuple(sorted(unsupported)),
                skipped_hidden_element_ids=hidden_ids,
                reason="A composição precisa ter exatamente uma câmera visível.",
            )
        if cameras[0].asset_id is not None:
            return VisualSceneCompileResult(
                status="invalid_camera",
                scene=None,
                scene_spec_sha256=None,
                source_document_sha256=document.sha256(),
                unsupported_element_ids=(cameras[0].element_id,),
                skipped_hidden_element_ids=hidden_ids,
                reason="A câmera não aceita asset_id neste backend.",
            )

        try:
            camera = _camera(cameras[0])
        except (VisualSceneCompilationError, ValueError):
            return VisualSceneCompileResult(
                status="invalid_camera",
                scene=None,
                scene_spec_sha256=None,
                source_document_sha256=document.sha256(),
                unsupported_element_ids=(cameras[0].element_id,),
                skipped_hidden_element_ids=hidden_ids,
                reason="A definição da câmera não é compatível com SceneSpec.",
            )

        # SceneSpec cannot preserve visual references, paint style, or layer compositing.
        if document.references:
            return VisualSceneCompileResult(
                status="unsupported_references",
                scene=None,
                scene_spec_sha256=None,
                source_document_sha256=document.sha256(),
                unsupported_element_ids=tuple(reference.reference_id for reference in document.references),
                skipped_hidden_element_ids=hidden_ids,
                reason="O renderer atual não consome referências visuais do documento.",
            )
        if (
            document.style.medium != "unspecified"
            or document.style.description
            or document.style.parameters
            or document.style.style_id != "style.default"
        ):
            return VisualSceneCompileResult(
                status="unsupported_style_profile",
                scene=None,
                scene_spec_sha256=None,
                source_document_sha256=document.sha256(),
                skipped_hidden_element_ids=hidden_ids,
                reason="SceneSpec ainda não representa o perfil de estilo do documento.",
            )
        layer_map = {layer.layer_id: layer for layer in document.layers}
        compositing_ids = tuple(sorted({
            element.element_id for element in active_elements
            if (
                layer_map[element.layer_id].opacity != 1.0
                or layer_map[element.layer_id].blend_mode != "normal"
            )
        }))
        if compositing_ids:
            return VisualSceneCompileResult(
                status="unsupported_layer_compositing",
                scene=None,
                scene_spec_sha256=None,
                source_document_sha256=document.sha256(),
                unsupported_element_ids=compositing_ids,
                skipped_hidden_element_ids=hidden_ids,
                reason="SceneSpec ainda não preserva opacidade/blend das camadas.",
            )

        spheres: list[SphereSpec] = []
        boxes: list[BoxSpec] = []
        oriented_boxes: list[OrientedBoxSpec] = []
        planes: list[PlaneSpec] = []
        point_lights: list[PointLightSpec] = []
        element_bindings: list[tuple[str, str]] = [("camera", cameras[0].element_id)]

        for element in active_elements:
            if element.kind in {"camera", "group"}:
                if element.asset_id is not None:
                    unsupported.add(element.element_id)
                    continue
                if element.kind == "group" and (
                    element.data
                    or element.transform.translation != (0.0, 0.0, 0.0)
                    or element.transform.rotation_degrees != (0.0, 0.0, 0.0)
                    or element.transform.scale != (1.0, 1.0, 1.0)
                ):
                    unsupported.add(element.element_id)
                continue
            if element.kind == "light":
                try:
                    data = element.data
                    if set(data) != {"intensity"}:
                        raise VisualSceneCompilationError("Luz pontual exige somente intensity.")
                    if element.asset_id is not None:
                        raise VisualSceneCompilationError("Luz não pode carregar asset neste backend.")
                    if element.transform.scale != (1.0, 1.0, 1.0) or element.transform.rotation_degrees != (0.0, 0.0, 0.0):
                        raise VisualSceneCompilationError("Transformação de luz não mapeada.")
                    point_lights.append(PointLightSpec(
                        position=element.transform.translation,
                        intensity=_vec3(data["intensity"], "light.intensity", 0.0, 1000.0),
                    ))
                    element_bindings.append((f"point_lights[{len(point_lights)-1}]", element.element_id))
                except (VisualSceneCompilationError, ValueError):
                    unsupported.add(element.element_id)
                continue
            if element.kind != "shape":
                unsupported.add(element.element_id)
                continue
            if element.asset_id is not None:
                unsupported.add(element.element_id)
                continue
            try:
                data = element.data
                primitive = data.get("primitive")
                material_keys = {
                    "material", "albedo", "emission", "metallic", "roughness",
                    "texture_pattern", "texture_color_a", "texture_color_b", "texture_scale",
                }
                primitive_keys = {
                    "sphere": {"radius"},
                    "box": {"half_extents"},
                    "plane": {"normal"},
                }
                if not isinstance(primitive, str) or primitive not in primitive_keys:
                    raise VisualSceneCompilationError("primitive não suportada pelo CPUPathTracer.")
                if set(data) - material_keys - primitive_keys[primitive] - {"primitive"}:
                    raise VisualSceneCompilationError("Shape possui dados não mapeados para sua primitive.")
                material_raw = data.get("material", {})
                if not isinstance(material_raw, Mapping):
                    raise VisualSceneCompilationError("material deve ser um objeto.")
                material_data = dict(material_raw)
                for key in (
                    "albedo", "emission", "metallic", "roughness",
                    "texture_pattern", "texture_color_a", "texture_color_b", "texture_scale",
                ):
                    if key in data:
                        material_data[key] = data[key]
                material = _material(material_data)
                translation = element.transform.translation
                scale = element.transform.scale
                rotation = element.transform.rotation_degrees

                if primitive == "sphere":
                    if max(scale) - min(scale) > 1e-9:
                        raise VisualSceneCompilationError("Sphere exige escala uniforme.")
                    radius = _finite(data.get("radius", 0.5), "sphere.radius", 0.001, 1000.0)
                    spheres.append(SphereSpec(
                        center=translation,
                        radius=radius * abs(scale[0]),
                        **material,
                    ))
                    element_bindings.append((f"spheres[{len(spheres)-1}]", element.element_id))
                elif primitive == "box":
                    half = _vec3(data.get("half_extents", (0.5, 0.5, 0.5)), "box.half_extents", 0.0001, 5000.0)
                    half = tuple(half[i] * abs(scale[i]) for i in range(3))
                    if any(value <= 0 for value in half):
                        raise VisualSceneCompilationError("Box exige half_extents positivos.")
                    if any(abs(v) > 1e-10 for v in rotation):
                        oriented_boxes.append(OrientedBoxSpec(
                            center=translation,
                            half_extents=half,
                            rotation=_quaternion_from_euler(rotation),
                            **material,
                        ))
                        element_bindings.append((f"oriented_boxes[{len(oriented_boxes)-1}]", element.element_id))
                    else:
                        boxes.append(BoxSpec(
                            minimum=tuple(translation[i] - half[i] for i in range(3)),
                            maximum=tuple(translation[i] + half[i] for i in range(3)),
                            **material,
                        ))
                        element_bindings.append((f"boxes[{len(boxes)-1}]", element.element_id))
                elif primitive == "plane":
                    if any(abs(v - 1.0) > 1e-9 for v in scale):
                        raise VisualSceneCompilationError("Plane com escala diferente de 1 ainda não está mapeado.")
                    normal = _vec3(data.get("normal", (0.0, 1.0, 0.0)), "plane.normal", -1.0, 1.0)
                    normal = _rotate(normal, rotation)
                    planes.append(PlaneSpec(
                        point=translation,
                        normal=normal,
                        **material,
                    ))
                    element_bindings.append((f"planes[{len(planes)-1}]", element.element_id))
                else:
                    raise VisualSceneCompilationError("primitive não suportada pelo CPUPathTracer.")
            except (VisualSceneCompilationError, ValueError, TypeError, OverflowError):
                unsupported.add(element.element_id)

        if unsupported:
            return VisualSceneCompileResult(
                status="unsupported_elements",
                scene=None,
                scene_spec_sha256=None,
                source_document_sha256=document.sha256(),
                unsupported_element_ids=tuple(sorted(unsupported)),
                skipped_hidden_element_ids=hidden_ids,
                reason="Um ou mais elementos visíveis não podem ser convertidos sem perda.",
            )

        try:
            scene = SceneSpec(
                camera=camera,
                spheres=tuple(spheres),
                boxes=tuple(boxes),
                oriented_boxes=tuple(oriented_boxes),
                planes=tuple(planes),
                point_lights=tuple(point_lights),
                scene_id=document.document_id,
                background_top=_vec3(
                    document.metadata.get("background_top", (0.42, 0.58, 0.82)),
                    "background_top", 0.0, 1.0,
                ),
                background_bottom=_vec3(
                    document.metadata.get("background_bottom", (0.055, 0.065, 0.09)),
                    "background_bottom", 0.0, 1.0,
                ),
            )
        except (ValueError, TypeError, OverflowError) as exc:
            raise VisualSceneCompilationError("Documento não pôde ser convertido em SceneSpec.") from exc
        return VisualSceneCompileResult(
            status="compiled",
            scene=scene,
            scene_spec_sha256=scene.sha256(),
            source_document_sha256=document.sha256(),
            unsupported_element_ids=(),
            skipped_hidden_element_ids=hidden_ids,
            element_bindings=tuple(element_bindings),
            reason=None,
        )


@dataclass(frozen=True)
class VisualRenderProvenance:
    """Immutable, non-authenticating lineage from an authored document to a task."""

    source_document_sha256: str
    scene_spec_sha256: str
    task_id: str
    task_sha256: str
    element_bindings: tuple[tuple[str, str], ...]
    skipped_hidden_element_ids: tuple[str, ...] = ()
    compiler_version: str = VisualSceneCompiler.VERSION

    SCHEMA = "mahoraga.visual_render_provenance.v1"
    MAX_BINDINGS = 512
    MAX_HIDDEN_IDS = 512

    def __post_init__(self) -> None:
        for field_name in ("source_document_sha256", "scene_spec_sha256", "task_sha256"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise VisualSceneCompilationError(f"{field_name} deve ser SHA-256 hexadecimal.")
        if not isinstance(self.task_id, str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", self.task_id
        ) is None:
            raise VisualSceneCompilationError("task_id da proveniência é inválido.")
        if not isinstance(self.compiler_version, str) or re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+", self.compiler_version
        ) is None:
            raise VisualSceneCompilationError("Versão do compilador na proveniência inválida.")
        if not isinstance(self.element_bindings, (tuple, list)):
            raise VisualSceneCompilationError("element_bindings deve ser uma sequência.")
        if len(self.element_bindings) > self.MAX_BINDINGS:
            raise VisualSceneCompilationError("Proveniência excede o limite de vínculos.")
        if any(not isinstance(item, (tuple, list)) or len(item) != 2
               for item in self.element_bindings):
            raise VisualSceneCompilationError("Cada vínculo deve conter caminho e element_id.")
        bindings = tuple((item[0], item[1]) for item in self.element_bindings)
        keys: set[str] = set()
        element_ids: set[str] = set()
        for binding in bindings:
            if len(binding) != 2:
                raise VisualSceneCompilationError("Cada vínculo deve conter caminho e element_id.")
            key, element_id = binding
            if not isinstance(key, str) or re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_.\[\]]{0,127}", key
            ) is None:
                raise VisualSceneCompilationError("Caminho de vínculo inválido.")
            if not isinstance(element_id, str) or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", element_id
            ) is None:
                raise VisualSceneCompilationError("element_id de proveniência inválido.")
            if key in keys or element_id in element_ids:
                raise VisualSceneCompilationError("Vínculos de proveniência devem ser únicos.")
            keys.add(key)
            element_ids.add(element_id)
        if not isinstance(self.skipped_hidden_element_ids, (tuple, list)):
            raise VisualSceneCompilationError("skipped_hidden_element_ids deve ser uma sequência.")
        hidden = tuple(self.skipped_hidden_element_ids)
        if len(hidden) > self.MAX_HIDDEN_IDS:
            raise VisualSceneCompilationError("IDs ocultos excedem o limite.")
        for element_id in hidden:
            if not isinstance(element_id, str) or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", element_id
            ) is None:
                raise VisualSceneCompilationError("ID de elemento oculto inválido.")
        if len(set(hidden)) != len(hidden):
            raise VisualSceneCompilationError("IDs ocultos contêm duplicatas.")
        if set(hidden) & element_ids:
            raise VisualSceneCompilationError("Elemento não pode estar visível e oculto na mesma proveniência.")
        object.__setattr__(self, "element_bindings", bindings)
        object.__setattr__(self, "skipped_hidden_element_ids", hidden)

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic lineage metadata; this is not a trust attestation."""
        return {
            "schema": self.SCHEMA,
            "source_document_sha256": self.source_document_sha256,
            "scene_spec_sha256": self.scene_spec_sha256,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "compiler_version": self.compiler_version,
            "element_bindings": [
                {"scene_path": key, "element_id": element_id}
                for key, element_id in self.element_bindings
            ],
            "skipped_hidden_element_ids": list(self.skipped_hidden_element_ids),
            "source_provenance_authenticated": False,
        }


@dataclass(frozen=True)
class VisualImageTaskCompileResult:
    """Prepared task contract plus source SceneSpec; this is not an execution result."""

    status: str
    task_spec: ImageTaskSpec | None
    scene: SceneSpec | None
    source_document_sha256: str | None
    scene_spec_sha256: str | None
    execution_started: bool = False
    unsupported_element_ids: tuple[str, ...] = ()
    skipped_hidden_element_ids: tuple[str, ...] = ()
    element_bindings: tuple[tuple[str, str], ...] = ()
    reason: str | None = None

    def render_provenance(self) -> VisualRenderProvenance:
        """Build lineage only for a successfully prepared task; never execute it."""
        if (
            self.status != "ready_for_governed_executor"
            or self.execution_started
            or self.task_spec is None
            or self.scene is None
            or self.source_document_sha256 is None
            or self.scene_spec_sha256 is None
        ):
            raise VisualSceneCompilationError(
                "Somente uma tarefa preparada com sucesso pode gerar proveniência."
            )
        if self.scene.sha256() != self.scene_spec_sha256:
            raise VisualSceneCompilationError("SceneSpec mudou após a compilação.")
        if self.task_spec.scene_spec_sha256 != self.scene_spec_sha256:
            raise VisualSceneCompilationError("ImageTaskSpec diverge da proveniência da cena.")
        return VisualRenderProvenance(
            source_document_sha256=self.source_document_sha256,
            scene_spec_sha256=self.scene_spec_sha256,
            task_id=self.task_spec.task_id,
            task_sha256=self.task_spec.sha256(),
            element_bindings=self.element_bindings,
            skipped_hidden_element_ids=self.skipped_hidden_element_ids,
        )


def compile_visual_image_task(
    document: VisualDocumentSpec,
    *,
    task_id: str,
    width: int = 64,
    height: int = 64,
    seed: int = 0,
    resource_budget: VisualResourceBudget | None = None,
) -> VisualImageTaskCompileResult:
    """Prepare a path_trace ImageTaskSpec; never calls selector, arbiter, or executor."""
    compiled = VisualSceneCompiler.compile(document)
    if compiled.status != "compiled" or compiled.scene is None:
        return VisualImageTaskCompileResult(
            status=compiled.status,
            task_spec=None,
            scene=None,
            source_document_sha256=compiled.source_document_sha256,
            scene_spec_sha256=None,
            execution_started=False,
            unsupported_element_ids=compiled.unsupported_element_ids,
            skipped_hidden_element_ids=compiled.skipped_hidden_element_ids,
            element_bindings=compiled.element_bindings,
            reason=compiled.reason,
        )
    if (
        isinstance(width, bool) or not isinstance(width, int)
        or isinstance(height, bool) or not isinstance(height, int)
        or width < 1 or height < 1
        or width > CPUPathTracerBackend.MAX_DIMENSION
        or height > CPUPathTracerBackend.MAX_DIMENSION
        or width * height > CPUPathTracerBackend.MAX_PIXELS
    ):
        return VisualImageTaskCompileResult(
            status="unsupported_render_dimensions",
            task_spec=None,
            scene=compiled.scene,
            source_document_sha256=compiled.source_document_sha256,
            scene_spec_sha256=compiled.scene_spec_sha256,
            execution_started=False,
            unsupported_element_ids=compiled.unsupported_element_ids,
            skipped_hidden_element_ids=compiled.skipped_hidden_element_ids,
            element_bindings=compiled.element_bindings,
            reason="As dimensões excedem os limites atuais do CPUPathTracer.",
        )
    budget = resource_budget if resource_budget is not None else VisualResourceBudget()
    try:
        task = ImageTaskSpec(
            task_id=task_id,
            operation="path_trace",
            scene_id=compiled.scene.scene_id,
            scene_spec_sha256=compiled.scene_spec_sha256,
            width=width,
            height=height,
            seed=seed,
            backend_preference="cpu.pathtracer",
            resource_budget=budget,
        )
    except (ImageTaskContractError, TypeError, ValueError) as exc:
        return VisualImageTaskCompileResult(
            status="invalid_task_spec",
            task_spec=None,
            scene=compiled.scene,
            source_document_sha256=compiled.source_document_sha256,
            scene_spec_sha256=compiled.scene_spec_sha256,
            execution_started=False,
            unsupported_element_ids=compiled.unsupported_element_ids,
            skipped_hidden_element_ids=compiled.skipped_hidden_element_ids,
            element_bindings=compiled.element_bindings,
            reason=str(exc),
        )
    return VisualImageTaskCompileResult(
        status="ready_for_governed_executor",
        task_spec=task,
        scene=compiled.scene,
        source_document_sha256=compiled.source_document_sha256,
        scene_spec_sha256=compiled.scene_spec_sha256,
        execution_started=False,
        unsupported_element_ids=compiled.unsupported_element_ids,
        skipped_hidden_element_ids=compiled.skipped_hidden_element_ids,
        element_bindings=compiled.element_bindings,
        reason="Tarefa preparada; selector, lease e executor ainda precisam aprovar a execução.",
    )
