"""Aprendizagem neural supervisionada de intenções do Mahoraga.

Este módulo reutiliza a rede neural, o treinador e a memória cognitiva.
Não executa comandos nem concede permissões operacionais.
"""

from __future__ import annotations

import hashlib
import json
import re
import os
import tempfile
import zipfile
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any

import numpy as np

from agent.linguistic_analysis import LinguisticAnalyzer
from agent.neural_core import Adam, MSELoss, NeuralError, build_mlp
from agent.neural_training import Trainer


def _synchronized(method):
    """Serialize model and dataset state transitions per engine instance."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return wrapper


class LanguageEngineError(Exception):
    pass


class LanguageEngine:
    VERSION = "0.1.0"
    CALIBRATION_TASK = "language_intent_classification"
    CONFIDENCE_TARGET_CANDIDATE_INTENT = "candidate_intent"
    MAX_EXAMPLES = 10000
    MAX_TEXT_LENGTH = 500
    PROVENANCE_SCHEMA_VERSION = 1
    MAX_PROVENANCE_RECORDS = 40000
    MAX_INTENT_LENGTH = 80
    MODEL_FORMAT_VERSION = 2
    FEATURE_SCHEMA_VERSION = "binary-bow-project-token-v1"
    MAX_EXAMPLE_DATASET_BYTES = 24 * 1024 * 1024
    MAX_METADATA_BYTES = 1 * 1024 * 1024
    MAX_MODEL_BYTES = 32 * 1024 * 1024

    def __init__(
        self,
        root: str | Path,
        cognitive,
        min_confidence: float = 0.60,
        min_margin: float = 0.15,
        seed: int = 42,
    ):
        if not 0.0 < min_confidence <= 1.0:
            raise ValueError("min_confidence inválida.")
        if not 0.0 <= min_margin <= 1.0:
            raise ValueError("min_margin inválida.")

        self.root = Path(root).expanduser().resolve()
        self.cognitive = cognitive
        self.base = self.root / "data" / "language_engine"
        self.dataset_path = self.base / "examples.json"
        self.model_path = self.base / "model.npz"
        self.metadata_path = self.base / "metadata.json"

        self.min_confidence = float(min_confidence)
        self.min_margin = float(min_margin)
        if (
            isinstance(seed, bool)
            or not isinstance(seed, (int, np.integer))
            or int(seed) < 0
        ):
            raise ValueError("seed deve ser um inteiro não negativo.")
        self.seed = int(seed)

        self._state_lock = RLock()
        self.examples: list[dict[str, str]] = []
        self.provenance_records: list[dict[str, Any]] = []
        self.vocabulary: list[str] = []
        self.labels: list[str] = []
        self.network = None
        self.trainer = None
        self.predictor_id: str | None = None
        self.ready = False
        self.linguistic = LinguisticAnalyzer()

        self._load_examples()

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.casefold().split())

    def _dataset_sha256(self) -> str:
        """Fingerprint the exact normalized examples used to train this model."""
        payload = json.dumps(
            self.examples,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _example_id(example: dict[str, str]) -> str:
        canonical = json.dumps(
            {"text": example["text"], "intent": example["intent"]},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _provenance_sha256(self) -> str:
        records = sorted(self.provenance_records, key=lambda item: (
            item["example_id"], item["source_label"] or "",
            item["recorded_at"] or "", item["record_id"] or "",
            item["trust_state"],
        ))
        payload = json.dumps(
            records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def _validate_provenance_record(cls, item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise LanguageEngineError("Registro de proveniência precisa ser um objeto.")
        required = {"example_id", "source_label", "recorded_at", "record_id", "trust_state"}
        if set(item) != required:
            raise LanguageEngineError("Esquema de proveniência incompatível.")
        example_id = item.get("example_id")
        if not isinstance(example_id, str) or not re.fullmatch(r"[0-9a-f]{64}", example_id):
            raise LanguageEngineError("example_id de proveniência inválido.")
        trust_state = item.get("trust_state")
        if trust_state == "legacy_source_unknown":
            if any(item.get(key) is not None for key in ("source_label", "recorded_at", "record_id")):
                raise LanguageEngineError("Proveniência legada não pode inventar origem ou data.")
            return {
                "example_id": example_id, "source_label": None,
                "recorded_at": None, "record_id": None,
                "trust_state": trust_state,
            }
        if trust_state != "caller_declared_unverified":
            raise LanguageEngineError("Estado de confiança da proveniência desconhecido.")
        source_label, recorded_at, record_id = (
            item.get("source_label"), item.get("recorded_at"), item.get("record_id")
        )
        if not isinstance(source_label, str) or not source_label.strip() or len(source_label) > 40:
            raise LanguageEngineError("Rótulo de origem inválido.")
        if not isinstance(recorded_at, str) or len(recorded_at) > 64:
            raise LanguageEngineError("Timestamp de proveniência inválido.")
        try:
            parsed = datetime.fromisoformat(recorded_at)
        except ValueError as exc:
            raise LanguageEngineError("Timestamp de proveniência inválido.") from exc
        if parsed.tzinfo is None:
            raise LanguageEngineError("Timestamp de proveniência precisa de fuso horário.")
        if not isinstance(record_id, str) or not re.fullmatch(r"[0-9a-f]{32}", record_id):
            raise LanguageEngineError("record_id de proveniência inválido.")
        return {
            "example_id": example_id, "source_label": source_label.strip(),
            "recorded_at": recorded_at, "record_id": record_id,
            "trust_state": trust_state,
        }

    def _checkpoint_sha256(self) -> str:
        digest = hashlib.sha256()
        with self.model_path.open("rb") as checkpoint:
            for chunk in iter(lambda: checkpoint.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _predictor_id_for_checkpoint(self, architecture: dict[str, Any]) -> str:
        identity = {
            "engine_version": self.VERSION,
            "model_format_version": self.MODEL_FORMAT_VERSION,
            "feature_schema_version": self.FEATURE_SCHEMA_VERSION,
            "linguistic_analyzer_version": self.linguistic.VERSION,
            "lexicon_version": self.linguistic.LEXICON_VERSION,
            "dataset_sha256": self._dataset_sha256(),
            "provenance_sha256": self._provenance_sha256(),
            "checkpoint_sha256": self._checkpoint_sha256(),
            "architecture": architecture,
            "seed": self.seed,
        }
        payload = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        fingerprint = hashlib.sha256(payload).hexdigest()[:24]
        return f"language-engine:{fingerprint}"

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)

    def _atomic_json(self, path: Path, data: dict[str, Any]) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        temporary = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.base,
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def _load_examples(self) -> None:
        if not self.dataset_path.exists():
            return

        try:
            if self.dataset_path.stat().st_size > self.MAX_EXAMPLE_DATASET_BYTES:
                raise LanguageEngineError("Arquivo de exemplos excede o limite de tamanho.")
            with self.dataset_path.open("r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                raise LanguageEngineError("Raiz do conjunto de exemplos precisa ser um objeto.")
            if data.get("version") != self.VERSION:
                raise LanguageEngineError("Versão do conjunto incompatível.")

            examples = data.get("examples")
            if not isinstance(examples, list) or len(examples) > self.MAX_EXAMPLES:
                raise LanguageEngineError("Conjunto de exemplos inválido.")

            validated, seen_pairs, text_labels = [], set(), {}
            for item in examples:
                example = self._validate_example(item)
                pair = (example["text"], example["intent"])
                previous_intent = text_labels.get(example["text"])
                if previous_intent is not None and previous_intent != example["intent"]:
                    raise LanguageEngineError("O mesmo texto aparece associado a intenções conflitantes.")
                text_labels[example["text"]] = example["intent"]
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    validated.append(example)

            has_version = "provenance_schema_version" in data
            has_records = "provenance" in data
            if not has_version and not has_records:
                self.provenance_records = [{
                    "example_id": self._example_id(example),
                    "source_label": None, "recorded_at": None,
                    "record_id": None, "trust_state": "legacy_source_unknown",
                } for example in validated]
            else:
                provenance_version = data.get("provenance_schema_version")
                if (
                    isinstance(provenance_version, bool)
                    or not isinstance(provenance_version, int)
                    or provenance_version != self.PROVENANCE_SCHEMA_VERSION
                ):
                    raise LanguageEngineError("Versão do esquema de proveniência incompatível.")
                raw_records = data.get("provenance")
                if not isinstance(raw_records, list) or len(raw_records) > self.MAX_PROVENANCE_RECORDS:
                    raise LanguageEngineError("Lista de proveniência inválida ou acima do limite.")
                valid_ids = {self._example_id(example) for example in validated}
                records, record_ids, record_keys, covered = [], set(), set(), set()
                for raw_record in raw_records:
                    record = self._validate_provenance_record(raw_record)
                    if record["example_id"] not in valid_ids:
                        raise LanguageEngineError("Proveniência referencia exemplo inexistente.")
                    if record["record_id"] is not None:
                        if record["record_id"] in record_ids:
                            raise LanguageEngineError("record_id de proveniência duplicado.")
                        record_ids.add(record["record_id"])
                    key = (record["example_id"], record["source_label"], record["trust_state"])
                    if key in record_keys:
                        raise LanguageEngineError("Registro de proveniência duplicado.")
                    record_keys.add(key)
                    covered.add(record["example_id"])
                    records.append(record)
                if covered != valid_ids:
                    raise LanguageEngineError("Há exemplos sem registro de proveniência.")
                self.provenance_records = records

            self.examples = validated

        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, AttributeError, RecursionError) as exc:
            raise LanguageEngineError("Não foi possível carregar os exemplos.") from exc

    def _validate_example(self, item: Any) -> dict[str, str]:
        if not isinstance(item, dict):
            raise ValueError("Exemplo deve ser um objeto.")
        text, intent = item.get("text"), item.get("intent")
        if not isinstance(text, str) or not isinstance(intent, str):
            raise ValueError("Texto e intenção devem ser strings.")
        text, intent = self._normalize(text), intent.strip().casefold()
        if not text or len(text) > self.MAX_TEXT_LENGTH:
            raise ValueError("Texto vazio ou muito longo.")
        if not intent or len(intent) > self.MAX_INTENT_LENGTH:
            raise ValueError("Intenção vazia ou muito longa.")
        if not self._tokens(text):
            raise ValueError("Texto sem palavras reconhecíveis.")
        return {"text": text, "intent": intent}

    @_synchronized
    def add_examples(
        self,
        examples: list[dict[str, str]],
        source: str = "user",
    ) -> dict[str, Any]:
        if not isinstance(examples, list) or not examples:
            raise ValueError("Informe uma lista não vazia de exemplos.")
        if not isinstance(source, str) or not source.strip() or len(source) > 40:
            raise ValueError("Origem inválida.")

        validated = [self._validate_example(item) for item in examples]
        unique_batch, batch_pairs = [], set()
        text_labels = {item["text"]: item["intent"] for item in self.examples}
        existing_pairs = {(item["text"], item["intent"]) for item in self.examples}
        for item in validated:
            previous_intent = text_labels.get(item["text"])
            if previous_intent is not None and previous_intent != item["intent"]:
                raise ValueError("O mesmo texto não pode ser associado a intenções diferentes.")
            text_labels[item["text"]] = item["intent"]
            pair = (item["text"], item["intent"])
            if pair not in batch_pairs:
                batch_pairs.add(pair)
                unique_batch.append(item)

        added = [item for item in unique_batch
                 if (item["text"], item["intent"]) not in existing_pairs]
        updated_examples = self.examples + added
        updated_provenance = list(self.provenance_records)
        existing_lineage = {
            (item["example_id"], item["source_label"], item["trust_state"])
            for item in updated_provenance
        }
        provenance_added = 0
        source_label = source.strip()
        timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        for item in unique_batch:
            example_id = self._example_id(item)
            key = (example_id, source_label, "caller_declared_unverified")
            if key in existing_lineage:
                continue
            updated_provenance.append({
                "example_id": example_id,
                "source_label": source_label,
                "recorded_at": timestamp,
                "record_id": uuid.uuid4().hex,
                "trust_state": "caller_declared_unverified",
            })
            existing_lineage.add(key)
            provenance_added += 1

        if not added and not provenance_added:
            return {"status": "unchanged", "added": 0}
        if len(updated_examples) > self.MAX_EXAMPLES:
            raise ValueError("Limite de exemplos atingido.")
        if len(updated_provenance) > self.MAX_PROVENANCE_RECORDS:
            raise ValueError("Limite de registros de proveniência atingido.")

        dataset = {
            "version": self.VERSION,
            "examples": updated_examples,
            "provenance_schema_version": self.PROVENANCE_SCHEMA_VERSION,
            "provenance": updated_provenance,
        }
        size = len(json.dumps(dataset, ensure_ascii=False, indent=2).encode("utf-8"))
        if size > self.MAX_EXAMPLE_DATASET_BYTES:
            raise ValueError("Conjunto com proveniência excede o limite de tamanho.")

        self._atomic_json(self.dataset_path, dataset)
        self.examples = updated_examples
        self.provenance_records = updated_provenance
        self.ready = False
        self.network = None
        self.trainer = None

        self.cognitive.record_observation(
            category="language_training_data",
            subject="examples_added" if added else "example_provenance_updated",
            data={
                "count": len(added),
                "provenance_records_added": provenance_added,
                "source": source_label,
            },
            source="language_engine",
            confidence=None,
            limitations=[
                "O rótulo de origem foi declarado pelo chamador e não foi verificado independentemente.",
                "Os exemplos continuam sendo dados supervisionados de escopo limitado; não demonstram compreensão geral da linguagem.",
            ],
        )

        return {
            "status": "recorded" if added else "provenance_updated",
            "added": len(added),
            "provenance_added": provenance_added,
            "dataset_sha256": self._dataset_sha256(),
            "provenance_sha256": self._provenance_sha256(),
        }

    def _features(self, texts: list[str]) -> np.ndarray:
        indexes = {word: i for i, word in enumerate(self.vocabulary)}
        matrix = np.zeros(
            (len(texts), len(self.vocabulary)),
            dtype=np.float32,
        )

        for row, text in enumerate(texts):
            for token in set(self._tokens(text)):
                projected = self.linguistic.project_token(token, indexes)
                if projected is not None:
                    matrix[row, indexes[projected]] = 1.0

        return matrix

    @_synchronized
    def train(self, epochs: int = 200) -> dict[str, Any]:
        if isinstance(epochs, bool) or not isinstance(epochs, int):
            raise ValueError("epochs deve ser inteiro.")
        if not 1 <= epochs <= 2000:
            raise ValueError("epochs deve estar entre 1 e 2000.")
        if len(self.examples) < 4:
            raise LanguageEngineError("São necessários pelo menos 4 exemplos.")

        labels = sorted({item["intent"] for item in self.examples})
        if len(labels) < 2:
            raise LanguageEngineError("São necessárias pelo menos 2 intenções.")

        counts = {
            label: sum(item["intent"] == label for item in self.examples)
            for label in labels
        }
        if any(count < 2 for count in counts.values()):
            raise LanguageEngineError(
                "Cada intenção precisa de pelo menos 2 exemplos."
            )

        vocabulary = sorted({
            token
            for item in self.examples
            for token in self._tokens(item["text"])
        })

        if not vocabulary:
            raise LanguageEngineError("Vocabulário vazio.")

        self.vocabulary = vocabulary
        self.labels = labels

        inputs = self._features([item["text"] for item in self.examples])
        label_indexes = {label: i for i, label in enumerate(labels)}

        targets = np.zeros(
            (len(self.examples), len(labels)),
            dtype=np.float32,
        )

        for row, item in enumerate(self.examples):
            targets[row, label_indexes[item["intent"]]] = 1.0

        network = build_mlp(
            input_size=len(vocabulary),
            hidden_sizes=[max(8, min(32, len(vocabulary) * 2))],
            output_size=len(labels),
            activation="tanh",
            output_activation="softmax",
            seed=self.seed,
        )

        optimizer = Adam(learning_rate=0.01)
        trainer = Trainer(
            network=network,
            optimizer=optimizer,
            loss=MSELoss(),
            batch_size=min(8, len(inputs)),
            shuffle=True,
            seed=self.seed,
        )

        result = trainer.fit(inputs, targets, epochs=epochs)

        self.base.mkdir(parents=True, exist_ok=True)
        network.save_checkpoint(self.model_path)
        predictor_id = self._predictor_id_for_checkpoint(network.config())

        metadata = {
            "version": self.VERSION,
            "model_format_version": self.MODEL_FORMAT_VERSION,
            "feature_schema_version": self.FEATURE_SCHEMA_VERSION,
            "linguistic_analyzer_version": self.linguistic.VERSION,
            "lexicon_version": self.linguistic.LEXICON_VERSION,
            "vocabulary": vocabulary,
            "labels": labels,
            "examples": len(self.examples),
            "dataset_sha256": self._dataset_sha256(),
            "provenance_schema_version": self.PROVENANCE_SCHEMA_VERSION,
            "provenance_sha256": self._provenance_sha256(),
            "provenance_records": len(self.provenance_records),
            "seed": self.seed,
            "architecture": network.config(),
        }
        self._atomic_json(self.metadata_path, metadata)

        self.network = network
        self.trainer = trainer
        self.predictor_id = predictor_id
        self.ready = True

        self.cognitive.record_learning(
            key="language_engine.training",
            learning={
                "labels": labels,
                "examples": len(self.examples),
                "epochs_completed": result["epochs_completed"],
                "final_loss": result["history"][-1]["loss"],
            },
            source="language_engine",
            metadata={
                "version": self.VERSION,
                "dataset_sha256": metadata["dataset_sha256"],
            },
        )

        return {
            "status": "trained",
            "labels": labels,
            "examples": len(self.examples),
            "epochs_completed": result["epochs_completed"],
            "final_loss": result["history"][-1]["loss"],
            "dataset_sha256": metadata["dataset_sha256"],
        }

    def _load_model(self) -> bool:
        if self.ready:
            return True

        if not self.metadata_path.exists() or not self.model_path.exists():
            return False

        try:
            if self.metadata_path.stat().st_size > self.MAX_METADATA_BYTES:
                return False
            if self.model_path.stat().st_size > self.MAX_MODEL_BYTES:
                return False
            with self.metadata_path.open("r", encoding="utf-8") as file:
                metadata = json.load(file)

            if not isinstance(metadata, dict):
                return False
            if (
                metadata.get("version") != self.VERSION
                or metadata.get("model_format_version") != self.MODEL_FORMAT_VERSION
                or metadata.get("feature_schema_version") != self.FEATURE_SCHEMA_VERSION
                or metadata.get("linguistic_analyzer_version") != self.linguistic.VERSION
                or metadata.get("lexicon_version") != self.linguistic.LEXICON_VERSION
            ):
                return False

            # Legacy or incompatible checkpoints remain on disk for recovery,
            # but cannot be loaded under a different feature/analyzer contract.
            if metadata.get("dataset_sha256") != self._dataset_sha256():
                return False
            if (
                metadata.get("provenance_schema_version") != self.PROVENANCE_SCHEMA_VERSION
                or metadata.get("provenance_sha256") != self._provenance_sha256()
                or metadata.get("provenance_records") != len(self.provenance_records)
            ):
                return False
            if metadata.get("examples") != len(self.examples):
                return False
            if (
                not isinstance(metadata.get("seed"), int)
                or isinstance(metadata.get("seed"), bool)
                or metadata.get("seed") != self.seed
            ):
                return False

            vocabulary = metadata.get("vocabulary")
            labels = metadata.get("labels")
            if (
                not isinstance(vocabulary, list)
                or not vocabulary
                or any(not isinstance(item, str) or not item for item in vocabulary)
                or len(vocabulary) != len(set(vocabulary))
                or not isinstance(labels, list)
                or len(labels) < 2
                or any(not isinstance(item, str) or not item for item in labels)
                or len(labels) != len(set(labels))
            ):
                return False

            network = build_mlp(
                len(vocabulary),
                [max(8, min(32, len(vocabulary) * 2))],
                len(labels),
                activation="tanh",
                output_activation="softmax",
                seed=self.seed,
            )
            if metadata.get("architecture") != network.config():
                return False
            network.load_checkpoint(self.model_path)

            predictor_id = self._predictor_id_for_checkpoint(network.config())
            self.vocabulary = vocabulary
            self.labels = labels
            self.network = network
            self.predictor_id = predictor_id
            self.ready = True
            return True

        except (NeuralError, OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError, RecursionError, EOFError, zipfile.BadZipFile):
            return False

    @_synchronized
    def classify(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            return {
                "recognized": False,
                "decision": "abstain",
                "intent": None,
                "reason": "invalid_text",
            }

        analysis = self.linguistic.analyze(text)
        decision = analysis["decision"]

        if decision in {"abstain", "clarify"}:
            return {
                "recognized": False,
                "decision": decision,
                "intent": None,
                "reason": analysis["reason"],
                "linguistic": analysis,
            }

        if not self._load_model():
            return {
                "recognized": False,
                "decision": "defer" if decision == "defer" else "abstain",
                "intent": None,
                "reason": (
                    "model_not_trained"
                    if decision != "defer"
                    else analysis["reason"]
                ),
                "linguistic": analysis,
            }

        vector = self._features([text])
        if not np.any(vector):
            return {
                "recognized": False,
                "decision": "defer" if decision == "defer" else "abstain",
                "intent": None,
                "reason": (
                    "unknown_vocabulary"
                    if decision != "defer"
                    else analysis["reason"]
                ),
                "linguistic": analysis,
            }

        probabilities = np.asarray(
            self.network.predict(vector)[0],
            dtype=np.float64,
        )

        if not np.all(np.isfinite(probabilities)):
            return {
                "recognized": False,
                "decision": "defer" if decision == "defer" else "abstain",
                "intent": None,
                "reason": "invalid_prediction",
                "linguistic": analysis,
            }

        order = np.argsort(probabilities)
        best_index = int(order[-1])
        confidence = float(probabilities[best_index])
        second = float(probabilities[order[-2]])
        margin = confidence - second
        prediction_metadata = {
            "candidate_intent": self.labels[best_index],
            "predictor_id": getattr(self, "predictor_id", None),
            "confidence_target": self.CONFIDENCE_TARGET_CANDIDATE_INTENT,
        }

        if decision == "defer":
            intent_hint = self.linguistic.infer_intent_hint(text)
            if intent_hint in self.labels:
                intent = intent_hint
                intent_source = "domain_anchor"
            elif (
                confidence >= self.min_confidence
                and margin >= self.min_margin
            ):
                intent = self.labels[best_index]
                intent_source = "neural"
            else:
                intent = None
                intent_source = None
            return {
                "recognized": False,
                "decision": "defer",
                "intent": intent,
                "intent_source": intent_source,
                "reason": analysis["reason"],
                "confidence": confidence,
                "margin": margin,
                "linguistic": analysis,
                **prediction_metadata,
            }

        if confidence < self.min_confidence or margin < self.min_margin:
            return {
                "recognized": False,
                "decision": "abstain",
                "intent": None,
                "reason": "low_confidence",
                "confidence": confidence,
                "margin": margin,
                "linguistic": analysis,
                **prediction_metadata,
            }

        return {
            "recognized": True,
            "decision": "recognize",
            "intent": self.labels[best_index],
            "intent_source": "neural",
            "confidence": confidence,
            "margin": margin,
            "linguistic": analysis,
            **prediction_metadata,
        }

    @_synchronized
    def status(self) -> dict[str, Any]:
        return {
            "component": "LanguageEngine",
            "version": self.VERSION,
            "examples": len(self.examples),
            "intents": sorted({
                item["intent"] for item in self.examples
            }),
            "provenance": {
                "schema_version": self.PROVENANCE_SCHEMA_VERSION,
                "records": len(self.provenance_records),
                "examples_with_declared_source": len({
                    item["example_id"] for item in self.provenance_records
                    if item["trust_state"] == "caller_declared_unverified"
                }),
                "examples_with_unknown_legacy_source": len({
                    item["example_id"] for item in self.provenance_records
                    if item["trust_state"] == "legacy_source_unknown"
                }),
                "verified_examples": 0,
                "source_identity_verified": False,
                "trust_boundary": "source labels are caller-declared and unverified",
                "sha256": self._provenance_sha256(),
            },
            "trained": self._load_model(),
            "predictor_id": self.predictor_id,
            "vocabulary_size": len(self.vocabulary),
            "linguistic_analysis": {
                "component": "LinguisticAnalyzer",
                "version": self.linguistic.VERSION,
                "lexicon_version": self.linguistic.LEXICON_VERSION,
                "lexical_alias_count": len(self.linguistic.TOKEN_ALIASES),
                "integrated": True,
            },
            "artistic_domain": "available_for_supervised_examples",
            "programming_domain": "available_for_supervised_examples",
            "blender_domain": "available_for_supervised_examples",
            "autonomous_execution": False,
        }
