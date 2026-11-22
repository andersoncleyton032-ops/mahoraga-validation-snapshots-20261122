"""Preflight limits for NumPy NPZ neural checkpoints.

The ZIP central directory and NPY headers are inspected before NumPy materializes
any array. This is resource validation, not artifact authentication.
"""
from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
import struct
import zipfile
import zlib

import numpy as np


MAX_CHECKPOINT_FILE_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_CHECKPOINT_METADATA_BYTES = 64 * 1024
MAX_NPY_HEADER_BYTES = 10_000


class CheckpointPreflightError(ValueError):
    """Raised when an NPZ checkpoint violates its bounded file contract."""



def open_checkpoint_file(path):
    """Open only a regular, non-symlink checkpoint without blocking on FIFOs.

    O_NOFOLLOW protects against symlink replacement on platforms that provide
    it; O_NONBLOCK prevents a FIFO path from hanging before fstat can reject it.
    """
    target = Path(path).expanduser()
    try:
        before = os.lstat(target)
    except OSError as exc:
        raise CheckpointPreflightError(
            "Caminho do checkpoint indisponível."
        ) from exc
    if not stat.S_ISREG(before.st_mode):
        raise CheckpointPreflightError(
            "Checkpoint precisa ser arquivo regular, não link/dispositivo/FIFO."
        )

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)

    try:
        descriptor = os.open(target, flags)
    except OSError as exc:
        raise CheckpointPreflightError(
            "Não foi possível abrir o checkpoint com segurança."
        ) from exc

    try:
        after = os.fstat(descriptor)
        if not stat.S_ISREG(after.st_mode):
            raise CheckpointPreflightError(
                "Checkpoint deixou de ser arquivo regular durante a abertura."
            )
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise CheckpointPreflightError(
                "O arquivo de checkpoint foi substituído durante a abertura."
            )
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise

def _read_npy_header(stream, label: str):
    try:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, fortran_order, dtype = np.lib.format.read_array_header_1_0(
                stream, max_header_size=MAX_NPY_HEADER_BYTES
            )
        elif version == (2, 0):
            shape, fortran_order, dtype = np.lib.format.read_array_header_2_0(
                stream, max_header_size=MAX_NPY_HEADER_BYTES
            )
        else:
            raise CheckpointPreflightError(
                f"Versão NPY não permitida em {label}: {version!r}"
            )
    except CheckpointPreflightError:
        raise
    except (EOFError, ValueError, TypeError, OSError, SyntaxError, RecursionError, struct.error) as exc:
        raise CheckpointPreflightError(
            f"Cabeçalho NPY inválido em {label}."
        ) from exc

    if not isinstance(shape, tuple) or not isinstance(fortran_order, bool):
        raise CheckpointPreflightError(f"Contrato NPY inválido em {label}.")
    if dtype.hasobject:
        raise CheckpointPreflightError(
            f"Dtype com objetos não permitido em {label}."
        )
    return shape, np.dtype(dtype), stream.tell()



