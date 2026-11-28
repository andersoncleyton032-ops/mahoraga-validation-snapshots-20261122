"""Evidence-gated experience replay and context-aware consolidation.

Episodes are append-only observations, not neural weight updates.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Any

from .attestation import attestation_request_id, validate_json


class AdaptiveLearning:
    VERSION = "0.5.0"
    EVENT_TYPE = "adaptive.experience.recorded"
    MAX_TEXT = 2000
    MAX_EPISODES = 500
    MAX_CONTEXT_BYTES = 4096
    MAX_REFERENCES_BYTES = 4096
    MAX_EVIDENCE_RECEIPT_BYTES = 8192

    def __init__(self, cognitive):
        self.cognitive = cognitive
        self.store = cognitive.store

    @staticmethod
    def _text(value: Any, field: str, maximum: int = 2000) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f"{field} deve ser texto não vazio com até {maximum} caracteres.")
        return value.strip()

    @staticmethod
    def _task_key(value: str) -> str:
        tokens = re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE)
        return " ".join(tokens)

    RETRIEVAL_STOPWORDS = frozenset({
        "a", "as", "o", "os", "um", "uma", "uns", "umas", "de", "do", "da",
        "dos", "das", "em", "no", "na", "nos", "nas", "por", "para", "com",
        "sem", "e", "ou", "que", "como", "ao", "aos", "se", "sobre", "meu",
        "minha", "meus", "minhas", "the", "a", "an", "and", "or", "of", "to",
        "in", "on", "for", "with", "without", "from", "by", "is", "are", "was",
        "were", "what", "how", "when", "where", "we", "our", "it", "this",
    })

    @classmethod
    def _retrieval_tokens(cls, value: str) -> set[str]:
        import unicodedata

        normalized = unicodedata.normalize("NFKD", value.casefold())
        normalized = "".join(
            char for char in normalized if not unicodedata.combining(char)
        )
        tokens = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
        return {
            token for token in tokens
            if len(token) > 1 and token not in cls.RETRIEVAL_STOPWORDS
        }

    @staticmethod
    def _context_retrieval_tags(context: dict[str, Any]) -> list[str]:
        tags = []
        for value in context.values():
            candidates = value if isinstance(value, list) else [value]
            for candidate in candidates:
                if (
                    isinstance(candidate, str)
                    and candidate.strip()
                    and len(candidate) <= 60
                    and candidate not in tags
                ):
                    tags.append(candidate.strip())
                if len(tags) >= 10:
                    return tags
        return tags

    @staticmethod
    def _character_ngrams(tokens: set[str], size: int = 3) -> set[str]:
        grams = set()
        for token in tokens:
            padded = f"^{token}$"
            if len(padded) <= size:
                grams.add(padded)
            else:
                grams.update(
                    padded[index:index + size]
                    for index in range(len(padded) - size + 1)
                )
        return grams

    @staticmethod
    def _jaccard(left: set[str], right: set[str]) -> float:
        union = left | right
        return len(left & right) / len(union) if union else 0.0

    @staticmethod
    def _dice(left: set[str], right: set[str]) -> float:
        total = len(left) + len(right)
        return (2.0 * len(left & right) / total) if total else 0.0

    @classmethod
    def _retrieval_score(
        cls, query_tokens: set[str], stored_tokens: set[str],
        query_tags: set[str], stored_tags: set[str],
    ) -> tuple[float, dict[str, float]]:
        token_overlap = cls._jaccard(query_tokens, stored_tokens)
        morphology = cls._dice(
            cls._character_ngrams(query_tokens),
            cls._character_ngrams(stored_tokens),
        )
        components = {
            "task_token_overlap": token_overlap,
            "task_morphology_similarity": morphology,
        }
        weights = {"task_token_overlap": 0.35, "task_morphology_similarity": 0.40}
        tag_overlap = cls._jaccard(query_tags, stored_tags) if query_tags else 0.0
        if query_tags:
            components["tag_overlap"] = tag_overlap
            weights["tag_overlap"] = 0.25
        active_weight = sum(weights.values())
        score = sum(
            components[name] * weight for name, weight in weights.items()
        ) / active_weight
        # Explicit caller tags may bridge task paraphrases, but never alter
        # context matching or evidence trust. Strong tag agreement is a
        # separate retrieval path, not proof that the episode is correct.
        if query_tags and tag_overlap >= 0.75:
            score = max(score, tag_overlap * 0.80)
        return round(score, 6), {
            name: round(value, 6) for name, value in components.items()
        }

    @staticmethod
    def _context_signature(context: dict[str, Any]) -> str:
        try:
            raw = json.dumps(
                context, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("context deve conter somente dados JSON finitos e não recursivos.") from exc
        if len(raw) > AdaptiveLearning.MAX_CONTEXT_BYTES:
            raise ValueError("context excede 4096 bytes.")
        return hashlib.sha256(raw).hexdigest()[:24]

    @staticmethod
    def _candidate_id(task_key: str, context_signature: str,
                      outcome: str, event_ids: list[int]) -> str:
        raw = json.dumps(
            [task_key, context_signature, outcome, sorted(event_ids)],
            ensure_ascii=False, separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _finite_float(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @classmethod
    def _numeric_vector(cls, value: Any, field: str) -> list[float]:
        values = value if isinstance(value, list) else [value]
        if not 1 <= len(values) <= 16:
            raise ValueError(f"{field} deve conter de 1 a 16 valores.")
        result = []
        for item in values:
            number = cls._finite_float(item)
            if number is None:
                raise ValueError(f"{field} deve conter somente números finitos representáveis.")
            result.append(number)
        return result

    @staticmethod
    def _bounded_mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    @classmethod
    def _variance(cls, values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = cls._bounded_mean(values)
        return sum((value - mean) ** 2 for value in values) / (len(values) - 1)

    @staticmethod
    def _canonical_sha256(value: dict[str, Any]) -> str:
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _episode_is_independently_verified(self, episode: dict[str, Any]) -> bool:
        receipt = episode.get("evidence_verification")
        verifier = getattr(self.cognitive, "evidence_verifier", None)
        verify_receipt = getattr(verifier, "verify_receipt", None)
        if not isinstance(receipt, dict) or not callable(verify_receipt):
            return False
        subject = {
            key: value for key, value in episode.items()
            if key not in {"evidence_verification", "event_id"}
        }
        try:
            subject_sha256 = self._canonical_sha256(subject)
            if (
                receipt.get("verified") is not True
                or receipt.get("subject_sha256") != subject_sha256
                or not isinstance(receipt.get("verifier_id"), str)
                or not receipt["verifier_id"].strip()
                or not isinstance(receipt.get("receipt_id"), str)
                or not receipt["receipt_id"].strip()
                or receipt.get("source_identity_verified") is not True
                or not isinstance(receipt.get("source_id"), str)
                or not receipt["source_id"].strip()
            ):
                return False
            return verify_receipt(
                receipt=receipt,
                action="adaptive.record_experience",
                subject_sha256=subject_sha256,
            ) is True
        except Exception:
            return False

    def _verify_episode_evidence(
        self, episode: dict[str, Any], attestation: Any
    ) -> dict[str, Any] | None:
        verifier = getattr(self.cognitive, "evidence_verifier", None)
        verify = getattr(verifier, "verify_attestation", None)
        if attestation is None or not callable(verify):
            return None
        subject_sha256 = self._canonical_sha256(episode)
        try:
            receipt = verify(
                attestation=attestation,
                action="adaptive.record_experience",
                subject_sha256=subject_sha256,
                source=episode["source"],
            )
        except Exception:
            return None
        if (
            not isinstance(receipt, dict)
            or receipt.get("verified") is not True
            or receipt.get("subject_sha256") != subject_sha256
            or receipt.get("source_identity_verified") is not True
            or not isinstance(receipt.get("source_id"), str)
            or not receipt["source_id"].strip()
            or len(receipt["source_id"]) > 256
            or not isinstance(receipt.get("verifier_id"), str)
            or not receipt["verifier_id"].strip()
            or len(receipt["verifier_id"]) > 256
            or not isinstance(receipt.get("receipt_id"), str)
            or not receipt["receipt_id"].strip()
            or len(receipt["receipt_id"]) > 256
        ):
            return None
        try:
            validate_json(receipt)
            encoded = json.dumps(
                receipt,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if len(encoded) > self.MAX_EVIDENCE_RECEIPT_BYTES:
                return None
            # Normalize to a detached JSON-only copy; preserve verifier fields
            # (e.g. signatures) needed for later verify_receipt calls.
            return json.loads(encoded.decode("utf-8"))
        except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
            return None

    def record_experience(
        self, task: str, action: str, outcome: str, source: str, *,
        expected_outcome: str | None = None,
        prediction: float | list[float] | None = None,
        observed: float | list[float] | None = None,
        prediction_scale: float | None = None,
        prediction_metric: str | None = None,
        predictor_id: str | None = None,
        confidence: float = 0.5,
        validation_evidence: list[str] | None = None,
        evidence_attestation: Any = None,
        validated: bool = False,
        tags: list[str] | None = None,
        context: dict[str, Any] | None = None,
        references: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        """Record an episode and, optionally, a bounded numeric prediction error.

        Numeric errors are normalized by a caller-declared fixed scale. Progress
        is estimated later only across matching task, context, metric and predictor.
        """
        self.cognitive._authorize("record_observation")
        task = self._text(task, "task", 240)
        action = self._text(action, "action", self.MAX_TEXT)
        outcome = self._text(outcome, "outcome", self.MAX_TEXT)
        source = self._text(source, "source", 160)
        if expected_outcome is not None:
            expected_outcome = self._text(expected_outcome, "expected_outcome", self.MAX_TEXT)
        confidence_value = self._finite_float(confidence)
        if confidence_value is None or not 0.0 <= confidence_value <= 1.0:
            raise ValueError("confidence deve ser finita e representável entre 0 e 1.")
        confidence = confidence_value
        if not isinstance(validated, bool):
            raise ValueError("validated deve ser booleano.")
        evidence = [] if validation_evidence is None else validation_evidence
        if not isinstance(evidence, list) or any(
            not isinstance(item, str) or not item.strip() or len(item) > 500
            for item in evidence
        ):
            raise ValueError("validation_evidence deve conter textos não vazios.")
        if validated and not evidence:
            raise ValueError("Experiência validada exige evidência explícita.")
        if tags is None:
            tags = []
        if not isinstance(tags, list) or len(tags) > 20 or any(
            not isinstance(tag, str) or not tag.strip() or len(tag) > 60
            for tag in tags
        ):
            raise ValueError("tags deve conter até 20 textos válidos.")
        if context is None:
            context = {}
        if not isinstance(context, dict):
            raise ValueError("context deve ser um objeto.")
        context_signature = self._context_signature(context)
        if references is None:
            references = {}
        if not isinstance(references, dict):
            raise ValueError("references deve ser um objeto.")
        try:
            references_json = json.dumps(
                references,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("references deve conter somente dados JSON finitos.") from exc
        if len(references_json.encode("utf-8")) > self.MAX_REFERENCES_BYTES:
            raise ValueError("references excede 4096 bytes.")
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
            or len(idempotency_key) > 200
        ):
            raise ValueError("idempotency_key deve conter até 200 caracteres.")
        task_key = self._task_key(task)
        if not task_key:
            raise ValueError("task precisa conter ao menos um token alfanumérico.")

        numeric_prediction = prediction is not None or observed is not None
        if numeric_prediction and expected_outcome is not None:
            raise ValueError("Use expected_outcome ou prediction/observed, não ambos.")
        prediction_error = None
        prediction_error_kind = None
        prediction_details = None
        if numeric_prediction:
            if prediction is None or observed is None:
                raise ValueError("prediction e observed precisam ser fornecidos juntos.")
            predicted_values = self._numeric_vector(prediction, "prediction")
            observed_values = self._numeric_vector(observed, "observed")
            if len(predicted_values) != len(observed_values):
                raise ValueError("prediction e observed precisam ter a mesma dimensão.")
            scale = self._finite_float(prediction_scale)
            if scale is None or scale <= 0:
                raise ValueError("prediction_scale precisa ser finito, representável e maior que zero.")
            prediction_metric = self._text(prediction_metric, "prediction_metric", 120)
            predictor_id = self._text(predictor_id, "predictor_id", 120)
            absolute_errors = [
                min(abs(actual - predicted) / scale, 1.0)
                for predicted, actual in zip(predicted_values, observed_values)
            ]
            prediction_error = self._bounded_mean(absolute_errors)
            prediction_error_kind = "normalized_mae_v1"
            prediction_details = {
                "metric": prediction_metric,
                "predictor_id": predictor_id,
                "prediction": predicted_values,
                "observed": observed_values,
                "normalization_scale": scale,
                "error_method": prediction_error_kind,
            }
        elif any(value is not None for value in (
            prediction_scale, prediction_metric, predictor_id
        )):
            raise ValueError(
                "Metadados de predição numérica exigem prediction e observed."
            )
        elif expected_outcome is not None:
            prediction_error = (
                0.0 if expected_outcome.casefold() == outcome.casefold() else 1.0
            )
            prediction_error_kind = "categorical_exact_v1"

        episode = {
            "task": task,
            "task_key": task_key,
            "context": context,
            "context_signature": context_signature,
            "action": action,
            "outcome": outcome,
            "expected_outcome": expected_outcome,
            "prediction_error": prediction_error,
            "prediction_error_kind": prediction_error_kind,
            "prediction_details": prediction_details,
            "confidence": confidence,
            "source": source,
            "validated": validated,
            "validation_evidence": [item.strip() for item in evidence],
            "validation_state": "caller_asserted_unverified" if validated else "not_validated",
            "tags": [tag.strip() for tag in tags],
            "references": references,
            "learning_state": "episodic_only",
            "neural_training_performed": False,
        }
        evidence_receipt = self._verify_episode_evidence(
            episode, evidence_attestation
        )
        episode["evidence_verification"] = evidence_receipt
        if idempotency_key is None:
            event_id = self.store.record_event(self.EVENT_TYPE, episode)
            event_created = True
        else:
            persisted = self.store.record_event_once(
                self.EVENT_TYPE,
                idempotency_key.strip(),
                episode,
            )
            event_id = persisted["event_id"]
            event_created = persisted["created"]
        return {
            "status": "episode_recorded",
            "event_id": event_id,
            "event_created": event_created,
            "learning_state": "episodic_only",
            "prediction_error": prediction_error,
            "prediction_error_kind": prediction_error_kind,
            "validation_claim": episode["validation_state"],
            "context_signature": context_signature,
            "neural_training_performed": False,
        }

    def record_research_result(
        self,
        *,
        plan_id: str,
        candidate_id: str,
        initiative_kind: str,
        initiative_source: str,
        method: str,
        result_status: str,
        summary: str,
        evidence_refs: list[str],
        attempt_id: str = "initial",
        approved: bool = False,
    ) -> dict:
        """Record a caller-reported research outcome as an episodic experience.

        The report is never marked independently verified or semantically
        consolidated. A stable plan/attempt pair makes duplicate reports idempotent.
        """
        if approved is not True:
            raise PermissionError(
                "Registrar resultado de pesquisa exige aprovação explícita."
            )
        if not isinstance(plan_id, str) or not re.fullmatch(
            r"research-[0-9a-f]{24}", plan_id
        ):
            raise ValueError("plan_id inválido.")
        if not isinstance(candidate_id, str) or not candidate_id.strip() or len(candidate_id) > 64:
            raise ValueError("candidate_id inválido.")
        if not isinstance(attempt_id, str) or not re.fullmatch(
            r"[A-Za-z0-9._-]{1,64}", attempt_id
        ):
            raise ValueError("attempt_id deve conter de 1 a 64 caracteres válidos.")
        initiative_kind = self._text(initiative_kind, "initiative_kind", 80)
        initiative_source = self._text(initiative_source, "initiative_source", 120)
        method = self._text(method, "method", self.MAX_TEXT)
        self.cognitive._authorize("introspect")
        plan_entry = self.store.get_memory(f"research_plan:{plan_id}")
        plan = (
            plan_entry.get("value")
            if isinstance(plan_entry, dict) else None
        )
        if (
            not isinstance(plan, dict)
            or plan.get("schema") != "mahoraga.research_plan"
            or plan.get("plan_id") != plan_id
            or plan.get("candidate_id") != candidate_id
            or plan.get("initiative_kind") != initiative_kind
            or plan.get("source") != initiative_source
            or plan.get("status") != "prepared_pending_execution_review"
        ):
            raise ValueError(
                "O resultado não está vinculado a um plano de pesquisa válido."
            )
        summary = self._text(summary, "summary", self.MAX_TEXT)
        allowed_statuses = {
            "completed",
            "failed",
            "inconclusive",
            "blocked",
            "cancelled",
        }
        if not isinstance(result_status, str) or result_status not in allowed_statuses:
            raise ValueError("result_status não pertence ao conjunto permitido.")
        if (
            not isinstance(evidence_refs, list)
            or not 1 <= len(evidence_refs) <= 20
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item) > 500
                for item in evidence_refs
            )
        ):
            raise ValueError("evidence_refs exige de 1 a 20 referências não vazias.")

        return self.record_experience(
            task=f"research initiative {initiative_kind}",
            action=method,
            outcome=result_status,
            source="research_orchestrator",
            confidence=0.5,
            validated=False,
            context={
                "initiative_kind": initiative_kind,
                "initiative_source": initiative_source,
            },
            references={
                "research_plan_id": plan_id,
                "initiative_candidate_id": candidate_id,
                "attempt_id": attempt_id,
                "result_status": result_status,
                "summary": summary,
                "evidence_refs": [item.strip() for item in evidence_refs],
                "reported_by": "caller_supplied_not_independently_verified",
            },
            idempotency_key=f"research-plan-result:{plan_id}:{attempt_id}",
        ) | {
            "status": "research_result_recorded",
            "result_status": result_status,
            "attempt_id": attempt_id,
            "independently_verified": False,
            "semantic_consolidation_performed": False,
        }


    def retrieve_experiences(
        self,
        task: str,
        *,
        context: dict[str, Any] | None = None,
        limit: int = 5,
        min_similarity: float = 0.5,
        query_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Recall context-bound episodes using hybrid lexical, morphology and tag signals.

        Retrieval is read-only and advisory. Tag overlap is used only when the
        caller supplies query tags; it is not treated as independent evidence.
        """
        self.cognitive._authorize("read_project")
        task = self._text(task, "task", 240)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("limit deve ser inteiro entre 1 e 20.")
        threshold = self._finite_float(min_similarity)
        if threshold is None or not 0.0 <= threshold <= 1.0:
            raise ValueError("min_similarity deve ser finita e estar entre 0 e 1.")
        if context is None:
            context = {}
        if not isinstance(context, dict):
            raise ValueError("context deve ser um objeto JSON.")
        if query_tags is None:
            query_tags = []
        if not isinstance(query_tags, list) or len(query_tags) > 10 or any(
            not isinstance(tag, str) or not tag.strip() or len(tag) > 60
            for tag in query_tags
        ):
            raise ValueError("query_tags deve conter até 10 textos válidos.")
        context_signature = self._context_signature(context)
        query_key = self._task_key(task)
        query_tokens = self._retrieval_tokens(task)
        context_tags = self._context_retrieval_tags(context)
        combined_query_tags = list(dict.fromkeys(context_tags + query_tags))[:10]
        normalized_query_tags = self._retrieval_tokens(" ".join(combined_query_tags))
        if not query_key or not query_tokens:
            raise ValueError("task precisa conter termos úteis para recuperação.")

        events = self.store.list_events(
            limit=self.MAX_EPISODES,
            event_type=self.EVENT_TYPE,
        )
        total_events = self.store.count_events(event_type=self.EVENT_TYPE)
        matches = []
        malformed_count = 0
        context_mismatch_count = 0
        for event in events:
            payload = event.get("payload")
            if not isinstance(payload, dict):
                malformed_count += 1
                continue
            if payload.get("context_signature") != context_signature:
                context_mismatch_count += 1
                continue
            stored_key = payload.get("task_key")
            stored_task = payload.get("task")
            if (
                not isinstance(stored_key, str) or not stored_key
                or not isinstance(stored_task, str) or not stored_task
            ):
                malformed_count += 1
                continue
            stored_tokens = self._retrieval_tokens(stored_task)
            if not stored_tokens:
                continue
            stored_tags = self._retrieval_tokens(
                " ".join(tag for tag in payload.get("tags", []) if isinstance(tag, str))
            )
            similarity, components = self._retrieval_score(
                query_tokens, stored_tokens, normalized_query_tags, stored_tags
            )
            exact = stored_key == query_key
            if exact:
                similarity = 1.0
            if similarity < threshold:
                continue
            independently_verified = self._episode_is_independently_verified(
                {**payload, "event_id": event.get("id")}
            )
            matches.append({
                "event_id": event["id"],
                "task": payload.get("task"),
                "action": payload.get("action"),
                "outcome": payload.get("outcome"),
                "tags": payload.get("tags", []),
                "prediction_error": payload.get("prediction_error"),
                "prediction_error_kind": payload.get("prediction_error_kind"),
                "created_at": event.get("created_at"),
                "task_similarity": round(similarity, 6),
                "similarity_components": components,
                "match_type": (
                    "exact_task" if exact else
                    "hybrid_task_and_tags" if normalized_query_tags else
                    "hybrid_lexical_morphology"
                ),
                "epistemic_state": (
                    "independently_verified_episode"
                    if independently_verified else "unverified_episode"
                ),
                "evidence_independently_verified": independently_verified,
                "caller_validation_claim": payload.get("validation_state", "not_validated"),
                "confidence": payload.get("confidence") if independently_verified else None,
                "advisory_only": True,
                "execution_authorized": False,
            })

        matches.sort(key=lambda item: (
            not item["evidence_independently_verified"],
            -item["task_similarity"],
            item["event_id"],
        ))
        selected = matches[:limit]
        history_truncated = total_events > len(events)
        return {
            "status": "bounded" if history_truncated else "completed",
            "query_task": task,
            "context_signature": context_signature,
            "retrieval_method": "hybrid_lexical_morphology_tag_v1",
            "query_tags_used": bool(normalized_query_tags),
            "context_tags_used": bool(context_tags),
            "match_count": len(matches),
            "returned_count": len(selected),
            "verified_match_count": sum(
                item["evidence_independently_verified"] for item in selected
            ),
            "unverified_match_count": sum(
                not item["evidence_independently_verified"] for item in selected
            ),
            "context_mismatch_count": context_mismatch_count,
            "experiences": selected,
            "history_window_limit": self.MAX_EPISODES,
            "history_may_be_incomplete": history_truncated,
            "malformed_event_count": malformed_count,
            "persistent_write_performed": False,
            "semantic_consolidation_performed": False,
            "execution_authorized": False,
            "memory_modified": False,
        }

    def review_experiences(self, limit: int = 200) -> dict:
        """Replay recent episodes and propose, but never apply, stable patterns."""
        self.cognitive._authorize("introspect")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.MAX_EPISODES:
            raise ValueError(f"limit deve ser inteiro entre 1 e {self.MAX_EPISODES}.")
        events = self.store.list_events(limit=limit, event_type=self.EVENT_TYPE)
        total_recorded_episodes = self.store.count_events(
            event_type=self.EVENT_TYPE
        )
        episodes = [
            {"event_id": item["id"], **item["payload"]}
            for item in reversed(events)
            if isinstance(item.get("payload"), dict)
        ]
        invalid_episode_event_count = len(events) - len(episodes)
        window_truncated = total_recorded_episodes > len(events)
        review_complete = not window_truncated and invalid_episode_event_count == 0
        prediction_groups = defaultdict(list)
        for episode in episodes:
            details = episode.get("prediction_details")
            error = self._finite_float(episode.get("prediction_error"))
            if (
                episode.get("prediction_error_kind") == "normalized_mae_v1"
                and isinstance(details, dict)
                and error is not None
                and 0.0 <= error <= 1.0
            ):
                scale = self._finite_float(details.get("normalization_scale"))
                key = (
                    episode.get("task_key"),
                    episode.get("context_signature"),
                    details.get("predictor_id"),
                    details.get("metric"),
                    scale,
                )
                if (
                    all(isinstance(value, str) and value for value in key[:4])
                    and scale is not None and scale > 0
                ):
                    prediction_groups[key].append(error)

        prediction_progress = []
        progress_by_context = defaultdict(list)
        prediction_group_count_by_context = defaultdict(int)
        for key, errors in prediction_groups.items():
            task_key, context_signature, predictor_id, metric, scale = key
            prediction_group_count_by_context[(task_key, context_signature)] += 1
            if len(errors) < 4:
                result = {
                    "task_key": task_key,
                    "context_signature": context_signature,
                    "predictor_id": predictor_id,
                    "metric": metric,
                    "normalization_scale": scale,
                    "sample_count": len(errors),
                    "status": "insufficient_samples",
                    "learning_progress": 0.0,
                    "uncertainty_reducible": 0.0,
                    "prediction_regression": 0.0,
                    "early_mean_error": None,
                    "recent_mean_error": None,
                }
            else:
                midpoint = len(errors) // 2
                early = errors[:midpoint]
                recent = errors[midpoint:]
                early_mean = self._bounded_mean(early)
                recent_mean = self._bounded_mean(recent)
                delta = early_mean - recent_mean
                progress = max(-1.0, min(1.0, delta / max(early_mean, 1e-9)))
                standard_error = math.sqrt(
                    self._variance(early) / len(early)
                    + self._variance(recent) / len(recent)
                )
                reducible = (
                    max(0.0, delta)
                    / (max(0.0, delta) + 2.0 * standard_error + 1e-9)
                    if delta > 0 else 0.0
                )
                result = {
                    "task_key": task_key,
                    "context_signature": context_signature,
                    "predictor_id": predictor_id,
                    "metric": metric,
                    "normalization_scale": scale,
                    "sample_count": len(errors),
                    "status": (
                        "progress_observed" if delta > 1e-9
                        else "regression_observed" if delta < -1e-9
                        else "no_progress_observed"
                    ),
                    "learning_progress": round(max(0.0, progress), 6),
                    "uncertainty_reducible": round(min(1.0, reducible), 6),
                    "prediction_regression": round(max(0.0, -progress), 6),
                    "early_mean_error": round(early_mean, 6),
                    "recent_mean_error": round(recent_mean, 6),
                }
            prediction_progress.append(result)
            if result["status"] != "insufficient_samples":
                progress_by_context[(task_key, context_signature)].append(result)

        groups = defaultdict(list)
        for episode in episodes:
            task_key = episode.get("task_key")
            context_signature = episode.get("context_signature")
            outcome = episode.get("outcome")
            if (
                isinstance(task_key, str) and task_key
                and isinstance(context_signature, str) and context_signature
                and isinstance(outcome, str) and outcome
            ):
                groups[(task_key, context_signature, outcome.casefold())].append(episode)

        candidates = []
        for (task_key, context_signature, _), group in groups.items():
            event_ids = sorted(item["event_id"] for item in group)
            verified = [
                item for item in group if self._episode_is_independently_verified(item)
            ]
            source_labels = sorted({
                item["evidence_verification"]["source_id"]
                for item in verified
            })
            validated_confidences = [
                float(item["confidence"]) for item in verified
                if isinstance(item.get("confidence"), (int, float))
                and not isinstance(item.get("confidence"), bool)
                and math.isfinite(float(item["confidence"]))
            ]
            verified_event_ids = sorted(item["event_id"] for item in verified)
            mean_confidence = (
                sum(validated_confidences) / len(validated_confidences)
                if validated_confidences else 0.0
            )
            action_variants = sorted({
                self._task_key(item["action"])
                for item in verified if isinstance(item.get("action"), str)
            })
            eligible = (
                len(verified) >= 3 and len(source_labels) >= 2
                and len(validated_confidences) >= 3 and mean_confidence >= 0.7
            )
            if eligible:
                candidates.append({
                    "candidate_id": self._candidate_id(
                        task_key, context_signature, verified[0]["outcome"], verified_event_ids
                    ),
                    "task_key": task_key,
                    "context_signature": context_signature,
                    "proposed_pattern": verified[0]["outcome"],
                    "episode_count": len(verified),
                    "unverified_episode_count": len(group) - len(verified),
                    "action_variants": action_variants,
                    "source_labels": source_labels,
                    "source_independence_verified": True,
                    "validated_episode_count": len(verified),
                    "mean_validated_confidence": round(mean_confidence, 4),
                    "learning_progress": round(
                        progress_by_context.get(
                            (task_key, context_signature), [{}]
                        )[0].get("learning_progress", 0.0)
                        if (
                            prediction_group_count_by_context.get(
                                (task_key, context_signature), 0
                            ) == 1
                            and len(progress_by_context.get(
                                (task_key, context_signature), []
                            )) == 1
                        ) else 0.0, 6
                    ),
                    "uncertainty_reducible": round(
                        progress_by_context.get(
                            (task_key, context_signature), [{}]
                        )[0].get("uncertainty_reducible", 0.0)
                        if (
                            prediction_group_count_by_context.get(
                                (task_key, context_signature), 0
                            ) == 1
                            and len(progress_by_context.get(
                                (task_key, context_signature), []
                            )) == 1
                        ) else 0.0, 6
                    ),
                    "prediction_regression": round(
                        max([
                            item["prediction_regression"]
                            for item in progress_by_context.get(
                                (task_key, context_signature), []
                            )
                        ] or [0.0]), 6
                    ),
                    "prediction_sample_count": sum(
                        item["sample_count"]
                        for item in prediction_progress
                        if item["task_key"] == task_key
                        and item["context_signature"] == context_signature
                    ),
                    "prediction_progress_ambiguous": prediction_group_count_by_context.get(
                        (task_key, context_signature), 0
                    ) > 1,
                    "event_ids": verified_event_ids,
                    "evidence_state": "independently_verified_by_configured_verifier",
                    "status": "candidate_requires_human_approval",
                    "automatic_consolidation": False,
                })

        categorical_errors = [
            error for item in episodes
            if item.get("prediction_error_kind") == "categorical_exact_v1"
            and (error := self._finite_float(item.get("prediction_error"))) is not None
            and 0.0 <= error <= 1.0
        ]
        numeric_errors = [
            error for item in episodes
            if item.get("prediction_error_kind") == "normalized_mae_v1"
            and (error := self._finite_float(item.get("prediction_error"))) is not None
            and 0.0 <= error <= 1.0
        ]
        candidate_count_before_history_guard = len(candidates)
        candidate_proposals_suppressed = not review_complete
        if candidate_proposals_suppressed:
            candidates = []

        return {
            "status": "reviewed",
            "replayed_episode_count": len(episodes),
            "events_examined": len(events),
            "total_recorded_episodes": total_recorded_episodes,
            "window_limit": limit,
            "window_truncated": window_truncated,
            "invalid_episode_event_count": invalid_episode_event_count,
            "review_complete": review_complete,
            "history_status": "complete" if review_complete else "incomplete",
            "candidate_count": len(candidates),
            "candidate_count_before_history_guard": candidate_count_before_history_guard,
            "candidate_proposals_suppressed": candidate_proposals_suppressed,
            "candidates": candidates,
            "prediction_error_rate": (
                round(sum(categorical_errors) / len(categorical_errors), 4)
                if categorical_errors else None
            ),
            "prediction_error_sample_count": len(categorical_errors),
            "normalized_prediction_error_mean": (
                round(sum(numeric_errors) / len(numeric_errors), 6)
                if numeric_errors else None
            ),
            "normalized_prediction_error_sample_count": len(numeric_errors),
            "prediction_progress": prediction_progress,
            "prediction_progress_group_count": len(prediction_progress),
            "learning_policy": {
                "episodic_memory": "fast_append_only_event_records",
                "task_identity": "full_normalized_task_and_context_signature",
                "semantic_consolidation": "slow_evidence_gated_and_human_approved",
                "replay": "bounded_recent_episode_review",
                "source_diversity": "verifier_authenticated_source_ids",
                "confidence": "independently_verified_episodes_only",
                "promotion_requires_one_shot_approval_attestation": True,
                "numeric_prediction_error": "normalized_mae_with_fixed_declared_scale",
                "learning_progress": "older_vs_recent_error_windows_same_task_context_metric_predictor",
                "minimum_progress_samples": 4,
                "progress_is_causal_proof": False,
                "automatic_weight_updates": False,
            },
            "memory_modified": False,
            "neural_training_performed": False,
        }

    def consolidate_candidate(
        self, candidate_id: str, *, approved: bool = False,
        approval_attestation: Any = None,
    ) -> dict:
        """Promote only with a verifier-consumed, retry-safe approval attestation.

        The legacy boolean is intentionally insufficient. Approval consumption
        and durable event persistence share one stable idempotency request key.
        """
        self.cognitive._authorize("record_learning")
        if not isinstance(candidate_id, str) or not re.fullmatch(r"[0-9a-f]{24}", candidate_id):
            raise ValueError("candidate_id inválido.")
        review = self.review_experiences(limit=self.MAX_EPISODES)
        if review.get("review_complete") is not True:
            raise PermissionError(
                "Consolidação bloqueada: o replay do histórico está incompleto."
            )
        candidate = next(
            (item for item in review["candidates"] if item["candidate_id"] == candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("Candidato não existe mais ou não atende aos critérios atuais.")
        if approval_attestation is None:
            raise PermissionError(
                "Promoção bloqueada: verificador confiável e atestado one-shot são obrigatórios."
            )

        subject_sha256 = self._canonical_sha256(candidate)
        try:
            approval_request_id = attestation_request_id(
                "adaptive.consolidate_candidate",
                approval_attestation,
                subject_sha256,
            )
        except PermissionError:
            raise
        except Exception as exc:
            raise PermissionError("Atestado de promoção inválido ou não verificável.") from exc

        key = f"adaptive.pattern.{candidate_id}"
        value = {
            "task_key": candidate["task_key"],
            "context_signature": candidate["context_signature"],
            "pattern": candidate["proposed_pattern"],
            "event_ids": candidate["event_ids"],
            "source_labels": candidate["source_labels"],
            "source_independence_verified": candidate["source_independence_verified"],
            "validated_episode_count": candidate["validated_episode_count"],
            "evidence_state": candidate["evidence_state"],
            "status": "human_approved_consolidation",
        }
        metadata = {
            "kind": "adaptive_experience_consolidation",
            "candidate_id": candidate_id,
            "learning_state": "promoted_from_independently_verified_episodes",
        }

        existing_memory = self.store.get_memory(key)
        if existing_memory is not None and (
            existing_memory.get("value") != value
            or existing_memory.get("metadata") != metadata
        ):
            raise RuntimeError(
                "Consolidação existente diverge do candidato atual; overwrite automático bloqueado."
            )

        record_once = getattr(self.store, "record_event_once", None)
        save_memory_if_absent = getattr(self.store, "save_memory_if_absent", None)
        if not callable(record_once) or not callable(save_memory_if_absent):
            raise RuntimeError(
                "KnowledgeStore sem persistência idempotente; promoção não pode ser gravada."
            )

        approval_verifier = getattr(self.cognitive, "approval_verifier", None)
        consume = getattr(approval_verifier, "consume_attestation", None)
        if not callable(consume):
            raise PermissionError(
                "Promoção bloqueada: verificador confiável e atestado one-shot são obrigatórios."
            )
        try:
            consumed = consume(
                attestation=approval_attestation,
                action="adaptive.consolidate_candidate",
                subject_sha256=subject_sha256,
                idempotency_key=approval_request_id,
            )
        except Exception as exc:
            raise PermissionError("Atestado de promoção inválido ou não verificável.") from exc
        if consumed is not True:
            raise PermissionError("Atestado de promoção inválido, expirado ou já utilizado.")

        event_payload = {
            "schema": "mahoraga.adaptive_consolidation",
            "candidate_id": candidate_id,
            "subject_sha256": subject_sha256,
            "approval_request_id": approval_request_id,
            "pattern": value,
            "approval_claim": "trusted_one_shot_attestation",
            "approval_verified": True,
        }
        saved = record_once(
            "adaptive.experience.consolidated",
            "adaptive_consolidation:" + approval_request_id,
            payload=event_payload,
        )

        memory_created = save_memory_if_absent(
            key, value, metadata=metadata,
        )
        if not memory_created:
            persisted = self.store.get_memory(key)
            if (
                not isinstance(persisted, dict)
                or persisted.get("value") != value
                or persisted.get("metadata") != metadata
            ):
                raise RuntimeError(
                    "Memória consolidada diverge do evento canônico; recuperação bloqueada."
                )

        event_created = saved.get("created") is True
        operation_created = event_created or memory_created
        return {
            "status": "consolidated" if operation_created else "already_consolidated",
            "memory_key": key,
            "candidate_id": candidate_id,
            "event_id": saved["event_id"],
            "event_created": event_created,
            "memory_created": memory_created,
            "duplicate": not operation_created,
            "approval_request_id": approval_request_id,
            "neural_training_performed": False,
        }

    def status(self) -> dict:
        self.cognitive._authorize("introspect")
        events = self.store.list_events(limit=self.MAX_EPISODES, event_type=self.EVENT_TYPE)
        total_recorded_episodes = self.store.count_events(
            event_type=self.EVENT_TYPE
        )
        window_truncated = total_recorded_episodes > len(events)
        invalid_episode_event_count = sum(
            not isinstance(item.get("payload"), dict) for item in events
        )
        history_complete = (
            not window_truncated and invalid_episode_event_count == 0
        )
        return {
            "component": "AdaptiveLearning",
            "version": self.VERSION,
            "episode_count_in_window": len(events),
            "episode_count_total": total_recorded_episodes,
            "max_replay_window": self.MAX_EPISODES,
            "window_truncated": window_truncated,
            "invalid_episode_event_count": invalid_episode_event_count,
            "history_complete": history_complete,
            "automatic_consolidation": False,
            "evidence_verifier_available": callable(
                getattr(getattr(self.cognitive, "evidence_verifier", None), "verify_receipt", None)
            ),
            "approval_verifier_available": callable(
                getattr(getattr(self.cognitive, "approval_verifier", None), "consume_attestation", None)
            ),
            "promotion_blocked_without_attestors": True,
            "promotion_persistence": {
                "store_retry_safe": (
                    callable(getattr(self.store, "record_event_once", None))
                    and callable(getattr(self.store, "save_memory_if_absent", None))
                ),
                "verifier_idempotency_key_required": True,
                "verifier_contract_runtime_verified": False,
                "event_type": "adaptive.experience.consolidated",
                "approval_request_id": "action_subject_token_sha256",
                "raw_attestation_persisted": False,
                "canonical_event_store": self.store is self.cognitive.store,
            },
            "experience_retrieval": {
                "supported": True,
                "strategy": "exact_context_signature_plus_hybrid_lexical_morphology_and_optional_tags",
                "embedding_model_used": False,
                "context_values_used_as_retrieval_hints": True,
                "caller_tags_are_evidence": False,
                "maximum_history_window": self.MAX_EPISODES,
                "maximum_returned_episodes": 20,
                "read_only": True,
                "independent_evidence_ranked_first": True,
                "unverified_confidence_exposed": False,
                "semantic_consolidation_performed": False,
                "execution_authorized": False,
            },
            "neural_training_connected": False,
            "shared_store": self.store is self.cognitive.store,
        }
