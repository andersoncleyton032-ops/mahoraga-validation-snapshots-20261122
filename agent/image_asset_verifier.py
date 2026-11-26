"""Verify supplied PNG bytes against a strict, bounded image profile."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
import hashlib
from typing import Any

from .image_asset import ImageAssetContractError, ImageAssetDescriptor
from .cpu_path_tracer import CPUPathTracerBackend, SceneSpec, TextureBuffer
from .image_generation import ImageGenerationEngine, ImageGenerationError
from .cancellation import CancellationToken


class ImageAssetVerificationError(ValueError):
    """Image bytes failed format, integrity, or metadata verification."""


def _freeze_evidence(value: Any) -> Any:
    """Defensively freeze nested verification evidence before exposing it."""
    if isinstance(value, dict):
        return MappingProxyType({
            key: _freeze_evidence(item) for key, item in value.items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_evidence(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_evidence(item) for item in value)
    return value


@dataclass(frozen=True)
class VerifiedImageAsset:
    """Result for bytes already supplied by a trusted host boundary.

    This verifier never opens a path, resolves a URI, performs network access,
    or requests Android permissions. It verifies only the bytes passed in.
    """

    descriptor: ImageAssetDescriptor
    verification: dict[str, Any]

    def __post_init__(self):
        if not isinstance(self.verification, dict):
            raise ImageAssetVerificationError("Evidência de verificação deve ser um dicionário.")
        object.__setattr__(self, "verification", _freeze_evidence(self.verification))

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptor": self.descriptor.to_dict(),
            "verification": dict(self.verification),
        }


@dataclass(frozen=True)
class DecodedTextureAsset:
    """Verified image with a bounded RGB8/RGBA8 texture buffer."""

    asset: VerifiedImageAsset
    texture: TextureBuffer

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.asset.to_dict(),
            "decoded_pixels": {
                "format": "RGBA8" if self.texture.channels == 4 else "RGB8",
                "channels": self.texture.channels,
                "byte_size": len(self.texture.pixels),
                "pixel_buffer_returned": True,
                "decoder_scope": "validated_png_filters_0_to_4",
            },
        }


@dataclass(frozen=True)
class DecodedImageAsset:
    """Verified RGB8 pixel buffer ready for downstream visual processing."""

    asset: VerifiedImageAsset
    rgb_pixels: bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.asset.to_dict(),
            "decoded_pixels": {
                "format": "RGB8",
                "byte_size": len(self.rgb_pixels),
                "pixel_buffer_returned": True,
                "decoder_scope": "validated_png_filters_0_to_4",
            },
        }


@dataclass(frozen=True)
class VerifiedTextureRender:
    """Bounded RGB8 render produced from a verified texture catalog."""

    width: int
    height: int
    rgb_pixels: bytes
    sha256: str
    renderer_backend: str
    renderer_version: str
    texture_asset_ids: tuple[str, ...]
    seed: int
    samples_per_pixel: int
    max_depth: int

    def __post_init__(self):
        if (
            isinstance(self.width, bool) or not isinstance(self.width, int)
            or isinstance(self.height, bool) or not isinstance(self.height, int)
            or self.width < 1 or self.height < 1
            or not isinstance(self.rgb_pixels, bytes)
            or len(self.rgb_pixels) != self.width * self.height * 3
            or hashlib.sha256(self.rgb_pixels).hexdigest() != self.sha256
        ):
            raise ImageAssetVerificationError("Resultado RGB renderizado inconsistente.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "RGB8",
            "width": self.width,
            "height": self.height,
            "byte_size": len(self.rgb_pixels),
            "sha256": self.sha256,
            "renderer_backend": self.renderer_backend,
            "renderer_version": self.renderer_version,
            "texture_asset_ids": list(self.texture_asset_ids),
            "seed": self.seed,
            "samples_per_pixel": self.samples_per_pixel,
            "max_depth": self.max_depth,
            "pixels_persisted": False,
        }


@dataclass(frozen=True)
class ImageTextureCatalog:
    """Bounded handoff from verified decoded assets to renderer texture IDs."""

    assets: tuple[DecodedTextureAsset, ...]

    MAX_TEXTURES = 8
    MAX_BYTES = 16 * 1024 * 1024

    def __post_init__(self):
        if not isinstance(self.assets, (tuple, list)):
            raise ImageAssetVerificationError("Assets do catálogo devem formar uma sequência.")
        assets = tuple(self.assets)
        if len(assets) > self.MAX_TEXTURES:
            raise ImageAssetVerificationError("Catálogo excede oito texturas.")
        identifiers = set()
        total_bytes = 0
        for item in assets:
            if (
                not isinstance(item, DecodedTextureAsset)
                or not isinstance(item.asset, VerifiedImageAsset)
                or not isinstance(item.texture, TextureBuffer)
                or not isinstance(item.asset.descriptor, ImageAssetDescriptor)
            ):
                raise ImageAssetVerificationError("Catálogo aceita apenas assets decodificados e tipados.")
            descriptor = item.asset.descriptor
            report = item.asset.verification
            actual_alpha = "straight" if item.texture.channels == 4 else "opaque"
            if (
                report.get("status") != "verified"
                or report.get("sha256_verified") is not True
                or report.get("byte_size_verified") is not True
                or report.get("pixel_decode_verified") is not True
                or descriptor.mime_type != "image/png"
                or report.get("actual_mime_type") != descriptor.mime_type
                or report.get("descriptor_color_space") != descriptor.color_space
                or report.get("resolved_color_space") != item.texture.color_space
                or report.get("actual_byte_size") != descriptor.byte_size
                or report.get("actual_sha256") != descriptor.content_sha256.lower()
                or report.get("actual_width") != descriptor.width
                or report.get("actual_height") != descriptor.height
                or report.get("actual_channels") != item.texture.channels
                or report.get("actual_alpha_mode") != actual_alpha
                or report.get("source_opened") is not False
                or report.get("source_ref_opened") is not False
                or report.get("network_accessed") is not False
                or report.get("android_permission_requested") is not False
            ):
                raise ImageAssetVerificationError("Asset não possui evidência coerente de verificação completa.")
            if item.texture.width != descriptor.width or item.texture.height != descriptor.height:
                raise ImageAssetVerificationError("Dimensões do buffer divergem do descriptor.")
            if descriptor.alpha_mode not in ("unknown", actual_alpha):
                raise ImageAssetVerificationError("Modo alpha do descriptor diverge do buffer.")
            asset_id = descriptor.asset_id
            if asset_id in identifiers:
                raise ImageAssetVerificationError(f"asset_id duplicado no catálogo: {asset_id}.")
            identifiers.add(asset_id)
            total_bytes += len(item.texture.pixels)
        if total_bytes > self.MAX_BYTES:
            raise ImageAssetVerificationError("Catálogo excede 16 MiB de pixels.")
        object.__setattr__(self, "assets", assets)

    @property
    def total_bytes(self) -> int:
        return sum(len(item.texture.pixels) for item in self.assets)

    def as_texture_map(self) -> dict[str, TextureBuffer]:
        return {
            item.asset.descriptor.asset_id: item.texture
            for item in self.assets
        }

    def resolve_for_scene(self, scene: Any) -> dict[str, TextureBuffer]:
        """Return a fresh texture map only if every scene image reference resolves."""
        if not isinstance(scene, SceneSpec):
            raise ImageAssetVerificationError("A cena deve ser um SceneSpec validado.")
        textures = self.as_texture_map()
        try:
            CPUPathTracerBackend._validate_texture_buffers(scene, textures)
        except (TypeError, ValueError) as exc:
            raise ImageAssetVerificationError(
                "Catálogo não resolve todas as texturas exigidas pela cena."
            ) from exc
        return textures

    @staticmethod
    def texture_asset_ids_for_scene(scene: SceneSpec) -> tuple[str, ...]:
        """Return only texture IDs actually referenced by scene materials."""
        materials = [
            *scene.spheres, *scene.triangles, *scene.planes, *scene.disks,
            *scene.boxes, *scene.oriented_boxes, *scene.cylinders,
            *scene.capsules, *scene.cones,
        ]
        for mesh in scene.meshes:
            materials.extend(mesh._triangles)
        return tuple(sorted({
            material.texture_id
            for material in materials
            if material.texture_pattern == "image" and material.texture_id is not None
        }))

    def render_rgb(
        self,
        scene: SceneSpec,
        width: int,
        height: int,
        *,
        seed: int = 0,
        samples_per_pixel: int = 1,
        max_depth: int = 3,
        cancellation_token: CancellationToken | None = None,
    ) -> VerifiedTextureRender:
        """Render a validated scene using only the catalog's verified texture buffers."""
        textures = self.resolve_for_scene(scene)
        try:
            pixels = CPUPathTracerBackend.render_rgb(
                width,
                height,
                scene=scene,
                seed=seed,
                samples_per_pixel=samples_per_pixel,
                max_depth=max_depth,
                textures=textures,
                cancellation_token=cancellation_token,
            )
        except (TypeError, ValueError) as exc:
            raise ImageAssetVerificationError(
                "Renderer rejeitou a cena, os limites ou o catálogo de texturas."
            ) from exc
        return VerifiedTextureRender(
            width=width,
            height=height,
            rgb_pixels=pixels,
            sha256=hashlib.sha256(pixels).hexdigest(),
            renderer_backend=CPUPathTracerBackend.BACKEND_ID,
            renderer_version=CPUPathTracerBackend.VERSION,
            texture_asset_ids=self.texture_asset_ids_for_scene(scene),
            seed=seed,
            samples_per_pixel=samples_per_pixel,
            max_depth=max_depth,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_count": len(self.assets),
            "total_pixel_bytes": self.total_bytes,
            "asset_ids": [item.asset.descriptor.asset_id for item in self.assets],
            "verified_assets_only": True,
        }


