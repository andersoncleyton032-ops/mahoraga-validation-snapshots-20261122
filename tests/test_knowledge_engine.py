import hashlib
import json
import sqlite3

import pytest

from agent.store import KnowledgeStore
from agent.knowledge_engine import KnowledgeEngine


@pytest.fixture
def engine(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge_test.sqlite3")
    return KnowledgeEngine(store)


def test_import_document_and_preserve_source(engine, tmp_path):
    source = tmp_path / "material.txt"
    original = ("Conteúdo de teste do Mahoraga. " * 30).encode("utf-8")
    source.write_bytes(original)

    result = engine.import_document(
        source, subject="Física", chunk_size=150, overlap=20
    )

    assert result["status"] == "imported"
    assert result["learning_status"] == "prepared_not_learned"
    assert result["chunks_created"] > 1
    assert source.read_bytes() == original

    documents = engine.list_documents()
    assert len(documents) == 1
    assert documents[0]["subject"] == "Física"


def test_duplicate_detection_by_sha256(engine, tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    content = "Material idêntico para teste de duplicidade." * 10

    first.write_text(content, encoding="utf-8")
    second.write_text(content, encoding="utf-8")

    imported = engine.import_document(first, "Teste")
    duplicate = engine.import_document(second, "Outro assunto")

    assert imported["status"] == "imported"
    assert duplicate["status"] == "duplicate"
    assert duplicate["document_id"] == imported["document_id"]
    assert engine.counts()["documents"] == 1


def test_chunks_have_valid_content_hashes(engine, tmp_path):
    source = tmp_path / "chunks.md"
    source.write_text("Palavra de teste. " * 100, encoding="utf-8")

    result = engine.import_document(
        source, "Linguagem", chunk_size=150, overlap=20
    )
    chunks = engine.list_chunks(result["document_id"])

    assert len(chunks) == result["chunks_created"]

    for chunk in chunks:
        digest = hashlib.sha256(
            chunk["content"].encode("utf-8")
        ).hexdigest()
        assert digest == chunk["sha256"]
        assert chunk["start_char"] >= 0
        assert chunk["end_char"] > chunk["start_char"]


def test_counts_include_documents_chunks_and_subjects(engine, tmp_path):
    for name, subject in (
        ("a.txt", "Física"),
        ("b.txt", "Matemática"),
        ("c.txt", "Física"),
    ):
        source = tmp_path / name
        source.write_text(("Conteúdo. " * 30) + name, encoding="utf-8")
        engine.import_document(source, subject)

    counts = engine.counts()

    assert counts["documents"] == 3
    assert counts["chunks"] >= 3
    assert counts["subjects"] == 2


def test_dataset_export_and_no_overwrite(engine, tmp_path):
    source = tmp_path / "export.txt"
    source.write_text("Conteúdo para exportação. " * 30, encoding="utf-8")
    engine.import_document(source, "Exportação")

    output = tmp_path / "dataset.jsonl"
    result = engine.export_dataset(output)

    records = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
    ]

    assert result["status"] == "dataset_prepared_not_training"
    assert result["records"] == len(records)
    assert records
    assert all(r["status"] == "prepared_not_learned" for r in records)

    with pytest.raises(FileExistsError):
        engine.export_dataset(output)

    assert output.exists()


def test_unsupported_extension_is_rejected(engine, tmp_path):
    source = tmp_path / "program.py"
    source.write_text("print('teste')", encoding="utf-8")

    with pytest.raises(ValueError, match="Formato não suportado"):
        engine.import_document(source, "Código")


def test_invalid_utf8_is_rejected(engine, tmp_path):
    source = tmp_path / "invalid.txt"
    source.write_bytes(b"\xff\xfe\xfa")

    with pytest.raises(ValueError, match="UTF-8"):
        engine.import_document(source, "Teste")


def test_empty_document_is_rejected(engine, tmp_path):
    source = tmp_path / "empty.txt"
    source.write_text("   \n  ", encoding="utf-8")

    with pytest.raises(ValueError, match="vazio"):
        engine.import_document(source, "Teste")


def test_invalid_chunk_size_and_overlap_are_rejected(engine, tmp_path):
    source = tmp_path / "parameters.txt"
    source.write_text("Conteúdo de teste. " * 30, encoding="utf-8")

    with pytest.raises(ValueError):
        engine.import_document(source, "Teste", chunk_size=99)

    with pytest.raises(ValueError):
        engine.import_document(source, "Teste", chunk_size=100, overlap=100)


def test_migration_is_registered_once(engine):
    with sqlite3.connect(engine.db_path) as db:
        versions = db.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]

    assert versions == [(1,), (2,), (3,), (4,), (5,)]
    assert integrity == "ok"


def test_subject_must_be_valid_text(engine, tmp_path):
    source = tmp_path / "subject.txt"
    source.write_text("Conteúdo de teste. " * 20, encoding="utf-8")

    for subject in (None, "", "   ", 123):
        with pytest.raises(ValueError):
            engine.import_document(source, subject)


def test_metadata_must_be_a_dictionary(engine, tmp_path):
    source = tmp_path / "metadata.txt"
    source.write_text("Conteúdo de teste. " * 20, encoding="utf-8")

    with pytest.raises(ValueError):
        engine.import_document(source, "Teste", metadata=["inválido"])


