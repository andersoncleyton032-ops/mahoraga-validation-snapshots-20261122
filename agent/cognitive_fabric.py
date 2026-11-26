"""Bounded, in-process cognitive signaling and working memory.

This module adds a coordination fabric around existing Mahoraga components.
It is deliberately transient: it does not own a database, spawn workers,
perform network access, or grant execution authority.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import inspect
import json
import math
import re
import threading
import uuid
from typing import Any, Callable
from types import MappingProxyType

from .graph_algorithms import bounded_simple_paths


class CognitiveFabricError(ValueError):
    """Invalid signal, workspace, graph, or dispatch request."""


class CognitiveFabricLimitError(CognitiveFabricError):
    """A bounded cycle reached one of its configured limits."""


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise CognitiveFabricError(f"{field} deve ser texto não vazio com até 128 caracteres.")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        raise CognitiveFabricError(f"{field} contém caracteres inválidos.")
    return value


def _strict_json(value: Any, *, max_bytes: int, max_depth: int = 12) -> tuple[Any, int]:
    """Validate JSON-compatible data, reject coercion and return a detached copy."""
    def walk(item: Any, depth: int) -> None:
        if depth > max_depth:
            raise CognitiveFabricError("Profundidade máxima do payload excedida.")
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise CognitiveFabricError("Valores numéricos não finitos não são permitidos.")
            return
        if isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
            return
        if isinstance(item, tuple):
            for child in item:
                walk(child, depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise CognitiveFabricError("Chaves de objetos devem ser texto.")
                walk(child, depth + 1)
            return
        raise CognitiveFabricError(
            f"Tipo não serializável no contexto cognitivo: {type(item).__name__}."
        )

    walk(value, 0)
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise CognitiveFabricError("Payload JSON inválido.") from exc
    size = len(encoded.encode("utf-8"))
    if size > max_bytes:
        raise CognitiveFabricLimitError(
            f"Payload excede o limite de {max_bytes} bytes."
        )
    return json.loads(encoded), size


def _freeze_json(value: Any) -> Any:
    """Recursively freeze a validated JSON payload before signal delivery."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    """Return a detached JSON-compatible representation of a frozen payload."""
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _confidence(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CognitiveFabricError("confidence deve ser número entre 0 e 1.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CognitiveFabricError("confidence deve ser finita e estar entre 0 e 1.") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise CognitiveFabricError("confidence deve ser finita e estar entre 0 e 1.")
    return number


@dataclass(frozen=True)
class SignalDraft:
    """A message a component may publish to the shared cognitive workspace."""

    topic: str
    source: str
    payload: dict[str, Any]
    target: str | None = None
    epistemic_state: str = "observation"
    confidence: float | None = None
    evidence_refs: tuple[str, ...] = ()
    causation_id: str | None = None


@dataclass(frozen=True)
class CognitiveSignal:
    signal_id: str
    correlation_id: str
    sequence: int
    topic: str
    source: str
    target: str | None
    created_at: str
    causation_id: str | None
    epistemic_state: str
    confidence: float | None
    evidence_refs: tuple[str, ...]
    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "correlation_id": self.correlation_id,
            "sequence": self.sequence,
            "topic": self.topic,
            "source": self.source,
            "target": self.target,
            "created_at": self.created_at,
            "causation_id": self.causation_id,
            "epistemic_state": self.epistemic_state,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "payload": _thaw_json(self.payload),
        }


class CognitiveWorkspace:
    """Request-scoped working memory; discarded when the cycle ends."""

    def __init__(
        self,
        fabric_token: str,
        *,
        correlation_id: str,
        metadata: dict[str, Any],
        max_signals: int,
        max_artifacts: int,
        max_artifact_bytes: int,
        max_total_artifact_bytes: int,
    ):
        self._fabric_token = fabric_token
        self.correlation_id = correlation_id
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.metadata, _ = _strict_json(metadata, max_bytes=16_384)
        self._max_signals = max_signals
        self._max_artifacts = max_artifacts
        self._max_artifact_bytes = max_artifact_bytes
        self._max_total_artifact_bytes = max_total_artifact_bytes
        self._artifacts: dict[str, dict[str, Any]] = {}
        self._artifact_sizes: dict[str, int] = {}
        self._artifact_bytes = 0
        self._signals: list[CognitiveSignal] = []
        self._stage_measurements: list[dict[str, Any]] = []

    def put(
        self,
        key: str,
        value: Any,
        *,
        source: str,
        epistemic_state: str = "working_context",
    ) -> None:
        key = _identifier(key, "artifact_key")
        source = _identifier(source, "source")
        if not isinstance(epistemic_state, str) or not epistemic_state or len(epistemic_state) > 80:
            raise CognitiveFabricError("epistemic_state inválido.")
        copied, size = _strict_json(
            {"source": source, "epistemic_state": epistemic_state, "value": value},
            max_bytes=self._max_artifact_bytes,
        )
        previous_size = self._artifact_sizes.get(key, 0)
        next_total = self._artifact_bytes - previous_size + size
        if key not in self._artifacts and len(self._artifacts) >= self._max_artifacts:
            raise CognitiveFabricLimitError("Limite de artefatos do workspace atingido.")
        if next_total > self._max_total_artifact_bytes:
            raise CognitiveFabricLimitError("Limite total de memória de trabalho atingido.")
        self._artifacts[key] = copied
        self._artifact_sizes[key] = size
        self._artifact_bytes = next_total

    def get(self, key: str, default: Any = None) -> Any:
        key = _identifier(key, "artifact_key")
        record = self._artifacts.get(key)
        if record is None:
            return default
        copied, _ = _strict_json(record["value"], max_bytes=self._max_artifact_bytes)
        return copied

    def has(self, key: str) -> bool:
        return key in self._artifacts

    def _append_signal(self, signal: CognitiveSignal) -> None:
        if len(self._signals) >= self._max_signals:
            raise CognitiveFabricLimitError("Limite de sinais do ciclo atingido.")
        self._signals.append(signal)

    def record_stage(
        self,
        stage: str,
        component: str,
        *,
        status: str,
        duration_ms: float,
    ) -> None:
        stage = _identifier(stage, "stage")
        component = _identifier(component, "component")
        if not isinstance(status, str) or not status or len(status) > 40:
            raise CognitiveFabricError("status da medição inválido.")
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)):
            raise CognitiveFabricError("duration_ms deve ser número finito não negativo.")
        try:
            duration = float(duration_ms)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CognitiveFabricError("duration_ms inválido.") from exc
        if not math.isfinite(duration) or duration < 0:
            raise CognitiveFabricError("duration_ms deve ser número finito não negativo.")
        if len(self._stage_measurements) >= 64:
            raise CognitiveFabricLimitError("Limite de medições por ciclo atingido.")
        self._stage_measurements.append({
            "stage": stage,
            "component": component,
            "status": status,
            "duration_ms": round(duration, 3),
        })

    @property
    def signals(self) -> tuple[CognitiveSignal, ...]:
        return tuple(self._signals)

    @property
    def stage_measurements(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._stage_measurements)

    def provenance_index(self) -> list[dict[str, Any]]:
        """Return artifact provenance and size without exposing artifact values."""
        return [
            {
                "artifact_key": key,
                "source": record["source"],
                "epistemic_state": record["epistemic_state"],
                "size_bytes": self._artifact_sizes[key],
            }
            for key, record in sorted(self._artifacts.items())
        ]

    @staticmethod
    def _continuity_timestamp(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 64:
            raise CognitiveFabricError(f"{field} precisa ser timestamp ISO-8601.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CognitiveFabricError(f"{field} precisa ser timestamp ISO-8601.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise CognitiveFabricError(f"{field} precisa incluir fuso horário.")
        return parsed.astimezone(timezone.utc).isoformat()

    def continuity_record(
        self,
        outcome: str,
        *,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        """Return a bounded, whitelisted cycle summary; this method never persists."""
        if not isinstance(outcome, str) or outcome not in {
            "completed", "deferred", "failed", "cancelled"
        }:
            raise CognitiveFabricError("outcome de continuidade inválido.")
        perspective = self.operational_perspective()
        correlation_id = _identifier(self.correlation_id, "correlation_id")
        created_at = self._continuity_timestamp(self.created_at, "created_at")
        completed_at = (
            None
            if completed_at is None
            else self._continuity_timestamp(completed_at, "completed_at")
        )

        focus = perspective["focus"]
        topics = focus["topics_observed"]
        components = focus["participating_components"]
        if not isinstance(topics, list) or len(topics) > self._max_signals:
            raise CognitiveFabricLimitError("Lista de tópicos excede o limite do ciclo.")
        if not isinstance(components, list) or len(components) > 128:
            raise CognitiveFabricLimitError("Lista de componentes excede o limite do ciclo.")
        topics = [_identifier(item, "topic") for item in topics]
        components = [_identifier(item, "component") for item in components]

        epistemic = perspective["epistemic_summary"]["counts_by_state"]
        if not isinstance(epistemic, dict) or len(epistemic) > self._max_signals:
            raise CognitiveFabricLimitError("Resumo epistemológico excede o limite.")
        epistemic_counts = {}
        for key, value in epistemic.items():
            key = _identifier(key, "epistemic_state")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CognitiveFabricError("Contagem epistemológica inválida.")
            epistemic_counts[key] = value

        measurements = []
        for item in perspective["stage_measurements"]:
            if not isinstance(item, dict) or set(item) != {
                "stage", "component", "status", "duration_ms"
            }:
                raise CognitiveFabricError("Medição de etapa possui campos inválidos.")
            status = _identifier(item["status"], "stage_status")
            duration = item["duration_ms"]
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(float(duration))
                or duration < 0
            ):
                raise CognitiveFabricError("Duração de etapa inválida.")
            measurements.append({
                "stage": _identifier(item["stage"], "stage"),
                "component": _identifier(item["component"], "component"),
                "status": status,
                "duration_ms": round(float(duration), 3),
            })
            if len(measurements) > 64:
                raise CognitiveFabricLimitError("Limite de medições de etapa excedido.")

        artifacts = []
        for item in perspective["artifacts"]:
            if not isinstance(item, dict) or set(item) != {
                "artifact_key", "source", "epistemic_state", "size_bytes"
            }:
                raise CognitiveFabricError("Proveniência de artefato possui campos inválidos.")
            size = item["size_bytes"]
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise CognitiveFabricError("Tamanho de artefato inválido.")
            epistemic_state = item["epistemic_state"]
            if (
                not isinstance(epistemic_state, str)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", epistemic_state)
            ):
                raise CognitiveFabricError("artifact_epistemic_state inválido.")
            artifacts.append({
                "artifact_key": _identifier(item["artifact_key"], "artifact_key"),
                "source": _identifier(item["source"], "artifact_source"),
                "epistemic_state": epistemic_state,
                "size_bytes": size,
            })
            if len(artifacts) > self._max_artifacts:
                raise CognitiveFabricLimitError("Limite de artefatos excedido.")

        record = {
            "schema": "mahoraga.cognitive_continuity_record",
            "schema_version": 1,
            "outcome": outcome,
            "cycle": {
                "correlation_id": correlation_id,
                "created_at": created_at,
                "completed_at": completed_at,
                "signal_count": perspective["cycle"]["signal_count"],
                "artifact_count": perspective["cycle"]["artifact_count"],
                "stage_count": perspective["cycle"]["stage_count"],
            },
            "focus": {
                "last_signal_topic": (
                    _identifier(focus["last_signal_topic"], "last_signal_topic")
                    if focus["last_signal_topic"] is not None else None
                ),
                "topics_observed": topics,
                "participating_components": components,
            },
            "epistemic_summary": {
                "counts_by_state": epistemic_counts,
                "reported_confidence_count": perspective["epistemic_summary"]["reported_confidence_count"],
                "reported_confidence_mean": perspective["epistemic_summary"]["reported_confidence_mean"],
                "calibration_claim": False,
            },
            "artifacts": artifacts,
            "stage_measurements": measurements,
            "causal_attribution": "not_established",
            "subjective_experience_status": "unknown_not_inferred",
            "redaction": {
                "raw_request_text_included": False,
                "signal_payloads_included": False,
                "evidence_refs_included": False,
                "artifact_values_included": False,
                "model_response_included": False,
            },
        }
        copied, _ = _strict_json(record, max_bytes=32_768)
        return copied

    def operational_perspective(self) -> dict[str, Any]:
        """Build one redacted, request-scoped view of the integrated cognitive cycle."""
        signals = self.signals
        topics = list(dict.fromkeys(signal.topic for signal in signals))
        processes = list(dict.fromkeys(
            component
            for signal in signals
            for component in (signal.source, signal.target)
            if component is not None
        ))
        epistemic_counts: dict[str, int] = {}
        confidence_values = []
        chain = []
        for signal in signals:
            epistemic_counts[signal.epistemic_state] = (
                epistemic_counts.get(signal.epistemic_state, 0) + 1
            )
            if signal.confidence is not None:
                confidence_values.append(signal.confidence)
            chain.append({
                "signal_id": signal.signal_id,
                "sequence": signal.sequence,
                "topic": signal.topic,
                "source": signal.source,
                "target": signal.target,
                "causation_id": signal.causation_id,
                "epistemic_state": signal.epistemic_state,
                "confidence_reported": signal.confidence,
                "evidence_ref_count": len(signal.evidence_refs),
            })
        return {
            "schema": "mahoraga.operational_perspective",
            "schema_version": 1,
            "perspective_type": "request_scoped_cognitive_workspace",
            "subjective_experience_status": "unknown_not_inferred",
            "causal_attribution": "not_established",
            "cycle": {
                "correlation_id": self.correlation_id,
                "created_at": self.created_at,
                "signal_count": len(signals),
                "artifact_count": len(self._artifacts),
                "stage_count": len(self._stage_measurements),
            },
            "focus": {
                "last_signal_topic": signals[-1].topic if signals else None,
                "topics_observed": topics,
                "participating_components": processes,
                "last_sequence": signals[-1].sequence if signals else 0,
            },
            "signal_chain": chain,
            "epistemic_summary": {
                "counts_by_state": dict(sorted(epistemic_counts.items())),
                "reported_confidence_count": len(confidence_values),
                "reported_confidence_mean": (
                    round(sum(confidence_values) / len(confidence_values), 6)
                    if confidence_values else None
                ),
            },
            "artifacts": self.provenance_index(),
            "stage_measurements": list(self.stage_measurements),
            "redaction": {
                "artifact_values_included": False,
                "signal_payloads_included": False,
                "raw_request_text_included": False,
            },
        }


class CognitiveFabric:
    """Bounded synchronous signal router, shared workspace and runtime graph."""

    VERSION = "0.2.0"
    MAX_COMPONENTS = 128
    MAX_RELATIONSHIPS = 512
    MAX_FLOW_EDGES = 256
    MAX_SIGNALS_PER_CYCLE = 64
    MAX_DISPATCH_DEPTH = 8
    MAX_SUBSCRIBERS_PER_TOPIC = 16
    MAX_SIGNAL_PAYLOAD_BYTES = 8_192

    def __init__(self):
        self._token = uuid.uuid4().hex
        self._component_ids: set[str] = set()
        self._verified_edges: list[dict[str, Any]] = []
        self._observed_flows: dict[tuple[str, str, str], int] = {}
        self._flow_lock = threading.Lock()
        self._subscriptions: dict[str, list[tuple[str, Callable]]] = {}

    def configure_connectome(
        self,
        *,
        component_ids: list[str] | tuple[str, ...] | set[str],
        verified_relationships: dict[str, tuple[str, str]],
    ) -> None:
        if not isinstance(component_ids, (list, tuple, set)):
            raise CognitiveFabricError("component_ids deve ser uma coleção de identificadores.")
        if len(component_ids) > self.MAX_COMPONENTS:
            raise CognitiveFabricLimitError("Limite de componentes do conectoma excedido.")
        nodes = {_identifier(item, "component_id") for item in component_ids}
        if not isinstance(verified_relationships, dict):
            raise CognitiveFabricError("verified_relationships deve ser um objeto.")
        if len(verified_relationships) > self.MAX_RELATIONSHIPS:
            raise CognitiveFabricLimitError("Limite de relações do conectoma excedido.")

        edges = []
        for relation_id, endpoints in sorted(verified_relationships.items()):
            relation_id = _identifier(relation_id, "relationship_id")
            if not isinstance(endpoints, (tuple, list)) or len(endpoints) != 2:
                raise CognitiveFabricError(f"Relação inválida: {relation_id}.")
            source = _identifier(endpoints[0], "relationship_source")
            target = _identifier(endpoints[1], "relationship_target")
            if source not in nodes or target not in nodes:
                raise CognitiveFabricError(
                    f"Relação {relation_id} referencia componente não registrado."
                )
            edges.append({
                "relationship_id": relation_id,
                "source": source,
                "target": target,
                "kind": "verified_shared_component",
                "evidence": "integrated_core_identity_invariant",
                "verified": True,
            })

        self._component_ids = nodes
        self._verified_edges = edges
        with self._flow_lock:
            self._observed_flows = {
                key: count for key, count in self._observed_flows.items()
                if key[0] in nodes and key[1] in nodes
            }
        self._subscriptions = {
            topic: [(component, handler) for component, handler in handlers if component in nodes]
            for topic, handlers in self._subscriptions.items()
        }

    def new_workspace(self, metadata: dict[str, Any] | None = None) -> CognitiveWorkspace:
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise CognitiveFabricError("metadata do workspace deve ser um objeto.")
        return CognitiveWorkspace(
            self._token,
            correlation_id=uuid.uuid4().hex,
            metadata=metadata,
            max_signals=self.MAX_SIGNALS_PER_CYCLE,
            max_artifacts=32,
            max_artifact_bytes=262_144,
            max_total_artifact_bytes=524_288,
        )

    def subscribe(self, topic: str, component_id: str, handler: Callable) -> None:
        topic = _identifier(topic, "topic")
        component_id = _identifier(component_id, "component_id")
        if component_id not in self._component_ids:
            raise CognitiveFabricError("Componente inscrito não existe no conectoma.")
        asynchronous = inspect.iscoroutinefunction(handler) or inspect.iscoroutinefunction(
            getattr(handler, "__call__", None)
        )
        if not callable(handler) or asynchronous:
            raise CognitiveFabricError("Handler deve ser uma função síncrona confiável.")
        handlers = self._subscriptions.setdefault(topic, [])
        if len(handlers) >= self.MAX_SUBSCRIBERS_PER_TOPIC:
            raise CognitiveFabricLimitError("Limite de assinantes do tópico atingido.")
        if any(component == component_id for component, _ in handlers):
            raise CognitiveFabricError("Componente já inscrito neste tópico.")
        handlers.append((component_id, handler))

    def publish(
        self,
        workspace: CognitiveWorkspace,
        draft: SignalDraft,
    ) -> CognitiveSignal:
        if not isinstance(workspace, CognitiveWorkspace) or workspace._fabric_token != self._token:
            raise CognitiveFabricError("Workspace não pertence a esta instância do fabric.")
        if not isinstance(draft, SignalDraft):
            raise CognitiveFabricError("publish requer um SignalDraft.")
        queue = deque([(draft, 0)])
        first_signal = None

        while queue:
            current, depth = queue.popleft()
            if depth > self.MAX_DISPATCH_DEPTH:
                raise CognitiveFabricLimitError("Profundidade máxima de despacho excedida.")
            signal = self._materialize_signal(workspace, current)
            if first_signal is None:
                first_signal = signal
            for component_id, handler in self._subscriptions.get(signal.topic, []):
                if signal.target is not None and signal.target != component_id:
                    continue
                proposals = handler(signal, workspace)
                flow_key = (signal.source, component_id, signal.topic)
                with self._flow_lock:
                    if (
                        flow_key not in self._observed_flows
                        and len(self._observed_flows) >= self.MAX_FLOW_EDGES
                    ):
                        raise CognitiveFabricLimitError(
                            "Limite de fluxos observados atingido."
                        )
                    self._observed_flows[flow_key] = (
                        self._observed_flows.get(flow_key, 0) + 1
                    )
                if proposals is None:
                    continue
                if isinstance(proposals, SignalDraft):
                    proposals = [proposals]
                if not isinstance(proposals, (list, tuple)):
                    raise CognitiveFabricError("Handler deve retornar SignalDraft, lista, tupla ou None.")
                for proposal in proposals:
                    if not isinstance(proposal, SignalDraft):
                        raise CognitiveFabricError("Handler retornou um objeto que não é SignalDraft.")
                    if proposal.causation_id is None:
                        proposal = replace(proposal, causation_id=signal.signal_id)
                    queue.append((proposal, depth + 1))
                    if len(queue) + len(workspace.signals) > workspace._max_signals:
                        raise CognitiveFabricLimitError("Fila de sinais excedeu o limite do ciclo.")

        if first_signal is None:
            raise CognitiveFabricError("Nenhum sinal foi produzido.")
        return first_signal

    def _materialize_signal(
        self,
        workspace: CognitiveWorkspace,
        draft: SignalDraft,
    ) -> CognitiveSignal:
        topic = _identifier(draft.topic, "topic")
        source = _identifier(draft.source, "source")
        target = None if draft.target is None else _identifier(draft.target, "target")
        if source not in self._component_ids or (target is not None and target not in self._component_ids):
            raise CognitiveFabricError("Sinal referencia componente ausente do conectoma.")
        if not isinstance(draft.payload, dict):
            raise CognitiveFabricError("payload do sinal deve ser um objeto.")
        payload, _ = _strict_json(draft.payload, max_bytes=self.MAX_SIGNAL_PAYLOAD_BYTES)
        if not isinstance(draft.epistemic_state, str) or not draft.epistemic_state or len(draft.epistemic_state) > 80:
            raise CognitiveFabricError("epistemic_state inválido.")
        evidence_refs = draft.evidence_refs
        if not isinstance(evidence_refs, (tuple, list)) or len(evidence_refs) > 16:
            raise CognitiveFabricError("evidence_refs deve conter até 16 referências.")
        refs = []
        for item in evidence_refs:
            if not isinstance(item, str) or not item.strip() or len(item) > 512:
                raise CognitiveFabricError("Referência de evidência inválida.")
            refs.append(item.strip())
        causation_id = draft.causation_id
        if causation_id is not None:
            causation_id = _identifier(causation_id, "causation_id")
        signal = CognitiveSignal(
            signal_id=uuid.uuid4().hex,
            correlation_id=workspace.correlation_id,
            sequence=len(workspace.signals) + 1,
            topic=topic,
            source=source,
            target=target,
            created_at=datetime.now(timezone.utc).isoformat(),
            causation_id=causation_id,
            epistemic_state=draft.epistemic_state,
            confidence=_confidence(draft.confidence),
            evidence_refs=tuple(refs),
            payload=_freeze_json(payload),
        )
        workspace._append_signal(signal)
        return signal

    def connectome_snapshot(self) -> dict[str, Any]:
        with self._flow_lock:
            flow_snapshot = tuple(self._observed_flows.items())
        flows = [
            {
                "source": source,
                "target": target,
                "topic": topic,
                "observed_count": count,
                "kind": "observed_runtime_flow",
                "causal_attribution": "not_established",
            }
            for (source, target, topic), count in sorted(flow_snapshot)
        ]
        return {
            "schema": "mahoraga.connectome_snapshot",
            "version": self.VERSION,
            "nodes": sorted(self._component_ids),
            "verified_structural_edges": [dict(item) for item in self._verified_edges],
            "observed_runtime_flows": flows,
            "node_count": len(self._component_ids),
            "verified_edge_count": len(self._verified_edges),
            "observed_flow_count": len(flows),
            "persistence": "in_memory_only",
        }


    def analyze_connectome(
        self,
        source: str | None = None,
        target: str | None = None,
        *,
        max_hops: int = 8,
        max_paths: int = 10,
        max_edge_visits: int = 1024,
    ) -> dict[str, Any]:
        """Return bounded topology metrics and optional paths for both graph layers.

        Verified shared-component relationships and actually delivered runtime
        flows are analysed separately. A path is structural evidence or an
        observed sequence, not proof that the chain causes a capability.
        """
        snapshot = self.connectome_snapshot()
        nodes = snapshot["nodes"]
        node_set = set(nodes)
        if (source is None) != (target is None):
            raise CognitiveFabricError("source e target devem ser informados juntos.")
        if source is not None:
            source = _identifier(source, "source")
            target = _identifier(target, "target")
            if source not in node_set or target not in node_set:
                raise CognitiveFabricError("source e target precisam existir no conectoma.")
            if source == target:
                raise CognitiveFabricError("source e target devem ser diferentes.")

        for field, value, minimum, maximum in (
            ("max_hops", max_hops, 1, self.MAX_DISPATCH_DEPTH),
            ("max_paths", max_paths, 1, 20),
            ("max_edge_visits", max_edge_visits, 1, 1024),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise CognitiveFabricError(
                    f"{field} deve ser inteiro entre {minimum} e {maximum}."
                )

        structural_edges = snapshot["verified_structural_edges"]
        structural_adjacency: dict[str, list[dict[str, Any]]] = {}
        structural_pairs = set()
        for edge in structural_edges:
            if edge.get("verified") is not True:
                continue
            left, right = edge["source"], edge["target"]
            structural_pairs.add((left, right))
            structural_adjacency.setdefault(left, []).append({
                "source": left,
                "target": right,
                "target_component": right,
                "relationship_id": edge["relationship_id"],
                "kind": edge["kind"],
                "evidence": edge["evidence"],
                "verified": True,
            })
        for edges in structural_adjacency.values():
            edges.sort(key=lambda item: (item["target"], item["relationship_id"]))

        flow_pairs: dict[tuple[str, str], dict[str, Any]] = {}
        for flow in snapshot["observed_runtime_flows"]:
            key = (flow["source"], flow["target"])
            aggregate = flow_pairs.setdefault(key, {
                "source": flow["source"],
                "target": flow["target"],
                "topics": set(),
                "observed_count": 0,
                "kind": "observed_runtime_flow",
                "causal_attribution": "not_established",
            })
            aggregate["topics"].add(flow["topic"])
            aggregate["observed_count"] += flow["observed_count"]

        observed_adjacency: dict[str, list[dict[str, Any]]] = {}
        observed_pairs = set()
        for key in sorted(flow_pairs):
            aggregate = flow_pairs[key]
            left, right = key
            observed_pairs.add(key)
            observed_adjacency.setdefault(left, []).append({
                "source": left,
                "target": right,
                "target_component": right,
                "topics": sorted(aggregate["topics"]),
                "observed_count": aggregate["observed_count"],
                "kind": aggregate["kind"],
                "causal_attribution": "not_established",
            })

        def summarize(pairs: set[tuple[str, str]]) -> dict[str, Any]:
            in_degree = {node: 0 for node in nodes}
            out_degree = {node: 0 for node in nodes}
            for left, right in pairs:
                out_degree[left] += 1
                in_degree[right] += 1
            reciprocal = set()
            for left, right in pairs:
                if left == right or (right, left) not in pairs:
                    continue
                reciprocal.add(tuple(sorted((left, right))))
            return {
                "edge_count": len(pairs),
                "edge_count_basis": "unique_ordered_component_pairs",
                "reciprocal_pair_count": len(reciprocal),
                "source_components": sorted(
                    node for node in nodes
                    if out_degree[node] > 0 and in_degree[node] == 0
                ),
                "sink_components": sorted(
                    node for node in nodes
                    if in_degree[node] > 0 and out_degree[node] == 0
                ),
                "isolated_components": sorted(
                    node for node in nodes
                    if in_degree[node] == 0 and out_degree[node] == 0
                ),
                "degree_by_component": {
                    node: {
                        "in_degree": in_degree[node],
                        "out_degree": out_degree[node],
                    }
                    for node in nodes
                },
                "max_in_degree": max(in_degree.values(), default=0),
                "max_out_degree": max(out_degree.values(), default=0),
            }

        structural = summarize(structural_pairs)
        observed = summarize(observed_pairs)
        observed["topic_count"] = len({
            topic
            for aggregate in flow_pairs.values()
            for topic in aggregate["topics"]
        })
        observed["total_deliveries"] = sum(
            aggregate["observed_count"] for aggregate in flow_pairs.values()
        )
        observed["flow_edge_count_by_topic"] = snapshot["observed_flow_count"]

        structural_paths = None
        observed_paths = None
        if source is not None and target is not None:
            structural_search = bounded_simple_paths(
                structural_adjacency,
                source,
                target,
                max_hops=max_hops,
                max_paths=max_paths,
                max_edge_visits=max_edge_visits,
            )
            observed_search = bounded_simple_paths(
                observed_adjacency,
                source,
                target,
                max_hops=max_hops,
                max_paths=max_paths,
                max_edge_visits=max_edge_visits,
            )

            def format_paths(search: dict[str, Any], path_kind: str) -> dict[str, Any]:
                formatted = []
                for path in search["paths"]:
                    formatted_edges = []
                    for edge in path["edges"]:
                        record = {
                            key: value for key, value in edge.items()
                            if key != "target"
                        }
                        formatted_edges.append(record)
                    formatted.append({
                        "component_ids": path["node_ids"],
                        "edges": formatted_edges,
                        "hops": len(formatted_edges),
                        "path_kind": path_kind,
                        "chain_capability_proven": False,
                        "causal_attribution": "not_established",
                    })
                return {
                    "path_count": len(formatted),
                    "paths": formatted,
                    "edge_visits": search["edge_visits"],
                    "search_may_be_truncated": search["search_may_be_truncated"],
                    "max_hops": max_hops,
                    "max_paths": max_paths,
                    "max_edge_visits": max_edge_visits,
                }

            structural_paths = format_paths(structural_search, "verified_structure")
            observed_paths = format_paths(observed_search, "observed_runtime_flow")

        return {
            "schema": "mahoraga.connectome_analysis",
            "version": self.VERSION,
            "node_count": len(nodes),
            "structural": {
                **structural,
                "edge_semantics": "verified_shared_component_relationship",
                "all_edges_verified": True,
            },
            "observed_runtime": {
                **observed,
                "edge_semantics": "handler_delivery_observed",
                "causal_attribution": "not_established",
            },
            "path_query": (
                {"source": source, "target": target}
                if source is not None else None
            ),
            "structural_paths": structural_paths,
            "observed_runtime_paths": observed_paths,
            "persistent_memory_written": False,
            "execution_performed": False,
            "causal_attribution": "not_established",
        }

    def workspace_report(self, workspace: CognitiveWorkspace) -> dict[str, Any]:
        if not isinstance(workspace, CognitiveWorkspace) or workspace._fabric_token != self._token:
            raise CognitiveFabricError("Workspace não pertence a esta instância do fabric.")
        measurements = list(workspace.stage_measurements)
        return {
            "schema": "mahoraga.cognitive_cycle_trace",
            "version": self.VERSION,
            "cycle_id": workspace.correlation_id,
            "signal_count": len(workspace.signals),
            "signals": [item.as_dict() for item in workspace.signals],
            "stage_measurements": measurements,
            "effectome": {
                "status": "observational_baseline",
                "measurements": measurements,
                "causal_attribution": "not_established",
                "note": "Latência e estado observados não demonstram causalidade; ablações e baselines controlados são necessários.",
            },
            "connectome_summary": {
                "node_count": len(self._component_ids),
                "verified_structural_edge_count": len(self._verified_edges),
                "observed_runtime_flow_count": len(self._observed_flows),
            },
            "persistent_memory_written": False,
            "background_work_started": False,
            "execution_authority_granted": False,
        }