def _preflight_zip_directory(stream, file_size: int, expected_names: set[str]):
    """Bound ZIP directory parsing before zipfile materializes ZipInfo objects."""
    max_entries = len(expected_names)
    if max_entries > 20_000:
        raise CheckpointPreflightError(
            "Quantidade esperada de membros ZIP excede o limite estrutural."
        )

    tail_length = min(file_size, 22 + 65_535)
    stream.seek(file_size - tail_length)
    tail = stream.read(tail_length)
    signature = b"PK\x05\x06"
    position = tail.rfind(signature)
    if position < 0 or position + 22 > len(tail):
        raise CheckpointPreflightError("Registro final ZIP (EOCD) ausente.")

    try:
        (
            _signature,
            disk_number,
            directory_disk,
            entries_on_disk,
            total_entries,
            directory_size,
            directory_offset,
            comment_length,
        ) = struct.unpack_from("<4s4H2LH", tail, position)
    except struct.error as exc:
        raise CheckpointPreflightError("Registro EOCD truncado.") from exc

    if position + 22 + comment_length != len(tail):
        raise CheckpointPreflightError(
            "Comentário ou posição do registro EOCD inconsistente."
        )
    if disk_number != 0 or directory_disk != 0 or entries_on_disk != total_entries:
        raise CheckpointPreflightError(
            "Arquivos ZIP multipartes não são permitidos."
        )
    if (
        total_entries == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
    ):
        raise CheckpointPreflightError(
            "Formato ZIP64 não permitido para checkpoints limitados."
        )
    if total_entries != max_entries:
        raise CheckpointPreflightError(
            "Contagem de membros ZIP incompatível antes da leitura do diretório."
        )

    eocd_offset = file_size - tail_length + position
    if directory_offset + directory_size != eocd_offset:
        raise CheckpointPreflightError(
            "Posição/tamanho do diretório central ZIP inconsistente."
        )

    maximum_directory_size = sum(
        46 + len(name.encode("utf-8")) + 1024
        for name in expected_names
    )
    maximum_directory_size = min(
        maximum_directory_size,
        8 * 1024 * 1024,
    )
    if directory_size > maximum_directory_size:
        raise CheckpointPreflightError(
            "Diretório central ZIP excede o limite estrutural."
        )

    stream.seek(0)

