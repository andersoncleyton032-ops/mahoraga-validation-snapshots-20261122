"""Local knowledge catalog and document preparation engine.

Imported documents are stored as provenance-linked chunks.
Importing material does not mean the neural core has learned it.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".json", ".csv", ".log", ".yaml", ".yml", ".xml"
}

_SEARCH_STOPWORDS = {
    "a", "as", "o", "os", "um", "uma", "uns", "umas", "de", "do", "da",
    "dos", "das", "em", "no", "na", "nos", "nas", "por", "para", "com",
    "sem", "ao", "aos", "à", "às", "e", "ou", "que", "se", "como", "qual",
    "quais", "quando", "onde", "porque", "porquê", "é", "ser", "foi", "são",
    "está", "estão", "era", "eram", "isso", "isto", "esse", "essa", "este",
    "esta", "meu", "minha", "seu", "sua", "me", "te", "lhe", "nos", "vos",
    "the", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False, default=str
    )


class KnowledgeEngine:
    VERSION = "0.2.0"
    MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
    MAX_SEARCH_QUERY_LENGTH = 500
    MAX_SEARCH_CANDIDATES = 5000
    MAX_SEARCH_CHUNK_CHARS = 4000

    def __init__(self, store):
        self.store = store
        self.db_path = Path(store.db_path)

    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def _search_normalize(text: str) -> str:
        decomposed = unicodedata.normalize("NFKD", text.casefold())
        return "".join(
            char for char in decomposed
            if not unicodedata.combining(char)
        )

    @classmethod
    def _search_tokens(cls, text: str) -> list[str]:
        normalized = cls._search_normalize(text)
        return [
            token for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
            if len(token) > 1 and token not in _SEARCH_STOPWORDS
        ]

    @staticmethod
    def _split_text(text: str, chunk_size: int, overlap: int):
        if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size < 100:
            raise ValueError("chunk_size deve ser inteiro e pelo menos 100.")
        if not isinstance(overlap, int) or isinstance(overlap, bool) or overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap deve ser inteiro, não negativo e menor que chunk_size.")

        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            if end < len(text):
                boundary = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
                if boundary > start + chunk_size // 2:
                    end = boundary

            chunk_start, chunk_end = start, end
            while chunk_start < chunk_end and text[chunk_start].isspace():
                chunk_start += 1
            while chunk_end > chunk_start and text[chunk_end - 1].isspace():
                chunk_end -= 1
            if chunk_start < chunk_end:
                chunks.append((text[chunk_start:chunk_end], chunk_start, chunk_end))

            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
        return chunks

    def import_document(
        self,
        path,
        subject: str,
        chunk_size: int = 2000,
        overlap: int = 200,
        metadata: dict | None = None,
    ) -> dict:
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("O assunto deve ser um texto não vazio.")
        subject = subject.strip()

        if metadata is None:
            metadata = {}
        elif not isinstance(metadata, dict):
            raise ValueError("metadata deve ser um dicionário.")

        try:
            metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata deve conter somente valores JSON válidos.") from exc

        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Formato não suportado: {source.suffix}. "
                "Use um arquivo de texto compatível."
            )
        if source.stat().st_size > self.MAX_DOCUMENT_BYTES:
            raise ValueError("Documento excede o limite de 25 MB.")

        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()

        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Documento não está em UTF-8 válido.") from exc

        if not text.strip():
            raise ValueError("Documento vazio.")

        chunks = self._split_text(text, chunk_size, overlap)
        now = _now()
        db = self._connect()

        try:
            db.execute("BEGIN IMMEDIATE")

            existing = db.execute(
                "SELECT id, file_name FROM knowledge_documents WHERE sha256=?",
                (digest,)
            ).fetchone()

            if existing:
                db.rollback()
                return {
                    "status": "duplicate",
                    "document_id": existing["id"],
                    "existing_file": existing["file_name"],
                    "sha256": digest,
                    "chunks_created": 0,
                }

            cursor = db.execute(
                """INSERT INTO knowledge_documents
                   (sha256, source_path, file_name, extension, subject,
                    char_count, status, metadata_json, imported_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'prepared', ?, ?)""",
                (
                    digest, str(source), source.name, source.suffix.lower(),
                    subject, len(text), metadata_json, now
                )
            )
            document_id = int(cursor.lastrowid)

            for index, (content, start, end) in enumerate(chunks):
                chunk_hash = hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest()

                db.execute(
                    """INSERT INTO knowledge_chunks
                       (document_id, chunk_index, content, sha256,
                        start_char, end_char, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        document_id, index, content, chunk_hash,
                        start, end, now
                    )
                )

            db.execute(
                """INSERT INTO events
                   (event_type, severity, payload_json, created_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    "knowledge.document_imported", "info",
                    _json({
                        "document_id": document_id,
                        "sha256": digest,
                        "subject": subject,
                        "chunks": len(chunks),
                    }),
                    now,
                )
            )
            db.commit()

            return {
                "status": "imported",
                "document_id": document_id,
                "sha256": digest,
                "chunks_created": len(chunks),
                "char_count": len(text),
                "learning_status": "prepared_not_learned",
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def list_documents(self, subject: str | None = None, limit: int = 100):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("limit deve estar entre 1 e 1000.")

        db = self._connect()
        try:
            if subject is None:
                rows = db.execute(
                    """SELECT * FROM knowledge_documents
                       ORDER BY imported_at DESC LIMIT ?""",
                    (limit,)
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT * FROM knowledge_documents
                       WHERE subject=? ORDER BY imported_at DESC LIMIT ?""",
                    (str(subject).strip(), limit)
                ).fetchall()

            return [{
                "id": row["id"],
                "sha256": row["sha256"],
                "source_path": row["source_path"],
                "file_name": row["file_name"],
                "extension": row["extension"],
                "subject": row["subject"],
                "char_count": row["char_count"],
                "status": row["status"],
                "metadata": json.loads(row["metadata_json"]),
                "imported_at": row["imported_at"],
            } for row in rows]
        finally:
            db.close()

    def list_chunks(self, document_id: int, limit: int = 1000):
        if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id <= 0:
            raise ValueError("document_id deve ser um inteiro positivo.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10000:
            raise ValueError("limit deve estar entre 1 e 10000.")
        db = self._connect()
        try:
            rows = db.execute(
                """SELECT chunk_index, content, sha256, start_char, end_char
                   FROM knowledge_chunks
                   WHERE document_id=?
                   ORDER BY chunk_index LIMIT ?""",
                (document_id, limit)
            ).fetchall()

            return [dict(row) for row in rows]
        finally:
            db.close()

    def get_chunk(self, document_id: int, chunk_index: int) -> dict | None:
        """Return one chunk with its document provenance, without modifying storage."""
        if (
            isinstance(document_id, bool)
            or not isinstance(document_id, int)
            or document_id <= 0
        ):
            raise ValueError("document_id deve ser um inteiro positivo.")
        if (
            isinstance(chunk_index, bool)
            or not isinstance(chunk_index, int)
            or chunk_index < 0
        ):
            raise ValueError("chunk_index deve ser um inteiro não negativo.")
        db = self._connect()
        try:
            row = db.execute(
                """SELECT d.id AS document_id, d.sha256 AS document_sha256,
                          d.file_name, d.subject, d.status, d.imported_at,
                          c.chunk_index, c.content, c.sha256 AS chunk_sha256,
                          c.start_char, c.end_char
                   FROM knowledge_documents d
                   JOIN knowledge_chunks c ON c.document_id=d.id
                   WHERE d.id=? AND c.chunk_index=?""",
                (document_id, chunk_index),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            db.close()

    def search_chunks(
        self,
        query: str,
        limit: int = 5,
        subject: str | None = None,
        max_candidates: int = 1000,
    ) -> list[dict]:
        """Recupera fragmentos por relevância lexical, sem alegar semântica neural.

        O ranking BM25 é local, determinístico e limitado em quantidade de
        candidatos. Resultados preservam a proveniência do documento e podem
        alimentar contexto cognitivo; não são tratados como fatos verificados.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("A consulta deve ser um texto não vazio.")
        if len(query) > self.MAX_SEARCH_QUERY_LENGTH:
            raise ValueError("A consulta excede 500 caracteres.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit deve estar entre 1 e 100.")
        if (
            not isinstance(max_candidates, int)
            or isinstance(max_candidates, bool)
            or not 1 <= max_candidates <= self.MAX_SEARCH_CANDIDATES
        ):
            raise ValueError("max_candidates deve estar entre 1 e 5000.")
        if subject is not None and (
            not isinstance(subject, str) or not subject.strip()
        ):
            raise ValueError("subject deve ser texto não vazio ou None.")

        query_tokens = list(dict.fromkeys(self._search_tokens(query)))
        if not query_tokens:
            raise ValueError("A consulta não contém termos informativos.")

        db = self._connect()
        try:
            sql = """
                SELECT d.id AS document_id, d.sha256 AS document_sha256,
                       d.file_name, d.subject, d.status, d.imported_at,
                       c.chunk_index, c.content, c.sha256 AS chunk_sha256,
                       c.start_char, c.end_char
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id=c.document_id
                WHERE d.status='prepared' AND length(c.content) <= ?
            """
            params: list[object] = [self.MAX_SEARCH_CHUNK_CHARS]
            if subject is not None:
                sql += " AND d.subject=?"
                params.append(subject.strip())
            sql += " ORDER BY d.imported_at DESC, d.id DESC, c.chunk_index LIMIT ?"
            params.append(max_candidates)
            rows = db.execute(sql, params).fetchall()
        finally:
            db.close()

        if not rows:
            return []

        documents = []
        document_frequencies = {token: 0 for token in query_tokens}
        total_length = 0

        for row in rows:
            tokens = self._search_tokens(row["content"])
            frequencies = {}
            for token in tokens:
                frequencies[token] = frequencies.get(token, 0) + 1
            for token in query_tokens:
                if frequencies.get(token, 0):
                    document_frequencies[token] += 1
            total_length += len(tokens)
            documents.append((row, frequencies, len(tokens)))

        count = len(documents)
        average_length = total_length / count if count else 0.0
        ranked = []
        normalized_query = self._search_normalize(query).strip()

        for row, frequencies, length in documents:
            score = 0.0
            matched = []
            for token in query_tokens:
                frequency = frequencies.get(token, 0)
                if not frequency:
                    continue
                matched.append(token)
                df = document_frequencies[token]
                inverse_frequency = math.log(
                    1.0 + (count - df + 0.5) / (df + 0.5)
                )
                denominator = frequency + 1.2 * (
                    1.0 - 0.75 + 0.75 * (
                        length / average_length if average_length else 0.0
                    )
                )
                score += inverse_frequency * (
                    frequency * 2.2 / denominator
                )

            if not matched:
                continue

            normalized_content = self._search_normalize(row["content"])
            phrase_match = normalized_query in normalized_content
            if phrase_match:
                score += 1.0

            ranked.append({
                "document_id": row["document_id"],
                "document_sha256": row["document_sha256"],
                "file_name": row["file_name"],
                "subject": row["subject"],
                "chunk_index": row["chunk_index"],
                "content": row["content"],
                "chunk_sha256": row["chunk_sha256"],
                "start_char": row["start_char"],
                "end_char": row["end_char"],
                "score": round(score, 8),
                "matched_terms": matched,
                "phrase_match": phrase_match,
                "ranking_method": "bm25_lexical_v1",
                "knowledge_status": "prepared_not_learned",
            })

        ranked.sort(
            key=lambda item: (
                -item["score"],
                item["document_id"],
                item["chunk_index"],
            )
        )
        return ranked[:limit]

    @staticmethod
    def fuse_rankings_rrf(
        ranked_lists: dict[str, list[dict]],
        *,
        weights: dict[str, float] | None = None,
        rrf_k: int = 60,
        limit: int = 10,
    ) -> list[dict]:
        """Fuse lexical/dense ranked candidates without comparing raw score scales.

        The method is deliberately model-agnostic: callers may provide BM25,
        dense-vector, or other already-ranked result lists. Candidate identity
        uses chunk SHA-256 when available, falling back to document/chunk IDs.
        It does not perform embedding inference, verify evidence, or promote
        retrieved material to learned knowledge.
        """
        if not isinstance(ranked_lists, dict) or not ranked_lists:
            raise ValueError("ranked_lists deve ser um dicionário não vazio.")
        if len(ranked_lists) > 16:
            raise ValueError("No máximo 16 canais de recuperação são permitidos.")
        if (
            isinstance(rrf_k, bool)
            or not isinstance(rrf_k, int)
            or not 1 <= rrf_k <= 10000
        ):
            raise ValueError("rrf_k deve ser um inteiro entre 1 e 10000.")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("limit deve ser um inteiro entre 1 e 100.")

        raw_source_names = list(ranked_lists)
        if any(
            not isinstance(name, str) or not name.strip() or len(name) > 80
            for name in raw_source_names
        ):
            raise ValueError("Cada canal precisa ter um nome válido de até 80 caracteres.")
        source_names = sorted(raw_source_names)
        if any(not isinstance(ranked_lists[name], list) for name in source_names):
            raise ValueError("Cada canal deve fornecer uma lista ranqueada.")
        if any(len(ranked_lists[name]) > 5000 for name in source_names):
            raise ValueError("Cada canal pode fornecer no máximo 5000 candidatos.")

        if weights is None:
            weights = {}
        if not isinstance(weights, dict):
            raise ValueError("weights deve ser um dicionário ou None.")
        unknown_weights = set(weights) - set(source_names)
        if unknown_weights:
            raise ValueError("weights contém canais não presentes em ranked_lists.")

        channel_weights: dict[str, float] = {}
        for source in source_names:
            raw_weight = weights.get(source, 1.0)
            if isinstance(raw_weight, bool) or not isinstance(raw_weight, (int, float)):
                raise ValueError("Cada peso RRF deve ser finito e positivo.")
            try:
                weight = float(raw_weight)
            except (OverflowError, ValueError) as exc:
                raise ValueError("Cada peso RRF deve ser finito e positivo.") from exc
            if not math.isfinite(weight) or weight <= 0.0:
                raise ValueError("Cada peso RRF deve ser finito e positivo.")
            channel_weights[source] = weight

        fused: dict[str, dict] = {}
        source_ranks: dict[str, dict[str, int]] = {}
        source_scores: dict[str, dict[str, float | None]] = {}

        for source in source_names:
            seen_in_source: set[str] = set()
            source_ranks[source] = {}
            source_scores[source] = {}
            for rank, raw_item in enumerate(ranked_lists[source], start=1):
                if not isinstance(raw_item, dict):
                    raise ValueError(f"Resultado inválido no canal {source!r}.")
                chunk_hash = raw_item.get("chunk_sha256")
                document_id = raw_item.get("document_id")
                chunk_index = raw_item.get("chunk_index")
                if (
                    isinstance(chunk_hash, str)
                    and re.fullmatch(r"[0-9a-fA-F]{64}", chunk_hash.strip())
                ):
                    identity = "sha256:" + chunk_hash.strip().lower()
                elif (
                    isinstance(document_id, int)
                    and not isinstance(document_id, bool)
                    and document_id > 0
                    and isinstance(chunk_index, int)
                    and not isinstance(chunk_index, bool)
                    and chunk_index >= 0
                ):
                    identity = f"document:{document_id}:chunk:{chunk_index}"
                else:
                    raise ValueError(
                        "Cada candidato precisa de chunk_sha256 ou document_id/chunk_index válidos."
                    )
                if identity in seen_in_source:
                    continue
                seen_in_source.add(identity)

                entry = fused.get(identity)
                if entry is None:
                    entry = dict(raw_item)
                    entry["retrieval_identity"] = identity
                    fused[identity] = entry
                else:
                    # Enrich missing provenance fields without overwriting the
                    # canonical content or metadata already chosen for this chunk.
                    for key, value in raw_item.items():
                        if key not in entry or entry[key] is None:
                            entry[key] = value

                source_ranks[source][identity] = rank
                raw_score = raw_item.get("score")
                normalized_score = None
                if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
                    try:
                        candidate_score = float(raw_score)
                    except (OverflowError, ValueError):
                        candidate_score = None
                    if candidate_score is not None and math.isfinite(candidate_score):
                        normalized_score = candidate_score
                source_scores[source][identity] = normalized_score

        scored = []
        for identity, item in fused.items():
            rank_map = {
                source: source_ranks[source][identity]
                for source in source_names
                if identity in source_ranks[source]
            }
            score = sum(
                channel_weights[source] / (rrf_k + rank)
                for source, rank in rank_map.items()
            )
            enriched = dict(item)
            enriched["rrf_score"] = round(score, 12)
            enriched["retrieval_fusion"] = {
                "method": "reciprocal_rank_fusion_v1",
                "rrf_k": rrf_k,
                "source_ranks": rank_map,
                "source_weights": {
                    source: channel_weights[source] for source in rank_map
                },
                "source_scores": {
                    source: source_scores[source][identity]
                    for source in rank_map
                },
                "epistemic_state": "retrieved_reference_not_verified_fact",
            }
            scored.append(enriched)

        scored.sort(
            key=lambda item: (
                -item["rrf_score"],
                item["retrieval_identity"],
            )
        )
        return scored[:limit]

    def counts(self) -> dict[str, int]:
        db = self._connect()
        try:
            documents = db.execute(
                "SELECT COUNT(*) FROM knowledge_documents"
            ).fetchone()[0]
            chunks = db.execute(
                "SELECT COUNT(*) FROM knowledge_chunks"
            ).fetchone()[0]
            subjects = db.execute(
                "SELECT COUNT(DISTINCT subject) FROM knowledge_documents"
            ).fetchone()[0]

            return {
                "documents": int(documents),
                "chunks": int(chunks),
                "subjects": int(subjects),
            }
        finally:
            db.close()

    def export_dataset(self, output_path, subject: str | None = None) -> dict:
        if subject is not None and (not isinstance(subject, str) or not subject.strip()):
            raise ValueError("subject deve ser um texto não vazio ou None.")

        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)

        db = self._connect()
        try:
            query = """
                SELECT d.id AS document_id, d.subject, d.sha256 AS document_sha256,
                       d.source_path, c.chunk_index, c.content, c.sha256 AS chunk_sha256
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id=c.document_id
                WHERE d.status='prepared'
            """
            params = ()
            if subject is not None:
                query += " AND d.subject=?"
                params = (str(subject).strip(),)
            query += " ORDER BY d.id, c.chunk_index"
            rows = db.execute(query, params).fetchall()
        finally:
            db.close()

        if not rows:
            raise ValueError("Não há fragmentos preparados para exportar.")

        created = False
        try:
            with output.open("x", encoding="utf-8") as handle:
                created = True
                for row in rows:
                    record = {
                        "document_id": row["document_id"],
                        "subject": row["subject"],
                        "document_sha256": row["document_sha256"],
                        "source_path": row["source_path"],
                        "chunk_index": row["chunk_index"],
                        "content": row["content"],
                        "chunk_sha256": row["chunk_sha256"],
                        "status": "prepared_not_learned",
                    }
                    handle.write(_json(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            if created and output.exists():
                output.unlink()
            raise

        return {
            "path": str(output.resolve()),
            "records": len(rows),
            "status": "dataset_prepared_not_training",
        }