class ImageAssetVerifier:
    """Verify PNG bytes using the renderer's bounded RGB8/RGBA8 decoder."""

    MAX_BYTES = min(
        ImageAssetDescriptor.MAX_SOURCE_BYTES,
        ImageGenerationEngine.MAX_PNG_BYTES,
    )

    @classmethod
    def read_bounded_stream(cls, stream: Any, *, chunk_size: int = 65_536) -> bytes:
        """Read from a caller-opened binary stream without owning or closing it."""
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
            raise ImageAssetVerificationError("chunk_size deve ser inteiro.")
        if not 1 <= chunk_size <= 262_144:
            raise ImageAssetVerificationError("chunk_size fora do limite permitido.")
        reader = getattr(stream, "read", None)
        if not callable(reader):
            raise ImageAssetVerificationError("A origem fornecida não oferece read().")

        content = bytearray()
        while True:
            request_size = min(chunk_size, cls.MAX_BYTES + 1 - len(content))
            try:
                chunk = reader(request_size)
            except Exception as exc:
                raise ImageAssetVerificationError("Falha ao ler o stream fornecido.") from exc
            if not isinstance(chunk, bytes):
                raise ImageAssetVerificationError("O stream deve retornar bytes.")
            if len(chunk) > request_size:
                raise ImageAssetVerificationError("O stream excedeu o tamanho solicitado.")
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > cls.MAX_BYTES:
                raise ImageAssetVerificationError("Stream excede o limite de bytes.")
        return bytes(content)

    @classmethod
    def verify_png_stream(
        cls,
        stream: Any,
        **metadata: Any,
    ) -> VerifiedImageAsset:
        """Verify a caller-opened stream; ownership, opening and closing stay external."""
        content = cls.read_bounded_stream(stream)
        return cls.verify_png_bytes(content, **metadata)

    @classmethod
    def verify_png_bytes(
        cls,
        content: bytes,
        *,
        asset_id: str,
        source_kind: str,
        source_ref: str,
        declared_mime_type: str | None = None,
        declared_byte_size: int | None = None,
        declared_sha256: str | None = None,
        declared_width: int | None = None,
        declared_height: int | None = None,
        license_status: str = "unknown",
        attribution: str | None = None,
    ) -> VerifiedImageAsset:
        """Derive metadata from supplied PNG bytes and reject declaration conflicts."""
        if not isinstance(content, bytes):
            raise ImageAssetVerificationError("O conteúdo deve ser bytes.")
        if not content or len(content) > cls.MAX_BYTES:
            raise ImageAssetVerificationError("Conteúdo vazio ou acima do limite de bytes.")
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ImageAssetVerificationError("Assinatura real não corresponde a PNG.")

        if declared_mime_type is not None and (
            not isinstance(declared_mime_type, str)
            or declared_mime_type != "image/png"
        ):
            raise ImageAssetVerificationError("MIME declarado diverge do formato detectado.")
        if declared_byte_size is not None and (
            isinstance(declared_byte_size, bool)
            or not isinstance(declared_byte_size, int)
            or declared_byte_size != len(content)
        ):
            raise ImageAssetVerificationError("Tamanho declarado diverge dos bytes recebidos.")
        digest = hashlib.sha256(content).hexdigest()
        if declared_sha256 is not None:
            if not isinstance(declared_sha256, str) or declared_sha256.lower() != digest:
                raise ImageAssetVerificationError("SHA-256 declarado diverge do conteúdo.")

        try:
            png_report = ImageGenerationEngine._validate_png(
                content,
                max_dimension=TextureBuffer.MAX_DIMENSION,
                max_pixels=TextureBuffer.MAX_PIXELS,
            )
        except (ImageGenerationError, ValueError, TypeError) as exc:
            raise ImageAssetVerificationError(
                "PNG não passou pela validação estrutural e de decodificação limitada."
            ) from exc

        width = png_report["width"]
        height = png_report["height"]
        if declared_width is not None and (
            isinstance(declared_width, bool)
            or not isinstance(declared_width, int)
            or declared_width != width
        ):
            raise ImageAssetVerificationError("Largura declarada diverge dos pixels.")
        if declared_height is not None and (
            isinstance(declared_height, bool)
            or not isinstance(declared_height, int)
            or declared_height != height
        ):
            raise ImageAssetVerificationError("Altura declarada diverge dos pixels.")

        try:
            descriptor = ImageAssetDescriptor(
                asset_id=asset_id,
                source_kind=source_kind,
                source_ref=source_ref,
                mime_type="image/png",
                byte_size=len(content),
                content_sha256=digest,
                width=width,
                height=height,
                color_space=(
                    "srgb" if png_report["source_color_space"] == "srgb" else "unknown"
                ),
                alpha_mode="straight" if png_report["channels"] == 4 else "opaque",
                license_status=license_status,
                attribution=attribution,
            )
        except ImageAssetContractError as exc:
            raise ImageAssetVerificationError(
                "Metadados de origem ou proveniência inválidos."
            ) from exc

        return VerifiedImageAsset(
            descriptor=descriptor,
            verification={
                "status": "verified",
                "verification_scope": [
                    "sha256_of_supplied_bytes",
                    "png_signature",
                    "png_chunk_order_and_crc",
                    "rgb8_rgba8_non_interlaced_profile",
                    "bounded_zlib_decode_and_unfilter",
                    "decoded_dimensions_and_pixel_buffer",
                    "declared_metadata_consistency",
                ],
                "actual_mime_type": "image/png",
                "actual_byte_size": len(content),
                "actual_sha256": digest,
                "byte_size_verified": True,
                "sha256_verified": True,
                "pixel_decode_verified": True,
                "actual_width": width,
                "actual_height": height,
                "actual_channels": png_report["channels"],
                "actual_alpha_mode": "straight" if png_report["channels"] == 4 else "opaque",
                "source_color_space": png_report["source_color_space"],
                "source_opened": False,
                "network_accessed": False,
                "android_permission_requested": False,
                "license_verified": False,
                "color_profile_interpreted": False,
                "visual_quality_assessed": False,
            },
        )

    @classmethod
    def verify_and_decode_png(
        cls,
        descriptor: ImageAssetDescriptor | dict[str, Any],
        content: bytes,
        *,
        assumed_color_space: str | None = None,
    ) -> DecodedTextureAsset:
        """Verify supplied bytes against an existing descriptor and return RGB8/RGBA8 pixels."""
        if isinstance(descriptor, dict):
            try:
                descriptor = ImageAssetDescriptor.from_mapping(descriptor)
            except ImageAssetContractError as exc:
                raise ImageAssetVerificationError("Descriptor inválido.") from exc
        if not isinstance(descriptor, ImageAssetDescriptor):
            raise ImageAssetVerificationError("Descriptor de imagem inválido.")
        if descriptor.mime_type != "image/png":
            raise ImageAssetVerificationError("Verificador aceita somente image/png.")
        if descriptor.orientation_degrees != 0:
            raise ImageAssetVerificationError("Orientação diferente de zero não é suportada.")

        verified = cls.verify_png_bytes(
            content,
            asset_id=descriptor.asset_id,
            source_kind=descriptor.source_kind,
            source_ref=descriptor.source_ref,
            declared_mime_type=descriptor.mime_type,
            declared_byte_size=descriptor.byte_size,
            declared_sha256=descriptor.content_sha256,
            declared_width=descriptor.width,
            declared_height=descriptor.height,
            license_status=descriptor.license_status,
            attribution=descriptor.attribution,
        )
        try:
            png_report = ImageGenerationEngine._validate_png(
                content,
                expected_width=descriptor.width,
                expected_height=descriptor.height,
                max_dimension=TextureBuffer.MAX_DIMENSION,
                max_pixels=TextureBuffer.MAX_PIXELS,
            )
        except (ImageGenerationError, ValueError, TypeError) as exc:
            raise ImageAssetVerificationError("Falha ao validar pixels PNG.") from exc

        if assumed_color_space is not None and assumed_color_space not in ("srgb", "linear"):
            raise ImageAssetVerificationError("assumed_color_space deve ser srgb ou linear.")
        if descriptor.color_space == "display_p3":
            raise ImageAssetVerificationError("Display-P3 ainda não é suportado.")
        if descriptor.color_space == "srgb":
            if assumed_color_space not in (None, "srgb"):
                raise ImageAssetVerificationError("Suposição de cor diverge do descriptor sRGB.")
            color_space = "srgb"
            color_space_basis = (
                "png_srgb_chunk"
                if png_report["source_color_space"] == "srgb"
                else "descriptor_claim"
            )
        elif descriptor.color_space == "unknown":
            if png_report["source_color_space"] == "srgb":
                if assumed_color_space not in (None, "srgb"):
                    raise ImageAssetVerificationError("Suposição de cor diverge do chunk sRGB.")
                color_space = "srgb"
                color_space_basis = "png_srgb_chunk"
            elif assumed_color_space in ("srgb", "linear"):
                color_space = assumed_color_space
                color_space_basis = "caller_assumption"
            else:
                raise ImageAssetVerificationError(
                    "Espaço de cor desconhecido; declare assumed_color_space."
                )
        else:
            raise ImageAssetVerificationError("Espaço de cor não suportado.")

        actual_alpha_mode = "straight" if png_report["channels"] == 4 else "opaque"
        if descriptor.alpha_mode not in ("unknown", actual_alpha_mode):
            raise ImageAssetVerificationError(
                f"alpha_mode declarado diverge do PNG ({actual_alpha_mode})."
            )
        try:
            texture = ImageGenerationEngine.decode_png_texture(
                content,
                color_space=color_space,
                expected_width=descriptor.width,
                expected_height=descriptor.height,
            )
        except (ImageGenerationError, ValueError) as exc:
            raise ImageAssetVerificationError("Falha ao decodificar textura PNG.") from exc

        verification = dict(verified.verification)
        verification.update({
            "descriptor_color_space": descriptor.color_space,
            "resolved_color_space": color_space,
            "color_space_basis": color_space_basis,
            "actual_channels": texture.channels,
            "actual_alpha_mode": actual_alpha_mode,
            "pixel_decode_verified": True,
            "source_ref_opened": False,
            "network_accessed": False,
            "android_permission_requested": False,
            "license_verified": False,
        })
        asset = VerifiedImageAsset(
            descriptor=descriptor,
            verification=verification,
        )
        return DecodedTextureAsset(asset=asset, texture=texture)

    @classmethod
    def verify_and_decode_png_stream(
        cls,
        descriptor: ImageAssetDescriptor | dict[str, Any],
        stream: Any,
        *,
        assumed_color_space: str | None = None,
        chunk_size: int = 65_536,
    ) -> DecodedTextureAsset:
        """Read a caller-opened bounded stream and verify/decode without closing it."""
        content = cls.read_bounded_stream(stream, chunk_size=chunk_size)
        return cls.verify_and_decode_png(
            descriptor, content, assumed_color_space=assumed_color_space
        )

    @classmethod
    def decode_png_rgb_bytes(
        cls,
        content: bytes,
        **metadata: Any,
    ) -> DecodedImageAsset:
        """Legacy RGB-only convenience wrapper; use verify_and_decode_png for RGBA."""
        verified = cls.verify_png_bytes(content, **metadata)
        try:
            texture = ImageGenerationEngine.decode_png_texture(
                content,
                color_space="srgb",
                expected_width=verified.descriptor.width,
                expected_height=verified.descriptor.height,
            )
        except (ImageGenerationError, ValueError) as exc:
            raise ImageAssetVerificationError("Falha ao decodificar buffer RGB.") from exc
        if texture.channels != 3:
            raise ImageAssetVerificationError(
                "decode_png_rgb_bytes aceita apenas PNG RGB; use verify_and_decode_png."
            )
        return DecodedImageAsset(asset=verified, rgb_pixels=texture.pixels)