def test_chunk_parameters_must_be_integers(engine, tmp_path):
    source = tmp_path / "types.txt"
    source.write_text("Conteúdo de teste. " * 20, encoding="utf-8")

    for chunk_size, overlap in (("200", 20), (200, "20"), (True, 0)):
        with pytest.raises(ValueError):
            engine.import_document(
                source, "Teste", chunk_size=chunk_size, overlap=overlap
            )


def test_list_chunks_validates_arguments(engine):
    for document_id, limit in ((1, 0), (1, -1), (1, 10001), ("inválido", 10)):
        with pytest.raises(ValueError):
            engine.list_chunks(document_id, limit)


def test_chunk_offsets_match_original_source(engine, tmp_path):
    source = tmp_path / "offsets.txt"
    original = "  Início com espaços.\n" + ("Conteúdo central. " * 30) + "\nFim.  "
    source.write_text(original, encoding="utf-8")

    result = engine.import_document(
        source, "Offsets", chunk_size=120, overlap=15
    )
    chunks = engine.list_chunks(result["document_id"])

    assert chunks
    for chunk in chunks:
        start = chunk["start_char"]
        end = chunk["end_char"]
        assert original[start:end] == chunk["content"]


def test_rrf_fuses_lexical_and_dense_rankings_by_candidate_identity():
    lexical = [
        {"document_id": 1, "chunk_index": 0, "chunk_sha256": "a" * 64, "content": "A", "score": 2.1},
        {"document_id": 1, "chunk_index": 1, "chunk_sha256": "b" * 64, "content": "B", "score": 1.2},
    ]
    dense = [
        {"document_id": 1, "chunk_index": 1, "chunk_sha256": "b" * 64, "content": "B", "score": 0.91},
        {"document_id": 2, "chunk_index": 0, "chunk_sha256": "c" * 64, "content": "C", "score": 0.87},
    ]

    fused = KnowledgeEngine.fuse_rankings_rrf(
        {"lexical": lexical, "dense": dense}, limit=10
    )

    assert [item["content"] for item in fused] == ["B", "A", "C"]
    assert fused[0]["retrieval_fusion"]["method"] == "reciprocal_rank_fusion_v1"
    assert fused[0]["retrieval_fusion"]["source_ranks"] == {
        "dense": 1, "lexical": 2
    }
    assert fused[0]["retrieval_fusion"]["epistemic_state"] == (
        "retrieved_reference_not_verified_fact"
    )
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"]


def test_rrf_deduplicates_within_a_channel_and_preserves_source_scores():
    chunk = {
        "document_id": 7,
        "chunk_index": 3,
        "chunk_sha256": "d" * 64,
        "content": "Trecho preservado",
        "score": 0.75,
    }
    second = {
        "document_id": 7,
        "chunk_index": 4,
        "chunk_sha256": "e" * 64,
        "content": "Outro trecho",
        "score": 0.70,
    }

    fused = KnowledgeEngine.fuse_rankings_rrf(
        {"lexical": [chunk, dict(chunk), second], "dense": [dict(chunk)]},
        weights={"lexical": 1.0, "dense": 2.0},
        rrf_k=10,
    )

    first = next(item for item in fused if item["chunk_sha256"] == "d" * 64)
    assert first["retrieval_fusion"]["source_ranks"] == {
        "dense": 1, "lexical": 1
    }
    assert first["retrieval_fusion"]["source_weights"] == {
        "dense": 2.0, "lexical": 1.0
    }
    assert first["retrieval_fusion"]["source_scores"] == {
        "dense": 0.75, "lexical": 0.75
    }
    assert len(fused) == 2
    assert chunk == {
        "document_id": 7, "chunk_index": 3, "chunk_sha256": "d" * 64,
        "content": "Trecho preservado", "score": 0.75
    }


def test_rrf_has_deterministic_tie_breaking_and_limit():
    first = {"document_id": 2, "chunk_index": 0, "chunk_sha256": "f" * 64}
    second = {"document_id": 1, "chunk_index": 0, "chunk_sha256": "a" * 64}
    fused = KnowledgeEngine.fuse_rankings_rrf(
        {"lexical": [first, second], "dense": [second, first]},
        rrf_k=60,
        limit=1,
    )
    assert len(fused) == 1
    assert fused[0]["chunk_sha256"] == "a" * 64


@pytest.mark.parametrize(
    "ranked_lists,kwargs",
    [
        ([], {}),
        ({"lexical": "not-a-list"}, {}),
        ({"lexical": [{}]}, {}),
        ({"lexical": [{"document_id": True, "chunk_index": 0}]}, {}),
        ({"lexical": []}, {"rrf_k": True}),
        ({"lexical": []}, {"rrf_k": 0}),
        ({"lexical": []}, {"limit": True}),
        ({"lexical": []}, {"weights": {"unknown": 1.0}}),
        ({"lexical": []}, {"weights": {"lexical": 0.0}}),
        ({"lexical": []}, {"weights": {"lexical": float("nan")}}),
        ({"lexical": [], 1: []}, {}),
        ({"lexical": []}, {"weights": {"lexical": 10 ** 10000}}),
        ({"lexical": [{"chunk_sha256": "not-a-hash"}]}, {}),
        ({"lexical": [{}] * 5001}, {}),
    ],
)
def test_rrf_rejects_invalid_inputs(ranked_lists, kwargs):
    with pytest.raises(ValueError):
        KnowledgeEngine.fuse_rankings_rrf(ranked_lists, **kwargs)
