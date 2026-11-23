from agent.integration_core import IntegratedCore


def test_generation_context_preserves_associative_provenance_and_uncertainty():
    prepared = {
        "knowledge": {
            "status": "retrieved",
            "matches": [{
                "document_id": 1,
                "document_sha256": "a" * 64,
                "file_name": "notes.md",
                "subject": "test",
                "chunk_index": 0,
                "chunk_sha256": "b" * 64,
                "ranking_method": "bm25_lexical_v1",
                "score": 1.2,
                "content": "A retrieved reference.",
            }],
            "associations": {
                "status": "completed",
                "associations": [{
                    "anchor_event_id": 3,
                    "source_event": {
                        "id": 1,
                        "event_type": "test.episode",
                        "created_at": "2026-11-17T12:00:00+00:00",
                        "payload": {"observation": "source event"},
                    },
                    "document_id": 1,
                    "chunk_index": 0,
                    "chunk_sha256": "b" * 64,
                    "relations": [{
                        "predicate": "related_to",
                        "direction": "outgoing",
                        "event": {
                            "id": 2,
                            "event_type": "test.episode",
                            "created_at": "2026-11-17T12:01:00+00:00",
                            "payload": {"observation": "related event"},
                        },
                        "relation_event": {"id": 4},
                        "verified": False,
                    }],
                }],
            },
        }
    }
    context, count = IntegratedCore._generation_knowledge_context(prepared)
    assert count == 1
    assert context is not None
    assert '"all_verified": false' in context
    assert '"related_event_id": 2' in context
    assert "candidate_unverified" in context
    assert "related event" in context