def preflight_npz(
    stream,
    expected_arrays: dict[str, tuple],
    metadata_key: str = "metadata",
):
    """Validate an open binary stream before calling numpy.load().

    expected_arrays maps archive keys (without .npy) to (shape, dtype).
    The same open descriptor is reused by the caller, avoiding a path-replacement
    race between preflight and array materialization.
    """
    if not hasattr(stream, "seek") or not hasattr(stream, "tell"):
        raise CheckpointPreflightError("Checkpoint exige arquivo seekable.")
    if not isinstance(expected_arrays, dict):
        raise CheckpointPreflightError("Contrato de arrays esperado é inválido.")
    if (
        not isinstance(metadata_key, str)
        or not metadata_key
        or metadata_key in expected_arrays
    ):
        raise CheckpointPreflightError("Chave de metadados inválida.")

    expected_names = {f"{key}.npy" for key in expected_arrays}
    expected_names.add(f"{metadata_key}.npy")
    total_uncompressed = 0

    try:
        stream.seek(0, 2)
        file_size = stream.tell()
        stream.seek(0)
        if not isinstance(file_size, int) or file_size <= 0:
            raise CheckpointPreflightError("Checkpoint vazio ou ilegível.")
        if file_size > MAX_CHECKPOINT_FILE_BYTES:
            raise CheckpointPreflightError(
                "Checkpoint excede o limite comprimido de 64 MiB."
            )

        _preflight_zip_directory(stream, file_size, expected_names)

        with zipfile.ZipFile(stream, mode="r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) != len(expected_names):
                raise CheckpointPreflightError(
                    "Quantidade de membros ZIP incompatível."
                )
            if len(names) != len(set(names)):
                raise CheckpointPreflightError("Membros ZIP duplicados.")
            if set(names) != expected_names:
                raise CheckpointPreflightError(
                    "Membros ZIP ausentes ou não declarados."
                )

            info_by_name = {info.filename: info for info in infos}
            for info in infos:
                if info.is_dir() or "/" in info.filename or "\\" in info.filename:
                    raise CheckpointPreflightError("Caminho ZIP não permitido.")
                if info.flag_bits & 0x1:
                    raise CheckpointPreflightError("Membro ZIP criptografado.")
                if info.compress_type not in {
                    zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED
                }:
                    raise CheckpointPreflightError(
                        "Método de compressão ZIP não permitido."
                    )
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise CheckpointPreflightError(
                        "Link simbólico ZIP não permitido."
                    )
                if info.file_size < 1:
                    raise CheckpointPreflightError("Membro ZIP vazio.")
                if info.file_size > MAX_CHECKPOINT_UNCOMPRESSED_BYTES:
                    raise CheckpointPreflightError(
                        "Membro ZIP excede o limite descomprimido."
                    )
                total_uncompressed += info.file_size

            for key, expected in expected_arrays.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or not isinstance(expected, (tuple, list))
                    or len(expected) != 2
                ):
                    raise CheckpointPreflightError(
                        "Definição de array esperada inválida."
                    )
                expected_shape = tuple(expected[0])
                expected_dtype = np.dtype(expected[1])
                if expected_dtype.hasobject:
                    raise CheckpointPreflightError(
                        "Dtype esperado com objetos não permitido."
                    )
                if any(
                    not isinstance(dimension, int)
                    or isinstance(dimension, bool)
                    or dimension < 0
                    for dimension in expected_shape
                ):
                    raise CheckpointPreflightError(
                        "Dimensão esperada inválida."
                    )

                info = info_by_name[f"{key}.npy"]
                expected_payload = (
                    math.prod(expected_shape) * expected_dtype.itemsize
                )
                if info.file_size > expected_payload + MAX_NPY_HEADER_BYTES:
                    raise CheckpointPreflightError(
                        f"Array excede o tamanho esperado: {key}."
                    )
                with archive.open(info, mode="r") as member:
                    shape, dtype, header_bytes = _read_npy_header(
                        member, info.filename
                    )
                if shape != expected_shape or dtype != expected_dtype:
                    raise CheckpointPreflightError(
                        f"Shape/dtype incompatível em {key}."
                    )
                if info.file_size != header_bytes + expected_payload:
                    raise CheckpointPreflightError(
                        f"Tamanho do payload incompatível em {key}."
                    )

            metadata_info = info_by_name[f"{metadata_key}.npy"]
            with archive.open(metadata_info, mode="r") as member:
                metadata_shape, metadata_dtype, metadata_header = (
                    _read_npy_header(member, metadata_info.filename)
                )
            if (
                len(metadata_shape) != 1
                or metadata_dtype != np.dtype(np.uint8)
                or not 1 <= metadata_shape[0] <= MAX_CHECKPOINT_METADATA_BYTES
            ):
                raise CheckpointPreflightError(
                    "Metadados fora do contrato de tamanho/tipo."
                )
            if (
                metadata_info.file_size
                != metadata_header + metadata_shape[0]
            ):
                raise CheckpointPreflightError(
                    "Tamanho do payload de metadados incompatível."
                )

            if total_uncompressed > MAX_CHECKPOINT_UNCOMPRESSED_BYTES:
                raise CheckpointPreflightError(
                    "Checkpoint excede o limite descomprimido de 128 MiB."
                )
    except CheckpointPreflightError:
        raise
    except (
        OSError, EOFError, RuntimeError, ValueError, TypeError,
        zipfile.BadZipFile, zlib.error, struct.error,
    ) as exc:
        raise CheckpointPreflightError(
            "Arquivo ZIP/NPZ inválido ou corrompido."
        ) from exc
    finally:
        try:
            stream.seek(0)
        except (OSError, ValueError):
            pass


def decode_metadata_array(array) -> dict:
    """Decode bounded UTF-8 JSON metadata with duplicate-key rejection."""
    if (
        not isinstance(array, np.ndarray)
        or array.dtype != np.dtype(np.uint8)
        or array.ndim != 1
        or not 1 <= array.size <= MAX_CHECKPOINT_METADATA_BYTES
    ):
        raise CheckpointPreflightError("Array de metadados inválido.")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise CheckpointPreflightError(
                    f"Chave duplicada nos metadados: {key}"
                )
            result[key] = value
        return result

    def reject_constant(value):
        raise CheckpointPreflightError(
            f"Constante JSON não permitida: {value}"
        )

    try:
        value = json.loads(
            array.tobytes().decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=reject_constant,
        )
    except CheckpointPreflightError:
        raise
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError) as exc:
        raise CheckpointPreflightError(
            "JSON dos metadados inválido."
        ) from exc

    if not isinstance(value, dict):
        raise CheckpointPreflightError(
            "Raiz dos metadados precisa ser objeto."
        )
    return value
