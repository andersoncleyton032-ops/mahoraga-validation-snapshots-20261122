#!/usr/bin/env python3
"""Reproducible held-out evaluation for Mahoraga's lexical knowledge retrieval.

The benchmark is deliberately separate from training. It measures retrieval
quality over a synthetic, versioned corpus and reports semantic-gap/typo cases
without pretending that BM25 understands paraphrases or misspellings.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "tests" / "fixtures" / "knowledge_retrieval_v1.json"
sys.path.insert(0, str(ROOT))

from agent.knowledge_engine import KnowledgeEngine
from agent.store import KnowledgeStore


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k deve ser inteiro positivo.")
    return len(set(retrieved[:k]) & relevant) / k


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k deve ser inteiro positivo.")
    if not relevant:
        raise ValueError("O conjunto de documentos relevantes não pode estar vazio.")
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    if not relevant:
        raise ValueError("O conjunto de documentos relevantes não pode estar vazio.")
    for rank, document_id in enumerate(retrieved, start=1):
        if document_id in relevant:
            return 1.0 / rank
    return 0.0


def _metrics(cases: list[dict[str, Any]], k: int) -> dict[str, float]:
    if not cases:
        return {
            "precision_at_k": 0.0,
            "recall_at_k": 0.0,
            "mrr": 0.0,
        }
    return {
        "precision_at_k": round(statistics.mean(
            precision_at_k(case["retrieved"], set(case["relevant"]), k)
            for case in cases
        ), 6),
        "recall_at_k": round(statistics.mean(
            recall_at_k(case["retrieved"], set(case["relevant"]), k)
            for case in cases
        ), 6),
        "mrr": round(statistics.mean(
            reciprocal_rank(case["retrieved"], set(case["relevant"]))
            for case in cases
        ), 6),
    }


def _load_suite(path: str | Path) -> dict[str, Any]:
    suite_path = Path(path).expanduser().resolve()
    try:
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Não foi possível ler o conjunto de avaliação: {exc}") from exc

    if not isinstance(suite, dict):
        raise ValueError("O conjunto de avaliação deve ser um objeto JSON.")
    if suite.get("version") != 1 or suite.get("split") != "held_out":
        raise ValueError("O conjunto deve usar version=1 e split='held_out'.")

    corpus = suite.get("corpus")
    queries = suite.get("queries")
    if not isinstance(corpus, list) or not corpus:
        raise ValueError("corpus deve ser uma lista não vazia.")
    if not isinstance(queries, list) or not queries:
        raise ValueError("queries deve ser uma lista não vazia.")

    ids = set()
    for item in corpus:
        if not isinstance(item, dict):
            raise ValueError("Cada documento do corpus deve ser um objeto.")
        identifier = item.get("id")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[a-z0-9_-]{1,80}", identifier)
            or identifier in ids
        ):
            raise ValueError(f"ID de documento inválido ou duplicado: {identifier!r}")
        if not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ValueError(f"Texto ausente no documento {identifier!r}.")
        if not isinstance(item.get("subject"), str) or not item["subject"].strip():
            raise ValueError(f"Assunto ausente no documento {identifier!r}.")
        ids.add(identifier)

    query_ids = set()
    for item in queries:
        if not isinstance(item, dict):
            raise ValueError("Cada consulta deve ser um objeto.")
        identifier = item.get("id")
        if not isinstance(identifier, str) or identifier in query_ids:
            raise ValueError(f"ID de consulta inválido ou duplicado: {identifier!r}")
        query_ids.add(identifier)
        if not isinstance(item.get("query"), str) or not item["query"].strip():
            raise ValueError(f"Consulta vazia: {identifier!r}")
        if not isinstance(item.get("category"), str) or not item["category"].strip():
            raise ValueError(f"Categoria ausente: {identifier!r}")
        relevant = item.get("relevant_document_ids")
        if not isinstance(relevant, list) or not relevant:
            raise ValueError(f"Relevância ausente: {identifier!r}")
        if any(document_id not in ids for document_id in relevant):
            raise ValueError(f"Documento relevante inexistente em {identifier!r}")

    return suite


def evaluate_suite(suite_path: str | Path = DEFAULT_SUITE, k: int = 3) -> dict[str, Any]:
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 100:
        raise ValueError("k deve estar entre 1 e 100.")

    suite = _load_suite(suite_path)
    with tempfile.TemporaryDirectory(prefix="mahoraga-retrieval-eval-") as temporary:
        root = Path(temporary)
        store = KnowledgeStore(root / "evaluation.sqlite3")
        engine = KnowledgeEngine(store)
        internal_ids: dict[str, int] = {}

        for document in suite["corpus"]:
            source = root / f"{document['id']}.txt"
            source.write_text(document["text"], encoding="utf-8")
            imported = engine.import_document(
                source,
                subject=document["subject"],
            )
            internal_ids[document["id"]] = imported["document_id"]

        reverse_ids = {
            internal_id: external_id
            for external_id, internal_id in internal_ids.items()
        }
        case_results = []
        max_candidates = min(
            engine.MAX_SEARCH_CANDIDATES,
            len(suite["corpus"]),
        )

        for query in suite["queries"]:
            matches = engine.search_chunks(
                query["query"],
                limit=k,
                max_candidates=max_candidates,
            )
            retrieved = []
            for match in matches:
                external_id = reverse_ids[match["document_id"]]
                if external_id not in retrieved:
                    retrieved.append(external_id)

            case_results.append({
                "id": query["id"],
                "category": query["category"],
                "query": query["query"],
                "relevant": list(query["relevant_document_ids"]),
                "retrieved": retrieved,
                "precision_at_k": round(
                    precision_at_k(
                        retrieved,
                        set(query["relevant_document_ids"]),
                        k,
                    ),
                    6,
                ),
                "recall_at_k": round(
                    recall_at_k(
                        retrieved,
                        set(query["relevant_document_ids"]),
                        k,
                    ),
                    6,
                ),
                "reciprocal_rank": round(
                    reciprocal_rank(
                        retrieved,
                        set(query["relevant_document_ids"]),
                    ),
                    6,
                ),
            })

        categories = sorted({case["category"] for case in case_results})
        by_category = {
            category: _metrics(
                [case for case in case_results if case["category"] == category],
                k,
            )
            for category in categories
        }

        return {
            "suite_id": suite["suite_id"],
            "suite_version": suite["version"],
            "split": suite["split"],
            "retrieval_method": "bm25_lexical_v1",
            "k": k,
            "corpus_documents": len(suite["corpus"]),
            "query_count": len(case_results),
            "lexical_query_count": sum(
                case["category"] == "lexical" for case in case_results
            ),
            "overall": _metrics(case_results, k),
            "by_category": by_category,
            "cases": case_results,
            "storage": "temporary_sqlite_discarded_after_evaluation",
            "training_performed": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default=str(DEFAULT_SUITE))
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--min-lexical-recall", type=float, default=0.95)
    parser.add_argument("--min-lexical-mrr", type=float, default=0.95)
    args = parser.parse_args(argv)

    try:
        report = evaluate_suite(args.suite, args.k)
    except (ValueError, TypeError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    lexical = report["by_category"].get("lexical")
    if lexical is None:
        print("ERRO: nenhuma consulta da categoria lexical.", file=sys.stderr)
        return 2

    if lexical["recall_at_k"] < args.min_lexical_recall:
        print(
            "FALHA: recall lexical abaixo do mínimo "
            f"({lexical['recall_at_k']} < {args.min_lexical_recall}).",
            file=sys.stderr,
        )
        return 1
    if lexical["mrr"] < args.min_lexical_mrr:
        print(
            "FALHA: MRR lexical abaixo do mínimo "
            f"({lexical['mrr']} < {args.min_lexical_mrr}).",
            file=sys.stderr,
        )
        return 1

    print(
        "RECUPERAÇÃO: BASELINE LEXICAL APROVADO "
        f"(Recall@{args.k}={lexical['recall_at_k']}, MRR={lexical['mrr']})."
    )
    print(
        "Limite: consultas semânticas e erros tipográficos são reportados, "
        "mas não fazem parte do critério de aprovação lexical."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
