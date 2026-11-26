"""Bounded deterministic CPU path tracer prototype for Mahoraga."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math
import random
from typing import Any

from .cancellation import CancellationToken

Vector3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]
UV2 = tuple[float, float]


class PathTracingError(ValueError):
    """Invalid scene, render settings or path-tracing budget."""


def _finite(value: Any, field: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PathTracingError(f"{field} deve ser número finito.")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise PathTracingError(f"{field} deve ser número finito.") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise PathTracingError(f"{field} fora do intervalo permitido.")
    return result


def _vec(value: Any, field: str, low: float, high: float) -> Vector3:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise PathTracingError(f"{field} deve conter três números.")
    return tuple(_finite(v, f"{field}[{i}]", low, high) for i, v in enumerate(value))  # type: ignore[return-value]


def _add(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: Vector3, b: Vector3) -> Vector3:
    return (a[0] * b[0], a[1] * b[1], a[2] * b[2])


def _scale(a: Vector3, k: float) -> Vector3:
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(v: Vector3, field: str) -> Vector3:
    length = math.sqrt(_dot(v, v))
    if not math.isfinite(length) or length <= 1e-12:
        raise PathTracingError(f"{field} não pode ser vetor nulo.")
    return _scale(v, 1.0 / length)


def _uv(value: Any, field: str) -> UV2:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise PathTracingError(f"{field} deve conter duas coordenadas.")
    return tuple(
        _finite(component, f"{field}[{index}]", -10000.0, 10000.0)
        for index, component in enumerate(value)
    )  # type: ignore[return-value]


def _plane_basis(normal: Vector3) -> tuple[Vector3, Vector3]:
    helper = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 1.0, 0.0)
    tangent = _norm(_cross(normal, helper), "plane UV tangent")
    return tangent, _cross(normal, tangent)


def _box_face_uv(
    point: Vector3,
    normal: Vector3,
    minimum: Vector3,
    maximum: Vector3,
) -> UV2:
    extents = tuple(maximum[index] - minimum[index] for index in range(3))
    if abs(normal[0]) >= abs(normal[1]) and abs(normal[0]) >= abs(normal[2]):
        return (
            (point[2] - minimum[2]) / extents[2],
            (point[1] - minimum[1]) / extents[1],
        )
    if abs(normal[1]) >= abs(normal[2]):
        return (
            (point[0] - minimum[0]) / extents[0],
            (point[2] - minimum[2]) / extents[2],
        )
    return (
        (point[0] - minimum[0]) / extents[0],
        (point[1] - minimum[1]) / extents[1],
    )


@dataclass(frozen=True)
class TextureBuffer:
    """Already-decoded bounded RGB8/RGBA8 pixels supplied by the caller."""

    width: int
    height: int
    pixels: bytes
    color_space: str = "srgb"
    channels: int = 3

    MAX_DIMENSION = 2048
    MAX_PIXELS = 1_048_576
    MAX_BYTES = MAX_PIXELS * 4

    def __post_init__(self):
        for field, value in (("width", self.width), ("height", self.height)):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= self.MAX_DIMENSION:
                raise PathTracingError(f"texture.{field} fora do limite.")
        if self.width * self.height > self.MAX_PIXELS:
            raise PathTracingError("Textura excede o orçamento de pixels.")
        if not isinstance(self.pixels, bytes):
            raise PathTracingError("TextureBuffer exige bytes RGB imutáveis.")
        if isinstance(self.channels, bool) or not isinstance(self.channels, int) or self.channels not in (3, 4):
            raise PathTracingError("TextureBuffer aceita RGB8 ou RGBA8.")
        expected = self.width * self.height * self.channels
        if len(self.pixels) != expected or len(self.pixels) > self.MAX_BYTES:
            raise PathTracingError("Tamanho do buffer RGB não corresponde às dimensões.")
        if self.color_space not in ("srgb", "linear"):
            raise PathTracingError("Espaço de cor da textura não suportado.")


def _texture_ref(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or any(not (character.isalnum() or character in "._:-") for character in value)
    ):
        raise PathTracingError(f"{field} inválido.")
    return value


def _quaternion(value: Any, field: str) -> Quaternion:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise PathTracingError(f"{field} deve conter quatro números (w, x, y, z).")
    raw = tuple(_finite(item, f"{field}[{index}]", -1.0, 1.0)
                for index, item in enumerate(value))
    length = math.sqrt(sum(item * item for item in raw))
    if length <= 1e-12:
        raise PathTracingError(f"{field} não pode ser quaternion nulo.")
    return tuple(item / length for item in raw)  # type: ignore[return-value]


def _quat_rotate(rotation: Quaternion, vector: Vector3) -> Vector3:
    w, x, y, z = rotation
    qv = (x, y, z)
    twice_cross = _scale(_cross(qv, vector), 2.0)
    return _add(vector, _add(_scale(twice_cross, w), _cross(qv, twice_cross)))


@dataclass(frozen=True)
class CameraSpec:
    origin: Vector3
    target: Vector3
    up: Vector3 = (0.0, 1.0, 0.0)
    vertical_fov_degrees: float = 42.0
    aperture: float = 0.0
    focus_distance: float = 5.0

    def __post_init__(self):
        object.__setattr__(self, "origin", _vec(self.origin, "camera.origin", -10000.0, 10000.0))
        object.__setattr__(self, "target", _vec(self.target, "camera.target", -10000.0, 10000.0))
        object.__setattr__(self, "up", _vec(self.up, "camera.up", -1.0, 1.0))
        object.__setattr__(
            self, "vertical_fov_degrees",
            _finite(self.vertical_fov_degrees, "camera.vertical_fov_degrees", 5.0, 120.0),
        )
        forward = _norm(_sub(self.target, self.origin), "camera forward")
        _norm(_cross(forward, self.up), "camera up")
        object.__setattr__(self, "aperture", _finite(self.aperture, "camera.aperture", 0.0, 1.0))
        object.__setattr__(
            self, "focus_distance",
            _finite(self.focus_distance, "camera.focus_distance", 0.1, 10000.0),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "CameraSpec":
        if not isinstance(value, dict):
            raise PathTracingError("camera deve ser um objeto.")
        allowed = {"origin", "target", "up", "vertical_fov_degrees", "aperture", "focus_distance"}
        if set(value) - allowed or not {"origin", "target"}.issubset(value):
            raise PathTracingError("Campos de camera desconhecidos ou ausentes.")
        return cls(
            _vec(value["origin"], "camera.origin", -10000.0, 10000.0),
            _vec(value["target"], "camera.target", -10000.0, 10000.0),
            _vec(value.get("up", [0.0, 1.0, 0.0]), "camera.up", -1.0, 1.0),
            _finite(value.get("vertical_fov_degrees", 42.0),
                    "camera.vertical_fov_degrees", 5.0, 120.0),
            _finite(value.get("aperture", 0.0), "camera.aperture", 0.0, 1.0),
            _finite(value.get("focus_distance", 5.0), "camera.focus_distance", 0.1, 10000.0),
        )


@dataclass(frozen=True)
class SphereSpec:
    center: Vector3
    radius: float
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    texture_pattern: str = "solid"
    texture_color_a: Vector3 | None = None
    texture_color_b: Vector3 | None = None
    texture_scale: float = 8.0
    texture_id: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "center", _vec(self.center, "sphere.center", -10000.0, 10000.0))
        object.__setattr__(self, "radius", _finite(self.radius, "sphere.radius", 0.001, 1000.0))
        object.__setattr__(self, "albedo", _vec(self.albedo, "sphere.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "sphere.emission", 0.0, 32.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "sphere.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "sphere.roughness", 0.02, 1.0))
        if self.texture_pattern not in ("solid", "checker", "image"):
            raise PathTracingError("Padrão de textura de sphere não suportado.")
        texture_id = _texture_ref(self.texture_id, "sphere.texture_id")
        if self.texture_pattern == "image":
            if texture_id is None:
                raise PathTracingError("Textura de imagem exige texture_id.")
            if any(value is not None for value in (self.texture_color_a, self.texture_color_b)):
                raise PathTracingError("Textura de imagem não aceita cores checker.")
        elif texture_id is not None:
            raise PathTracingError("texture_id só pode ser usado com texture_pattern=image.")
        object.__setattr__(self, "texture_id", texture_id)
        if self.texture_pattern == "checker":
            if self.texture_color_a is None or self.texture_color_b is None:
                raise PathTracingError("Checker de sphere exige duas cores.")
            object.__setattr__(self, "texture_color_a", _vec(self.texture_color_a, "sphere.texture_color_a", 0.0, 1.0))
            object.__setattr__(self, "texture_color_b", _vec(self.texture_color_b, "sphere.texture_color_b", 0.0, 1.0))
        object.__setattr__(self, "texture_scale", _finite(self.texture_scale, "sphere.texture_scale", 0.1, 256.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "SphereSpec":
        if not isinstance(value, dict):
            raise PathTracingError("Cada esfera deve ser um objeto.")
        allowed = {
            "center",
            "radius",
            "albedo",
            "emission",
            "metallic",
            "roughness",
            "texture_pattern",
            "texture_color_a",
            "texture_color_b",
            "texture_scale",
            "texture_id",
        }
        if set(value) - allowed or not {"center", "radius", "albedo"}.issubset(value):
            raise PathTracingError("Campos de esfera desconhecidos ou ausentes.")
        return cls(
            _vec(value["center"], "sphere.center", -10000.0, 10000.0),
            _finite(value["radius"], "sphere.radius", 0.001, 1000.0),
            _vec(value["albedo"], "sphere.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]),
                 "sphere.emission", 0.0, 32.0),
            _finite(value.get("metallic", 0.0), "sphere.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "sphere.roughness", 0.02, 1.0),
            value.get("texture_pattern", "solid"),
            _vec(value["texture_color_a"], "sphere.texture_color_a", 0.0, 1.0) if value.get("texture_color_a") is not None else None,
            _vec(value["texture_color_b"], "sphere.texture_color_b", 0.0, 1.0) if value.get("texture_color_b") is not None else None,
            _finite(value.get("texture_scale", 8.0), "sphere.texture_scale", 0.1, 256.0),
            _texture_ref(value.get("texture_id"), "sphere.texture_id"),
        )


@dataclass(frozen=True)
class TriangleSpec:
    a: Vector3
    b: Vector3
    c: Vector3
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    uv_a: UV2 | None = None
    uv_b: UV2 | None = None
    uv_c: UV2 | None = None
    texture_pattern: str = "solid"
    texture_color_a: Vector3 | None = None
    texture_color_b: Vector3 | None = None
    texture_scale: float = 8.0
    texture_id: str | None = None

    def __post_init__(self):
        a = _vec(self.a, "triangle.a", -10000.0, 10000.0)
        b = _vec(self.b, "triangle.b", -10000.0, 10000.0)
        c = _vec(self.c, "triangle.c", -10000.0, 10000.0)
        cross = _cross(_sub(b, a), _sub(c, a))
        if _dot(cross, cross) <= 1e-20:
            raise PathTracingError("Triângulo possui área nula.")
        object.__setattr__(self, "a", a)
        object.__setattr__(self, "b", b)
        object.__setattr__(self, "c", c)
        object.__setattr__(self, "albedo", _vec(self.albedo, "triangle.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "triangle.emission", 0.0, 100.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "triangle.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "triangle.roughness", 0.02, 1.0))
        uv_values = (self.uv_a, self.uv_b, self.uv_c)
        if any(value is not None for value in uv_values):
            if any(value is None for value in uv_values):
                raise PathTracingError("Triângulo exige UVs nos três vértices ou em nenhum.")
            object.__setattr__(self, "uv_a", _uv(self.uv_a, "triangle.uv_a"))
            object.__setattr__(self, "uv_b", _uv(self.uv_b, "triangle.uv_b"))
            object.__setattr__(self, "uv_c", _uv(self.uv_c, "triangle.uv_c"))
        if self.texture_pattern not in ("solid", "checker", "image"):
            raise PathTracingError("Padrão de textura do triângulo não suportado.")
        texture_id = _texture_ref(self.texture_id, "triangle.texture_id")
        if self.texture_pattern == "image":
            if texture_id is None:
                raise PathTracingError("Textura de imagem exige texture_id.")
            if any(value is not None for value in (self.texture_color_a, self.texture_color_b)):
                raise PathTracingError("Textura de imagem não aceita cores checker.")
        elif texture_id is not None:
            raise PathTracingError("texture_id só pode ser usado com texture_pattern=image.")
        object.__setattr__(self, "texture_id", texture_id)
        if self.texture_pattern == "checker":
            if self.texture_color_a is None or self.texture_color_b is None:
                raise PathTracingError("Checker exige texture_color_a e texture_color_b.")
            object.__setattr__(self, "texture_color_a", _vec(self.texture_color_a, "triangle.texture_color_a", 0.0, 1.0))
            object.__setattr__(self, "texture_color_b", _vec(self.texture_color_b, "triangle.texture_color_b", 0.0, 1.0))
        object.__setattr__(self, "texture_scale", _finite(self.texture_scale, "triangle.texture_scale", 0.1, 256.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "TriangleSpec":
        if not isinstance(value, dict) or set(value) - {"a", "b", "c", "albedo", "emission", "metallic", "roughness", "uv_a", "uv_b", "uv_c", "texture_pattern", "texture_color_a", "texture_color_b", "texture_scale", "texture_id"}:
            raise PathTracingError("Triângulo contém campos desconhecidos ou formato inválido.")
        if not {"a", "b", "c", "albedo"}.issubset(value):
            raise PathTracingError("Triângulo exige a, b, c e albedo.")
        a = _vec(value["a"], "triangle.a", -10000.0, 10000.0)
        b = _vec(value["b"], "triangle.b", -10000.0, 10000.0)
        c = _vec(value["c"], "triangle.c", -10000.0, 10000.0)
        cross = _cross(_sub(b, a), _sub(c, a))
        if _dot(cross, cross) <= 1e-20:
            raise PathTracingError("Triângulo possui área nula.")
        return cls(
            a, b, c,
            _vec(value["albedo"], "triangle.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]), "triangle.emission", 0.0, 100.0),
            _finite(value.get("metallic", 0.0), "triangle.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "triangle.roughness", 0.02, 1.0),
            _uv(value["uv_a"], "triangle.uv_a") if value.get("uv_a") is not None else None,
            _uv(value["uv_b"], "triangle.uv_b") if value.get("uv_b") is not None else None,
            _uv(value["uv_c"], "triangle.uv_c") if value.get("uv_c") is not None else None,
            value.get("texture_pattern", "solid"),
            _vec(value["texture_color_a"], "triangle.texture_color_a", 0.0, 1.0) if value.get("texture_color_a") is not None else None,
            _vec(value["texture_color_b"], "triangle.texture_color_b", 0.0, 1.0) if value.get("texture_color_b") is not None else None,
            _finite(value.get("texture_scale", 8.0), "triangle.texture_scale", 0.1, 256.0),
            _texture_ref(value.get("texture_id"), "triangle.texture_id"),
        )


@dataclass(frozen=True)
class MeshMaterialSpec:
    """Per-face mesh material using the renderer's current bounded surface model."""

    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    texture_pattern: str = "solid"
    texture_color_a: Vector3 | None = None
    texture_color_b: Vector3 | None = None
    texture_scale: float = 8.0
    texture_id: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "albedo", _vec(self.albedo, "mesh_material.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "mesh_material.emission", 0.0, 100.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "mesh_material.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "mesh_material.roughness", 0.02, 1.0))
        if self.texture_pattern not in ("solid", "checker", "image"):
            raise PathTracingError("Padrão de textura do material não suportado.")
        texture_id = _texture_ref(self.texture_id, "mesh_material.texture_id")
        if self.texture_pattern == "image":
            if texture_id is None:
                raise PathTracingError("Textura de imagem exige texture_id.")
            if any(value is not None for value in (self.texture_color_a, self.texture_color_b)):
                raise PathTracingError("Textura de imagem não aceita cores checker.")
        elif texture_id is not None:
            raise PathTracingError("texture_id só pode ser usado com texture_pattern=image.")
        object.__setattr__(self, "texture_id", texture_id)
        if self.texture_pattern == "checker":
            if self.texture_color_a is None or self.texture_color_b is None:
                raise PathTracingError("Checker exige duas cores.")
            object.__setattr__(self, "texture_color_a", _vec(self.texture_color_a, "mesh_material.texture_color_a", 0.0, 1.0))
            object.__setattr__(self, "texture_color_b", _vec(self.texture_color_b, "mesh_material.texture_color_b", 0.0, 1.0))
        object.__setattr__(self, "texture_scale", _finite(self.texture_scale, "mesh_material.texture_scale", 0.1, 256.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "MeshMaterialSpec":
        allowed = {
            "albedo", "emission", "metallic", "roughness", "texture_pattern",
            "texture_color_a", "texture_color_b", "texture_scale", "texture_id",
        }
        if not isinstance(value, dict) or set(value) - allowed or "albedo" not in value:
            raise PathTracingError("Material de malha exige albedo e não aceita campos extras.")
        return cls(
            _vec(value["albedo"], "mesh_material.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]), "mesh_material.emission", 0.0, 100.0),
            _finite(value.get("metallic", 0.0), "mesh_material.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "mesh_material.roughness", 0.02, 1.0),
            value.get("texture_pattern", "solid"),
            _vec(value["texture_color_a"], "mesh_material.texture_color_a", 0.0, 1.0) if value.get("texture_color_a") is not None else None,
            _vec(value["texture_color_b"], "mesh_material.texture_color_b", 0.0, 1.0) if value.get("texture_color_b") is not None else None,
            _finite(value.get("texture_scale", 8.0), "mesh_material.texture_scale", 0.1, 256.0),
            _texture_ref(value.get("texture_id"), "mesh_material.texture_id"),
        )


@dataclass(frozen=True)
class TriangleBVHNode:
    minimum: Vector3
    maximum: Vector3
    left: Any = None
    right: Any = None
    face_indices: tuple[int, ...] = ()


def _triangle_bounds(triangle: TriangleSpec) -> tuple[Vector3, Vector3]:
    return (
        tuple(min(triangle.a[axis], triangle.b[axis], triangle.c[axis]) for axis in range(3)),
        tuple(max(triangle.a[axis], triangle.b[axis], triangle.c[axis]) for axis in range(3)),
    )


def _build_triangle_bvh(
    triangles: tuple[TriangleSpec, ...],
    face_indices: tuple[int, ...],
    leaf_size: int = 4,
) -> TriangleBVHNode:
    bounds = [_triangle_bounds(triangles[index]) for index in face_indices]
    minimum = tuple(min(item[0][axis] for item in bounds) for axis in range(3))
    maximum = tuple(max(item[1][axis] for item in bounds) for axis in range(3))
    if len(face_indices) <= leaf_size:
        return TriangleBVHNode(minimum, maximum, face_indices=face_indices)

    centroids = {
        index: tuple(
            (triangles[index].a[axis] + triangles[index].b[axis]
             + triangles[index].c[axis]) / 3.0
            for axis in range(3)
        )
        for index in face_indices
    }
    extents = tuple(maximum[axis] - minimum[axis] for axis in range(3))
    split_axis = max(range(3), key=lambda axis: extents[axis])
    ordered = tuple(sorted(face_indices, key=lambda index: (centroids[index][split_axis], index)))
    middle = len(ordered) // 2
    left = _build_triangle_bvh(triangles, ordered[:middle], leaf_size)
    right = _build_triangle_bvh(triangles, ordered[middle:], leaf_size)
    return TriangleBVHNode(minimum, maximum, left=left, right=right)


def _ray_bounds_entry(
    origin: Vector3,
    direction: Vector3,
    minimum: Vector3,
    maximum: Vector3,
    max_distance: float,
):
    near = -math.inf
    far = math.inf
    for axis in range(3):
        component = direction[axis]
        if abs(component) < 1e-12:
            if origin[axis] < minimum[axis] or origin[axis] > maximum[axis]:
                return None
            continue
        inverse = 1.0 / component
        first = (minimum[axis] - origin[axis]) * inverse
        second = (maximum[axis] - origin[axis]) * inverse
        if first > second:
            first, second = second, first
        near = max(near, first)
        far = min(far, second)
        if near > far:
            return None
    if far <= 1e-8 or near >= max_distance:
        return None
    return max(near, 0.0)


@dataclass(frozen=True)
class TriangleMeshSpec:
    """Indexed triangle mesh with one bounded material shared by all faces."""

    vertices: tuple[Vector3, ...]
    faces: tuple[tuple[int, int, int], ...]
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    materials: tuple[MeshMaterialSpec, ...] = ()
    face_material_indices: tuple[int, ...] = ()
    uvs: tuple[UV2, ...] = ()

    MAX_VERTICES = 256
    MAX_MATERIALS = 16
    MAX_FACES = 384

    def __post_init__(self):
        if not isinstance(self.vertices, (list, tuple)) or not 3 <= len(self.vertices) <= self.MAX_VERTICES:
            raise PathTracingError("Mesh exige de 3 a 256 vértices.")
        vertices = tuple(
            _vec(vertex, f"mesh.vertices[{index}]", -10000.0, 10000.0)
            for index, vertex in enumerate(self.vertices)
        )
        if not isinstance(self.faces, (list, tuple)) or not 1 <= len(self.faces) <= self.MAX_FACES:
            raise PathTracingError("Mesh exige de 1 a 384 faces triangulares.")
        faces = []
        for face_index, face in enumerate(self.faces):
            if not isinstance(face, (list, tuple)) or len(face) != 3:
                raise PathTracingError(f"mesh.faces[{face_index}] deve conter três índices.")
            if any(isinstance(index, bool) or not isinstance(index, int) for index in face):
                raise PathTracingError(f"mesh.faces[{face_index}] contém índice não inteiro.")
            if any(index < 0 or index >= len(vertices) for index in face):
                raise PathTracingError(f"mesh.faces[{face_index}] contém índice fora dos vértices.")
            if len(set(face)) != 3:
                raise PathTracingError(f"mesh.faces[{face_index}] repete índices.")
            faces.append(tuple(face))
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "faces", tuple(faces))
        if not isinstance(self.uvs, (list, tuple)):
            raise PathTracingError("mesh.uvs deve ser uma sequência.")
        if self.uvs and len(self.uvs) != len(vertices):
            raise PathTracingError("Mesh deve fornecer uma coordenada UV por vértice.")
        uvs = tuple(
            _uv(value, f"mesh.uvs[{index}]")
            for index, value in enumerate(self.uvs)
        )
        object.__setattr__(self, "uvs", uvs)
        object.__setattr__(self, "albedo", _vec(self.albedo, "mesh.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "mesh.emission", 0.0, 100.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "mesh.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "mesh.roughness", 0.02, 1.0))
        if not isinstance(self.materials, (list, tuple)) or len(self.materials) > self.MAX_MATERIALS:
            raise PathTracingError(f"Mesh aceita até {self.MAX_MATERIALS} materiais.")
        materials = tuple(self.materials)
        if any(not isinstance(material, MeshMaterialSpec) for material in materials):
            raise PathTracingError("Mesh contém material com tipo inválido.")
        if not materials:
            if self.face_material_indices:
                raise PathTracingError("Índices de material exigem uma lista de materiais.")
            materials = (
                MeshMaterialSpec(self.albedo, self.emission, self.metallic, self.roughness),
            )
            material_indices = (0,) * len(faces)
        else:
            if not isinstance(self.face_material_indices, (list, tuple)):
                raise PathTracingError("face_material_indices deve ser uma sequência.")
            material_indices = tuple(self.face_material_indices)
            if len(material_indices) != len(faces):
                raise PathTracingError("Cada face precisa de exatamente um índice de material.")
            if any(
                isinstance(index, bool) or not isinstance(index, int)
                or index < 0 or index >= len(materials)
                for index in material_indices
            ):
                raise PathTracingError("Índice de material de face fora do intervalo.")
        object.__setattr__(self, "materials", materials)
        object.__setattr__(self, "face_material_indices", material_indices)
        triangles = tuple(
            TriangleSpec(
                vertices[a], vertices[b], vertices[c],
                materials[material_indices[face_index]].albedo,
                materials[material_indices[face_index]].emission,
                materials[material_indices[face_index]].metallic,
                materials[material_indices[face_index]].roughness,
                uvs[a] if uvs else None,
                uvs[b] if uvs else None,
                uvs[c] if uvs else None,
                materials[material_indices[face_index]].texture_pattern,
                materials[material_indices[face_index]].texture_color_a,
                materials[material_indices[face_index]].texture_color_b,
                materials[material_indices[face_index]].texture_scale,
                materials[material_indices[face_index]].texture_id,
            )
            for face_index, (a, b, c) in enumerate(faces)
        )
        object.__setattr__(self, "_triangles", triangles)
        object.__setattr__(
            self, "_bvh", _build_triangle_bvh(
                triangles, tuple(range(len(triangles)))
            )
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "TriangleMeshSpec":
        allowed = {
            "vertices", "faces", "albedo", "emission", "metallic", "roughness",
            "materials", "face_material_indices", "uvs",
        }
        required = {"vertices", "faces"}
        if isinstance(value, dict) and "materials" not in value:
            required.add("albedo")
        if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
            raise PathTracingError("Mesh exige vertices, faces e albedo; campos extras não são aceitos.")
        return cls(
            value["vertices"],
            value["faces"],
            _vec(value.get("albedo", [0.0, 0.0, 0.0]), "mesh.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]), "mesh.emission", 0.0, 100.0),
            _finite(value.get("metallic", 0.0), "mesh.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "mesh.roughness", 0.02, 1.0),
            tuple(MeshMaterialSpec.from_mapping(item) for item in value.get("materials", [])),
            value.get("face_material_indices", ()),
            value.get("uvs", ()),
        )


@dataclass(frozen=True)
class PointLightSpec:
    position: Vector3
    intensity: Vector3

    def __post_init__(self):
        object.__setattr__(
            self, "position", _vec(self.position, "light.position", -10000.0, 10000.0)
        )
        object.__setattr__(
            self, "intensity", _vec(self.intensity, "light.intensity", 0.0, 1000.0)
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PointLightSpec":
        if not isinstance(value, dict) or set(value) != {"position", "intensity"}:
            raise PathTracingError("Luz pontual exige position e intensity.")
        return cls(
            _vec(value["position"], "light.position", -10000.0, 10000.0),
            _vec(value["intensity"], "light.intensity", 0.0, 1000.0),
        )


@dataclass(frozen=True)
class DiskSpec:
    """Finite one-sided-orientation circular disk in an arbitrary plane."""

    center: Vector3
    normal: Vector3
    radius: float
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    texture_pattern: str = "solid"
    texture_color_a: Vector3 | None = None
    texture_color_b: Vector3 | None = None
    texture_scale: float = 8.0
    texture_id: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "center", _vec(self.center, "disk.center", -10000.0, 10000.0))
        object.__setattr__(
            self, "normal",
            _norm(_vec(self.normal, "disk.normal", -1.0, 1.0), "disk normal"),
        )
        object.__setattr__(self, "radius", _finite(self.radius, "disk.radius", 0.001, 1000.0))
        object.__setattr__(self, "albedo", _vec(self.albedo, "disk.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "disk.emission", 0.0, 100.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "disk.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "disk.roughness", 0.02, 1.0))
        if self.texture_pattern not in ("solid", "checker", "image"):
            raise PathTracingError("Padrão de textura de disk não suportado.")
        texture_id = _texture_ref(self.texture_id, "disk.texture_id")
        if self.texture_pattern == "image":
            if texture_id is None:
                raise PathTracingError("Textura de imagem exige texture_id.")
            if any(value is not None for value in (self.texture_color_a, self.texture_color_b)):
                raise PathTracingError("Textura de imagem não aceita cores checker.")
        elif texture_id is not None:
            raise PathTracingError("texture_id só pode ser usado com texture_pattern=image.")
        object.__setattr__(self, "texture_id", texture_id)
        if self.texture_pattern == "checker":
            if self.texture_color_a is None or self.texture_color_b is None:
                raise PathTracingError("Checker de disk exige duas cores.")
            object.__setattr__(self, "texture_color_a", _vec(self.texture_color_a, "disk.texture_color_a", 0.0, 1.0))
            object.__setattr__(self, "texture_color_b", _vec(self.texture_color_b, "disk.texture_color_b", 0.0, 1.0))
        object.__setattr__(self, "texture_scale", _finite(self.texture_scale, "disk.texture_scale", 0.1, 256.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "DiskSpec":
        allowed = {
            "center",
            "normal",
            "radius",
            "albedo",
            "emission",
            "metallic",
            "roughness",
            "texture_pattern",
            "texture_color_a",
            "texture_color_b",
            "texture_scale",
            "texture_id",
        }
        required = {"center", "normal", "radius", "albedo"}
        if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
            raise PathTracingError("Disco exige center, normal, radius e albedo.")
        return cls(
            _vec(value["center"], "disk.center", -10000.0, 10000.0),
            _vec(value["normal"], "disk.normal", -1.0, 1.0),
            _finite(value["radius"], "disk.radius", 0.001, 1000.0),
            _vec(value["albedo"], "disk.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]), "disk.emission", 0.0, 100.0),
            _finite(value.get("metallic", 0.0), "disk.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "disk.roughness", 0.02, 1.0),
            value.get("texture_pattern", "solid"),
            _vec(value["texture_color_a"], "disk.texture_color_a", 0.0, 1.0) if value.get("texture_color_a") is not None else None,
            _vec(value["texture_color_b"], "disk.texture_color_b", 0.0, 1.0) if value.get("texture_color_b") is not None else None,
            _finite(value.get("texture_scale", 8.0), "disk.texture_scale", 0.1, 256.0),
            _texture_ref(value.get("texture_id"), "disk.texture_id"),
        )


@dataclass(frozen=True)
class ConeSpec:
    """Finite right circular cone with an apex, base center and closed base disk."""

    apex: Vector3
    base_center: Vector3
    base_radius: float
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    texture_pattern: str = "solid"
    texture_color_a: Vector3 | None = None
    texture_color_b: Vector3 | None = None
    texture_scale: float = 8.0
    texture_id: str | None = None

    def __post_init__(self):
        apex = _vec(self.apex, "cone.apex", -10000.0, 10000.0)
        base = _vec(self.base_center, "cone.base_center", -10000.0, 10000.0)
        axis = _sub(apex, base)
        length_squared = _dot(axis, axis)
        if not 1e-8 <= length_squared <= 4e8:
            raise PathTracingError("Altura do cone degenerada ou fora do limite.")
        object.__setattr__(self, "apex", apex)
        object.__setattr__(self, "base_center", base)
        object.__setattr__(self, "base_radius", _finite(self.base_radius, "cone.base_radius", 0.001, 1000.0))
        object.__setattr__(self, "albedo", _vec(self.albedo, "cone.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "cone.emission", 0.0, 100.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "cone.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "cone.roughness", 0.02, 1.0))
        if self.texture_pattern not in ("solid", "checker", "image"):
            raise PathTracingError("Padrão de textura de cone não suportado.")
        texture_id = _texture_ref(self.texture_id, "cone.texture_id")
        if self.texture_pattern == "image":
            if texture_id is None:
                raise PathTracingError("Textura de imagem exige texture_id.")
            if any(value is not None for value in (self.texture_color_a, self.texture_color_b)):
                raise PathTracingError("Textura de imagem não aceita cores checker.")
        elif texture_id is not None:
            raise PathTracingError("texture_id só pode ser usado com texture_pattern=image.")
        object.__setattr__(self, "texture_id", texture_id)
        if self.texture_pattern == "checker":
            if self.texture_color_a is None or self.texture_color_b is None:
                raise PathTracingError("Checker de cone exige duas cores.")
            object.__setattr__(self, "texture_color_a", _vec(self.texture_color_a, "cone.texture_color_a", 0.0, 1.0))
            object.__setattr__(self, "texture_color_b", _vec(self.texture_color_b, "cone.texture_color_b", 0.0, 1.0))
        object.__setattr__(self, "texture_scale", _finite(self.texture_scale, "cone.texture_scale", 0.1, 256.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "ConeSpec":
        allowed = {
            "apex",
            "base_center",
            "base_radius",
            "albedo",
            "emission",
            "metallic",
            "roughness",
            "texture_pattern",
            "texture_color_a",
            "texture_color_b",
            "texture_scale",
            "texture_id",
        }
        required = {"apex", "base_center", "base_radius", "albedo"}
        if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
            raise PathTracingError("Cone exige apex, base_center, base_radius e albedo.")
        return cls(
            _vec(value["apex"], "cone.apex", -10000.0, 10000.0),
            _vec(value["base_center"], "cone.base_center", -10000.0, 10000.0),
            _finite(value["base_radius"], "cone.base_radius", 0.001, 1000.0),
            _vec(value["albedo"], "cone.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]), "cone.emission", 0.0, 100.0),
            _finite(value.get("metallic", 0.0), "cone.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "cone.roughness", 0.02, 1.0),
            value.get("texture_pattern", "solid"),
            _vec(value["texture_color_a"], "cone.texture_color_a", 0.0, 1.0) if value.get("texture_color_a") is not None else None,
            _vec(value["texture_color_b"], "cone.texture_color_b", 0.0, 1.0) if value.get("texture_color_b") is not None else None,
            _finite(value.get("texture_scale", 8.0), "cone.texture_scale", 0.1, 256.0),
            _texture_ref(value.get("texture_id"), "cone.texture_id"),
        )


@dataclass(frozen=True)
class CapsuleSpec:
    """Segment swept by a sphere; useful for smooth limb-like geometry."""

    start: Vector3
    end: Vector3
    radius: float
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    texture_pattern: str = "solid"
    texture_color_a: Vector3 | None = None
    texture_color_b: Vector3 | None = None
    texture_scale: float = 8.0
    texture_id: str | None = None

    def __post_init__(self):
        start = _vec(self.start, "capsule.start", -10000.0, 10000.0)
        end = _vec(self.end, "capsule.end", -10000.0, 10000.0)
        axis = _sub(end, start)
        length_squared = _dot(axis, axis)
        if not 1e-8 <= length_squared <= 4e8:
            raise PathTracingError("Eixo da cápsula degenerado ou fora do limite.")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "radius", _finite(self.radius, "capsule.radius", 0.001, 1000.0))
        object.__setattr__(self, "albedo", _vec(self.albedo, "capsule.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "capsule.emission", 0.0, 100.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "capsule.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "capsule.roughness", 0.02, 1.0))
        if self.texture_pattern not in ("solid", "checker", "image"):
            raise PathTracingError("Padrão de textura de capsule não suportado.")
        texture_id = _texture_ref(self.texture_id, "capsule.texture_id")
        if self.texture_pattern == "image":
            if texture_id is None:
                raise PathTracingError("Textura de imagem exige texture_id.")
            if any(value is not None for value in (self.texture_color_a, self.texture_color_b)):
                raise PathTracingError("Textura de imagem não aceita cores checker.")
        elif texture_id is not None:
            raise PathTracingError("texture_id só pode ser usado com texture_pattern=image.")
        object.__setattr__(self, "texture_id", texture_id)
        if self.texture_pattern == "checker":
            if self.texture_color_a is None or self.texture_color_b is None:
                raise PathTracingError("Checker de capsule exige duas cores.")
            object.__setattr__(self, "texture_color_a", _vec(self.texture_color_a, "capsule.texture_color_a", 0.0, 1.0))
            object.__setattr__(self, "texture_color_b", _vec(self.texture_color_b, "capsule.texture_color_b", 0.0, 1.0))
        object.__setattr__(self, "texture_scale", _finite(self.texture_scale, "capsule.texture_scale", 0.1, 256.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "CapsuleSpec":
        allowed = {
            "start",
            "end",
            "radius",
            "albedo",
            "emission",
            "metallic",
            "roughness",
            "texture_pattern",
            "texture_color_a",
            "texture_color_b",
            "texture_scale",
            "texture_id",
        }
        required = {"start", "end", "radius", "albedo"}
        if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
            raise PathTracingError("Cápsula exige start, end, radius e albedo.")
        return cls(
            _vec(value["start"], "capsule.start", -10000.0, 10000.0),
            _vec(value["end"], "capsule.end", -10000.0, 10000.0),
            _finite(value["radius"], "capsule.radius", 0.001, 1000.0),
            _vec(value["albedo"], "capsule.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]), "capsule.emission", 0.0, 100.0),
            _finite(value.get("metallic", 0.0), "capsule.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "capsule.roughness", 0.02, 1.0),
            value.get("texture_pattern", "solid"),
            _vec(value["texture_color_a"], "capsule.texture_color_a", 0.0, 1.0) if value.get("texture_color_a") is not None else None,
            _vec(value["texture_color_b"], "capsule.texture_color_b", 0.0, 1.0) if value.get("texture_color_b") is not None else None,
            _finite(value.get("texture_scale", 8.0), "capsule.texture_scale", 0.1, 256.0),
            _texture_ref(value.get("texture_id"), "capsule.texture_id"),
        )


@dataclass(frozen=True)
class CylinderSpec:
    """Finite capped cylinder defined by its two cap centers and radius."""

    start: Vector3
    end: Vector3
    radius: float
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    texture_pattern: str = "solid"
    texture_color_a: Vector3 | None = None
    texture_color_b: Vector3 | None = None
    texture_scale: float = 8.0
    texture_id: str | None = None

    def __post_init__(self):
        start = _vec(self.start, "cylinder.start", -10000.0, 10000.0)
        end = _vec(self.end, "cylinder.end", -10000.0, 10000.0)
        axis = _sub(end, start)
        length_squared = _dot(axis, axis)
        if not 1e-8 <= length_squared <= 4e8:
            raise PathTracingError("Eixo do cilindro degenerado ou fora do limite.")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "radius", _finite(self.radius, "cylinder.radius", 0.001, 1000.0))
        object.__setattr__(self, "albedo", _vec(self.albedo, "cylinder.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "cylinder.emission", 0.0, 100.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "cylinder.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "cylinder.roughness", 0.02, 1.0))
        if self.texture_pattern not in ("solid", "checker", "image"):
            raise PathTracingError("Padrão de textura de cylinder não suportado.")
        texture_id = _texture_ref(self.texture_id, "cylinder.texture_id")
        if self.texture_pattern == "image":
            if texture_id is None:
                raise PathTracingError("Textura de imagem exige texture_id.")
            if any(value is not None for value in (self.texture_color_a, self.texture_color_b)):
                raise PathTracingError("Textura de imagem não aceita cores checker.")
        elif texture_id is not None:
            raise PathTracingError("texture_id só pode ser usado com texture_pattern=image.")
        object.__setattr__(self, "texture_id", texture_id)
        if self.texture_pattern == "checker":
            if self.texture_color_a is None or self.texture_color_b is None:
                raise PathTracingError("Checker de cylinder exige duas cores.")
            object.__setattr__(self, "texture_color_a", _vec(self.texture_color_a, "cylinder.texture_color_a", 0.0, 1.0))
            object.__setattr__(self, "texture_color_b", _vec(self.texture_color_b, "cylinder.texture_color_b", 0.0, 1.0))
        object.__setattr__(self, "texture_scale", _finite(self.texture_scale, "cylinder.texture_scale", 0.1, 256.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "CylinderSpec":
        allowed = {
            "start",
            "end",
            "radius",
            "albedo",
            "emission",
            "metallic",
            "roughness",
            "texture_pattern",
            "texture_color_a",
            "texture_color_b",
            "texture_scale",
            "texture_id",
        }
        required = {"start", "end", "radius", "albedo"}
        if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
            raise PathTracingError("Cilindro exige start, end, radius e albedo.")
        return cls(
            _vec(value["start"], "cylinder.start", -10000.0, 10000.0),
            _vec(value["end"], "cylinder.end", -10000.0, 10000.0),
            _finite(value["radius"], "cylinder.radius", 0.001, 1000.0),
            _vec(value["albedo"], "cylinder.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]), "cylinder.emission", 0.0, 100.0),
            _finite(value.get("metallic", 0.0), "cylinder.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "cylinder.roughness", 0.02, 1.0),
            value.get("texture_pattern", "solid"),
            _vec(value["texture_color_a"], "cylinder.texture_color_a", 0.0, 1.0) if value.get("texture_color_a") is not None else None,
            _vec(value["texture_color_b"], "cylinder.texture_color_b", 0.0, 1.0) if value.get("texture_color_b") is not None else None,
            _finite(value.get("texture_scale", 8.0), "cylinder.texture_scale", 0.1, 256.0),
            _texture_ref(value.get("texture_id"), "cylinder.texture_id"),
        )


@dataclass(frozen=True)
class OrientedBoxSpec:
    """Rotated box using a normalized world-space quaternion (w, x, y, z)."""

    center: Vector3
    half_extents: Vector3
    rotation: Quaternion
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    texture_pattern: str = "solid"
    texture_color_a: Vector3 | None = None
    texture_color_b: Vector3 | None = None
    texture_scale: float = 8.0
    texture_id: str | None = None

    def __post_init__(self):
        extents = _vec(self.half_extents, "oriented_box.half_extents", 0.0001, 5000.0)
        object.__setattr__(self, "center", _vec(self.center, "oriented_box.center", -10000.0, 10000.0))
        object.__setattr__(self, "half_extents", extents)
        object.__setattr__(self, "rotation", _quaternion(self.rotation, "oriented_box.rotation"))
        object.__setattr__(self, "albedo", _vec(self.albedo, "oriented_box.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "oriented_box.emission", 0.0, 100.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "oriented_box.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "oriented_box.roughness", 0.02, 1.0))
        if self.texture_pattern not in ("solid", "checker", "image"):
            raise PathTracingError("Padrão de textura de oriented_box não suportado.")
        texture_id = _texture_ref(self.texture_id, "oriented_box.texture_id")
        if self.texture_pattern == "image":
            if texture_id is None:
                raise PathTracingError("Textura de imagem exige texture_id.")
            if any(value is not None for value in (self.texture_color_a, self.texture_color_b)):
                raise PathTracingError("Textura de imagem não aceita cores checker.")
        elif texture_id is not None:
            raise PathTracingError("texture_id só pode ser usado com texture_pattern=image.")
        object.__setattr__(self, "texture_id", texture_id)
        if self.texture_pattern == "checker":
            if self.texture_color_a is None or self.texture_color_b is None:
                raise PathTracingError("Checker de oriented_box exige duas cores.")
            object.__setattr__(self, "texture_color_a", _vec(self.texture_color_a, "oriented_box.texture_color_a", 0.0, 1.0))
            object.__setattr__(self, "texture_color_b", _vec(self.texture_color_b, "oriented_box.texture_color_b", 0.0, 1.0))
        object.__setattr__(self, "texture_scale", _finite(self.texture_scale, "oriented_box.texture_scale", 0.1, 256.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "OrientedBoxSpec":
        allowed = {
            "center",
            "half_extents",
            "rotation",
            "albedo",
            "emission",
            "metallic",
            "roughness",
            "texture_pattern",
            "texture_color_a",
            "texture_color_b",
            "texture_scale",
            "texture_id",
        }
        required = {"center", "half_extents", "rotation", "albedo"}
        if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
            raise PathTracingError("Caixa orientada exige center, half_extents, rotation e albedo.")
        return cls(
            _vec(value["center"], "oriented_box.center", -10000.0, 10000.0),
            _vec(value["half_extents"], "oriented_box.half_extents", 0.0001, 5000.0),
            _quaternion(value["rotation"], "oriented_box.rotation"),
            _vec(value["albedo"], "oriented_box.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]), "oriented_box.emission", 0.0, 100.0),
            _finite(value.get("metallic", 0.0), "oriented_box.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "oriented_box.roughness", 0.02, 1.0),
            value.get("texture_pattern", "solid"),
            _vec(value["texture_color_a"], "oriented_box.texture_color_a", 0.0, 1.0) if value.get("texture_color_a") is not None else None,
            _vec(value["texture_color_b"], "oriented_box.texture_color_b", 0.0, 1.0) if value.get("texture_color_b") is not None else None,
            _finite(value.get("texture_scale", 8.0), "oriented_box.texture_scale", 0.1, 256.0),
            _texture_ref(value.get("texture_id"), "oriented_box.texture_id"),
        )


@dataclass(frozen=True)
class BoxSpec:
    """Axis-aligned box with strict positive extents and the common material contract."""

    minimum: Vector3
    maximum: Vector3
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    texture_pattern: str = "solid"
    texture_color_a: Vector3 | None = None
    texture_color_b: Vector3 | None = None
    texture_scale: float = 8.0
    texture_id: str | None = None

    def __post_init__(self):
        minimum = _vec(self.minimum, "box.minimum", -10000.0, 10000.0)
        maximum = _vec(self.maximum, "box.maximum", -10000.0, 10000.0)
        if any(maximum[index] - minimum[index] <= 1e-4 for index in range(3)):
            raise PathTracingError("Caixa exige extensão positiva em todos os eixos.")
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)
        object.__setattr__(self, "albedo", _vec(self.albedo, "box.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "box.emission", 0.0, 100.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "box.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "box.roughness", 0.02, 1.0))
        if self.texture_pattern not in ("solid", "checker", "image"):
            raise PathTracingError("Padrão de textura de box não suportado.")
        texture_id = _texture_ref(self.texture_id, "box.texture_id")
        if self.texture_pattern == "image":
            if texture_id is None:
                raise PathTracingError("Textura de imagem exige texture_id.")
            if any(value is not None for value in (self.texture_color_a, self.texture_color_b)):
                raise PathTracingError("Textura de imagem não aceita cores checker.")
        elif texture_id is not None:
            raise PathTracingError("texture_id só pode ser usado com texture_pattern=image.")
        object.__setattr__(self, "texture_id", texture_id)
        if self.texture_pattern == "checker":
            if self.texture_color_a is None or self.texture_color_b is None:
                raise PathTracingError("Checker de box exige duas cores.")
            object.__setattr__(self, "texture_color_a", _vec(self.texture_color_a, "box.texture_color_a", 0.0, 1.0))
            object.__setattr__(self, "texture_color_b", _vec(self.texture_color_b, "box.texture_color_b", 0.0, 1.0))
        object.__setattr__(self, "texture_scale", _finite(self.texture_scale, "box.texture_scale", 0.1, 256.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "BoxSpec":
        allowed = {
            "minimum",
            "maximum",
            "albedo",
            "emission",
            "metallic",
            "roughness",
            "texture_pattern",
            "texture_color_a",
            "texture_color_b",
            "texture_scale",
            "texture_id",
        }
        required = {"minimum", "maximum", "albedo"}
        if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
            raise PathTracingError("Caixa exige minimum, maximum e albedo.")
        return cls(
            _vec(value["minimum"], "box.minimum", -10000.0, 10000.0),
            _vec(value["maximum"], "box.maximum", -10000.0, 10000.0),
            _vec(value["albedo"], "box.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]), "box.emission", 0.0, 100.0),
            _finite(value.get("metallic", 0.0), "box.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "box.roughness", 0.02, 1.0),
            value.get("texture_pattern", "solid"),
            _vec(value["texture_color_a"], "box.texture_color_a", 0.0, 1.0) if value.get("texture_color_a") is not None else None,
            _vec(value["texture_color_b"], "box.texture_color_b", 0.0, 1.0) if value.get("texture_color_b") is not None else None,
            _finite(value.get("texture_scale", 8.0), "box.texture_scale", 0.1, 256.0),
            _texture_ref(value.get("texture_id"), "box.texture_id"),
        )


@dataclass(frozen=True)
class PlaneSpec:
    """Infinite plane with a validated unit normal and the common material contract."""

    point: Vector3
    normal: Vector3
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)
    metallic: float = 0.0
    roughness: float = 1.0
    texture_pattern: str = "solid"
    texture_color_a: Vector3 | None = None
    texture_color_b: Vector3 | None = None
    texture_scale: float = 8.0
    texture_id: str | None = None

    def __post_init__(self):
        object.__setattr__(
            self, "point", _vec(self.point, "plane.point", -10000.0, 10000.0)
        )
        object.__setattr__(
            self, "normal",
            _norm(_vec(self.normal, "plane.normal", -1.0, 1.0), "plane normal"),
        )
        object.__setattr__(self, "albedo", _vec(self.albedo, "plane.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "plane.emission", 0.0, 100.0))
        object.__setattr__(self, "metallic", _finite(self.metallic, "plane.metallic", 0.0, 1.0))
        object.__setattr__(self, "roughness", _finite(self.roughness, "plane.roughness", 0.02, 1.0))
        if self.texture_pattern not in ("solid", "checker", "image"):
            raise PathTracingError("Padrão de textura de plane não suportado.")
        texture_id = _texture_ref(self.texture_id, "plane.texture_id")
        if self.texture_pattern == "image":
            if texture_id is None:
                raise PathTracingError("Textura de imagem exige texture_id.")
            if any(value is not None for value in (self.texture_color_a, self.texture_color_b)):
                raise PathTracingError("Textura de imagem não aceita cores checker.")
        elif texture_id is not None:
            raise PathTracingError("texture_id só pode ser usado com texture_pattern=image.")
        object.__setattr__(self, "texture_id", texture_id)
        if self.texture_pattern == "checker":
            if self.texture_color_a is None or self.texture_color_b is None:
                raise PathTracingError("Checker de plane exige duas cores.")
            object.__setattr__(self, "texture_color_a", _vec(self.texture_color_a, "plane.texture_color_a", 0.0, 1.0))
            object.__setattr__(self, "texture_color_b", _vec(self.texture_color_b, "plane.texture_color_b", 0.0, 1.0))
        object.__setattr__(self, "texture_scale", _finite(self.texture_scale, "plane.texture_scale", 0.1, 256.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "PlaneSpec":
        allowed = {
            "point",
            "normal",
            "albedo",
            "emission",
            "metallic",
            "roughness",
            "texture_pattern",
            "texture_color_a",
            "texture_color_b",
            "texture_scale",
            "texture_id",
        }
        required = {"point", "normal", "albedo"}
        if not isinstance(value, dict) or set(value) - allowed or not required.issubset(value):
            raise PathTracingError("Plano exige point, normal e albedo; campos extras não são aceitos.")
        return cls(
            _vec(value["point"], "plane.point", -10000.0, 10000.0),
            _vec(value["normal"], "plane.normal", -1.0, 1.0),
            _vec(value["albedo"], "plane.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]), "plane.emission", 0.0, 100.0),
            _finite(value.get("metallic", 0.0), "plane.metallic", 0.0, 1.0),
            _finite(value.get("roughness", 1.0), "plane.roughness", 0.02, 1.0),
            value.get("texture_pattern", "solid"),
            _vec(value["texture_color_a"], "plane.texture_color_a", 0.0, 1.0) if value.get("texture_color_a") is not None else None,
            _vec(value["texture_color_b"], "plane.texture_color_b", 0.0, 1.0) if value.get("texture_color_b") is not None else None,
            _finite(value.get("texture_scale", 8.0), "plane.texture_scale", 0.1, 256.0),
            _texture_ref(value.get("texture_id"), "plane.texture_id"),
        )


@dataclass(frozen=True)
class AreaLightSpec:
    """One-sided rectangular area emitter defined by center and two full edge vectors."""

    center: Vector3
    edge_u: Vector3
    edge_v: Vector3
    intensity: Vector3

    def __post_init__(self):
        center = _vec(self.center, "area_light.center", -10000.0, 10000.0)
        edge_u = _vec(self.edge_u, "area_light.edge_u", -1000.0, 1000.0)
        edge_v = _vec(self.edge_v, "area_light.edge_v", -1000.0, 1000.0)
        cross = _cross(edge_u, edge_v)
        area = math.sqrt(_dot(cross, cross))
        if not math.isfinite(area) or not 1e-6 <= area <= 1_000_000.0:
            raise PathTracingError("Área da luz retangular fora do limite.")
        object.__setattr__(self, "center", center)
        object.__setattr__(self, "edge_u", edge_u)
        object.__setattr__(self, "edge_v", edge_v)
        object.__setattr__(
            self, "intensity", _vec(self.intensity, "area_light.intensity", 0.0, 1000.0)
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "AreaLightSpec":
        if not isinstance(value, dict) or set(value) != {
            "center", "edge_u", "edge_v", "intensity",
        }:
            raise PathTracingError(
                "Luz de área exige center, edge_u, edge_v e intensity."
            )
        return cls(
            _vec(value["center"], "area_light.center", -10000.0, 10000.0),
            _vec(value["edge_u"], "area_light.edge_u", -1000.0, 1000.0),
            _vec(value["edge_v"], "area_light.edge_v", -1000.0, 1000.0),
            _vec(value["intensity"], "area_light.intensity", 0.0, 1000.0),
        )


@dataclass(frozen=True)
class SceneSpec:
    camera: CameraSpec
    spheres: tuple[SphereSpec, ...]
    triangles: tuple[TriangleSpec, ...] = ()
    point_lights: tuple[PointLightSpec, ...] = ()
    background_top: Vector3 = (0.42, 0.58, 0.82)
    background_bottom: Vector3 = (0.055, 0.065, 0.09)
    scene_id: str = "legacy-sphere-scene"
    area_lights: tuple[AreaLightSpec, ...] = ()
    planes: tuple[PlaneSpec, ...] = ()
    boxes: tuple[BoxSpec, ...] = ()
    cylinders: tuple[CylinderSpec, ...] = ()
    oriented_boxes: tuple[OrientedBoxSpec, ...] = ()
    capsules: tuple[CapsuleSpec, ...] = ()
    cones: tuple[ConeSpec, ...] = ()
    disks: tuple[DiskSpec, ...] = ()
    meshes: tuple[TriangleMeshSpec, ...] = ()

    MAX_SPHERES = 32
    MAX_TRIANGLES = 64
    MAX_POINT_LIGHTS = 8
    MAX_AREA_LIGHTS = 4
    MAX_PLANES = 16
    MAX_BOXES = 16
    MAX_CYLINDERS = 16
    MAX_ORIENTED_BOXES = 16
    MAX_CAPSULES = 16
    MAX_CONES = 16
    MAX_DISKS = 16
    MAX_MESHES = 8
    MAX_MESH_TRIANGLES = 512
    SCHEMA = "mahoraga.scene_spec.v22"

    def __post_init__(self):
        if not isinstance(self.camera, CameraSpec):
            raise PathTracingError("camera precisa ser CameraSpec.")
        collections = (
            ("spheres", self.spheres, SphereSpec, self.MAX_SPHERES),
            ("triangles", self.triangles, TriangleSpec, self.MAX_TRIANGLES),
            ("point_lights", self.point_lights, PointLightSpec, self.MAX_POINT_LIGHTS),
            ("area_lights", self.area_lights, AreaLightSpec, self.MAX_AREA_LIGHTS),
            ("planes", self.planes, PlaneSpec, self.MAX_PLANES),
            ("boxes", self.boxes, BoxSpec, self.MAX_BOXES),
            ("cylinders", self.cylinders, CylinderSpec, self.MAX_CYLINDERS),
            ("oriented_boxes", self.oriented_boxes, OrientedBoxSpec, self.MAX_ORIENTED_BOXES),
            ("capsules", self.capsules, CapsuleSpec, self.MAX_CAPSULES),
            ("cones", self.cones, ConeSpec, self.MAX_CONES),
            ("disks", self.disks, DiskSpec, self.MAX_DISKS),
            ("meshes", self.meshes, TriangleMeshSpec, self.MAX_MESHES),
        )
        for field, values, expected_type, maximum in collections:
            if not isinstance(values, (list, tuple)) or len(values) > maximum:
                raise PathTracingError(f"{field} deve conter até {maximum} itens.")
            normalized = tuple(values)
            if any(not isinstance(item, expected_type) for item in normalized):
                raise PathTracingError(f"{field} contém item com tipo inválido.")
            object.__setattr__(self, field, normalized)
        if sum(len(mesh.faces) for mesh in self.meshes) > self.MAX_MESH_TRIANGLES:
            raise PathTracingError(
                f"Meshes excedem {self.MAX_MESH_TRIANGLES} triângulos no total."
            )
        object.__setattr__(
            self, "background_top", _vec(self.background_top, "background_top", 0.0, 1.0)
        )
        object.__setattr__(
            self, "background_bottom", _vec(self.background_bottom, "background_bottom", 0.0, 1.0)
        )
        if (
            not isinstance(self.scene_id, str)
            or not self.scene_id.strip()
            or len(self.scene_id) > 96
        ):
            raise PathTracingError("scene_id inválido.")
        object.__setattr__(self, "scene_id", self.scene_id.strip())

    @classmethod
    def from_mapping(cls, value: Any) -> "SceneSpec":
        if not isinstance(value, dict):
            raise PathTracingError("scene deve ser um objeto JSON.")
        allowed = {
            "schema", "scene_id", "camera", "spheres", "triangles",
            "point_lights", "area_lights", "planes", "boxes", "cylinders", "oriented_boxes", "capsules", "cones", "disks", "meshes", "background_top", "background_bottom",
        }
        if set(value) - allowed:
            raise PathTracingError("scene contém campos desconhecidos.")
        schema = value.get("schema")
        supported_schemas = {
            None,
            "mahoraga.scene.v1",
            *(f"mahoraga.scene_spec.v{version}" for version in range(1, 23)),
        }
        if schema is not None and (
            not isinstance(schema, str) or schema not in supported_schemas
        ):
            raise PathTracingError("Versão de SceneSpec não suportada.")
        camera = CameraSpec.from_mapping(value.get("camera"))
        raw_spheres = value.get("spheres")
        if not isinstance(raw_spheres, list) or len(raw_spheres) > cls.MAX_SPHERES:
            raise PathTracingError("spheres deve conter até 32 elementos.")
        spheres = tuple(SphereSpec.from_mapping(item) for item in raw_spheres)
        raw_triangles = value.get("triangles", [])
        if not isinstance(raw_triangles, list) or len(raw_triangles) > cls.MAX_TRIANGLES:
            raise PathTracingError("triangles deve conter até 64 elementos.")
        triangles = tuple(TriangleSpec.from_mapping(item) for item in raw_triangles)
        raw_lights = value.get("point_lights", [])
        if not isinstance(raw_lights, list) or len(raw_lights) > cls.MAX_POINT_LIGHTS:
            raise PathTracingError("point_lights deve conter até 8 elementos.")
        lights = tuple(PointLightSpec.from_mapping(item) for item in raw_lights)
        raw_area_lights = value.get("area_lights", [])
        if not isinstance(raw_area_lights, list) or len(raw_area_lights) > cls.MAX_AREA_LIGHTS:
            raise PathTracingError(f"area_lights deve conter até {cls.MAX_AREA_LIGHTS} elementos.")
        area_lights = tuple(AreaLightSpec.from_mapping(item) for item in raw_area_lights)
        raw_planes = value.get("planes", [])
        if not isinstance(raw_planes, list) or len(raw_planes) > cls.MAX_PLANES:
            raise PathTracingError(f"planes deve conter até {cls.MAX_PLANES} elementos.")
        planes = tuple(PlaneSpec.from_mapping(item) for item in raw_planes)
        raw_boxes = value.get("boxes", [])
        if not isinstance(raw_boxes, list) or len(raw_boxes) > cls.MAX_BOXES:
            raise PathTracingError(f"boxes deve conter até {cls.MAX_BOXES} elementos.")
        boxes = tuple(BoxSpec.from_mapping(item) for item in raw_boxes)
        raw_cylinders = value.get("cylinders", [])
        if not isinstance(raw_cylinders, list) or len(raw_cylinders) > cls.MAX_CYLINDERS:
            raise PathTracingError(f"cylinders deve conter até {cls.MAX_CYLINDERS} elementos.")
        cylinders = tuple(CylinderSpec.from_mapping(item) for item in raw_cylinders)
        raw_oriented_boxes = value.get("oriented_boxes", [])
        if not isinstance(raw_oriented_boxes, list) or len(raw_oriented_boxes) > cls.MAX_ORIENTED_BOXES:
            raise PathTracingError(f"oriented_boxes deve conter até {cls.MAX_ORIENTED_BOXES} elementos.")
        oriented_boxes = tuple(OrientedBoxSpec.from_mapping(item) for item in raw_oriented_boxes)
        raw_capsules = value.get("capsules", [])
        if not isinstance(raw_capsules, list) or len(raw_capsules) > cls.MAX_CAPSULES:
            raise PathTracingError(f"capsules deve conter até {cls.MAX_CAPSULES} elementos.")
        capsules = tuple(CapsuleSpec.from_mapping(item) for item in raw_capsules)
        raw_cones = value.get("cones", [])
        if not isinstance(raw_cones, list) or len(raw_cones) > cls.MAX_CONES:
            raise PathTracingError(f"cones deve conter até {cls.MAX_CONES} elementos.")
        cones = tuple(ConeSpec.from_mapping(item) for item in raw_cones)
        raw_disks = value.get("disks", [])
        if not isinstance(raw_disks, list) or len(raw_disks) > cls.MAX_DISKS:
            raise PathTracingError(f"disks deve conter até {cls.MAX_DISKS} elementos.")
        disks = tuple(DiskSpec.from_mapping(item) for item in raw_disks)
        raw_meshes = value.get("meshes", [])
        if not isinstance(raw_meshes, list) or len(raw_meshes) > cls.MAX_MESHES:
            raise PathTracingError(f"meshes deve conter até {cls.MAX_MESHES} elementos.")
        meshes = tuple(TriangleMeshSpec.from_mapping(item) for item in raw_meshes)
        mesh_triangle_count = sum(len(mesh.faces) for mesh in meshes)
        if mesh_triangle_count > cls.MAX_MESH_TRIANGLES:
            raise PathTracingError(
                f"Meshes excedem {cls.MAX_MESH_TRIANGLES} triângulos no total."
            )
        top = _vec(value.get("background_top", [0.42, 0.58, 0.82]),
                   "background_top", 0.0, 1.0)
        bottom = _vec(value.get("background_bottom", [0.055, 0.065, 0.09]),
                      "background_bottom", 0.0, 1.0)
        scene_id = value.get("scene_id", "legacy-sphere-scene")
        if not isinstance(scene_id, str) or not scene_id.strip() or len(scene_id) > 96:
            raise PathTracingError("scene_id inválido.")
        return cls(
            camera, spheres, triangles, lights, top, bottom, scene_id,
            area_lights, planes, boxes, cylinders, oriented_boxes, capsules, cones, disks, meshes
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "scene_id": self.scene_id,
            "camera": {
                "origin": list(self.camera.origin),
                "target": list(self.camera.target),
                "up": list(self.camera.up),
                "vertical_fov_degrees": self.camera.vertical_fov_degrees,
                "aperture": self.camera.aperture,
                "focus_distance": self.camera.focus_distance,
            },
            "spheres": [
                {
                    "center": list(item.center),
                    "radius": item.radius,
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
                    "metallic": item.metallic,
                    "roughness": item.roughness,
                    "texture_pattern": item.texture_pattern,
                    "texture_color_a": list(item.texture_color_a) if item.texture_color_a is not None else None,
                    "texture_color_b": list(item.texture_color_b) if item.texture_color_b is not None else None,
                    "texture_scale": item.texture_scale,
                    "texture_id": item.texture_id,
                }
                for item in self.spheres
            ],
            "triangles": [
                {
                    "a": list(item.a),
                    "b": list(item.b),
                    "c": list(item.c),
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
                    "metallic": item.metallic,
                    "roughness": item.roughness,
                    "uv_a": list(item.uv_a) if item.uv_a is not None else None,
                    "uv_b": list(item.uv_b) if item.uv_b is not None else None,
                    "uv_c": list(item.uv_c) if item.uv_c is not None else None,
                    "texture_pattern": item.texture_pattern,
                    "texture_color_a": list(item.texture_color_a) if item.texture_color_a is not None else None,
                    "texture_color_b": list(item.texture_color_b) if item.texture_color_b is not None else None,
                    "texture_scale": item.texture_scale,
                    "texture_id": item.texture_id,
                }
                for item in self.triangles
            ],
            "point_lights": [
                {"position": list(item.position), "intensity": list(item.intensity)}
                for item in self.point_lights
            ],
            "area_lights": [
                {
                    "center": list(item.center),
                    "edge_u": list(item.edge_u),
                    "edge_v": list(item.edge_v),
                    "intensity": list(item.intensity),
                }
                for item in self.area_lights
            ],
            "planes": [
                {
                    "point": list(item.point),
                    "normal": list(item.normal),
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
                    "metallic": item.metallic,
                    "roughness": item.roughness,
                    "texture_pattern": item.texture_pattern,
                    "texture_color_a": list(item.texture_color_a) if item.texture_color_a is not None else None,
                    "texture_color_b": list(item.texture_color_b) if item.texture_color_b is not None else None,
                    "texture_scale": item.texture_scale,
                    "texture_id": item.texture_id,
                }
                for item in self.planes
            ],
            "boxes": [
                {
                    "minimum": list(item.minimum),
                    "maximum": list(item.maximum),
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
                    "metallic": item.metallic,
                    "roughness": item.roughness,
                    "texture_pattern": item.texture_pattern,
                    "texture_color_a": list(item.texture_color_a) if item.texture_color_a is not None else None,
                    "texture_color_b": list(item.texture_color_b) if item.texture_color_b is not None else None,
                    "texture_scale": item.texture_scale,
                    "texture_id": item.texture_id,
                }
                for item in self.boxes
            ],
            "cylinders": [
                {
                    "start": list(item.start),
                    "end": list(item.end),
                    "radius": item.radius,
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
                    "metallic": item.metallic,
                    "roughness": item.roughness,
                    "texture_pattern": item.texture_pattern,
                    "texture_color_a": list(item.texture_color_a) if item.texture_color_a is not None else None,
                    "texture_color_b": list(item.texture_color_b) if item.texture_color_b is not None else None,
                    "texture_scale": item.texture_scale,
                    "texture_id": item.texture_id,
                }
                for item in self.cylinders
            ],
            "oriented_boxes": [
                {
                    "center": list(item.center),
                    "half_extents": list(item.half_extents),
                    "rotation": list(item.rotation),
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
                    "metallic": item.metallic,
                    "roughness": item.roughness,
                    "texture_pattern": item.texture_pattern,
                    "texture_color_a": list(item.texture_color_a) if item.texture_color_a is not None else None,
                    "texture_color_b": list(item.texture_color_b) if item.texture_color_b is not None else None,
                    "texture_scale": item.texture_scale,
                    "texture_id": item.texture_id,
                }
                for item in self.oriented_boxes
            ],
            "capsules": [
                {
                    "start": list(item.start),
                    "end": list(item.end),
                    "radius": item.radius,
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
                    "metallic": item.metallic,
                    "roughness": item.roughness,
                    "texture_pattern": item.texture_pattern,
                    "texture_color_a": list(item.texture_color_a) if item.texture_color_a is not None else None,
                    "texture_color_b": list(item.texture_color_b) if item.texture_color_b is not None else None,
                    "texture_scale": item.texture_scale,
                    "texture_id": item.texture_id,
                }
                for item in self.capsules
            ],
            "cones": [
                {
                    "apex": list(item.apex),
                    "base_center": list(item.base_center),
                    "base_radius": item.base_radius,
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
                    "metallic": item.metallic,
                    "roughness": item.roughness,
                    "texture_pattern": item.texture_pattern,
                    "texture_color_a": list(item.texture_color_a) if item.texture_color_a is not None else None,
                    "texture_color_b": list(item.texture_color_b) if item.texture_color_b is not None else None,
                    "texture_scale": item.texture_scale,
                    "texture_id": item.texture_id,
                }
                for item in self.cones
            ],
            "disks": [
                {
                    "center": list(item.center),
                    "normal": list(item.normal),
                    "radius": item.radius,
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
                    "metallic": item.metallic,
                    "roughness": item.roughness,
                    "texture_pattern": item.texture_pattern,
                    "texture_color_a": list(item.texture_color_a) if item.texture_color_a is not None else None,
                    "texture_color_b": list(item.texture_color_b) if item.texture_color_b is not None else None,
                    "texture_scale": item.texture_scale,
                    "texture_id": item.texture_id,
                }
                for item in self.disks
            ],
            "meshes": [
                {
                    "vertices": [list(vertex) for vertex in item.vertices],
                    "faces": [list(face) for face in item.faces],
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
                    "metallic": item.metallic,
                    "roughness": item.roughness,
                    "materials": [
                        {
                            "albedo": list(material.albedo),
                            "emission": list(material.emission),
                            "metallic": material.metallic,
                            "roughness": material.roughness,
                            "texture_pattern": material.texture_pattern,
                            "texture_color_a": list(material.texture_color_a) if material.texture_color_a is not None else None,
                            "texture_color_b": list(material.texture_color_b) if material.texture_color_b is not None else None,
                            "texture_scale": material.texture_scale,
                            "texture_id": material.texture_id,
                        }
                        for material in item.materials
                    ],
                    "face_material_indices": list(item.face_material_indices),
                    "uvs": [list(uv) for uv in item.uvs],
                }
                for item in self.meshes
            ],
            "background_top": list(self.background_top),
            "background_bottom": list(self.background_bottom),
        }

    def sha256(self) -> str:
        canonical = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def default(cls) -> "SceneSpec":
        return cls(
            CameraSpec((0.0, 1.0, 4.2), (0.0, 0.1, 0.0)),
            (
                SphereSpec((0.0, -1000.75, 0.0), 1000.0, (0.72, 0.72, 0.72)),
                SphereSpec((0.0, 0.05, 0.0), 0.75, (0.78, 0.22, 0.12)),
                SphereSpec((1.25, -0.12, -0.25), 0.62, (0.12, 0.42, 0.78)),
                SphereSpec((-1.25, 1.8, 0.2), 0.48, (0.0, 0.0, 0.0), (5.0, 4.5, 3.8)),
            ),
        )

class CPUPathTracerBackend:
    """Deterministic, bounded, single-threaded sphere/triangle path tracer."""
    VERSION = "2.4.0"
    BACKEND_ID = "cpu.pathtracer"
    MAX_DIMENSION = 128
    MAX_PIXELS = 16_384
    MAX_SAMPLES_PER_PIXEL = 8
    MAX_DEPTH = 4
    MAX_SPHERES = SceneSpec.MAX_SPHERES
    MAX_TRIANGLES = SceneSpec.MAX_TRIANGLES
    MAX_POINT_LIGHTS = SceneSpec.MAX_POINT_LIGHTS
    MAX_AREA_LIGHTS = SceneSpec.MAX_AREA_LIGHTS
    MAX_PLANES = SceneSpec.MAX_PLANES
    MAX_BOXES = SceneSpec.MAX_BOXES
    MAX_CYLINDERS = SceneSpec.MAX_CYLINDERS
    MAX_ORIENTED_BOXES = SceneSpec.MAX_ORIENTED_BOXES
    MAX_CAPSULES = SceneSpec.MAX_CAPSULES
    MAX_CONES = SceneSpec.MAX_CONES
    MAX_DISKS = SceneSpec.MAX_DISKS
    AREA_LIGHT_SAMPLES = 2
    MAX_INTERSECTION_BUDGET = 4_194_304
    RAY_EPSILON = 1e-4

    @classmethod
    def _hit_sphere(cls, origin: Vector3, direction: Vector3,
                    sphere: SphereSpec, max_distance: float = math.inf):
        offset = _sub(origin, sphere.center)
        a = _dot(direction, direction)
        half_b = _dot(offset, direction)
        c = _dot(offset, offset) - sphere.radius * sphere.radius
        discriminant = half_b * half_b - a * c
        if discriminant < 0.0:
            return None
        root = math.sqrt(discriminant)
        distance = (-half_b - root) / a
        if distance <= cls.RAY_EPSILON:
            distance = (-half_b + root) / a
        if distance <= cls.RAY_EPSILON or distance >= max_distance:
            return None
        point = _add(origin, _scale(direction, distance))
        normal = _norm(_scale(_sub(point, sphere.center), 1.0 / sphere.radius), "sphere normal")
        if _dot(direction, normal) > 0.0:
            normal = _scale(normal, -1.0)
        unit_normal = _scale(_sub(point, sphere.center), 1.0 / sphere.radius)
        uv = (
            0.5 + math.atan2(unit_normal[2], unit_normal[0]) / math.tau,
            math.acos(max(-1.0, min(1.0, unit_normal[1]))) / math.pi,
        )
        return distance, point, normal, sphere, None, None, uv

    @classmethod
    def _hit_triangle(cls, origin: Vector3, direction: Vector3,
                      triangle: TriangleSpec, max_distance: float = math.inf):
        edge1, edge2 = _sub(triangle.b, triangle.a), _sub(triangle.c, triangle.a)
        pvec = _cross(direction, edge2)
        determinant = _dot(edge1, pvec)
        if abs(determinant) < 1e-10:
            return None
        inverse = 1.0 / determinant
        tvec = _sub(origin, triangle.a)
        u = _dot(tvec, pvec) * inverse
        if u < 0.0 or u > 1.0:
            return None
        qvec = _cross(tvec, edge1)
        v = _dot(direction, qvec) * inverse
        if v < 0.0 or u + v > 1.0:
            return None
        distance = _dot(edge2, qvec) * inverse
        if distance <= cls.RAY_EPSILON or distance >= max_distance:
            return None
        normal = _norm(_cross(edge1, edge2), "triangle normal")
        if _dot(direction, normal) > 0.0:
            normal = _scale(normal, -1.0)
        point = _add(origin, _scale(direction, distance))
        interpolated_uv = None
        if triangle.uv_a is not None:
            weight_a = 1.0 - u - v
            interpolated_uv = (
                weight_a * triangle.uv_a[0]
                + u * triangle.uv_b[0]
                + v * triangle.uv_c[0],
                weight_a * triangle.uv_a[1]
                + u * triangle.uv_b[1]
                + v * triangle.uv_c[1],
            )
        return distance, point, normal, triangle, u, v, interpolated_uv

    @classmethod
    def _hit_oriented_box(
        cls,
        origin: Vector3,
        direction: Vector3,
        box: OrientedBoxSpec,
        max_distance: float = math.inf,
    ):
        w, x, y, z = box.rotation
        inverse_rotation = (w, -x, -y, -z)
        local_origin = _quat_rotate(
            inverse_rotation, _sub(origin, box.center)
        )
        local_direction = _quat_rotate(inverse_rotation, direction)
        near_distance = -math.inf
        far_distance = math.inf
        near_normal: Vector3 = (0.0, 0.0, 0.0)
        far_normal: Vector3 = (0.0, 0.0, 0.0)

        for axis in range(3):
            component = local_direction[axis]
            extent = box.half_extents[axis]
            coordinate = local_origin[axis]
            if abs(component) < 1e-12:
                if coordinate < -extent or coordinate > extent:
                    return None
                continue
            first = (-extent - coordinate) / component
            second = (extent - coordinate) / component
            first_normal = [0.0, 0.0, 0.0]
            second_normal = [0.0, 0.0, 0.0]
            first_normal[axis] = -1.0
            second_normal[axis] = 1.0
            if first > second:
                first, second = second, first
                first_normal, second_normal = second_normal, first_normal
            if first > near_distance:
                near_distance = first
                near_normal = tuple(first_normal)
            if second < far_distance:
                far_distance = second
                far_normal = tuple(second_normal)
            if near_distance > far_distance:
                return None

        if far_distance <= cls.RAY_EPSILON:
            return None
        if near_distance > cls.RAY_EPSILON:
            distance, local_normal = near_distance, near_normal
        else:
            distance, local_normal = far_distance, far_normal
        if distance >= max_distance:
            return None
        normal = _norm(
            _quat_rotate(box.rotation, local_normal),
            "oriented box world normal",
        )
        local_point = _add(local_origin, _scale(local_direction, distance))
        local_minimum = _scale(box.half_extents, -1.0)
        local_maximum = box.half_extents
        uv = _box_face_uv(
            local_point, local_normal, local_minimum, local_maximum
        )
        if _dot(direction, normal) > 0.0:
            normal = _scale(normal, -1.0)
        point = _add(origin, _scale(direction, distance))
        return distance, point, normal, box, None, None, uv

    @classmethod
    def _hit_disk(
        cls,
        origin: Vector3,
        direction: Vector3,
        disk: DiskSpec,
        max_distance: float = math.inf,
    ):
        denominator = _dot(direction, disk.normal)
        if abs(denominator) < 1e-10:
            return None
        distance = _dot(_sub(disk.center, origin), disk.normal) / denominator
        if distance <= cls.RAY_EPSILON or distance >= max_distance:
            return None
        point = _add(origin, _scale(direction, distance))
        radial = _sub(point, disk.center)
        radial = _sub(radial, _scale(disk.normal, _dot(radial, disk.normal)))
        if _dot(radial, radial) > disk.radius * disk.radius:
            return None
        tangent, bitangent = _plane_basis(disk.normal)
        uv = (
            0.5 + _dot(radial, tangent) / (2.0 * disk.radius),
            0.5 + _dot(radial, bitangent) / (2.0 * disk.radius),
        )
        normal = disk.normal
        if _dot(direction, normal) > 0.0:
            normal = _scale(normal, -1.0)
        return distance, point, normal, disk, None, None, uv

    @classmethod
    def _hit_cone(
        cls,
        origin: Vector3,
        direction: Vector3,
        cone: ConeSpec,
        max_distance: float = math.inf,
    ):
        axis_vector = _sub(cone.apex, cone.base_center)
        height = math.sqrt(_dot(axis_vector, axis_vector))
        axis = _scale(axis_vector, 1.0 / height)
        helper = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0)
        tangent = _norm(_cross(axis, helper), "cone UV tangent")
        bitangent = _cross(axis, tangent)
        offset = _sub(origin, cone.base_center)
        direction_axis = _dot(direction, axis)
        offset_axis = _dot(offset, axis)
        direction_perp = _sub(direction, _scale(axis, direction_axis))
        offset_perp = _sub(offset, _scale(axis, offset_axis))
        slope = cone.base_radius / height
        slope_squared = slope * slope
        a = _dot(direction_perp, direction_perp) - slope_squared * direction_axis ** 2
        b = (
            2.0 * _dot(offset_perp, direction_perp)
            + 2.0 * slope_squared * (height - offset_axis) * direction_axis
        )
        c = (
            _dot(offset_perp, offset_perp)
            - slope_squared * (height - offset_axis) ** 2
        )
        candidates = []

        if abs(a) > 1e-14:
            discriminant = b * b - 4.0 * a * c
            if discriminant >= 0.0:
                root = math.sqrt(max(0.0, discriminant))
                side_distances = (
                    (-b - root) / (2.0 * a),
                    (-b + root) / (2.0 * a),
                )
            else:
                side_distances = ()
        elif abs(b) > 1e-14:
            side_distances = (-c / b,)
        else:
            side_distances = ()

        for distance in sorted(side_distances):
            if distance <= cls.RAY_EPSILON or distance >= max_distance:
                continue
            axial = offset_axis + distance * direction_axis
            if 0.0 <= axial <= height:
                point = _add(origin, _scale(direction, distance))
                axis_point = _add(cone.base_center, _scale(axis, axial))
                radial = _sub(point, axis_point)
                normal_vector = _add(
                    radial,
                    _scale(axis, slope_squared * (height - axial)),
                )
                if _dot(normal_vector, normal_vector) <= 1e-20:
                    normal_vector = axis
                normal = _norm(normal_vector, "cone side normal")
                angle = math.atan2(
                    _dot(radial, bitangent), _dot(radial, tangent)
                )
                uv = (0.5 + angle / math.tau, axial / height)
                candidates.append((distance, point, normal, cone, uv))

        if abs(direction_axis) > 1e-12:
            distance = -offset_axis / direction_axis
            if cls.RAY_EPSILON < distance < max_distance:
                point = _add(origin, _scale(direction, distance))
                radial = _sub(point, cone.base_center)
                radial = _sub(radial, _scale(axis, _dot(radial, axis)))
                if _dot(radial, radial) <= cone.base_radius ** 2 + 1e-10:
                    uv = (
                        0.5 + _dot(radial, tangent) / (2.0 * cone.base_radius),
                        0.5 + _dot(radial, bitangent) / (2.0 * cone.base_radius),
                    )
                    candidates.append((distance, point, _scale(axis, -1.0), cone, uv))

        if not candidates:
            return None
        distance, point, normal, material, uv = min(
            candidates, key=lambda item: item[0]
        )
        if _dot(direction, normal) > 0.0:
            normal = _scale(normal, -1.0)
        return distance, point, normal, material, None, None, uv

    @classmethod
    def _hit_capsule(
        cls,
        origin: Vector3,
        direction: Vector3,
        capsule: CapsuleSpec,
        max_distance: float = math.inf,
    ):
        axis_vector = _sub(capsule.end, capsule.start)
        axis_length = math.sqrt(_dot(axis_vector, axis_vector))
        axis = _scale(axis_vector, 1.0 / axis_length)
        helper = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0)
        tangent = _norm(_cross(axis, helper), "capsule UV tangent")
        bitangent = _cross(axis, tangent)
        offset = _sub(origin, capsule.start)
        direction_axis = _dot(direction, axis)
        offset_axis = _dot(offset, axis)
        direction_perp = _sub(direction, _scale(axis, direction_axis))
        offset_perp = _sub(offset, _scale(axis, offset_axis))
        a = _dot(direction_perp, direction_perp)
        b = 2.0 * _dot(direction_perp, offset_perp)
        c = _dot(offset_perp, offset_perp) - capsule.radius * capsule.radius
        candidates = []

        if a > 1e-14:
            discriminant = b * b - 4.0 * a * c
            if discriminant >= 0.0:
                root = math.sqrt(max(0.0, discriminant))
                for distance in sorted((
                    (-b - root) / (2.0 * a),
                    (-b + root) / (2.0 * a),
                )):
                    if distance <= cls.RAY_EPSILON or distance >= max_distance:
                        continue
                    axial = offset_axis + distance * direction_axis
                    if 0.0 <= axial <= axis_length:
                        point = _add(origin, _scale(direction, distance))
                        axis_point = _add(capsule.start, _scale(axis, axial))
                        radial = _sub(point, axis_point)
                        normal = _norm(radial, "capsule side normal")
                        angle = math.atan2(
                            _dot(radial, bitangent), _dot(radial, tangent)
                        )
                        uv = (
                            0.5 + angle / math.tau,
                            (axial + capsule.radius) / (axis_length + 2.0 * capsule.radius),
                        )
                        candidates.append((distance, point, normal, capsule, uv))

        for cap_center, is_start in (
            (capsule.start, True), (capsule.end, False)
        ):
            sphere_offset = _sub(origin, cap_center)
            sphere_b = 2.0 * _dot(direction, sphere_offset)
            sphere_c = _dot(sphere_offset, sphere_offset) - capsule.radius ** 2
            discriminant = sphere_b * sphere_b - 4.0 * sphere_c
            if discriminant < 0.0:
                continue
            root = math.sqrt(max(0.0, discriminant))
            for distance in sorted((
                (-sphere_b - root) * 0.5,
                (-sphere_b + root) * 0.5,
            )):
                if distance <= cls.RAY_EPSILON or distance >= max_distance:
                    continue
                point = _add(origin, _scale(direction, distance))
                relative = _sub(point, capsule.start)
                axial = _dot(relative, axis)
                if (is_start and axial <= 1e-9) or (
                    not is_start and axial >= axis_length - 1e-9
                ):
                    radial = _sub(relative, _scale(axis, axial))
                    normal = _norm(_sub(point, cap_center), "capsule cap normal")
                    angle = math.atan2(
                        _dot(radial, bitangent), _dot(radial, tangent)
                    )
                    uv = (
                        0.5 + angle / math.tau,
                        (axial + capsule.radius) / (axis_length + 2.0 * capsule.radius),
                    )
                    candidates.append((distance, point, normal, capsule, uv))

        if not candidates:
            return None
        distance, point, normal, material, uv = min(
            candidates, key=lambda item: item[0]
        )
        if _dot(direction, normal) > 0.0:
            normal = _scale(normal, -1.0)
        return distance, point, normal, material, None, None, uv

    @classmethod
    def _hit_cylinder(
        cls,
        origin: Vector3,
        direction: Vector3,
        cylinder: CylinderSpec,
        max_distance: float = math.inf,
    ):
        axis_vector = _sub(cylinder.end, cylinder.start)
        axis_length = math.sqrt(_dot(axis_vector, axis_vector))
        axis = _scale(axis_vector, 1.0 / axis_length)
        helper = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0)
        tangent = _norm(_cross(axis, helper), "cylinder UV tangent")
        bitangent = _cross(axis, tangent)
        offset = _sub(origin, cylinder.start)
        direction_axis = _dot(direction, axis)
        offset_axis = _dot(offset, axis)
        direction_perp = _sub(direction, _scale(axis, direction_axis))
        offset_perp = _sub(offset, _scale(axis, offset_axis))
        a = _dot(direction_perp, direction_perp)
        b = 2.0 * _dot(direction_perp, offset_perp)
        c = _dot(offset_perp, offset_perp) - cylinder.radius * cylinder.radius
        candidates = []

        if a > 1e-14:
            discriminant = b * b - 4.0 * a * c
            if discriminant >= 0.0:
                root = math.sqrt(max(0.0, discriminant))
                for distance in sorted((
                    (-b - root) / (2.0 * a),
                    (-b + root) / (2.0 * a),
                )):
                    if distance <= cls.RAY_EPSILON or distance >= max_distance:
                        continue
                    axial = offset_axis + distance * direction_axis
                    if 0.0 <= axial <= axis_length:
                        point = _add(origin, _scale(direction, distance))
                        axis_point = _add(cylinder.start, _scale(axis, axial))
                        radial = _sub(point, axis_point)
                        normal = _norm(radial, "cylinder side normal")
                        angle = math.atan2(
                            _dot(radial, bitangent), _dot(radial, tangent)
                        )
                        uv = (0.5 + angle / math.tau, axial / axis_length)
                        candidates.append((distance, point, normal, cylinder, uv))

        if abs(direction_axis) > 1e-12:
            for cap_center, cap_normal in (
                (cylinder.start, _scale(axis, -1.0)),
                (cylinder.end, axis),
            ):
                distance = _dot(_sub(cap_center, origin), cap_normal) / _dot(
                    direction, cap_normal
                )
                if distance <= cls.RAY_EPSILON or distance >= max_distance:
                    continue
                point = _add(origin, _scale(direction, distance))
                radial = _sub(point, cap_center)
                radial = _sub(radial, _scale(axis, _dot(radial, axis)))
                if _dot(radial, radial) <= cylinder.radius * cylinder.radius + 1e-10:
                    uv = (
                        0.5 + _dot(radial, tangent) / (2.0 * cylinder.radius),
                        0.5 + _dot(radial, bitangent) / (2.0 * cylinder.radius),
                    )
                    candidates.append((distance, point, cap_normal, cylinder, uv))

        if not candidates:
            return None
        distance, point, normal, material, uv = min(
            candidates, key=lambda item: item[0]
        )
        if _dot(direction, normal) > 0.0:
            normal = _scale(normal, -1.0)
        return distance, point, normal, material, None, None, uv

    @classmethod
    def _hit_box(
        cls,
        origin: Vector3,
        direction: Vector3,
        box: BoxSpec,
        max_distance: float = math.inf,
    ):
        near_distance = -math.inf
        far_distance = math.inf
        near_normal: Vector3 = (0.0, 0.0, 0.0)
        far_normal: Vector3 = (0.0, 0.0, 0.0)

        for axis in range(3):
            component = direction[axis]
            if abs(component) < 1e-12:
                if (
                    origin[axis] < box.minimum[axis]
                    or origin[axis] > box.maximum[axis]
                ):
                    return None
                continue

            inverse = 1.0 / component
            first = (box.minimum[axis] - origin[axis]) * inverse
            second = (box.maximum[axis] - origin[axis]) * inverse
            first_normal = [0.0, 0.0, 0.0]
            second_normal = [0.0, 0.0, 0.0]
            first_normal[axis] = -1.0
            second_normal[axis] = 1.0
            if first > second:
                first, second = second, first
                first_normal, second_normal = second_normal, first_normal

            if first > near_distance:
                near_distance = first
                near_normal = tuple(first_normal)
            if second < far_distance:
                far_distance = second
                far_normal = tuple(second_normal)
            if near_distance > far_distance:
                return None

        if far_distance <= cls.RAY_EPSILON:
            return None
        if near_distance > cls.RAY_EPSILON:
            distance, normal = near_distance, near_normal
        else:
            distance, normal = far_distance, far_normal
        if distance >= max_distance:
            return None
        point = _add(origin, _scale(direction, distance))
        uv = _box_face_uv(point, normal, box.minimum, box.maximum)
        if _dot(direction, normal) > 0.0:
            normal = _scale(normal, -1.0)
        return distance, point, normal, box, None, None, uv

    @classmethod
    def _hit_plane(
        cls,
        origin: Vector3,
        direction: Vector3,
        plane: PlaneSpec,
        max_distance: float = math.inf,
    ):
        denominator = _dot(direction, plane.normal)
        if abs(denominator) < 1e-10:
            return None
        distance = _dot(_sub(plane.point, origin), plane.normal) / denominator
        if distance <= cls.RAY_EPSILON or distance >= max_distance:
            return None
        normal = plane.normal
        point = _add(origin, _scale(direction, distance))
        tangent, bitangent = _plane_basis(plane.normal)
        relative = _sub(point, plane.point)
        uv = (_dot(relative, tangent), _dot(relative, bitangent))
        if _dot(direction, normal) > 0.0:
            normal = _scale(normal, -1.0)
        return distance, point, normal, plane, None, None, uv

    @classmethod
    def _closest_hit(cls, origin: Vector3, direction: Vector3,
                     scene: SceneSpec, max_distance: float = math.inf):
        closest, closest_distance = None, max_distance
        for shape in scene.spheres:
            hit = cls._hit_sphere(origin, direction, shape, closest_distance)
            if hit is not None:
                closest, closest_distance = hit, hit[0]
        for shape in scene.triangles:
            hit = cls._hit_triangle(origin, direction, shape, closest_distance)
            if hit is not None:
                closest, closest_distance = hit, hit[0]
        for mesh in scene.meshes:
            stack = [mesh._bvh]
            while stack:
                node = stack.pop()
                if _ray_bounds_entry(
                    origin, direction, node.minimum, node.maximum, closest_distance
                ) is None:
                    continue
                if node.face_indices:
                    for face_index in node.face_indices:
                        shape = mesh._triangles[face_index]
                        hit = cls._hit_triangle(
                            origin, direction, shape, closest_distance
                        )
                        if hit is not None:
                            closest, closest_distance = hit, hit[0]
                else:
                    children = []
                    for child in (node.left, node.right):
                        if child is None:
                            continue
                        entry = _ray_bounds_entry(
                            origin, direction, child.minimum, child.maximum,
                            closest_distance,
                        )
                        if entry is not None:
                            children.append((entry, child))
                    children.sort(key=lambda item: item[0], reverse=True)
                    stack.extend(child for _entry, child in children)
        for shape in scene.planes:
            hit = cls._hit_plane(origin, direction, shape, closest_distance)
            if hit is not None:
                closest, closest_distance = hit, hit[0]
        for shape in scene.boxes:
            hit = cls._hit_box(origin, direction, shape, closest_distance)
            if hit is not None:
                closest, closest_distance = hit, hit[0]
        for shape in scene.cylinders:
            hit = cls._hit_cylinder(origin, direction, shape, closest_distance)
            if hit is not None:
                closest, closest_distance = hit, hit[0]
        for shape in scene.oriented_boxes:
            hit = cls._hit_oriented_box(origin, direction, shape, closest_distance)
            if hit is not None:
                closest, closest_distance = hit, hit[0]
        for shape in scene.capsules:
            hit = cls._hit_capsule(origin, direction, shape, closest_distance)
            if hit is not None:
                closest, closest_distance = hit, hit[0]
        for shape in scene.cones:
            hit = cls._hit_cone(origin, direction, shape, closest_distance)
            if hit is not None:
                closest, closest_distance = hit, hit[0]
        for shape in scene.disks:
            hit = cls._hit_disk(origin, direction, shape, closest_distance)
            if hit is not None:
                closest, closest_distance = hit, hit[0]
        return closest



    @staticmethod
    def _cosine_direction(normal: Vector3, rng: random.Random) -> Vector3:
        first, second = rng.random(), rng.random()
        radius, angle = math.sqrt(first), math.tau * second
        local_x, local_y = radius * math.cos(angle), radius * math.sin(angle)
        local_z = math.sqrt(max(0.0, 1.0 - first))
        helper = (0.0, 1.0, 0.0) if abs(normal[1]) < 0.999 else (1.0, 0.0, 0.0)
        tangent = _norm(_cross(helper, normal), "tangent")
        bitangent = _cross(normal, tangent)
        return _norm(_add(_add(_scale(tangent, local_x), _scale(bitangent, local_y)),
                          _scale(normal, local_z)), "sampled direction")

    @staticmethod
    def _environment(direction: Vector3, scene: SceneSpec) -> Vector3:
        amount = max(0.0, min(1.0, 0.5 * (direction[1] + 1.0)))
        return tuple(
            scene.background_bottom[i] * (1.0 - amount)
            + scene.background_top[i] * amount for i in range(3)
        )  # type: ignore[return-value]

    @classmethod
    def _validate_texture_buffers(
        cls,
        scene: SceneSpec,
        textures: dict[str, TextureBuffer] | None,
    ) -> dict[str, TextureBuffer]:
        if textures is None:
            resolved_textures: dict[str, TextureBuffer] = {}
        elif not isinstance(textures, dict) or len(textures) > 8:
            raise PathTracingError("Forneça no máximo oito buffers de textura.")
        else:
            resolved_textures = dict(textures)
        total_bytes = 0
        for texture_id, texture in resolved_textures.items():
            validated_id = _texture_ref(texture_id, "texture_id")
            if validated_id is None or validated_id != texture_id:
                raise PathTracingError("Identificador de textura inválido.")
            if not isinstance(texture, TextureBuffer):
                raise PathTracingError("Cada textura deve ser TextureBuffer validado.")
            total_bytes += len(texture.pixels)
        if total_bytes > 16 * 1024 * 1024:
            raise PathTracingError("Buffers de textura excedem 16 MiB no total.")

        surface_materials = [
            *scene.spheres, *scene.triangles, *scene.planes, *scene.disks,
            *scene.boxes, *scene.oriented_boxes, *scene.cylinders,
            *scene.capsules, *scene.cones,
        ]
        for mesh in scene.meshes:
            surface_materials.extend(mesh._triangles)
        for material in surface_materials:
            if material.texture_pattern != "image":
                continue
            if isinstance(material, TriangleSpec) and material.uv_a is None:
                raise PathTracingError("Textura de imagem em triângulo exige UVs nos três vértices.")
            if material.texture_id not in resolved_textures:
                raise PathTracingError(
                    f"Buffer de textura ausente: {material.texture_id}."
                )
        return resolved_textures

    @staticmethod
    def _sample_surface_albedo(
        material: Any,
        uv: UV2 | None,
        textures: dict[str, TextureBuffer] | None = None,
    ) -> Vector3:
        if material.texture_pattern == "checker" and uv is not None:
            cell_u = math.floor(uv[0] * material.texture_scale)
            cell_v = math.floor(uv[1] * material.texture_scale)
            return (
                material.texture_color_a
                if (cell_u + cell_v) % 2 == 0
                else material.texture_color_b
            )
        if material.texture_pattern == "image":
            if uv is None or textures is None or material.texture_id not in textures:
                raise PathTracingError("Textura de imagem sem UV ou buffer resolvido.")
            texture = textures[material.texture_id]
            u = (uv[0] % 1.0) * texture.width - 0.5
            v = (uv[1] % 1.0) * texture.height - 0.5
            x0_raw, y0_raw = math.floor(u), math.floor(v)
            tx, ty = u - x0_raw, v - y0_raw
            x0, x1 = x0_raw % texture.width, (x0_raw + 1) % texture.width
            y0, y1 = y0_raw % texture.height, (y0_raw + 1) % texture.height

            def texel(x: int, y: int, channel: int) -> float:
                pixel_offset = (y * texture.width + x) * texture.channels
                value = texture.pixels[pixel_offset + channel] / 255.0
                if channel < 3:
                    if texture.color_space == "srgb":
                        value = (
                            value / 12.92
                            if value <= 0.04045
                            else ((value + 0.055) / 1.055) ** 2.4
                        )
                    if texture.channels == 4:
                        alpha = texture.pixels[pixel_offset + 3] / 255.0
                        value *= alpha
                return value

            sampled_channels = []
            for channel in range(texture.channels):
                top = (
                    texel(x0, y0, channel) * (1.0 - tx)
                    + texel(x1, y0, channel) * tx
                )
                bottom = (
                    texel(x0, y1, channel) * (1.0 - tx)
                    + texel(x1, y1, channel) * tx
                )
                sampled_channels.append(top * (1.0 - ty) + bottom * ty)
            if texture.channels == 4:
                alpha = sampled_channels[3]
                return tuple(
                    sampled_channels[channel]
                    + material.albedo[channel] * (1.0 - alpha)
                    for channel in range(3)
                )  # type: ignore[return-value]
            return tuple(sampled_channels)  # type: ignore[return-value]
        return material.albedo

    @classmethod
    def _direct_lighting(
        cls,
        point: Vector3,
        normal: Vector3,
        albedo: Vector3,
        metallic: float,
        roughness: float,
        view_direction: Vector3,
        scene: SceneSpec,
        rng: random.Random,
    ) -> Vector3:
        result: Vector3 = (0.0, 0.0, 0.0)

        def evaluate_sample(
            light_position: Vector3,
            intensity: Vector3,
            light_factor: float,
        ) -> Vector3:
            displacement = _sub(light_position, point)
            distance_squared = _dot(displacement, displacement)
            if distance_squared <= 1e-10 or light_factor <= 0.0:
                return (0.0, 0.0, 0.0)
            distance = math.sqrt(distance_squared)
            direction = _scale(displacement, 1.0 / distance)
            cosine = max(0.0, _dot(normal, direction))
            if cosine <= 0.0:
                return (0.0, 0.0, 0.0)
            shadow_origin = _add(point, _scale(normal, cls.RAY_EPSILON * 2.0))
            if cls._closest_hit(
                shadow_origin, direction, scene, distance - cls.RAY_EPSILON
            ) is not None:
                return (0.0, 0.0, 0.0)

            diffuse_factor = (1.0 - metallic) * cosine * light_factor / (
                math.pi * distance_squared
            )
            diffuse = _mul(albedo, _scale(intensity, diffuse_factor))
            halfway_sum = _add(direction, view_direction)
            halfway_length_squared = _dot(halfway_sum, halfway_sum)
            specular: Vector3 = (0.0, 0.0, 0.0)
            if metallic > 0.0 and halfway_length_squared > 1e-12:
                halfway = _norm(halfway_sum, "light halfway vector")
                normal_halfway = max(0.0, _dot(normal, halfway))
                exponent = max(2.0, 2.0 / (roughness * roughness) - 2.0)
                normalization = (exponent + 2.0) / (2.0 * math.pi)
                specular_factor = (
                    metallic
                    * normalization
                    * (normal_halfway ** exponent)
                    * cosine
                    * light_factor
                    / distance_squared
                )
                specular = _mul(albedo, _scale(intensity, specular_factor))
            return _add(diffuse, specular)

        for light in scene.point_lights:
            result = _add(
                result,
                evaluate_sample(light.position, light.intensity, 1.0),
            )

        for light in scene.area_lights:
            cross = _cross(light.edge_u, light.edge_v)
            area = math.sqrt(_dot(cross, cross))
            light_normal = _scale(cross, 1.0 / area)
            for _sample in range(cls.AREA_LIGHT_SAMPLES):
                sample_position = _add(
                    light.center,
                    _add(
                        _scale(light.edge_u, rng.random() - 0.5),
                        _scale(light.edge_v, rng.random() - 0.5),
                    ),
                )
                displacement = _sub(sample_position, point)
                distance_squared = _dot(displacement, displacement)
                if distance_squared <= 1e-10:
                    continue
                direction = _scale(displacement, 1.0 / math.sqrt(distance_squared))
                cosine_light = max(0.0, _dot(light_normal, _scale(direction, -1.0)))
                if cosine_light <= 0.0:
                    continue
                light_factor = (
                    area * cosine_light / cls.AREA_LIGHT_SAMPLES
                )
                result = _add(
                    result,
                    evaluate_sample(sample_position, light.intensity, light_factor),
                )
        return result



    @classmethod
    def render_rgb(cls, width: int, height: int, *,
                   scene: SceneSpec | dict[str, Any] | None = None,
                   seed: int = 0, samples_per_pixel: int = 1,
                   max_depth: int = 3,
                   textures: dict[str, TextureBuffer] | None = None,
                   cancellation_token: CancellationToken | None = None) -> bytes:
        if cancellation_token is not None and not isinstance(cancellation_token, CancellationToken):
            raise PathTracingError("cancellation_token deve ser um CancellationToken.")
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        for name, value in (("width", width), ("height", height), ("seed", seed),
                            ("samples_per_pixel", samples_per_pixel), ("max_depth", max_depth)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise PathTracingError(f"{name} deve ser inteiro.")
        if not 1 <= width <= cls.MAX_DIMENSION or not 1 <= height <= cls.MAX_DIMENSION:
            raise PathTracingError("Dimensões fora do limite do protótipo.")
        pixel_count = width * height
        if pixel_count > cls.MAX_PIXELS:
            raise PathTracingError("Imagem excede o orçamento de pixels.")
        if not -(2**63) <= seed < 2**63:
            raise PathTracingError("seed fora do intervalo signed 64-bit.")
        if not 1 <= samples_per_pixel <= cls.MAX_SAMPLES_PER_PIXEL:
            raise PathTracingError("samples_per_pixel fora do limite.")
        if not 1 <= max_depth <= cls.MAX_DEPTH:
            raise PathTracingError("max_depth fora do limite.")
        resolved = SceneSpec.default() if scene is None else (
            scene if isinstance(scene, SceneSpec) else SceneSpec.from_mapping(scene)
        )
        texture_buffers = cls._validate_texture_buffers(resolved, textures)
        geometry_count = max(
            1,
            len(resolved.spheres) + len(resolved.triangles)
            + len(resolved.planes) + len(resolved.boxes)
            + len(resolved.cylinders) + len(resolved.oriented_boxes)
            + len(resolved.capsules) + len(resolved.cones)
            + len(resolved.disks)
            + sum(len(mesh.faces) for mesh in resolved.meshes),
        )
        light_work = (
            1 + len(resolved.point_lights)
            + len(resolved.area_lights) * cls.AREA_LIGHT_SAMPLES
        )
        work = (
            pixel_count * samples_per_pixel * max_depth
            * geometry_count * light_work
        )
        if (len(resolved.spheres) > cls.MAX_SPHERES
                or len(resolved.triangles) > cls.MAX_TRIANGLES
                or len(resolved.point_lights) > cls.MAX_POINT_LIGHTS
                or len(resolved.area_lights) > cls.MAX_AREA_LIGHTS
                or len(resolved.planes) > cls.MAX_PLANES
                or len(resolved.boxes) > cls.MAX_BOXES
                or len(resolved.cylinders) > cls.MAX_CYLINDERS
                or len(resolved.oriented_boxes) > cls.MAX_ORIENTED_BOXES
                or len(resolved.capsules) > cls.MAX_CAPSULES
                or len(resolved.cones) > cls.MAX_CONES
                or len(resolved.disks) > cls.MAX_DISKS
                or len(resolved.meshes) > SceneSpec.MAX_MESHES
                or sum(len(mesh.faces) for mesh in resolved.meshes) > SceneSpec.MAX_MESH_TRIANGLES
                or work > cls.MAX_INTERSECTION_BUDGET):
            raise PathTracingError("Cena excede os limites ou orçamento de interseções.")

        camera = resolved.camera
        forward = _norm(_sub(camera.target, camera.origin), "camera forward")
        right = _norm(_cross(forward, camera.up), "camera right")
        camera_up = _norm(_cross(right, forward), "camera up")
        half_height = math.tan(math.radians(camera.vertical_fov_degrees) * 0.5)
        half_width = half_height * (width / height)
        output, offset = bytearray(pixel_count * 3), 0
        for y in range(height):
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            for x in range(width):
                if cancellation_token is not None:
                    cancellation_token.raise_if_cancelled()
                pixel_seed = (seed ^ ((y * width + x) * 0x9E3779B185EBCA87)) & ((1 << 64) - 1)
                rng = random.Random(pixel_seed)
                accumulated: Vector3 = (0.0, 0.0, 0.0)
                for _sample in range(samples_per_pixel):
                    u = (2.0 * ((x + rng.random()) / width) - 1.0) * half_width
                    v = (1.0 - 2.0 * ((y + rng.random()) / height)) * half_height
                    direction = _norm(_add(_add(forward, _scale(right, u)),
                                           _scale(camera_up, v)), "camera ray")
                    origin = camera.origin
                    if camera.aperture > 0.0:
                        lens_radius = camera.aperture * 0.5 * math.sqrt(rng.random())
                        lens_angle = math.tau * rng.random()
                        lens_offset = _add(
                            _scale(right, lens_radius * math.cos(lens_angle)),
                            _scale(camera_up, lens_radius * math.sin(lens_angle)),
                        )
                        forward_projection = _dot(direction, forward)
                        if forward_projection <= 1e-8:
                            raise PathTracingError("Raio de câmera não cruza o plano focal.")
                        focus_point = _add(
                            camera.origin,
                            _scale(direction, camera.focus_distance / forward_projection),
                        )
                        origin = _add(camera.origin, lens_offset)
                        direction = _norm(
                            _sub(focus_point, origin),
                            "depth of field ray",
                        )
                    throughput: Vector3 = (1.0, 1.0, 1.0)
                    radiance: Vector3 = (0.0, 0.0, 0.0)
                    for _bounce in range(max_depth):
                        hit = cls._closest_hit(origin, direction, resolved)
                        if hit is None:
                            radiance = _add(radiance, _mul(
                                throughput, cls._environment(direction, resolved)))
                            break
                        _, point, normal, material = hit[:4]
                        hit_uv = hit[6] if len(hit) > 6 else None
                        surface_albedo = (
                            cls._sample_surface_albedo(material, hit_uv, texture_buffers)
                            if hasattr(material, "texture_pattern")
                            else material.albedo
                        )
                        radiance = _add(radiance, _mul(throughput, material.emission))
                        if (resolved.point_lights or resolved.area_lights) and max(surface_albedo) > 0.0:
                            direct = cls._direct_lighting(
                                point,
                                normal,
                                surface_albedo,
                                material.metallic,
                                material.roughness,
                                _scale(direction, -1.0),
                                resolved,
                                rng,
                            )
                            radiance = _add(radiance, _mul(throughput, direct))
                        if max(surface_albedo) <= 0.0:
                            break
                        throughput = _mul(throughput, surface_albedo)
                        if max(throughput) < 1e-4:
                            break
                        if material.metallic > 0.0 and rng.random() < material.metallic:
                            reflected = _norm(
                                _sub(
                                    direction,
                                    _scale(normal, 2.0 * _dot(direction, normal)),
                                ),
                                "metallic reflection",
                            )
                            if material.roughness > 0.02:
                                rough_sample = cls._cosine_direction(reflected, rng)
                                direction = _norm(
                                    _add(
                                        _scale(reflected, 1.0 - material.roughness),
                                        _scale(rough_sample, material.roughness),
                                    ),
                                    "rough metallic reflection",
                                )
                            else:
                                direction = reflected
                        else:
                            direction = cls._cosine_direction(normal, rng)
                        origin = _add(point, _scale(normal, cls.RAY_EPSILON * 2.0))
                    accumulated = _add(accumulated, radiance)
                averaged = _scale(accumulated, 1.0 / samples_per_pixel)
                for channel in averaged:
                    bounded = max(0.0, channel) if math.isfinite(channel) else 0.0
                    mapped = bounded / (1.0 + bounded)
                    srgb = (12.92 * mapped if mapped <= 0.0031308
                            else 1.055 * mapped ** (1.0 / 2.4) - 0.055)
                    output[offset] = max(0, min(255, int(round(srgb * 255.0))))
                    offset += 1
        return bytes(output)



    @classmethod
    def status(cls) -> dict[str, Any]:
        return {
            "component": "CPUPathTracerBackend",
            "version": cls.VERSION,
            "backend": cls.BACKEND_ID,
            "status": "implemented_unvalidated",
            "dependencies": "python_standard_library",
            "supported_geometry": [
                "sphere", "triangle", "plane", "axis_aligned_box",
                "capped_cylinder", "oriented_box", "capsule", "closed_cone",
                "disk", "indexed_triangle_mesh"
            ],
            "box_intersection": "slab",
            "mesh_acceleration": "median_split_bvh",
            "mesh_bvh_leaf_size": 4,
            "mesh_material_slots": TriangleMeshSpec.MAX_MATERIALS,
            "mesh_uv_coordinates": True,
            "triangle_uv_interpolation": "barycentric",
            "procedural_texture_patterns": ["solid", "checker"],
            "sphere_uv_mapping": "spherical",
            "cylinder_uv_mapping": ["side_cylindrical", "cap_planar"],
            "box_uv_mapping": "face_planar",
            "capsule_uv_mapping": "axial_cylindrical",
            "cone_uv_mapping": ["side_cylindrical", "base_planar"],
            "plane_uv_mapping": "orthonormal_world_basis",
            "disk_uv_mapping": "planar_radial",
            "image_texture_sampling": "rgb8_bilinear_repeat",
            "image_texture_supported_geometry": [
                "sphere", "triangle", "plane", "disk", "axis_aligned_box",
                "oriented_box", "capped_cylinder", "capsule", "cone",
                "indexed_triangle_mesh",
            ],
            "max_texture_buffers": 8,
            "max_texture_buffer_bytes": 16 * 1024 * 1024,
            "supported_materials": ["lambertian", "metallic_roughness", "emissive"],
            "supported_camera_features": ["pinhole", "depth_of_field"],
            "supported_lights": ["point", "rectangular_area"],
            "max_dimension": cls.MAX_DIMENSION,
            "max_pixels": cls.MAX_PIXELS,
            "max_samples_per_pixel": cls.MAX_SAMPLES_PER_PIXEL,
            "max_depth": cls.MAX_DEPTH,
            "threads": 1,
            "tiles": False,
            "cancellation": True,
            "cancellation_granularity": "per_pixel",
            "direct_light_sampling": True,
            "area_lights": cls.MAX_AREA_LIGHTS,
            "area_light_samples_per_bounce": cls.AREA_LIGHT_SAMPLES,
            "max_planes": cls.MAX_PLANES,
            "max_boxes": cls.MAX_BOXES,
            "max_cylinders": cls.MAX_CYLINDERS,
            "max_oriented_boxes": cls.MAX_ORIENTED_BOXES,
            "max_capsules": cls.MAX_CAPSULES,
            "max_cones": cls.MAX_CONES,
            "max_disks": cls.MAX_DISKS,
            "max_meshes": SceneSpec.MAX_MESHES,
            "max_mesh_triangles": SceneSpec.MAX_MESH_TRIANGLES,
            "real_device_validation": False,
        }
