"""Bounded deterministic CPU path tracer prototype for Mahoraga."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math
import random
from typing import Any

Vector3 = tuple[float, float, float]


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


@dataclass(frozen=True)
class CameraSpec:
    origin: Vector3
    target: Vector3
    up: Vector3 = (0.0, 1.0, 0.0)
    vertical_fov_degrees: float = 42.0

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

    @classmethod
    def from_mapping(cls, value: Any) -> "CameraSpec":
        if not isinstance(value, dict):
            raise PathTracingError("camera deve ser um objeto.")
        allowed = {"origin", "target", "up", "vertical_fov_degrees"}
        if set(value) - allowed or not {"origin", "target"}.issubset(value):
            raise PathTracingError("Campos de camera desconhecidos ou ausentes.")
        return cls(
            _vec(value["origin"], "camera.origin", -10000.0, 10000.0),
            _vec(value["target"], "camera.target", -10000.0, 10000.0),
            _vec(value.get("up", [0.0, 1.0, 0.0]), "camera.up", -1.0, 1.0),
            _finite(value.get("vertical_fov_degrees", 42.0),
                    "camera.vertical_fov_degrees", 5.0, 120.0),
        )


@dataclass(frozen=True)
class SphereSpec:
    center: Vector3
    radius: float
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)

    def __post_init__(self):
        object.__setattr__(self, "center", _vec(self.center, "sphere.center", -10000.0, 10000.0))
        object.__setattr__(self, "radius", _finite(self.radius, "sphere.radius", 0.001, 1000.0))
        object.__setattr__(self, "albedo", _vec(self.albedo, "sphere.albedo", 0.0, 1.0))
        object.__setattr__(self, "emission", _vec(self.emission, "sphere.emission", 0.0, 32.0))

    @classmethod
    def from_mapping(cls, value: Any) -> "SphereSpec":
        if not isinstance(value, dict):
            raise PathTracingError("Cada esfera deve ser um objeto.")
        allowed = {"center", "radius", "albedo", "emission"}
        if set(value) - allowed or not {"center", "radius", "albedo"}.issubset(value):
            raise PathTracingError("Campos de esfera desconhecidos ou ausentes.")
        return cls(
            _vec(value["center"], "sphere.center", -10000.0, 10000.0),
            _finite(value["radius"], "sphere.radius", 0.001, 1000.0),
            _vec(value["albedo"], "sphere.albedo", 0.0, 1.0),
            _vec(value.get("emission", [0.0, 0.0, 0.0]),
                 "sphere.emission", 0.0, 32.0),
        )


@dataclass(frozen=True)
class TriangleSpec:
    a: Vector3
    b: Vector3
    c: Vector3
    albedo: Vector3
    emission: Vector3 = (0.0, 0.0, 0.0)

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

    @classmethod
    def from_mapping(cls, value: Any) -> "TriangleSpec":
        if not isinstance(value, dict) or set(value) - {"a", "b", "c", "albedo", "emission"}:
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
class SceneSpec:
    camera: CameraSpec
    spheres: tuple[SphereSpec, ...]
    triangles: tuple[TriangleSpec, ...] = ()
    point_lights: tuple[PointLightSpec, ...] = ()
    background_top: Vector3 = (0.42, 0.58, 0.82)
    background_bottom: Vector3 = (0.055, 0.065, 0.09)
    scene_id: str = "legacy-sphere-scene"

    MAX_SPHERES = 32
    MAX_TRIANGLES = 64
    MAX_POINT_LIGHTS = 8
    SCHEMA = "mahoraga.scene_spec.v1"

    def __post_init__(self):
        if not isinstance(self.camera, CameraSpec):
            raise PathTracingError("camera precisa ser CameraSpec.")
        collections = (
            ("spheres", self.spheres, SphereSpec, self.MAX_SPHERES),
            ("triangles", self.triangles, TriangleSpec, self.MAX_TRIANGLES),
            ("point_lights", self.point_lights, PointLightSpec, self.MAX_POINT_LIGHTS),
        )
        for field, values, expected_type, maximum in collections:
            if not isinstance(values, (list, tuple)) or len(values) > maximum:
                raise PathTracingError(f"{field} deve conter até {maximum} itens.")
            normalized = tuple(values)
            if any(not isinstance(item, expected_type) for item in normalized):
                raise PathTracingError(f"{field} contém item com tipo inválido.")
            object.__setattr__(self, field, normalized)
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
            "point_lights", "background_top", "background_bottom",
        }
        if set(value) - allowed:
            raise PathTracingError("scene contém campos desconhecidos.")
        schema = value.get("schema")
        if schema not in (None, "mahoraga.scene.v1", cls.SCHEMA):
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
        top = _vec(value.get("background_top", [0.42, 0.58, 0.82]),
                   "background_top", 0.0, 1.0)
        bottom = _vec(value.get("background_bottom", [0.055, 0.065, 0.09]),
                      "background_bottom", 0.0, 1.0)
        scene_id = value.get("scene_id", "legacy-sphere-scene")
        if not isinstance(scene_id, str) or not scene_id.strip() or len(scene_id) > 96:
            raise PathTracingError("scene_id inválido.")
        return cls(camera, spheres, triangles, lights, top, bottom, scene_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "scene_id": self.scene_id,
            "camera": {
                "origin": list(self.camera.origin),
                "target": list(self.camera.target),
                "up": list(self.camera.up),
                "vertical_fov_degrees": self.camera.vertical_fov_degrees,
            },
            "spheres": [
                {
                    "center": list(item.center),
                    "radius": item.radius,
                    "albedo": list(item.albedo),
                    "emission": list(item.emission),
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
                }
                for item in self.triangles
            ],
            "point_lights": [
                {"position": list(item.position), "intensity": list(item.intensity)}
                for item in self.point_lights
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
    VERSION = "0.2.0"
    BACKEND_ID = "cpu.pathtracer"
    MAX_DIMENSION = 128
    MAX_PIXELS = 16_384
    MAX_SAMPLES_PER_PIXEL = 8
    MAX_DEPTH = 4
    MAX_SPHERES = SceneSpec.MAX_SPHERES
    MAX_TRIANGLES = SceneSpec.MAX_TRIANGLES
    MAX_POINT_LIGHTS = SceneSpec.MAX_POINT_LIGHTS
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
        return distance, point, normal, sphere

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
        return distance, _add(origin, _scale(direction, distance)), normal, triangle

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
    def _direct_lighting(cls, point: Vector3, normal: Vector3,
                         albedo: Vector3, scene: SceneSpec) -> Vector3:
        result: Vector3 = (0.0, 0.0, 0.0)
        for light in scene.point_lights:
            displacement = _sub(light.position, point)
            distance_squared = _dot(displacement, displacement)
            if distance_squared <= 1e-10:
                continue
            distance = math.sqrt(distance_squared)
            direction = _scale(displacement, 1.0 / distance)
            cosine = max(0.0, _dot(normal, direction))
            if cosine <= 0.0:
                continue
            shadow_origin = _add(point, _scale(normal, cls.RAY_EPSILON * 2.0))
            if cls._closest_hit(shadow_origin, direction, scene,
                                distance - cls.RAY_EPSILON) is not None:
                continue
            irradiance = _scale(light.intensity, cosine / (math.pi * distance_squared))
            result = _add(result, _mul(albedo, irradiance))
        return result



    @classmethod
    def render_rgb(cls, width: int, height: int, *,
                   scene: SceneSpec | dict[str, Any] | None = None,
                   seed: int = 0, samples_per_pixel: int = 1,
                   max_depth: int = 3) -> bytes:
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
        geometry_count = max(1, len(resolved.spheres) + len(resolved.triangles))
        work = (pixel_count * samples_per_pixel * max_depth
                * geometry_count * (1 + len(resolved.point_lights)))
        if (len(resolved.spheres) > cls.MAX_SPHERES
                or len(resolved.triangles) > cls.MAX_TRIANGLES
                or len(resolved.point_lights) > cls.MAX_POINT_LIGHTS
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
            for x in range(width):
                pixel_seed = (seed ^ ((y * width + x) * 0x9E3779B185EBCA87)) & ((1 << 64) - 1)
                rng = random.Random(pixel_seed)
                accumulated: Vector3 = (0.0, 0.0, 0.0)
                for _sample in range(samples_per_pixel):
                    u = (2.0 * ((x + rng.random()) / width) - 1.0) * half_width
                    v = (1.0 - 2.0 * ((y + rng.random()) / height)) * half_height
                    direction = _norm(_add(_add(forward, _scale(right, u)),
                                           _scale(camera_up, v)), "camera ray")
                    origin = camera.origin
                    throughput: Vector3 = (1.0, 1.0, 1.0)
                    radiance: Vector3 = (0.0, 0.0, 0.0)
                    for _bounce in range(max_depth):
                        hit = cls._closest_hit(origin, direction, resolved)
                        if hit is None:
                            radiance = _add(radiance, _mul(
                                throughput, cls._environment(direction, resolved)))
                            break
                        _, point, normal, material = hit
                        radiance = _add(radiance, _mul(throughput, material.emission))
                        if resolved.point_lights and max(material.albedo) > 0.0:
                            direct = cls._direct_lighting(point, normal, material.albedo, resolved)
                            radiance = _add(radiance, _mul(throughput, direct))
                        if max(material.albedo) <= 0.0:
                            break
                        throughput = _mul(throughput, material.albedo)
                        if max(throughput) < 1e-4:
                            break
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
            "supported_geometry": ["sphere", "triangle"],
            "supported_materials": ["lambertian", "emissive"],
            "max_dimension": cls.MAX_DIMENSION,
            "max_pixels": cls.MAX_PIXELS,
            "max_triangles": cls.MAX_TRIANGLES,
            "max_point_lights": cls.MAX_POINT_LIGHTS,
            "max_samples_per_pixel": cls.MAX_SAMPLES_PER_PIXEL,
            "max_depth": cls.MAX_DEPTH,
            "threads": 1,
            "tiles": False,
            "cancellation": False,
            "direct_light_sampling": True,
            "real_device_validation": False,
        }
