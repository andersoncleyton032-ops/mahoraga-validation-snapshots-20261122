import pytest

from agent.knowledge_engine import KnowledgeEngine
from agent.store import KnowledgeStore


@pytest.fixture
def engine(tmp_path):
    store = KnowledgeStore(tmp_path / "retrieval.sqlite3")
    return KnowledgeEngine(store)


def _import(engine, tmp_path, name, text, subject="hardware"):
    source = tmp_path / name
    source.write_text(text, encoding="utf-8")
    return engine.import_document(source, subject=subject)


def test_search_chunks_ranks_relevant_content_and_preserves_provenance(
    engine, tmp_path
):
    relevant = _import(
        engine,
        tmp_path,
        "thermal.md",
        "A temperatura do processador aumenta durante carga sustentada. "
        "O monitoramento da CPU registra aquecimento e consumo.",
    )
    _import(
        engine,
        tmp_path,
        "visual.md",
        "A cena do Blender contém uma malha, vértices e materiais.",
        subject="graphics",
    )

    results = engine.search_chunks("temperatura processador CPU", limit=5)

    assert results
    assert results[0]["document_id"] == relevant["document_id"]
    assert results[0]["file_name"] == "thermal.md"
    assert results[0]["subject"] == "hardware"
    assert results[0]["ranking_method"] == "bm25_lexical_v1"
    assert results[0]["knowledge_status"] == "prepared_not_learned"
    assert results[0]["chunk_sha256"]
    assert results[0]["matched_terms"] == ["temperatura", "processador", "cpu"]


def test_search_chunks_is_accent_insensitive_and_deterministic(engine, tmp_path):
    imported = _import(
        engine,
        tmp_path,
        "energia.txt",
        "A eficiência energética depende da medição de energia e temperatura.",
    )

    first = engine.search_chunks("eficiencia energetica", limit=3)
    second = engine.search_chunks("eficiência energética", limit=3)

    assert first == second
    assert first[0]["document_id"] == imported["document_id"]
    assert first[0]["phrase_match"] is True


def test_search_chunks_applies_exact_subject_filter(engine, tmp_path):
    hardware = _import(
        engine, tmp_path, "hardware.txt",
        "A temperatura do processador deve ser monitorada.", "hardware"
    )
    _import(
        engine, tmp_path, "physics.txt",
        "A temperatura de um fluido varia com a energia.", "physics"
    )

    results = engine.search_chunks(
        "temperatura", subject="hardware"
    )

    assert results
    assert {item["document_id"] for item in results} == {
        hardware["document_id"]
    }


def test_search_chunks_returns_empty_when_no_terms_match(engine, tmp_path):
    _import(
        engine, tmp_path, "notes.txt",
        "A geometria da malha contém vértices e polígonos."
    )

    assert engine.search_chunks("temperatura do processador") == []


def test_search_chunks_rejects_invalid_queries_and_bounds(engine):
    for query in ("", "   ", "a e de", "x"):
        with pytest.raises(ValueError):
            engine.search_chunks(query)

    with pytest.raises(ValueError, match="500 caracteres"):
        engine.search_chunks("palavra " * 70)

    for limit in (0, 101, True):
        with pytest.raises(ValueError):
            engine.search_chunks("temperatura", limit=limit)

    for max_candidates in (0, 5001, True):
        with pytest.raises(ValueError):
            engine.search_chunks(
                "temperatura", max_candidates=max_candidates
            )

    with pytest.raises(ValueError, match="subject"):
        engine.search_chunks("temperatura", subject="   ")


def test_search_chunks_uses_only_prepared_knowledge(engine, tmp_path):
    imported = _import(
        engine, tmp_path, "prepared.txt",
        "A temperatura do sistema deve ser monitorada."
    )
    assert imported["status"] == "imported"

    results = engine.search_chunks("temperatura sistema")

    assert results
    assert all(
        item["knowledge_status"] == "prepared_not_learned"
        for item in results
    )



def test_search_chunks_skips_oversized_fragments_to_bound_memory(
    engine, tmp_path
):
    source = tmp_path / "oversized.txt"
    source.write_text("temperatura " + ("dados " * 1000), encoding="utf-8")
    engine.import_document(
        source, subject="hardware", chunk_size=10000, overlap=0
    )

    assert engine.search_chunks("temperatura") == []
