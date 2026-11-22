"""Evidence-based calibration and abstention support for Mahoraga.

The monitor reuses independently verified adaptive-learning episodes in the
canonical KnowledgeStore. Metrics are scoped to a predictor identity to avoid
mixing unrelated models. It never trains weights or authorizes actions.
"""
from __future__ import annotations

import math
import re
from typing import Any


class MetacognitiveMonitor:
    VERSION = "0.3.0"
    EVENT_TYPE = "adaptive.experience.recorded"
    MAX_EVENTS = 1000
    DEFAULT_BINS = 10

    def __init__(self, cognitive):
        self.cognitive = cognitive
        self.store = cognitive.store

    @staticmethod
    def _probability(value: Any, field: str = "confidence") -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} deve ser um número entre 0 e 1.")
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(f"{field} deve ser finito e estar entre 0 e 1.") from exc
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise ValueError(f"{field} deve ser finito e estar entre 0 e 1.")
        return number

    @staticmethod
    def _identifier(value: str | None, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip() or len(value) > 120:
            raise ValueError(f"{field} deve ser texto não vazio com até 120 caracteres.")
        return value.strip()

    @staticmethod
    def _task_key(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip() or len(value) > 240:
            raise ValueError("task deve ser texto não vazio com até 240 caracteres.")
        normalized = " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))
        if not normalized:
            raise ValueError("task precisa conter ao menos um token alfanumérico.")
        return normalized

    @staticmethod
    def _metrics(samples: list[tuple[float, float]], bins: int) -> dict[str, Any]:
        if not samples:
            return {
                "sample_count": 0,
                "brier_score": None,
                "expected_calibration_error": None,
                "reliability_bins": [],
            }
        brier = sum((confidence - outcome) ** 2 for confidence, outcome in samples) / len(samples)
        grouped = [[] for _ in range(bins)]
        for confidence, outcome in samples:
            grouped[min(int(confidence * bins), bins - 1)].append((confidence, outcome))
        reliability = []
        ece = 0.0
        for index, values in enumerate(grouped):
            if not values:
                continue
            mean_confidence = sum(item[0] for item in values) / len(values)
            accuracy = sum(item[1] for item in values) / len(values)
            ece += (len(values) / len(samples)) * abs(mean_confidence - accuracy)
            reliability.append({
                "lower_bound": index / bins,
                "upper_bound": (index + 1) / bins,
                "count": len(values),
                "mean_confidence": mean_confidence,
                "observed_accuracy": accuracy,
            })
        return {
            "sample_count": len(samples),
            "brier_score": brier,
            "expected_calibration_error": ece,
            "reliability_bins": reliability,
        }

    def report(
        self,
        limit: int = 500,
        bins: int = DEFAULT_BINS,
        task: str | None = None,
        predictor_id: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self.MAX_EVENTS:
            raise ValueError("limit deve ser um inteiro entre 1 e 1000.")
        if isinstance(bins, bool) or not isinstance(bins, int) or not 2 <= bins <= 50:
            raise ValueError("bins deve ser um inteiro entre 2 e 50.")
        task_filter = self._task_key(task)
        predictor_filter = self._identifier(predictor_id, "predictor_id")
        events = self.store.list_events(limit=limit, event_type=self.EVENT_TYPE)
        # Event history is append-only. Count after reading the bounded window so
        # concurrent appends are conservatively reported as an incomplete window.
        total_recorded_episodes = self.store.count_events(event_type=self.EVENT_TYPE)
        window_truncated = total_recorded_episodes > len(events)

        categorical_by_scope: dict[tuple[str, str], list[tuple[float, float]]] = {}
        numeric_by_scope: dict[tuple[str, str], list[float]] = {}
        unverified = 0
        verified = 0
        predictor_identity_conflicts = 0
        invalid_predictions = 0
        invalid_episode_metadata = 0
        out_of_scope_task = 0
        out_of_scope_predictor = 0
        evidence_verification_checks = 0

        adaptive = self.cognitive.adaptive_learning
        for event in events:
            episode = event.get("payload", {})
            if not isinstance(episode, dict):
                unverified += 1
                continue

            # Parse and apply cheap scope filters before invoking the evidence
            # verifier. A scoped calibration query must not verify unrelated
            # tasks or predictors, which can be costly on mobile hardware.
            references = episode.get("references", {})
            raw_details = episode.get("prediction_details")
            if not isinstance(references, dict) or (
                raw_details is not None and not isinstance(raw_details, dict)
            ):
                invalid_episode_metadata += 1
                continue
            details = raw_details or {}

            predictor_values = []
            invalid_predictor_metadata = False
            for raw_predictor in (
                references.get("predictor_id"),
                details.get("predictor_id"),
            ):
                if raw_predictor is None:
                    continue
                if (
                    not isinstance(raw_predictor, str)
                    or not raw_predictor.strip()
                    or len(raw_predictor) > 120
                ):
                    invalid_predictor_metadata = True
                    break
                predictor_values.append(raw_predictor.strip())
            if invalid_predictor_metadata:
                invalid_episode_metadata += 1
                continue
            if len(set(predictor_values)) > 1:
                predictor_identity_conflicts += 1
                continue
            current_predictor = predictor_values[0] if predictor_values else "unspecified"

            raw_task_key = episode.get("task_key")
            raw_task = episode.get("task")
            try:
                canonical_task = self._task_key(raw_task_key) if raw_task_key is not None else None
                source_task = self._task_key(raw_task) if raw_task is not None else None
            except ValueError:
                invalid_episode_metadata += 1
                continue
            if canonical_task is not None and source_task is not None and canonical_task != source_task:
                invalid_episode_metadata += 1
                continue
            current_task = canonical_task or source_task
            if current_task is None:
                invalid_episode_metadata += 1
                continue

            if task_filter is not None and current_task != task_filter:
                out_of_scope_task += 1
                continue
            if predictor_filter is not None and current_predictor != predictor_filter:
                out_of_scope_predictor += 1
                continue

            evidence_verification_checks += 1
            if not adaptive._episode_is_independently_verified(episode):
                unverified += 1
                continue

            verified += 1
            scope = (current_predictor, current_task)
            kind = episode.get("prediction_error_kind")
            if kind == "categorical_exact_v1":
                try:
                    confidence = self._probability(episode.get("confidence"))
                except ValueError:
                    invalid_predictions += 1
                    continue
                error = episode.get("prediction_error")
                if isinstance(error, bool) or not isinstance(error, (int, float)):
                    invalid_predictions += 1
                    continue
                try:
                    error = float(error)
                except (OverflowError, TypeError, ValueError):
                    invalid_predictions += 1
                    continue
                if not math.isfinite(error) or not 0.0 <= error <= 1.0:
                    invalid_predictions += 1
                    continue
                categorical_by_scope.setdefault(scope, []).append(
                    (confidence, 1.0 - error)
                )
            elif kind == "normalized_mae_v1":
                error = episode.get("prediction_error")
                if isinstance(error, bool) or not isinstance(error, (int, float)):
                    invalid_predictions += 1
                    continue
                try:
                    value = float(error)
                except (OverflowError, TypeError, ValueError):
                    invalid_predictions += 1
                    continue
                if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                    invalid_predictions += 1
                    continue
                numeric_by_scope.setdefault(scope, []).append(value)

        # Aggregate calibration is deliberately available only for one exact
        # predictor/task pair. Partial scopes are reported as disjoint groups.
        exact_scope = predictor_filter is not None and task_filter is not None
        selected_scope = (predictor_filter, task_filter) if exact_scope else None
        selected_samples = (
            categorical_by_scope.get(selected_scope, [])
            if selected_scope is not None else []
        )
        selected_numeric = (
            numeric_by_scope.get(selected_scope, [])
            if selected_scope is not None else []
        )
        metrics = self._metrics(selected_samples, bins)

        by_scope: dict[str, dict[str, Any]] = {}
        numeric_error_by_scope: dict[str, dict[str, float]] = {}
        for (scope_predictor, scope_task), values in sorted(categorical_by_scope.items()):
            by_scope.setdefault(scope_predictor, {})[scope_task] = self._metrics(values, bins)
        for (scope_predictor, scope_task), values in sorted(numeric_by_scope.items()):
            numeric_error_by_scope.setdefault(scope_predictor, {})[scope_task] = (
                sum(values) / len(values)
            )

        by_task = {}
        if predictor_filter is not None:
            by_task = {
                scope_task: self._metrics(values, bins)
                for (scope_predictor, scope_task), values in sorted(categorical_by_scope.items())
                if scope_predictor == predictor_filter
            }
        by_predictor = {}
        if task_filter is not None:
            by_predictor = {
                scope_predictor: self._metrics(values, bins)
                for (scope_predictor, scope_task), values in sorted(categorical_by_scope.items())
                if scope_task == task_filter
            }

        has_any_data = bool(categorical_by_scope or numeric_by_scope)
        has_predictor_data = any(
            scope_predictor == predictor_filter
            for scope_predictor, _ in (
                set(categorical_by_scope) | set(numeric_by_scope)
            )
        ) if predictor_filter is not None else False
        has_task_data = any(
            scope_task == task_filter
            for _, scope_task in (
                set(categorical_by_scope) | set(numeric_by_scope)
            )
        ) if task_filter is not None else False

        if exact_scope and selected_samples:
            status = "available"
        elif exact_scope and selected_numeric:
            status = "numeric_only"
        elif predictor_filter is None and has_task_data:
            status = "predictor_scope_required"
        elif predictor_filter is None and task_filter is None and has_any_data:
            status = "predictor_scope_required"
        elif task_filter is None and predictor_filter is not None and has_predictor_data:
            status = "task_scope_required"
        else:
            status = "uncalibrated"

        return {
            "component": "MetacognitiveMonitor",
            "version": self.VERSION,
            "status": status,
            "episodes_examined": len(events),
            "total_recorded_episodes": total_recorded_episodes,
            "window_limit": limit,
            "window_truncated": window_truncated,
            "independently_verified_episodes": verified,
            "unverified_episodes_excluded": unverified,
            "out_of_scope_task_episodes": out_of_scope_task,
            "out_of_scope_predictor_episodes": out_of_scope_predictor,
            "evidence_verification_checks": evidence_verification_checks,
            "predictor_identity_conflicts_excluded": predictor_identity_conflicts,
            "invalid_episode_metadata_excluded": invalid_episode_metadata,
            "invalid_predictions_excluded": invalid_predictions,
            "categorical_prediction_count": len(selected_samples),
            "numeric_prediction_count": len(selected_numeric),
            **metrics,
            "brier_score_method": "binary_correctness_v1",
            "mean_normalized_numeric_error": (
                sum(selected_numeric) / len(selected_numeric)
                if selected_numeric else None
            ),
            "by_task": by_task,
            "by_predictor": by_predictor,
            "by_scope": by_scope,
            "numeric_error_by_scope": numeric_error_by_scope,
            "task_filter": task_filter,
            "predictor_filter": predictor_filter,
            "limitations": [
                "Somente episódios com recibo de evidência verificado entram nas métricas.",
                "Métricas agregadas exigem predictor_id e task; pares diferentes nunca são misturados.",
                "Brier mede correção binária da predição, não um Brier multiclasses completo.",
                "ECE depende do número e da distribuição das amostras por bin.",
                "A calibração é específica aos dados, tarefas e versões observados.",
                "A métrica não prova compreensão geral nem autoriza ações.",
                "Predições numéricas usam erro normalizado, não calibração probabilística.",
            ],
        }

    def assess(
        self,
        confidence: float,
        *,
        task: str | None = None,
        predictor_id: str | None = None,
        minimum_samples: int = 20,
        minimum_confidence: float = 0.65,
        maximum_ece: float = 0.15,
        minimum_bin_samples: int = 5,
    ) -> dict[str, Any]:
        confidence = self._probability(confidence)
        minimum_confidence = self._probability(minimum_confidence, "minimum_confidence")
        maximum_ece = self._probability(maximum_ece, "maximum_ece")
        predictor_filter = self._identifier(predictor_id, "predictor_id")
        if (
            isinstance(minimum_samples, bool)
            or not isinstance(minimum_samples, int)
            or not 1 <= minimum_samples <= self.MAX_EVENTS
        ):
            raise ValueError("minimum_samples deve ser um inteiro entre 1 e 1000.")
        if (
            isinstance(minimum_bin_samples, bool)
            or not isinstance(minimum_bin_samples, int)
            or not 1 <= minimum_bin_samples <= self.MAX_EVENTS
        ):
            raise ValueError("minimum_bin_samples deve ser um inteiro entre 1 e 1000.")

        report = self.report(limit=self.MAX_EVENTS, task=task, predictor_id=predictor_filter)
        reasons = []
        if report["window_truncated"]:
            reasons.append("histórico truncado: a avaliação não cobre todos os episódios registrados")
        if predictor_filter is None:
            reasons.append("predictor_id é obrigatório para evitar misturar modelos")
        if self._task_key(task) is None:
            reasons.append("task é obrigatório para evitar misturar domínios")
        if report["categorical_prediction_count"] < minimum_samples:
            reasons.append("amostra verificada insuficiente para calibrar esta decisão")
        if confidence < minimum_confidence:
            reasons.append("confiança abaixo do limiar mínimo")
        ece = report["expected_calibration_error"]
        if ece is None or ece > maximum_ece:
            reasons.append("calibração global ausente ou erro de calibração acima do limite")

        bin_index = min(int(confidence * self.DEFAULT_BINS), self.DEFAULT_BINS - 1)
        expected_lower_bound = bin_index / self.DEFAULT_BINS
        current_bin = next(
            (
                item for item in report["reliability_bins"]
                if math.isclose(
                    item["lower_bound"], expected_lower_bound,
                    rel_tol=0.0, abs_tol=1e-12,
                )
            ),
            None,
        )
        current_bin_error = None
        if current_bin is None or current_bin["count"] < minimum_bin_samples:
            reasons.append("amostra insuficiente no intervalo da confiança atual")
        else:
            current_bin_error = abs(
                current_bin["mean_confidence"] - current_bin["observed_accuracy"]
            )
            if current_bin_error > maximum_ece:
                reasons.append("calibração inadequada no intervalo da confiança atual")

        return {
            "decision": "abstain" if reasons else "proceed_with_caution",
            "abstain": bool(reasons),
            "reasons": reasons,
            "confidence": confidence,
            "calibration": report,
            "calibration_bin": current_bin,
            "calibration_bin_error": current_bin_error,
            "minimum_bin_samples": minimum_bin_samples,
            "execution_authorized": False,
            "note": "Esta avaliação é consultiva e não substitui Dharma nem AutonomyGovernor.",
        }

    def status(self) -> dict[str, Any]:
        """Return a cheap operational snapshot; calibration is an explicit query."""
        episodes_recorded = self.store.count_events(event_type=self.EVENT_TYPE)
        return {
            "component": "MetacognitiveMonitor",
            "version": self.VERSION,
            "status": "not_assessed",
            "episodes_recorded": episodes_recorded,
            "calibration_computed": False,
            "evidence_verification_checks": 0,
            "requires_scoped_report": True,
            "execution_performed": False,
            "note": (
                "Use report(task=..., predictor_id=...) for an evidence-verified "
                "calibration report. Status snapshots never verify episode receipts."
            ),
        }
