"""Durable, content-addressed storage for verified PNG image assets.

The first ArtifactStore slice intentionally supports PNG only. It stores media
bytes outside KnowledgeStore and persists metadata-only descriptors beside
content-addressed blobs. Every read re-verifies the bytes and descriptor.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any

from .image_asset import ImageAssetDescriptor
from .image_asset_verifier import ImageAssetVerificationError, ImageAssetVerifier, VerifiedImageAsset


class ArtifactStoreError(OSError):
    """Artifact storage, lookup, or integrity validation failed."""


class ArtifactStoreDurabilityError(ArtifactStoreError):
    """An artifact entry was linked, but directory durability is uncertain."""

    def __init__(self, message: str, *, committed: bool):
        super().__init__(message)
        self.committed = committed


@dataclass(frozen=True)
class StoredImageArtifact:
    """Verified PNG bytes and their immutable metadata/provenance descriptor."""

    content: bytes
    asset: VerifiedImageAsset
    blob_path: Path

    def __post_init__(self) -> None:
        if (
            not isinstance(self.content, bytes)
            or not isinstance(self.asset, VerifiedImageAsset)
            or not isinstance(self.blob_path, Path)
        ):
            raise ArtifactStoreError("StoredImageArtifact exige bytes, VerifiedImageAsset e Path.")
        descriptor = self.asset.descriptor
        if (
            len(self.content) != descriptor.byte_size
            or hashlib.sha256(self.content).hexdigest() != descriptor.content_sha256
        ):
            raise ArtifactStoreError("Bytes não correspondem ao descriptor verificado.")

    def to_dict(self) -> dict[str, Any]:
        """Return metadata only; media bytes are deliberately excluded."""
        return {
            "descriptor": self.asset.descriptor.to_dict(),
            "verification": dict(self.asset.verification),
            "content_bytes_available": True,
            "content_included": False,
        }


class ArtifactStore:
    """Content-addressed PNG ArtifactStore with strict no-follow file access.

    Asset IDs are opaque and deterministic for a given byte payload plus its
    declared source/provenance metadata. Different provenance declarations for
    identical bytes receive distinct asset IDs but share one immutable blob.
    This class never opens source URIs, accesses a network, or requests Android
    permissions.
    """

    SCHEMA = "mahoraga.artifact_store.v1"
    MAX_DESCRIPTOR_BYTES = 65_536
    ASSET_ID_PATTERN = re.compile(r"asset-[0-9a-f]{48}")

    def __init__(self, root: str | Path):
        candidate = Path(root).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        if candidate != candidate.resolve(strict=False):
            raise ArtifactStoreError("artifact_root deve ser canônico e não conter symlinks.")
        self.root = candidate
        self.blob_root = self.root / "blobs"
        self.descriptor_root = self.root / "descriptors"
        self._ensure_layout()

    def _ensure_layout(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            for directory in (self.root, self.blob_root, self.descriptor_root):
                if (
                    directory.is_symlink()
                    or not directory.is_dir()
                    or directory.resolve(strict=True) != directory
                ):
                    raise ArtifactStoreError("Diretório do ArtifactStore não é canônico e seguro.")
                if stat.S_IMODE(directory.stat().st_mode) & 0o077:
                    raise ArtifactStoreError(
                        "Diretório do ArtifactStore precisa ser privado (permissões 0700)."
                    )
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError("Não foi possível preparar o ArtifactStore.") from exc

    @staticmethod
    def _canonical_json(value: dict[str, Any]) -> bytes:
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ArtifactStoreError("Metadados do artefato não são serializáveis.") from exc

    @classmethod
    def _asset_id_for_descriptor(cls, descriptor: ImageAssetDescriptor) -> str:
        identity = descriptor.to_dict()
        for field in (
            "asset_id", "descriptor_validation",
            "content_integrity_verified", "source_opened",
        ):
            identity.pop(field, None)
        digest = hashlib.sha256(cls._canonical_json(identity)).hexdigest()
        return "asset-" + digest[:48]

    @staticmethod
    def _blob_path(root: Path, digest: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ArtifactStoreError("Digest de conteúdo inválido.")
        return root / "blobs" / digest[:2] / (digest + ".png")

    def _descriptor_path(self, asset_id: str) -> Path:
        if not isinstance(asset_id, str) or self.ASSET_ID_PATTERN.fullmatch(asset_id) is None:
            raise ArtifactStoreError("asset_id inválido.")
        return self.descriptor_root / (asset_id + ".json")

    @staticmethod
    def _read_bounded(path: Path, max_bytes: int) -> bytes:
        descriptor = -1
        try:
            parent = path.parent
            if (
                parent.is_symlink()
                or not parent.is_dir()
                or parent.resolve(strict=True) != parent
                or stat.S_IMODE(parent.stat().st_mode) & 0o077
            ):
                raise ArtifactStoreError("Diretório pai do artefato não é privado e canônico.")
            before = os.lstat(path)
            if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
                raise ArtifactStoreError("Entrada do ArtifactStore não é arquivo regular.")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            after = os.fstat(descriptor)
            if (
                not stat.S_ISREG(after.st_mode)
                or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or after.st_size > max_bytes
            ):
                raise ArtifactStoreError("Arquivo mudou ou excedeu o limite durante a leitura.")
            content = bytearray()
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                while True:
                    chunk = handle.read(min(65_536, max_bytes + 1 - len(content)))
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise ArtifactStoreError("Arquivo excede o limite de leitura.")
            return bytes(content)
        except ArtifactStoreError:
            raise
        except OSError as exc:
            raise ArtifactStoreError("Não foi possível ler o artefato com segurança.") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        directory_fd = -1
        try:
            directory_fd = os.open(
                directory,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            os.fsync(directory_fd)
        finally:
            if directory_fd >= 0:
                os.close(directory_fd)

    def _atomic_create(self, destination: Path, content: bytes) -> None:
        parent = destination.parent
        if (
            parent.is_symlink()
            or not parent.is_dir()
            or parent.resolve(strict=True) != parent
            or stat.S_IMODE(parent.stat().st_mode) & 0o077
        ):
            raise ArtifactStoreError("Diretório de destino não é canônico.")
        if os.path.lexists(destination):
            existing = self._read_bounded(destination, max(len(content), 1))
            if existing != content:
                raise ArtifactStoreError("Colisão: conteúdo existente diverge do esperado.")
            return

        temporary_path = None
        committed = False
        try:
            fd, temporary_name = tempfile.mkstemp(
                prefix=".mahoraga-artifact-", suffix=".tmp", dir=parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(fd, "wb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # Hard-link creation is atomic and fails rather than replacing
                # an existing content-addressed entry.
                os.link(temporary_path, destination)
                committed = True
            except FileExistsError:
                existing = self._read_bounded(destination, max(len(content), 1))
                if existing != content:
                    raise ArtifactStoreError("Colisão de conteúdo no ArtifactStore.")
            if committed:
                try:
                    self._fsync_directory(parent)
                except OSError as exc:
                    raise ArtifactStoreDurabilityError(
                        "Entrada criada, mas durabilidade do diretório não confirmada.",
                        committed=True,
                    ) from exc
        except (ArtifactStoreError, ArtifactStoreDurabilityError):
            raise
        except OSError as exc:
            raise ArtifactStoreError("Falha ao gravar artefato de forma atômica.") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _parse_descriptor(content: bytes) -> ImageAssetDescriptor:
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Chave JSON duplicada.")
                result[key] = value
            return result

        def reject_constant(value):
            raise ValueError("Constante JSON não permitida: " + value)

        try:
            payload = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=unique_pairs,
                parse_constant=reject_constant,
            )
            return ImageAssetDescriptor.from_mapping(payload)
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ArtifactStoreError("Descriptor de imagem inválido ou adulterado.") from exc

    def put_png(
        self,
        content: bytes,
        *,
        source_kind: str,
        source_ref: str,
        license_status: str = "unknown",
        attribution: str | None = None,
        declared_sha256: str | None = None,
        declared_width: int | None = None,
        declared_height: int | None = None,
    ) -> StoredImageArtifact:
        """Verify and durably store PNG bytes without opening their declared source."""
        if not isinstance(content, bytes):
            raise ArtifactStoreError("Conteúdo PNG precisa ser bytes.")
        digest = hashlib.sha256(content).hexdigest()
        try:
            verified = ImageAssetVerifier.verify_png_bytes(
                content,
                asset_id="pending-" + digest[:48],
                source_kind=source_kind,
                source_ref=source_ref,
                declared_mime_type="image/png",
                declared_byte_size=len(content),
                declared_sha256=declared_sha256,
                declared_width=declared_width,
                declared_height=declared_height,
                license_status=license_status,
                attribution=attribution,
            )
        except ImageAssetVerificationError as exc:
            raise ArtifactStoreError("PNG não passou pela verificação de entrada.") from exc

        asset_id = self._asset_id_for_descriptor(verified.descriptor)
        descriptor = replace(verified.descriptor, asset_id=asset_id)
        verified = VerifiedImageAsset(
            descriptor=descriptor,
            verification=dict(verified.verification),
        )
        descriptor_bytes = self._canonical_json(descriptor.to_dict())
        if len(descriptor_bytes) > self.MAX_DESCRIPTOR_BYTES:
            raise ArtifactStoreError("Descriptor excede o limite de armazenamento.")

        blob_path = self._blob_path(self.root, digest)
        if (
            self.blob_root.is_symlink()
            or not self.blob_root.is_dir()
            or self.blob_root.resolve(strict=True) != self.blob_root
        ):
            raise ArtifactStoreError("Diretório de blobs foi substituído ou não é canônico.")
        blob_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (
            blob_path.parent.is_symlink()
            or not blob_path.parent.is_dir()
            or blob_path.parent.resolve(strict=True) != blob_path.parent
        ):
            raise ArtifactStoreError("Diretório do blob não é canônico.")
        self._atomic_create(blob_path, content)
        self._atomic_create(self._descriptor_path(asset_id), descriptor_bytes)
        return StoredImageArtifact(content=content, asset=verified, blob_path=blob_path)

    def get_png(self, asset_id: str) -> StoredImageArtifact:
        """Resolve an opaque asset ID and re-verifies descriptor and stored bytes."""
        descriptor_path = self._descriptor_path(asset_id)
        descriptor_bytes = self._read_bounded(
            descriptor_path, self.MAX_DESCRIPTOR_BYTES
        )
        descriptor = self._parse_descriptor(descriptor_bytes)
        if descriptor.asset_id != asset_id:
            raise ArtifactStoreError("asset_id do descriptor diverge da chave consultada.")
        if self._asset_id_for_descriptor(descriptor) != asset_id:
            raise ArtifactStoreError("Identidade do descriptor não corresponde ao asset_id.")

        blob_path = self._blob_path(self.root, descriptor.content_sha256.lower())
        content = self._read_bounded(blob_path, ImageAssetVerifier.MAX_BYTES)
        try:
            verified = ImageAssetVerifier.verify_png_bytes(
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
        except ImageAssetVerificationError as exc:
            raise ArtifactStoreError("Bytes armazenados não passaram pela revalidação.") from exc
        if verified.descriptor.to_dict() != descriptor.to_dict():
            raise ArtifactStoreError("Descriptor persistido diverge dos metadados derivados dos bytes.")
        return StoredImageArtifact(content=content, asset=verified, blob_path=blob_path)

    def contains(self, asset_id: str) -> bool:
        """Return whether a descriptor path exists; this is not an integrity claim."""
        path = self._descriptor_path(asset_id)
        return os.path.lexists(path)
