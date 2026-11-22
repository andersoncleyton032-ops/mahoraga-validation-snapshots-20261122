"""Deterministic, dependency-free image synthesis and rendering backends."""
from __future__ import annotations
import hashlib
import math
import os
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Any
from .cpu_path_tracer import CPUPathTracerBackend, SceneSpec


class ImageGenerationError(ValueError):
    """Invalid image-generation request or artifact failure."""


class ProceduralImageBackend:
    VERSION = "0.1.0"
    BACKEND_ID = "procedural.plasma"
    MAX_DIMENSION = 1024
    MAX_PIXELS = 524_288

    @staticmethod
    def _chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (struct.pack(">I", len(payload)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    @classmethod
    def _encode_png(cls, width: int, height: int, pixels: bytes) -> bytes:
        if len(pixels) != width * height * 3:
            raise ImageGenerationError("Buffer RGB incompatível com as dimensões.")
        scanlines, stride = bytearray(), width * 3
        for y in range(height):
            scanlines.append(0)
            start = y * stride
            scanlines.extend(pixels[start:start + stride])
        header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + cls._chunk(b"IHDR", header)
                + cls._chunk(b"IDAT", zlib.compress(bytes(scanlines), level=6))
                + cls._chunk(b"IEND", b""))

    @staticmethod
    def _palette(value: float) -> tuple[int, int, int]:
        value = max(0.0, min(1.0, value))
        return tuple(int(max(0, min(255, round(
            (0.5 + 0.5 * math.sin(6.283185307179586 * (value + phase))) * 255
        )))) for phase in (0.0, 0.33, 0.67))  # type: ignore[return-value]

    @classmethod
    def render(cls, width: int, height: int, seed: int = 0) -> bytes:
        if isinstance(width, bool) or not isinstance(width, int):
            raise ImageGenerationError("width deve ser inteiro.")
        if isinstance(height, bool) or not isinstance(height, int):
            raise ImageGenerationError("height deve ser inteiro.")
        if not 1 <= width <= cls.MAX_DIMENSION or not 1 <= height <= cls.MAX_DIMENSION:
            raise ImageGenerationError("Dimensões fora do limite permitido.")
        if width * height > cls.MAX_PIXELS:
            raise ImageGenerationError("A imagem excede o orçamento máximo de pixels.")
        if isinstance(seed, bool) or not isinstance(seed, int) or not -(2**63) <= seed < 2**63:
            raise ImageGenerationError("seed deve ser inteiro signed 64-bit.")
        phase = (seed % 1_000_003) / 1_000_003.0 * math.tau
        denominator_x, denominator_y = max(1, width - 1), max(1, height - 1)
        pixels, offset = bytearray(width * height * 3), 0
        for y in range(height):
            ny = y / denominator_y
            for x in range(width):
                nx = x / denominator_x
                radial = math.hypot(nx - 0.5, ny - 0.5)
                field = (math.sin(nx * 8.0 + phase) + math.sin(ny * 8.0 - phase * 0.7)
                         + math.sin((nx + ny) * 6.0 + phase * 0.3)
                         + math.sin(radial * 18.0 - phase))
                pixels[offset:offset + 3] = bytes(cls._palette((field + 4.0) / 8.0))
                offset += 3
        return cls._encode_png(width, height, bytes(pixels))


class ImageGenerationEngine:
    """One image subsystem, with explicit deterministic backends."""
    VERSION = "0.3.0"

    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.procedural = ProceduralImageBackend()
        self.path_tracer = CPUPathTracerBackend

    def _store_png(self, png: bytes) -> dict[str, Any]:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        if not self.artifact_root.is_dir():
            raise ImageGenerationError("artifact_root não é um diretório.")
        digest = hashlib.sha256(png).hexdigest()
        destination = self.artifact_root / f"image-{digest[:24]}.png"
        if not destination.exists():
            fd, temporary_name = tempfile.mkstemp(
                prefix=".mahoraga-image-", suffix=".tmp", dir=self.artifact_root
            )
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(png)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, destination)
            except Exception:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
                raise
        stored = destination.read_bytes()
        if stored != png or hashlib.sha256(stored).hexdigest() != digest:
            raise ImageGenerationError("A validação do artefato PNG falhou.")
        return {"artifact_path": str(destination), "sha256": digest, "byte_size": len(png)}

    def generate_procedural(self, width: int, height: int, *, seed: int = 0) -> dict[str, Any]:
        png = self.procedural.render(width, height, seed)
        return {
            "schema": "mahoraga.generated_image", "status": "completed",
            "backend": self.procedural.BACKEND_ID, "engine_version": self.VERSION,
            "width": width, "height": height, "seed": seed, "format": "png",
            **self._store_png(png), "deterministic": True, "validated": True,
            "artifact_validated": True,
            "validation_scope": "artifact_integrity_only",
            "visual_quality_validated": False,
            "neural_model_used": False, "blender_required": False, "path_tracing": False,
        }

    def generate_path_traced(self, width: int, height: int, *,
                             scene: SceneSpec | dict[str, Any] | None = None,
                             seed: int = 0, samples_per_pixel: int = 1,
                             max_depth: int = 3) -> dict[str, Any]:
        resolved_scene = (
            SceneSpec.default() if scene is None
            else scene if isinstance(scene, SceneSpec)
            else SceneSpec.from_mapping(scene)
        )
        rgb = self.path_tracer.render_rgb(
            width, height, scene=resolved_scene, seed=seed,
            samples_per_pixel=samples_per_pixel, max_depth=max_depth,
        )
        png = self.procedural._encode_png(width, height, rgb)
        return {
            "schema": "mahoraga.generated_image", "status": "completed",
            "backend": self.path_tracer.BACKEND_ID, "engine_version": self.VERSION,
            "renderer_version": self.path_tracer.VERSION, "width": width, "height": height,
            "seed": seed, "samples_per_pixel": samples_per_pixel, "max_depth": max_depth,
            "scene_schema": SceneSpec.SCHEMA,
            "scene_sha256": resolved_scene.sha256(), "scene": resolved_scene.to_dict(),
            "format": "png",
            **self._store_png(png), "deterministic": True, "validated": True,
            "artifact_validated": True,
            "validation_scope": "artifact_integrity_only",
            "visual_quality_validated": False,
            "neural_model_used": False, "blender_required": False, "path_tracing": True,
        }

    def status(self) -> dict[str, Any]:
        return {
            "component": "ImageGenerationEngine", "version": self.VERSION,
            "available_backends": [self.procedural.BACKEND_ID, self.path_tracer.BACKEND_ID],
            "neural_generation_available": False, "path_tracing_available": True,
            "path_tracer_status": self.path_tracer.status(),
            "runtime_dispatch_enabled": False, "blender_required": False,
            "artifact_root": str(self.artifact_root), "status": "implemented_unvalidated",
        }
