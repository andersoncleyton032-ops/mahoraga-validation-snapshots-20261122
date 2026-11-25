"""Deterministic, dependency-free image synthesis and rendering backends."""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import struct
import stat
import tempfile
import zlib
from pathlib import Path
from typing import Any
from .cpu_path_tracer import CPUPathTracerBackend, SceneSpec, TextureBuffer
from .cancellation import CancellationToken, OperationCancelled


class ImageGenerationError(ValueError):
    """Invalid image-generation request or artifact failure."""


class ImageRenderManifestError(OSError):
    """The PNG exists, but its lineage manifest was not safely committed."""

    def __init__(self, message: str, *, manifest_committed: bool):
        super().__init__(message)
        self.image_committed = True
        self.manifest_committed = manifest_committed


class ImageArtifactDurabilityError(OSError):
    """Artifact replacement committed, but directory durability is uncertain."""

    def __init__(self, message: str):
        super().__init__(message)
        self.committed = True


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
    def render(
        cls, width: int, height: int, seed: int = 0,
        *, cancellation_token: CancellationToken | None = None,
    ) -> bytes:
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
        if cancellation_token is not None and not isinstance(cancellation_token, CancellationToken):
            raise ImageGenerationError("cancellation_token deve ser um CancellationToken.")
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        phase = (seed % 1_000_003) / 1_000_003.0 * math.tau
        denominator_x, denominator_y = max(1, width - 1), max(1, height - 1)
        pixels, offset = bytearray(width * height * 3), 0
        for y in range(height):
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
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
    VERSION = "0.9.0"
    MAX_DIMENSION = ProceduralImageBackend.MAX_DIMENSION
    MAX_PIXELS = ProceduralImageBackend.MAX_PIXELS
    MAX_PNG_BYTES = 4_000_000

    def __init__(self, artifact_root: str | Path):
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self._artifact_store: Any = None
        self.procedural = ProceduralImageBackend()
        self.path_tracer = CPUPathTracerBackend

    @property
    def artifact_store(self) -> Any:
        """Lazily create the shared PNG store; engine construction remains side-effect free."""
        if self._artifact_store is None:
            # Lazy import avoids the image_generation ↔ image_asset_verifier cycle.
            from .artifact_store import ArtifactStore
            self._artifact_store = ArtifactStore(self.artifact_root / "asset_store")
        return self._artifact_store

    @staticmethod
    def _validate_visual_document_provenance(
        value: Any,
        *,
        scene_sha256: str,
        expected: Any = None,
    ) -> dict[str, Any]:
        """Validate recorded visual lineage without claiming source authentication."""
        if hasattr(value, "to_dict") and callable(value.to_dict):
            value = value.to_dict()
        if not isinstance(value, dict):
            raise ImageGenerationError("visual_document provenance deve ser um objeto.")
        required = {
            "schema", "source_document_sha256", "scene_spec_sha256", "task_id",
            "task_sha256", "compiler_version", "element_bindings",
            "skipped_hidden_element_ids", "source_provenance_authenticated",
        }
        if set(value) != required or value.get("schema") != "mahoraga.visual_render_provenance.v1":
            raise ImageGenerationError("Schema/campos da proveniência visual incompatíveis.")
        for field in ("source_document_sha256", "scene_spec_sha256", "task_sha256"):
            if not isinstance(value.get(field), str) or re.fullmatch(r"[0-9a-f]{64}", value[field]) is None:
                raise ImageGenerationError(f"Digest da proveniência inválido: {field}.")
        if value["scene_spec_sha256"] != scene_sha256:
            raise ImageGenerationError("Proveniência visual diverge do SceneSpec renderizado.")
        if not isinstance(value.get("task_id"), str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value["task_id"]
        ) is None:
            raise ImageGenerationError("task_id da proveniência visual inválido.")
        if not isinstance(value.get("compiler_version"), str) or re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+", value["compiler_version"]
        ) is None:
            raise ImageGenerationError("compiler_version da proveniência visual inválida.")
        bindings = value.get("element_bindings")
        hidden = value.get("skipped_hidden_element_ids")
        if not isinstance(bindings, list) or len(bindings) > 512:
            raise ImageGenerationError("element_bindings excede o contrato.")
        if not isinstance(hidden, list) or len(hidden) > 512:
            raise ImageGenerationError("skipped_hidden_element_ids excede o contrato.")
        keys: set[str] = set()
        element_ids: set[str] = set()
        normalized_bindings = []
        for item in bindings:
            if not isinstance(item, dict) or set(item) != {"scene_path", "element_id"}:
                raise ImageGenerationError("Binding da proveniência visual inválido.")
            key, element_id = item["scene_path"], item["element_id"]
            if not isinstance(key, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_.\[\]]{0,127}", key) is None:
                raise ImageGenerationError("scene_path da proveniência visual inválido.")
            if not isinstance(element_id, str) or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", element_id
            ) is None:
                raise ImageGenerationError("element_id da proveniência visual inválido.")
            if key in keys or element_id in element_ids:
                raise ImageGenerationError("Bindings da proveniência visual devem ser únicos.")
            keys.add(key)
            element_ids.add(element_id)
            normalized_bindings.append({"scene_path": key, "element_id": element_id})
        for element_id in hidden:
            if not isinstance(element_id, str) or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", element_id
            ) is None:
                raise ImageGenerationError("ID oculto na proveniência visual inválido.")
        if len(set(hidden)) != len(hidden) or set(hidden) & element_ids:
            raise ImageGenerationError("IDs ocultos da proveniência são duplicados ou conflitantes.")
        if value.get("source_provenance_authenticated") is not False:
            raise ImageGenerationError("Proveniência visual não pode alegar autenticação da origem.")
        normalized = {
            "schema": value["schema"],
            "source_document_sha256": value["source_document_sha256"],
            "scene_spec_sha256": value["scene_spec_sha256"],
            "task_id": value["task_id"],
            "task_sha256": value["task_sha256"],
            "compiler_version": value["compiler_version"],
            "element_bindings": normalized_bindings,
            "skipped_hidden_element_ids": list(hidden),
            "source_provenance_authenticated": False,
        }
        if expected is not None:
            expected_value = expected.to_dict() if hasattr(expected, "to_dict") else expected
            if normalized != expected_value:
                raise ImageGenerationError("Proveniência persistida diverge do registro esperado.")
        return normalized

    @staticmethod
    def _read_existing_artifact(path: Path) -> bytes:
        """Read only a regular file, rejecting symlinks and path swaps."""
        try:
            before = os.lstat(path)
        except FileNotFoundError:
            raise
        if not stat.S_ISREG(before.st_mode):
            raise ImageGenerationError(
                "O destino do artefato não é um arquivo regular."
            )

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ImageGenerationError("Artefato não pôde ser aberto sem seguir symlinks.") from exc
        try:
            after = os.fstat(descriptor)
            if (
                not stat.S_ISREG(after.st_mode)
                or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
            ):
                raise ImageGenerationError(
                    "O destino do artefato mudou durante a leitura."
                )
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                return handle.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _read_bounded_existing_artifact(path: Path, max_bytes: int) -> bytes:
        """Read one regular artifact without following symlinks or exceeding its bound."""
        try:
            before = os.lstat(path)
        except FileNotFoundError:
            raise
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise ImageGenerationError("Artefato não regular ou acima do limite.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            after = os.fstat(descriptor)
            if (
                not stat.S_ISREG(after.st_mode)
                or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or after.st_size > max_bytes
            ):
                raise ImageGenerationError("Artefato mudou ou excedeu o limite durante a leitura.")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                content = handle.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ImageGenerationError("Artefato excede o limite durante a leitura.")
            return content
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def verify_render_artifact(
        self,
        image_path: str | Path,
        manifest_path: str | Path,
    ) -> dict[str, Any]:
        """Verify a generated PNG and its lineage sidecar without changing either."""
        root = self.artifact_root
        if (
            root.is_symlink()
            or root.resolve(strict=False) != root
            or not root.exists()
            or not root.is_dir()
        ):
            raise ImageGenerationError("artifact_root não é um diretório canônico existente.")
        image = Path(image_path).expanduser()
        manifest_file = Path(manifest_path).expanduser()
        if (
            not image.is_absolute()
            or not manifest_file.is_absolute()
            or image.parent != root
            or manifest_file.parent != root
            or image.parent.resolve(strict=True) != root
            or manifest_file.parent.resolve(strict=True) != root
        ):
            raise ImageGenerationError("Artefatos devem estar diretamente em artifact_root.")
        if re.fullmatch(r"image-[0-9a-f]{24}\.png", image.name) is None:
            raise ImageGenerationError("Nome do PNG não corresponde ao padrão de artefatos.")
        if re.fullmatch(
            rf"image-{image.name[6:30]}-[0-9a-f]{{16}}\.manifest\.json",
            manifest_file.name,
        ) is None:
            raise ImageGenerationError("Manifesto não corresponde ao PNG informado.")

        png = self._read_bounded_existing_artifact(image, self.MAX_PNG_BYTES)
        manifest_bytes = self._read_bounded_existing_artifact(manifest_file, 65_536)
        image_digest = hashlib.sha256(png).hexdigest()
        if image.name != f"image-{image_digest[:24]}.png":
            raise ImageGenerationError("Nome do PNG não corresponde ao seu SHA-256.")

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Chave JSON duplicada.")
                result[key] = value
            return result

        try:
            manifest = json.loads(
                manifest_bytes.decode("utf-8"),
                object_pairs_hook=unique_object,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise ImageGenerationError("Manifesto JSON inválido ou com chaves duplicadas.") from exc
        if not isinstance(manifest, dict):
            raise ImageGenerationError("Manifesto deve ser um objeto JSON.")
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_file.name != (
            f"image-{image_digest[:24]}-{manifest_digest[:16]}.manifest.json"
        ):
            raise ImageGenerationError("Nome do manifesto não corresponde ao seu SHA-256.")

        if not isinstance(manifest, dict):
            raise ImageGenerationError("Manifesto JSON deve ser um objeto.")
        base_top_keys = {
            "schema", "output", "render", "input_assets",
            "input_source_refs_recorded", "source_provenance_authenticated",
            "license_status_authenticated", "visual_quality_assessed",
        }
        manifest_schema = manifest.get("schema")
        if manifest_schema == "mahoraga.image_render_manifest.v1":
            if set(manifest) != base_top_keys:
                raise ImageGenerationError("Campos do manifesto v1 incompatíveis.")
        elif manifest_schema == "mahoraga.image_render_manifest.v2":
            if set(manifest) != base_top_keys | {"visual_document"}:
                raise ImageGenerationError("Campos do manifesto v2 incompatíveis.")
        else:
            raise ImageGenerationError("Schema de manifesto incompatível.")
        output = manifest["output"]
        render = manifest["render"]
        inputs = manifest["input_assets"]
        if not isinstance(output, dict) or not isinstance(render, dict) or not isinstance(inputs, list):
            raise ImageGenerationError("Seções do manifesto possuem tipos inválidos.")
        if manifest_schema == "mahoraga.image_render_manifest.v2":
            self._validate_visual_document_provenance(
                manifest["visual_document"], scene_sha256=render.get("scene_sha256")
            )
        if set(output) != {
            "asset_id", "source_kind", "mime_type", "byte_size", "sha256",
            "width", "height", "orientation_degrees", "color_space",
            "alpha_mode", "license_status_declared",
        }:
            raise ImageGenerationError("Campos de output do manifesto incompatíveis.")
        if set(render) != {
            "backend", "renderer_version", "engine_version", "scene_schema",
            "scene_sha256", "rgb_sha256", "texture_asset_ids",
            "seed", "samples_per_pixel", "max_depth",
        }:
            raise ImageGenerationError("Campos de render do manifesto incompatíveis.")
        if len(inputs) > 8:
            raise ImageGenerationError("Manifesto excede oito assets de entrada.")

        png_report = self._validate_png(png)
        width, height = png_report["width"], png_report["height"]
        if (
            png_report["channels"] != 3
            or not isinstance(output["asset_id"], str)
            or output["asset_id"] != f"generated-{image_digest[:24]}"
            or output["source_kind"] != "generated"
            or output["mime_type"] != "image/png"
            or isinstance(output["orientation_degrees"], bool)
            or not isinstance(output["orientation_degrees"], int)
            or output["orientation_degrees"] != 0
            or output["color_space"] != "unknown"
            or output["alpha_mode"] != "opaque"
            or output["license_status_declared"] != "unknown"
            or isinstance(output["byte_size"], bool)
            or not isinstance(output["byte_size"], int)
            or output["byte_size"] != len(png)
            or output["sha256"] != image_digest
            or isinstance(output["width"], bool)
            or not isinstance(output["width"], int)
            or output["width"] != width
            or isinstance(output["height"], bool)
            or not isinstance(output["height"], int)
            or output["height"] != height
            or width > CPUPathTracerBackend.MAX_DIMENSION
            or height > CPUPathTracerBackend.MAX_DIMENSION
            or width * height > CPUPathTracerBackend.MAX_PIXELS
        ):
            raise ImageGenerationError("Manifesto output diverge do PNG armazenado.")

        def valid_digest(value):
            return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

        if (
            render["backend"] != CPUPathTracerBackend.BACKEND_ID
            or render["scene_schema"] != SceneSpec.SCHEMA
            or not valid_digest(render["scene_sha256"])
            or not valid_digest(render["rgb_sha256"])
            or any(
                isinstance(render[field], bool) or not isinstance(render[field], int)
                for field in ("seed", "samples_per_pixel", "max_depth")
            )
            or not -(2**63) <= render["seed"] < 2**63
            or not 1 <= render["samples_per_pixel"] <= CPUPathTracerBackend.MAX_SAMPLES_PER_PIXEL
            or not 1 <= render["max_depth"] <= CPUPathTracerBackend.MAX_DEPTH
            or not isinstance(render["renderer_version"], str) or not render["renderer_version"]
            or not isinstance(render["engine_version"], str) or not render["engine_version"]
            or not isinstance(render["texture_asset_ids"], list)
            or len(render["texture_asset_ids"]) > 8
            or any(not isinstance(asset_id, str) for asset_id in render["texture_asset_ids"])
            or len(set(render["texture_asset_ids"])) != len(render["texture_asset_ids"])
        ):
            raise ImageGenerationError("Metadados de render do manifesto inválidos.")

        asset_ids = set()
        input_fields = {
            "asset_id", "source_kind", "mime_type", "byte_size", "sha256",
            "width", "height", "channels", "color_space", "alpha_mode",
            "license_status_declared", "verification_status", "verification_scope",
            "license_authenticated", "provenance_authenticated",
        }
        for item in inputs:
            if not isinstance(item, dict) or set(item) != input_fields:
                raise ImageGenerationError("Descriptor de entrada no manifesto inválido.")
            if (
                not isinstance(item["asset_id"], str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", item["asset_id"]) is None
                or item["asset_id"] in asset_ids
                or not isinstance(item["source_kind"], str)
                or item["source_kind"] not in ImageAssetDescriptor.SOURCE_KINDS
                or item["mime_type"] != "image/png"
                or isinstance(item["byte_size"], bool)
                or not isinstance(item["byte_size"], int)
                or not 1 <= item["byte_size"] <= self.MAX_PNG_BYTES
                or not valid_digest(item["sha256"])
                or any(
                    isinstance(item[field], bool) or not isinstance(item[field], int)
                    or not 1 <= item[field] <= TextureBuffer.MAX_DIMENSION
                    for field in ("width", "height")
                )
                or item["width"] * item["height"] > ImageAssetDescriptor.MAX_PIXELS
                or isinstance(item["channels"], bool)
                or not isinstance(item["channels"], int)
                or item["channels"] not in (3, 4)
                or not isinstance(item["color_space"], str)
                or item["color_space"] not in ("srgb", "linear")
                or item["alpha_mode"] != ("straight" if item["channels"] == 4 else "opaque")
                or not isinstance(item["license_status_declared"], str)
                or item["license_status_declared"] not in ImageAssetDescriptor.LICENSE_STATUSES
                or item["verification_status"] != "verified"
                or not isinstance(item["verification_scope"], list)
                or any(not isinstance(scope, str) for scope in item["verification_scope"])
                or item["license_authenticated"] is not False
                or item["provenance_authenticated"] is not False
            ):
                raise ImageGenerationError("Metadados de asset de entrada inválidos.")
            asset_ids.add(item["asset_id"])

        if (
            manifest["input_source_refs_recorded"] is not False
            or manifest["source_provenance_authenticated"] is not False
            or manifest["license_status_authenticated"] is not False
            or manifest["visual_quality_assessed"] is not False
        ):
            raise ImageGenerationError("Manifesto faz alegações de confiança não suportadas.")

        texture = self.decode_png_texture(
            png, color_space="srgb", expected_width=width, expected_height=height
        )
        try:
            output_descriptor = ImageAssetDescriptor(
                asset_id=output["asset_id"],
                source_kind=output["source_kind"],
                source_ref=f"artifact://sha256/{image_digest}",
                mime_type=output["mime_type"],
                byte_size=output["byte_size"],
                content_sha256=output["sha256"],
                width=output["width"],
                height=output["height"],
                orientation_degrees=output["orientation_degrees"],
                color_space=output["color_space"],
                alpha_mode=output["alpha_mode"],
                license_status=output["license_status_declared"],
            )
        except (TypeError, ValueError) as exc:
            raise ImageGenerationError("Descriptor reconstruído do PNG é inválido.") from exc
        if hashlib.sha256(texture.pixels).hexdigest() != render["rgb_sha256"]:
            raise ImageGenerationError("Digest RGB do manifesto diverge dos pixels PNG.")
        if asset_ids != set(render["texture_asset_ids"]):
            raise ImageGenerationError("IDs de entrada inconsistentes.")

        return {
            "status": "verified",
            "image_path": str(image),
            "manifest_path": str(manifest_file),
            "image_sha256": image_digest,
            "manifest_sha256": manifest_digest,
            "png_bytes": png,
            "image_asset_descriptor": output_descriptor.to_dict(),
            "width": width,
            "height": height,
            "texture": texture,
            "visual_signal": png_report["visual_signal"],
            "manifest": manifest,
            "verification": {
                "png_structure_and_crc_verified": True,
                "manifest_schema_and_digest_verified": True,
                "rgb_pixel_digest_verified": True,
                "input_asset_metadata_shape_verified": True,
                "visual_signal_measurement_scope": "low_level_pixel_signal_only",
                "visual_quality_assessed": False,
                "source_provenance_authenticated": False,
                "license_authenticated": False,
                "visual_quality_assessed": False,
            },
        }

    def verify_stored_render_artifact(
        self,
        asset_id: str,
        manifest_path: str | Path,
        *,
        expected_scene_sha256: str | None = None,
        expected_visual_provenance: Any = None,
    ) -> dict[str, Any]:
        """Re-verify a content-addressed PNG and its lineage manifest."""
        from .artifact_store import ArtifactStoreError
        from .image_asset_verifier import ImageAssetVerificationError, ImageAssetVerifier

        root = self.artifact_root
        if (
            root.is_symlink()
            or root.resolve(strict=False) != root
            or not root.exists()
            or not root.is_dir()
        ):
            raise ImageGenerationError("artifact_root não é um diretório canônico existente.")
        manifest_file = Path(manifest_path).expanduser()
        if (
            not manifest_file.is_absolute()
            or manifest_file.parent != root
            or manifest_file.parent.resolve(strict=True) != root
        ):
            raise ImageGenerationError("Manifesto deve estar diretamente em artifact_root.")
        try:
            stored = self.artifact_store.get_png(asset_id)
        except ArtifactStoreError as exc:
            raise ImageGenerationError("PNG não passou pela revalidação do ArtifactStore.") from exc
        descriptor = stored.asset.descriptor
        image_digest = hashlib.sha256(stored.content).hexdigest()
        if image_digest != descriptor.content_sha256 or descriptor.asset_id != asset_id:
            raise ImageGenerationError("Identidade ou digest do PNG armazenado diverge.")
        manifest_bytes = self._read_bounded_existing_artifact(manifest_file, 65_536)
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_file.name != (
            f"image-{image_digest[:24]}-{manifest_digest[:16]}.manifest.json"
        ):
            raise ImageGenerationError("Nome do manifesto não corresponde aos digests.")
        if not re.fullmatch(r"[0-9a-f]{64}", manifest_digest):
            raise ImageGenerationError("Digest do manifesto inválido.")

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Chave JSON duplicada.")
                result[key] = value
            return result

        def reject_constant(value):
            raise ValueError("Constante JSON não permitida: " + value)

        try:
            manifest = json.loads(
                manifest_bytes.decode("utf-8"),
                object_pairs_hook=unique_object,
                parse_constant=reject_constant,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise ImageGenerationError("Manifesto JSON inválido.") from exc
        base_top_keys = {
            "schema", "output", "render", "input_assets",
            "input_source_refs_recorded", "source_provenance_authenticated",
            "license_status_authenticated", "visual_quality_assessed",
        }
        manifest_schema = manifest.get("schema") if isinstance(manifest, dict) else None
        if manifest_schema == "mahoraga.image_render_manifest.v1":
            if set(manifest) != base_top_keys:
                raise ImageGenerationError("Campos do manifesto v1 incompatíveis.")
        elif manifest_schema == "mahoraga.image_render_manifest.v2":
            if set(manifest) != base_top_keys | {"visual_document"}:
                raise ImageGenerationError("Campos do manifesto v2 incompatíveis.")
        else:
            raise ImageGenerationError("Schema de manifesto incompatível.")
        output, render, inputs = (
            manifest.get("output"), manifest.get("render"), manifest.get("input_assets")
        )
        if not isinstance(output, dict) or not isinstance(render, dict) or not isinstance(inputs, list):
            raise ImageGenerationError("Seções do manifesto possuem tipos inválidos.")
        if manifest_schema == "mahoraga.image_render_manifest.v2":
            self._validate_visual_document_provenance(
                manifest["visual_document"],
                scene_sha256=render.get("scene_sha256"),
                expected=expected_visual_provenance,
            )
        elif expected_visual_provenance is not None:
            raise ImageGenerationError("Manifesto não contém a proveniência visual esperada.")
        output_fields = {
            "asset_id", "source_kind", "mime_type", "byte_size", "sha256",
            "width", "height", "orientation_degrees", "color_space",
            "alpha_mode", "license_status_declared",
        }
        render_fields = {
            "backend", "renderer_version", "engine_version", "scene_schema",
            "scene_sha256", "rgb_sha256", "texture_asset_ids",
            "seed", "samples_per_pixel", "max_depth",
        }
        if set(output) != output_fields or set(render) != render_fields or len(inputs) > 8:
            raise ImageGenerationError("Campos do manifesto incompatíveis.")
        expected_output = {
            "asset_id": descriptor.asset_id,
            "source_kind": descriptor.source_kind,
            "mime_type": descriptor.mime_type,
            "byte_size": descriptor.byte_size,
            "sha256": descriptor.content_sha256.lower(),
            "width": descriptor.width,
            "height": descriptor.height,
            "orientation_degrees": descriptor.orientation_degrees,
            "color_space": descriptor.color_space,
            "alpha_mode": descriptor.alpha_mode,
            "license_status_declared": descriptor.license_status,
        }
        if output != expected_output or descriptor.source_kind != "generated":
            raise ImageGenerationError("Descriptor de saída diverge do ArtifactStore.")
        def valid_digest(value):
            return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
        scene_digest = render.get("scene_sha256")
        rgb_digest = render.get("rgb_sha256")
        if (
            render.get("backend") != CPUPathTracerBackend.BACKEND_ID
            or render.get("renderer_version") != CPUPathTracerBackend.VERSION
            or render.get("engine_version") != self.VERSION
            or render.get("scene_schema") != SceneSpec.SCHEMA
            or not valid_digest(scene_digest)
            or not valid_digest(rgb_digest)
            or (
                expected_scene_sha256 is not None
                and scene_digest != expected_scene_sha256
            )
            or isinstance(render.get("seed"), bool)
            or not isinstance(render.get("seed"), int)
            or not -(2**63) <= render["seed"] < 2**63
            or isinstance(render.get("samples_per_pixel"), bool)
            or not isinstance(render.get("samples_per_pixel"), int)
            or not 1 <= render["samples_per_pixel"] <= CPUPathTracerBackend.MAX_SAMPLES_PER_PIXEL
            or isinstance(render.get("max_depth"), bool)
            or not isinstance(render.get("max_depth"), int)
            or not 1 <= render["max_depth"] <= CPUPathTracerBackend.MAX_DEPTH
            or not isinstance(render.get("texture_asset_ids"), list)
            or len(render["texture_asset_ids"]) > 8
            or any(not isinstance(value, str) for value in render["texture_asset_ids"])
            or len(set(render["texture_asset_ids"])) != len(render["texture_asset_ids"])
        ):
            raise ImageGenerationError("Metadados de render inválidos ou não correspondentes.")
        if (
            manifest["input_source_refs_recorded"] is not False
            or manifest["source_provenance_authenticated"] is not False
            or manifest["license_status_authenticated"] is not False
            or manifest["visual_quality_assessed"] is not False
        ):
            raise ImageGenerationError("Manifesto contém alegações de confiança não suportadas.")

        input_fields = {
            "asset_id", "source_kind", "mime_type", "byte_size", "sha256",
            "width", "height", "channels", "color_space", "alpha_mode",
            "license_status_declared", "verification_status", "verification_scope",
            "license_authenticated", "provenance_authenticated",
        }
        verified_input_ids = set()
        for item in inputs:
            if not isinstance(item, dict) or set(item) != input_fields:
                raise ImageGenerationError("Descriptor de asset de entrada inválido.")
            input_id = item.get("asset_id")
            if (
                not isinstance(input_id, str)
                or input_id in verified_input_ids
                or item.get("verification_status") != "verified"
                or item.get("license_authenticated") is not False
                or item.get("provenance_authenticated") is not False
                or not isinstance(item.get("verification_scope"), list)
                or any(not isinstance(scope, str) for scope in item["verification_scope"])
                or item.get("color_space") not in {"srgb", "linear"}
            ):
                raise ImageGenerationError("Metadados de entrada inválidos.")
            try:
                input_stored = self.artifact_store.get_png(input_id)
                decoded = ImageAssetVerifier.verify_and_decode_png(
                    input_stored.asset.descriptor,
                    input_stored.content,
                    assumed_color_space=item["color_space"],
                )
            except (ArtifactStoreError, ImageAssetVerificationError) as exc:
                raise ImageGenerationError("Asset de textura não passou pela revalidação.") from exc
            input_descriptor = input_stored.asset.descriptor
            expected_input = {
                "asset_id": input_descriptor.asset_id,
                "source_kind": input_descriptor.source_kind,
                "mime_type": input_descriptor.mime_type,
                "byte_size": input_descriptor.byte_size,
                "sha256": input_descriptor.content_sha256.lower(),
                "width": input_descriptor.width,
                "height": input_descriptor.height,
                "channels": decoded.texture.channels,
                "color_space": decoded.texture.color_space,
                "alpha_mode": decoded.asset.verification.get("actual_alpha_mode"),
                "license_status_declared": input_descriptor.license_status,
                "verification_status": "verified",
                "verification_scope": list(decoded.asset.verification.get("verification_scope", ())),
                "license_authenticated": False,
                "provenance_authenticated": False,
            }
            if item != expected_input:
                raise ImageGenerationError("Descriptor de entrada diverge do ArtifactStore.")
            verified_input_ids.add(input_id)
        if verified_input_ids != set(render["texture_asset_ids"]):
            raise ImageGenerationError("Assets de entrada não correspondem às texturas do render.")

        try:
            png_report = self._validate_png(
                stored.content,
                expected_width=descriptor.width,
                expected_height=descriptor.height,
                max_dimension=CPUPathTracerBackend.MAX_DIMENSION,
                max_pixels=CPUPathTracerBackend.MAX_PIXELS,
            )
            if png_report["channels"] != 3:
                raise ImageGenerationError("Render path-traced deve ser RGB8.")
            texture = self.decode_png_texture(
                stored.content,
                color_space="srgb",
                expected_width=descriptor.width,
                expected_height=descriptor.height,
            )
        except ImageGenerationError:
            raise
        if hashlib.sha256(texture.pixels).hexdigest() != rgb_digest:
            raise ImageGenerationError("Digest RGB do manifesto diverge dos pixels armazenados.")
        return {
            "status": "verified",
            "asset_id": asset_id,
            "blob_path": str(stored.blob_path),
            "manifest_path": str(manifest_file),
            "image_sha256": image_digest,
            "manifest_sha256": manifest_digest,
            "image_asset_descriptor": descriptor.to_dict(),
            "width": descriptor.width,
            "height": descriptor.height,
            "visual_signal": png_report["visual_signal"],
            "manifest": manifest,
            "verification": {
                "artifact_store_descriptor_verified": True,
                "png_structure_and_crc_verified": True,
                "manifest_schema_and_digest_verified": True,
                "rgb_pixel_digest_verified": True,
                "input_assets_reverified": True,
                "scene_digest_matches_expected": expected_scene_sha256 is None or scene_digest == expected_scene_sha256,
                "visual_signal_measurement_scope": "low_level_pixel_signal_only",
                "visual_quality_assessed": False,
                "source_provenance_authenticated": False,
                "license_authenticated": False,
            },
        }

    def compare_render_artifacts(
        self,
        first_image_path: str | Path,
        first_manifest_path: str | Path,
        second_image_path: str | Path,
        second_manifest_path: str | Path,
    ) -> dict[str, Any]:
        """Compare two verified RGB8 renders without scoring aesthetic quality."""
        first = self.verify_render_artifact(first_image_path, first_manifest_path)
        second = self.verify_render_artifact(second_image_path, second_manifest_path)
        if (first["width"], first["height"]) != (second["width"], second["height"]):
            raise ImageGenerationError(
                "Comparação exige artefatos com as mesmas dimensões."
            )

        left = first["texture"].pixels
        right = second["texture"].pixels
        channel_abs = [0, 0, 0]
        channel_squared = [0, 0, 0]
        max_error = 0
        changed_pixels = 0
        for offset in range(0, len(left), 3):
            pixel_changed = False
            for channel in range(3):
                difference = abs(left[offset + channel] - right[offset + channel])
                channel_abs[channel] += difference
                channel_squared[channel] += difference * difference
                max_error = max(max_error, difference)
                pixel_changed = pixel_changed or difference != 0
            if pixel_changed:
                changed_pixels += 1

        pixel_count = first["width"] * first["height"]
        channel_count = pixel_count * 3
        channel_mae = [value / pixel_count for value in channel_abs]
        mae = sum(channel_abs) / channel_count
        rmse = math.sqrt(sum(channel_squared) / channel_count)
        psnr = None if rmse == 0.0 else 20.0 * math.log10(255.0 / rmse)
        return {
            "status": "compared",
            "width": first["width"],
            "height": first["height"],
            "first_image_sha256": first["image_sha256"],
            "second_image_sha256": second["image_sha256"],
            "first_manifest_sha256": first["manifest_sha256"],
            "second_manifest_sha256": second["manifest_sha256"],
            "identical_rgb_pixels": rmse == 0.0,
            "mae_rgb": mae,
            "mae_by_channel": {
                "red": channel_mae[0],
                "green": channel_mae[1],
                "blue": channel_mae[2],
            },
            "rmse_rgb": rmse,
            "psnr_db": psnr,
            "max_channel_error": max_error,
            "changed_pixel_count": changed_pixels,
            "changed_pixel_fraction": changed_pixels / pixel_count,
            "first_visual_signal": first["visual_signal"],
            "second_visual_signal": second["visual_signal"],
            "metric_scope": "bounded_rgb8_pixel_difference_only",
            "semantic_equivalence_assessed": False,
            "visual_quality_assessed": False,
        }

    @staticmethod
    def _measure_visual_signal(
        raw: bytes, width: int, height: int, channels: int = 3
    ) -> dict[str, Any]:
        """Measure bounded RGB signal statistics; this is not an aesthetic quality score."""
        stride = width * channels
        pixel_count = width * height
        histogram = [0] * 16
        channel_histograms = [[0] * 16 for _ in range(3)]
        channel_sum = [0, 0, 0]
        channel_square_sum = [0, 0, 0]
        channel_min = [255, 255, 255]
        channel_max = [0, 0, 0]
        luminance_sum = 0
        luminance_square_sum = 0
        minimum_luminance = 255
        maximum_luminance = 0
        clipped_pixels = 0
        saturation_sum = 0.0
        high_saturation_pixels = 0
        horizontal_difference = 0
        vertical_difference = 0
        strong_edge_pairs = 0
        horizontal_pairs = height * max(0, width - 1)
        vertical_pairs = max(0, height - 1) * width
        previous_row: list[int] | None = None

        for y in range(height):
            row_offset = y * stride
            current_row: list[int] = []
            previous_luminance: int | None = None
            for x in range(width):
                offset = row_offset + x * channels
                red, green, blue = raw[offset], raw[offset + 1], raw[offset + 2]
                rgb = (red, green, blue)
                for channel, value in enumerate(rgb):
                    channel_sum[channel] += value
                    channel_square_sum[channel] += value * value
                    channel_min[channel] = min(channel_min[channel], value)
                    channel_max[channel] = max(channel_max[channel], value)
                    channel_histograms[channel][value >> 4] += 1
                maximum_rgb = max(rgb)
                minimum_rgb = min(rgb)
                saturation = (
                    (maximum_rgb - minimum_rgb) / maximum_rgb
                    if maximum_rgb else 0.0
                )
                saturation_sum += saturation
                if saturation >= 0.75:
                    high_saturation_pixels += 1

                luminance = (2126 * red + 7152 * green + 722 * blue) // 10000
                current_row.append(luminance)
                luminance_sum += luminance
                luminance_square_sum += luminance * luminance
                minimum_luminance = min(minimum_luminance, luminance)
                maximum_luminance = max(maximum_luminance, luminance)
                histogram[luminance >> 4] += 1
                if red <= 1 or green <= 1 or blue <= 1 or red >= 254 or green >= 254 or blue >= 254:
                    clipped_pixels += 1
                if previous_luminance is not None:
                    difference = abs(luminance - previous_luminance)
                    horizontal_difference += difference
                    if difference >= 16:
                        strong_edge_pairs += 1
                if previous_row is not None:
                    difference = abs(luminance - previous_row[x])
                    vertical_difference += difference
                    if difference >= 16:
                        strong_edge_pairs += 1
                previous_luminance = luminance
            previous_row = current_row

        mean = luminance_sum / pixel_count
        variance = max(0.0, luminance_square_sum / pixel_count - mean * mean)
        standard_deviation = math.sqrt(variance)
        edge_pairs = horizontal_pairs + vertical_pairs
        edge_mean = (
            (horizontal_difference + vertical_difference) / edge_pairs
            if edge_pairs else 0.0
        )
        edge_fraction = strong_edge_pairs / edge_pairs if edge_pairs else 0.0
        entropy = 0.0
        for bucket_count in histogram:
            if bucket_count:
                probability = bucket_count / pixel_count
                entropy -= probability * math.log2(probability)

        channel_means = [value / pixel_count for value in channel_sum]
        channel_stddevs = [
            math.sqrt(max(
                0.0,
                channel_square_sum[index] / pixel_count
                - channel_means[index] * channel_means[index],
            ))
            for index in range(3)
        ]
        channel_entropy = []
        for channel_histogram in channel_histograms:
            entropy_value = 0.0
            for bucket_count in channel_histogram:
                if bucket_count:
                    probability = bucket_count / pixel_count
                    entropy_value -= probability * math.log2(probability)
            channel_entropy.append(round(entropy_value, 4))

        if standard_deviation < 1.0 and edge_mean < 0.5:
            signal_state = "uniform_or_blank"
        elif maximum_luminance - minimum_luminance < 8:
            signal_state = "low_dynamic_range"
        else:
            signal_state = "non_uniform_signal"

        return {
            "signal_state": signal_state,
            "pixel_count": pixel_count,
            "luminance_mean": round(mean, 4),
            "luminance_stddev": round(standard_deviation, 4),
            "luminance_min": minimum_luminance,
            "luminance_max": maximum_luminance,
            "luminance_range": maximum_luminance - minimum_luminance,
            "luminance_entropy_16bin_bits": round(entropy, 4),
            "rgb_channel_mean": {
                "red": round(channel_means[0], 4),
                "green": round(channel_means[1], 4),
                "blue": round(channel_means[2], 4),
            },
            "rgb_channel_stddev": {
                "red": round(channel_stddevs[0], 4),
                "green": round(channel_stddevs[1], 4),
                "blue": round(channel_stddevs[2], 4),
            },
            "rgb_channel_range": {
                "red": channel_max[0] - channel_min[0],
                "green": channel_max[1] - channel_min[1],
                "blue": channel_max[2] - channel_min[2],
            },
            "rgb_channel_entropy_16bin_bits": {
                "red": channel_entropy[0],
                "green": channel_entropy[1],
                "blue": channel_entropy[2],
            },
            "mean_saturation_fraction": round(saturation_sum / pixel_count, 6),
            "high_saturation_pixel_fraction": round(
                high_saturation_pixels / pixel_count, 6
            ),
            "mean_neighbor_luminance_difference": round(edge_mean, 4),
            "strong_edge_pair_fraction": round(edge_fraction, 6),
            "clipped_pixel_fraction": round(clipped_pixels / pixel_count, 6),
            "measurement_scope": "low_level_pixel_signal_only",
            "artistic_quality_assessed": False,
        }

    @staticmethod
    def _unfilter_png_pixels(
        raw: bytes, width: int, height: int, channels: int
    ) -> bytes:
        """Reverse PNG scanline filters 0-4 for bounded RGB8/RGBA8 rows."""
        stride = width * channels
        expected_size = height * (stride + 1)
        if len(raw) != expected_size:
            raise ImageGenerationError("Tamanho de scanlines PNG inválido.")
        output = bytearray(width * height * channels)
        previous = bytearray(stride)
        offset = 0
        for row in range(height):
            filter_type = raw[offset]
            source = raw[offset + 1:offset + 1 + stride]
            offset += stride + 1
            if filter_type not in (0, 1, 2, 3, 4):
                raise ImageGenerationError("Filtro de scanline PNG não suportado.")
            reconstructed = bytearray(stride)
            for index, value in enumerate(source):
                left = reconstructed[index - channels] if index >= channels else 0
                above = previous[index]
                upper_left = previous[index - channels] if index >= channels else 0
                if filter_type == 0:
                    predictor = 0
                elif filter_type == 1:
                    predictor = left
                elif filter_type == 2:
                    predictor = above
                elif filter_type == 3:
                    predictor = (left + above) // 2
                else:
                    estimate = left + above - upper_left
                    distance_left = abs(estimate - left)
                    distance_above = abs(estimate - above)
                    distance_upper_left = abs(estimate - upper_left)
                    if distance_left <= distance_above and distance_left <= distance_upper_left:
                        predictor = left
                    elif distance_above <= distance_upper_left:
                        predictor = above
                    else:
                        predictor = upper_left
                reconstructed[index] = (value + predictor) & 0xFF
            output[row * stride:(row + 1) * stride] = reconstructed
            previous = reconstructed
        return bytes(output)

    @classmethod
    def _validate_png(
        cls,
        png: bytes,
        expected_width: int | None = None,
        expected_height: int | None = None,
        max_dimension: int | None = None,
        max_pixels: int | None = None,
    ) -> dict[str, Any]:
        """Validate bounded non-interlaced RGB8/RGBA8 PNG structure and pixels."""
        dimension_limit = cls.MAX_DIMENSION if max_dimension is None else max_dimension
        pixel_limit = cls.MAX_PIXELS if max_pixels is None else max_pixels
        if (
            isinstance(dimension_limit, bool) or not isinstance(dimension_limit, int)
            or dimension_limit < 1
            or isinstance(pixel_limit, bool) or not isinstance(pixel_limit, int)
            or pixel_limit < 1
        ):
            raise ImageGenerationError("Limites de dimensão/pixels inválidos.")
        dimension_limit = min(cls.MAX_DIMENSION, dimension_limit)
        pixel_limit = min(cls.MAX_PIXELS, pixel_limit)
        signature = b"\x89PNG\r\n\x1a\n"
        if not isinstance(png, bytes) or not png.startswith(signature):
            raise ImageGenerationError("Assinatura PNG inválida.")
        if len(png) > cls.MAX_PNG_BYTES:
            raise ImageGenerationError("PNG excede o limite de bytes permitido.")

        offset = len(signature)
        chunks = []
        while offset < len(png):
            if len(png) - offset < 12:
                raise ImageGenerationError("Chunk PNG truncado.")
            length = struct.unpack(">I", png[offset:offset + 4])[0]
            if length > cls.MAX_PNG_BYTES or offset + 12 + length > len(png):
                raise ImageGenerationError("Comprimento de chunk PNG inválido.")
            kind = png[offset + 4:offset + 8]
            payload_start = offset + 8
            payload_end = payload_start + length
            payload = png[payload_start:payload_end]
            expected_crc = struct.unpack(">I", png[payload_end:payload_end + 4])[0]
            actual_crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
            if actual_crc != expected_crc:
                raise ImageGenerationError("CRC de chunk PNG inválido.")
            chunks.append((kind, payload))
            offset = payload_end + 4
            if kind == b"IEND":
                break

        if offset != len(png):
            raise ImageGenerationError("Dados extras após IEND.")
        kinds = [kind for kind, _ in chunks]
        srgb_chunks = [payload for kind, payload in chunks if kind == b"sRGB"]
        idat_positions = [index for index, kind in enumerate(kinds) if kind == b"IDAT"]
        if (
            len(kinds) < 3
            or kinds[0] != b"IHDR"
            or kinds[-1] != b"IEND"
            or any(kind not in (b"IHDR", b"sRGB", b"IDAT", b"IEND") for kind in kinds)
            or len(srgb_chunks) > 1
            or not idat_positions
        ):
            raise ImageGenerationError("Ordem ou conjunto de chunks PNG não suportado.")
        first_idat, last_idat = idat_positions[0], idat_positions[-1]
        expected_kinds = (
            [b"IHDR"]
            + ([b"sRGB"] if srgb_chunks else [])
            + [b"IDAT"] * len(idat_positions)
            + [b"IEND"]
        )
        if kinds != expected_kinds or idat_positions != list(range(first_idat, last_idat + 1)):
            raise ImageGenerationError("Chunks sRGB/IDAT fora de ordem ou não contíguos.")
        if len(chunks[-1][1]) != 0:
            raise ImageGenerationError("Chunk IEND deve estar vazio.")
        if srgb_chunks and (
            len(srgb_chunks[0]) != 1 or srgb_chunks[0][0] > 3
        ):
            raise ImageGenerationError("Chunk sRGB inválido.")
        header = chunks[0][1]
        if len(header) != 13:
            raise ImageGenerationError("IHDR PNG possui tamanho inválido.")
        width, height, bit_depth, color_type, compression, filtering, interlace = (
            struct.unpack(">IIBBBBB", header)
        )
        if (
            width < 1 or height < 1
            or width > dimension_limit or height > dimension_limit
            or width * height > pixel_limit
        ):
            raise ImageGenerationError("Dimensões PNG fora do orçamento permitido.")
        if expected_width is not None and width != expected_width:
            raise ImageGenerationError("Largura PNG diverge da solicitação.")
        if expected_height is not None and height != expected_height:
            raise ImageGenerationError("Altura PNG diverge da solicitação.")
        if (
            bit_depth != 8 or color_type not in (2, 6)
            or compression != 0 or filtering != 0 or interlace != 0
        ):
            raise ImageGenerationError(
                "Perfil PNG incompatível; esperado RGB8/RGBA8 não entrelaçado."
            )
        channels = 3 if color_type == 2 else 4

        expected_raw_size = height * (1 + width * channels)
        decoder = zlib.decompressobj()
        try:
            compressed_idat = b"".join(
                payload for kind, payload in chunks if kind == b"IDAT"
            )
            raw = decoder.decompress(compressed_idat, expected_raw_size + 1)
            if len(raw) > expected_raw_size or decoder.unconsumed_tail:
                raise ImageGenerationError("Dados descomprimidos excedem as dimensões PNG.")
            remaining = expected_raw_size + 1 - len(raw)
            raw += decoder.flush(remaining)
        except zlib.error as exc:
            raise ImageGenerationError("Fluxo zlib do PNG inválido.") from exc
        if (
            len(raw) != expected_raw_size
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            raise ImageGenerationError("Dados IDAT não correspondem às dimensões PNG.")

        stride = width * channels
        filters_used = sorted({
            raw[row * (stride + 1)] for row in range(height)
        })
        if any(filter_type not in (0, 1, 2, 3, 4) for filter_type in filters_used):
            raise ImageGenerationError("Filtro de scanline PNG não suportado.")
        pixels = cls._unfilter_png_pixels(raw, width, height, channels)

        return {
            "valid": True,
            "width": width,
            "height": height,
            "bit_depth": bit_depth,
            "color_type": "truecolor_rgb" if channels == 3 else "truecolor_rgba",
            "channels": channels,
            "interlace": False,
            "scanline_filter": filters_used[0] if len(filters_used) == 1 else "mixed",
            "scanline_filters_used": filters_used,
            "source_color_space": "srgb" if srgb_chunks else "unspecified",
            "validation_scope": "png_structure_and_decoded_pixels",
            "visual_signal": cls._measure_visual_signal(pixels, width, height, channels),
        }

    @classmethod
    def decode_png_texture(
        cls,
        png: bytes,
        *,
        color_space: str,
        expected_width: int | None = None,
        expected_height: int | None = None,
    ) -> TextureBuffer:
        """Decode the engine's bounded RGB8/RGBA8 PNG profile into a texture buffer."""
        validation = cls._validate_png(
            png,
            expected_width=expected_width,
            expected_height=expected_height,
            max_dimension=TextureBuffer.MAX_DIMENSION,
            max_pixels=TextureBuffer.MAX_PIXELS,
        )
        width, height = validation["width"], validation["height"]
        if validation["source_color_space"] == "srgb" and color_space != "srgb":
            raise ImageGenerationError(
                "color_space informado diverge do chunk sRGB do PNG."
            )
        offset = 8
        idat = bytearray()
        while offset < len(png):
            length = struct.unpack(">I", png[offset:offset + 4])[0]
            kind = png[offset + 4:offset + 8]
            payload_start = offset + 8
            payload_end = payload_start + length
            if kind == b"IDAT":
                idat.extend(png[payload_start:payload_end])
            offset = payload_end + 4
            if kind == b"IEND":
                break

        channels = validation["channels"]
        expected_raw_size = height * (1 + width * channels)
        decoder = zlib.decompressobj()
        try:
            raw = decoder.decompress(bytes(idat), expected_raw_size + 1)
            if len(raw) > expected_raw_size or decoder.unconsumed_tail:
                raise ImageGenerationError("PNG descomprimido excede o orçamento.")
            raw += decoder.flush(expected_raw_size + 1 - len(raw))
        except zlib.error as exc:
            raise ImageGenerationError("Fluxo zlib do PNG inválido.") from exc
        if (
            len(raw) != expected_raw_size
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            raise ImageGenerationError("PNG descomprimido não corresponde às dimensões.")

        pixels = cls._unfilter_png_pixels(raw, width, height, channels)
        return TextureBuffer(
            width, height, pixels, color_space=color_space, channels=channels
        )

    def _store_png(
        self,
        png: bytes,
        expected_width: int | None = None,
        expected_height: int | None = None,
        *,
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        """Verify and commit PNG bytes through the shared content-addressed store."""
        from .artifact_store import ArtifactStore, ArtifactStoreError, ArtifactStoreDurabilityError

        png_validation = self._validate_png(
            png, expected_width=expected_width, expected_height=expected_height
        )
        digest = hashlib.sha256(png).hexdigest()
        try:
            stored = self.artifact_store.put_png(
                png,
                source_kind="generated",
                source_ref=source_ref or f"artifact://sha256/{digest}",
                license_status="unknown",
                declared_sha256=digest,
                declared_width=png_validation["width"],
                declared_height=png_validation["height"],
            )
        except ArtifactStoreDurabilityError as exc:
            raise ImageArtifactDurabilityError(
                "O blob PNG foi vinculado, mas a durabilidade do diretório não foi confirmada."
            ) from exc
        except ArtifactStoreError as exc:
            raise ImageGenerationError(
                "PNG passou pela validação, mas o ArtifactStore não confirmou a gravação."
            ) from exc

        descriptor = stored.asset.descriptor
        return {
            "artifact_path": str(stored.blob_path),
            "asset_id": descriptor.asset_id,
            "artifact_store_schema": ArtifactStore.SCHEMA,
            "sha256": digest,
            "byte_size": len(stored.content),
            "png_validation": png_validation,
            "image_asset_descriptor": descriptor.to_dict(),
            "artifact_integrity": {
                "status": "verified",
                "content_integrity_verified": True,
                "verification_scope": [
                    "png_structure_and_decoded_size",
                    "sha256_of_supplied_bytes",
                    "content_addressed_atomic_blob_commit",
                    "immutable_blob_path_derived_from_sha256",
                ],
                "sha256": digest,
                "byte_size": len(stored.content),
                "asset_id": descriptor.asset_id,
                "store_schema": ArtifactStore.SCHEMA,
                "license_verified": False,
                "visual_quality_assessed": False,
            },
        }

    def _store_render_manifest(
        self,
        image_sha256: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically store a bounded lineage manifest in the image artifact root."""
        if (
            not isinstance(image_sha256, str)
            or len(image_sha256) != 64
            or any(character not in "0123456789abcdef" for character in image_sha256)
        ):
            raise ImageGenerationError("Digest do PNG inválido para o manifesto.")
        try:
            payload = json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ImageRenderManifestError(
                "PNG armazenado, mas o manifesto de linhagem não pôde ser serializado.",
                manifest_committed=False,
            ) from exc
        if not payload or len(payload) > 65_536:
            raise ImageRenderManifestError(
                "PNG armazenado, mas o manifesto excede 64 KiB.",
                manifest_committed=False,
            )

        manifest_sha256 = hashlib.sha256(payload).hexdigest()
        destination = self.artifact_root / (
            f"image-{image_sha256[:24]}-{manifest_sha256[:16]}.manifest.json"
        )
        temporary_name = None
        replaced = False
        try:
            if (
                self.artifact_root.is_symlink()
                or self.artifact_root.resolve(strict=False) != self.artifact_root
            ):
                raise ImageGenerationError("artifact_root mudou para um caminho não canônico.")
            self.artifact_root.mkdir(parents=True, exist_ok=True)
            if (
                self.artifact_root.is_symlink()
                or not self.artifact_root.is_dir()
                or self.artifact_root.resolve(strict=True) != self.artifact_root
            ):
                raise ImageGenerationError("artifact_root não é um diretório estável e canônico.")

            if os.path.lexists(destination):
                stored = self._read_existing_artifact(destination)
                if stored != payload:
                    raise ImageGenerationError("Manifesto existente diverge do conteúdo esperado.")
            else:
                fd, temporary_name = tempfile.mkstemp(
                    prefix=".mahoraga-manifest-", suffix=".tmp", dir=self.artifact_root
                )
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, destination)
                replaced = True
                temporary_name = None
                try:
                    directory_fd = os.open(
                        self.artifact_root,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                    )
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except OSError as exc:
                    raise ImageRenderManifestError(
                        "O PNG e o manifesto foram substituídos, mas a durabilidade "
                        "do diretório não pôde ser confirmada.",
                        manifest_committed=True,
                    ) from exc

            stored = self._read_existing_artifact(destination)
            if stored != payload or hashlib.sha256(stored).hexdigest() != manifest_sha256:
                raise ImageGenerationError("A validação do manifesto armazenado falhou.")
        except ImageRenderManifestError:
            raise
        except Exception as exc:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
            raise ImageRenderManifestError(
                "O PNG foi armazenado, mas o manifesto de linhagem não foi confirmado.",
                manifest_committed=replaced,
            ) from exc

        return {
            "manifest_path": str(destination),
            "manifest_sha256": manifest_sha256,
            "manifest_byte_size": len(payload),
            "manifest_integrity_verified": True,
        }

    def generate_procedural(
        self, width: int, height: int, *, seed: int = 0,
        cancellation_token: CancellationToken | None = None,
    ) -> dict[str, Any]:
        if cancellation_token is not None and not isinstance(cancellation_token, CancellationToken):
            raise ImageGenerationError("cancellation_token deve ser um CancellationToken.")
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        png = self.procedural.render(
            width, height, seed, cancellation_token=cancellation_token
        )
        if cancellation_token is not None and not cancellation_token.begin_commit():
            raise OperationCancelled("operation_cancelled_before_artifact_commit")
        return {
            "schema": "mahoraga.generated_image", "status": "completed",
            "backend": self.procedural.BACKEND_ID, "engine_version": self.VERSION,
            "width": width, "height": height, "seed": seed, "format": "png",
            **self._store_png(png, width, height), "deterministic": True, "validated": True,
            "artifact_validated": True,
            "validation_scope": "png_structure_and_artifact_integrity",
            "visual_quality_validated": False,
            "neural_model_used": False, "blender_required": False, "path_tracing": False,
        }

    def generate_path_traced(self, width: int, height: int, *,
                             scene: SceneSpec | dict[str, Any] | None = None,
                             seed: int = 0, samples_per_pixel: int = 1,
                             max_depth: int = 3,
                             cancellation_token: CancellationToken | None = None) -> dict[str, Any]:
        if cancellation_token is not None and not isinstance(cancellation_token, CancellationToken):
            raise ImageGenerationError("cancellation_token deve ser um CancellationToken.")
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        resolved_scene = (
            SceneSpec.default() if scene is None
            else scene if isinstance(scene, SceneSpec)
            else SceneSpec.from_mapping(scene)
        )
        rgb = self.path_tracer.render_rgb(
            width, height, scene=resolved_scene, seed=seed,
            samples_per_pixel=samples_per_pixel, max_depth=max_depth,
            cancellation_token=cancellation_token,
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        png = self.procedural._encode_png(width, height, rgb)
        if cancellation_token is not None and not cancellation_token.begin_commit():
            raise OperationCancelled("operation_cancelled_before_artifact_commit")
        return {
            "schema": "mahoraga.generated_image", "status": "completed",
            "backend": self.path_tracer.BACKEND_ID, "engine_version": self.VERSION,
            "renderer_version": self.path_tracer.VERSION, "width": width, "height": height,
            "seed": seed, "samples_per_pixel": samples_per_pixel, "max_depth": max_depth,
            "scene_schema": SceneSpec.SCHEMA,
            "scene_sha256": resolved_scene.sha256(), "scene": resolved_scene.to_dict(),
            "format": "png",
            **self._store_png(png, width, height), "deterministic": True, "validated": True,
            "artifact_validated": True,
            "validation_scope": "png_structure_and_artifact_integrity",
            "visual_quality_validated": False,
            "neural_model_used": False, "blender_required": False, "path_tracing": True,
        }

    def generate_path_traced_with_catalog(
        self,
        width: int,
        height: int,
        *,
        scene: SceneSpec | dict[str, Any],
        texture_catalog: Any,
        seed: int = 0,
        samples_per_pixel: int = 1,
        max_depth: int = 3,
        cancellation_token: CancellationToken | None = None,
        visual_provenance: Any = None,
    ) -> dict[str, Any]:
        """Render with verified image inputs and store the validated PNG artifact."""
        from .image_asset_verifier import ImageAssetVerificationError, ImageTextureCatalog

        if cancellation_token is not None and not isinstance(cancellation_token, CancellationToken):
            raise ImageGenerationError("cancellation_token deve ser um CancellationToken.")
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if not isinstance(texture_catalog, ImageTextureCatalog):
            raise ImageGenerationError(
                "texture_catalog deve ser um ImageTextureCatalog verificado."
            )
        try:
            resolved_scene = (
                scene if isinstance(scene, SceneSpec) else SceneSpec.from_mapping(scene)
            )
            rendered = texture_catalog.render_rgb(
                resolved_scene,
                width,
                height,
                seed=seed,
                samples_per_pixel=samples_per_pixel,
                max_depth=max_depth,
                cancellation_token=cancellation_token,
            )
        except (ImageAssetVerificationError, TypeError, ValueError) as exc:
            raise ImageGenerationError(
                "Falha na validação da cena ou no render com texturas verificadas."
            ) from exc

        visual_provenance_payload = None
        if visual_provenance is not None:
            visual_provenance_payload = self._validate_visual_document_provenance(
                visual_provenance, scene_sha256=resolved_scene.sha256()
            )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        png = self.procedural._encode_png(width, height, rendered.rgb_pixels)
        if cancellation_token is not None and not cancellation_token.begin_commit():
            raise OperationCancelled("operation_cancelled_before_artifact_commit")
        stored = self._store_png(
            png, width, height,
            source_ref=(
                f"mahoraga://visual-document/{visual_provenance_payload['source_document_sha256']}"
                if visual_provenance_payload is not None else None
            ),
        )
        used_ids = set(rendered.texture_asset_ids)
        input_assets = []
        for item in texture_catalog.assets:
            descriptor = item.asset.descriptor
            if descriptor.asset_id not in used_ids:
                continue
            evidence = item.asset.verification
            input_assets.append({
                "asset_id": descriptor.asset_id,
                "source_kind": descriptor.source_kind,
                "mime_type": descriptor.mime_type,
                "byte_size": descriptor.byte_size,
                "sha256": descriptor.content_sha256.lower(),
                "width": descriptor.width,
                "height": descriptor.height,
                "channels": item.texture.channels,
                "color_space": evidence.get("resolved_color_space"),
                "alpha_mode": evidence.get("actual_alpha_mode"),
                "license_status_declared": descriptor.license_status,
                "verification_status": evidence.get("status"),
                "verification_scope": list(evidence.get("verification_scope", ())),
                "license_authenticated": False,
                "provenance_authenticated": False,
            })
        manifest = {
            "schema": (
                "mahoraga.image_render_manifest.v2"
                if visual_provenance_payload is not None
                else "mahoraga.image_render_manifest.v1"
            ),
            "output": {
                "asset_id": stored["image_asset_descriptor"]["asset_id"],
                "source_kind": "generated",
                "mime_type": "image/png",
                "byte_size": stored["byte_size"],
                "sha256": stored["sha256"],
                "width": width,
                "height": height,
                "orientation_degrees": 0,
                "color_space": "unknown",
                "alpha_mode": "opaque",
                "license_status_declared": "unknown",
            },
            "render": {
                "backend": rendered.renderer_backend,
                "renderer_version": rendered.renderer_version,
                "engine_version": self.VERSION,
                "scene_schema": SceneSpec.SCHEMA,
                "scene_sha256": resolved_scene.sha256(),
                "rgb_sha256": rendered.sha256,
                "texture_asset_ids": list(rendered.texture_asset_ids),
                "seed": seed,
                "samples_per_pixel": samples_per_pixel,
                "max_depth": max_depth,
            },
            "input_assets": input_assets,
            "input_source_refs_recorded": False,
            "source_provenance_authenticated": False,
            "license_status_authenticated": False,
            "visual_quality_assessed": False,
        }
        if visual_provenance_payload is not None:
            manifest["visual_document"] = visual_provenance_payload
        manifest_stored = self._store_render_manifest(stored["sha256"], manifest)
        return {
            "schema": "mahoraga.generated_image",
            "status": "completed",
            "backend": rendered.renderer_backend,
            "engine_version": self.VERSION,
            "renderer_version": rendered.renderer_version,
            "width": width,
            "height": height,
            "seed": seed,
            "samples_per_pixel": samples_per_pixel,
            "max_depth": max_depth,
            "scene_schema": SceneSpec.SCHEMA,
            "scene_sha256": resolved_scene.sha256(),
            "scene": resolved_scene.to_dict(),
            "format": "png",
            **stored,
            **manifest_stored,
            "lineage_manifest": manifest,
            "visual_document_provenance": visual_provenance_payload,
            "render_rgb_sha256": rendered.sha256,
            "texture_asset_ids": list(rendered.texture_asset_ids),
            "texture_catalog": texture_catalog.to_dict(),
            "texture_inputs_verified": True,
            "input_sources_opened": False,
            "deterministic": True,
            "validated": True,
            "artifact_validated": True,
            "validation_scope": "verified_texture_inputs_png_structure_and_artifact_integrity",
            "visual_quality_validated": False,
            "neural_model_used": False,
            "blender_required": False,
            "path_tracing": True,
            "pixels_persisted": True,
        }

    def status(self) -> dict[str, Any]:
        return {
            "component": "ImageGenerationEngine", "version": self.VERSION,
            "available_backends": [self.procedural.BACKEND_ID, self.path_tracer.BACKEND_ID],
            "neural_generation_available": False, "path_tracing_available": True,
            "path_tracer_status": self.path_tracer.status(),
            "runtime_dispatch_enabled": False, "blender_required": False,
            "cancellation": True,
            "cancellation_granularity": "procedural_rows_and_pathtracer_pixels",
            "artifact_root": str(self.artifact_root),
            "artifact_store": {
                "schema": "mahoraga.artifact_store.v1",
                "supported_media_types": ["image/png"],
                "content_addressed": True,
                "initialized": self._artifact_store is not None,
                "generated_output_storage": True,
                "input_asset_resolution": "IntegratedCore",
            },
            "status": "implemented_unvalidated",
        }
