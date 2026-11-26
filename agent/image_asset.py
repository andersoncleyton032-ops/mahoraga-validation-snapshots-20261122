"""Strict metadata-only contract for image assets; never opens or fetches sources."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, ClassVar


class ImageAssetContractError(ValueError):
    """Invalid image asset descriptor."""


@dataclass(frozen=True)
class ImageAssetDescriptor:
    """Portable image reference with explicit provenance and bounded metadata.

    This descriptor validates claims and shape only. It does not read source bytes,
    authenticate a URI, verify the digest, decode pixels, or grant permissions.
    """

    asset_id: str
    source_kind: str
    source_ref: str
    mime_type: str
    byte_size: int
    content_sha256: str
    width: int
    height: int
    orientation_degrees: int = 0
    color_space: str = "unknown"
    alpha_mode: str = "unknown"
    license_status: str = "unknown"
    attribution: str | None = None

    SCHEMA: ClassVar[str] = "mahoraga.image_asset.v1"
    MAX_SOURCE_BYTES: ClassVar[int] = 32 * 1024 * 1024
    MAX_DIMENSION: ClassVar[int] = 8192
    MAX_PIXELS: ClassVar[int] = 16_777_216
    SOURCE_KINDS: ClassVar[frozenset[str]] = frozenset({
        "android_content_uri", "user_upload", "generated", "external_provider",
    })
    MIME_TYPES: ClassVar[frozenset[str]] = frozenset({
        "image/png", "image/jpeg", "image/webp", "image/avif", "image/heic",
    })
    COLOR_SPACES: ClassVar[frozenset[str]] = frozenset({
        "srgb", "display_p3", "unknown",
    })
    ALPHA_MODES: ClassVar[frozenset[str]] = frozenset({
        "opaque", "straight", "premultiplied", "unknown",
    })
    LICENSE_STATUSES: ClassVar[frozenset[str]] = frozenset({
        "user_supplied", "public_domain", "licensed", "unknown",
    })

    def __post_init__(self) -> None:
        if not isinstance(self.asset_id, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", self.asset_id
        ):
            raise ImageAssetContractError("asset_id inválido.")
        if not isinstance(self.source_kind, str) or self.source_kind not in self.SOURCE_KINDS:
            raise ImageAssetContractError("source_kind não suportado.")
        if (
            not isinstance(self.source_ref, str)
            or not self.source_ref
            or len(self.source_ref) > 2048
            or any(ord(character) < 32 for character in self.source_ref)
        ):
            raise ImageAssetContractError("source_ref inválido.")
        if not isinstance(self.mime_type, str) or self.mime_type not in self.MIME_TYPES:
            raise ImageAssetContractError("mime_type não suportado pelo contrato.")
        self._validate_integer(self.byte_size, "byte_size", 1, self.MAX_SOURCE_BYTES)
        if (
            not isinstance(self.content_sha256, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", self.content_sha256) is None
        ):
            raise ImageAssetContractError("content_sha256 deve conter 64 dígitos hexadecimais.")
        self._validate_integer(self.width, "width", 1, self.MAX_DIMENSION)
        self._validate_integer(self.height, "height", 1, self.MAX_DIMENSION)
        if self.width * self.height > self.MAX_PIXELS:
            raise ImageAssetContractError("Imagem excede o orçamento máximo de pixels.")
        if (
            isinstance(self.orientation_degrees, bool)
            or not isinstance(self.orientation_degrees, int)
            or self.orientation_degrees not in (0, 90, 180, 270)
        ):
            raise ImageAssetContractError("orientation_degrees deve ser 0, 90, 180 ou 270.")
        if not isinstance(self.color_space, str) or self.color_space not in self.COLOR_SPACES:
            raise ImageAssetContractError("color_space desconhecido.")
        if not isinstance(self.alpha_mode, str) or self.alpha_mode not in self.ALPHA_MODES:
            raise ImageAssetContractError("alpha_mode desconhecido.")
        if (
            not isinstance(self.license_status, str)
            or self.license_status not in self.LICENSE_STATUSES
        ):
            raise ImageAssetContractError("license_status desconhecido.")
        if self.attribution is not None and (
            not isinstance(self.attribution, str)
            or len(self.attribution) > 512
            or any(ord(character) < 32 and character not in "\\t" for character in self.attribution)
        ):
            raise ImageAssetContractError("attribution inválida.")

    @staticmethod
    def _validate_integer(value: Any, field: str, minimum: int, maximum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ImageAssetContractError(f"{field} fora do intervalo permitido.")

    @classmethod
    def from_mapping(cls, value: Any) -> "ImageAssetDescriptor":
        if not isinstance(value, dict):
            raise ImageAssetContractError("Descriptor deve ser um objeto.")
        allowed = {
            "schema", "asset_id", "source_kind", "source_ref", "mime_type",
            "byte_size", "content_sha256", "width", "height",
            "orientation_degrees", "color_space", "alpha_mode",
            "license_status", "attribution", "descriptor_validation",
            "content_integrity_verified", "source_opened",
        }
        if set(value) - allowed:
            raise ImageAssetContractError("Descriptor contém campos desconhecidos.")
        if (
            (
                "descriptor_validation" in value
                and (
                    not isinstance(value["descriptor_validation"], str)
                    or value["descriptor_validation"] != "metadata_only"
                )
            )
            or (
                "content_integrity_verified" in value
                and value["content_integrity_verified"] is not False
            )
            or (
                "source_opened" in value
                and value["source_opened"] is not False
            )
        ):
            raise ImageAssetContractError(
                "Claims do descriptor não podem afirmar verificação de conteúdo ou abertura da origem."
            )
        if value.get("schema") != cls.SCHEMA:
            raise ImageAssetContractError("Schema de imagem ausente ou incompatível.")
        required = {
            "asset_id", "source_kind", "source_ref", "mime_type", "byte_size",
            "content_sha256", "width", "height",
        }
        if not required.issubset(value):
            raise ImageAssetContractError("Descriptor contém campos obrigatórios ausentes.")
        return cls(
            asset_id=value["asset_id"],
            source_kind=value["source_kind"],
            source_ref=value["source_ref"],
            mime_type=value["mime_type"],
            byte_size=value["byte_size"],
            content_sha256=value["content_sha256"],
            width=value["width"],
            height=value["height"],
            orientation_degrees=value.get("orientation_degrees", 0),
            color_space=value.get("color_space", "unknown"),
            alpha_mode=value.get("alpha_mode", "unknown"),
            license_status=value.get("license_status", "unknown"),
            attribution=value.get("attribution"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a canonical metadata record without claiming byte verification."""
        return {
            "schema": self.SCHEMA,
            "asset_id": self.asset_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "mime_type": self.mime_type,
            "byte_size": self.byte_size,
            "content_sha256": self.content_sha256.lower(),
            "width": self.width,
            "height": self.height,
            "orientation_degrees": self.orientation_degrees,
            "color_space": self.color_space,
            "alpha_mode": self.alpha_mode,
            "license_status": self.license_status,
            "attribution": self.attribution,
            "descriptor_validation": "metadata_only",
            "content_integrity_verified": False,
            "source_opened": False,
        }
