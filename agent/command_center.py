"""Central segura de interpretação e encaminhamento de comandos."""


class CommandCenter:
    VERSION = "0.2.0"

    COMMANDS = {
        "status": "status",
        "estado": "status",
        "status do mahoraga": "status",
        "estado do mahoraga": "status",
        "inspecionar blender": "blender.inspect",
        "inspecionar cena": "blender.inspect",
        "blender inspect": "blender.inspect",
        "criar templo": "blender.create_temple",
        "criar templo mahoraga": "blender.create_temple",
    }

    ALLOWED_INTENTS = {"status", "blender.inspect"}

    def __init__(self, core):
        self.core = core

    def interpret(self, command):
        if not isinstance(command, str):
            return {
                "intent": "invalid",
                "recognized": False,
                "decision": "abstain",
            }

        normalized = " ".join(command.casefold().split())
        intent = self.COMMANDS.get(normalized)
        if intent is not None:
            return {
                "intent": intent,
                "recognized": True,
                "method": "exact",
                "decision": "recognize",
                "confidence": 1.0,
                "margin": 1.0,
            }

        language = getattr(self.core, "language", None)
        classifier = getattr(language, "classify", None)
        if not callable(classifier):
            return {
                "intent": "unknown",
                "recognized": False,
                "decision": "abstain",
            }

        try:
            result = classifier(command)
            if not isinstance(result, dict):
                return {
                    "intent": "unknown",
                    "recognized": False,
                    "decision": "abstain",
                }

            decision = result.get("decision")
            if decision in {"abstain", "clarify", "defer"}:
                candidate = result.get("intent")
                if candidate not in self.ALLOWED_INTENTS:
                    candidate = "unknown"
                return {
                    "intent": candidate,
                    "recognized": False,
                    "decision": decision,
                    "reason": result.get("reason"),
                    "confidence": result.get("confidence", 0.0),
                    "margin": result.get("margin", 0.0),
                }

            if result.get("recognized") is not True:
                return {
                    "intent": "unknown",
                    "recognized": False,
                    "decision": "abstain",
                    "reason": result.get("reason"),
                }

            intent = result.get("intent")
            if intent not in self.ALLOWED_INTENTS:
                return {
                    "intent": "unknown",
                    "recognized": False,
                    "decision": "abstain",
                    "reason": "unsupported_intent",
                }

            confidence = result["confidence"]
            margin = result["margin"]
            if isinstance(confidence, bool) or isinstance(margin, bool):
                raise ValueError("Confidence values cannot be boolean.")
            confidence = float(confidence)
            margin = float(margin)
            if not (0 <= confidence <= 1 and 0 <= margin <= 1):
                raise ValueError("Confidence values outside the valid range.")

        except Exception:
            return {
                "intent": "unknown",
                "recognized": False,
                "decision": "abstain",
            }

        return {
            "intent": intent,
            "recognized": True,
            "method": "language_model",
            "decision": "recognize",
            "confidence": confidence,
            "margin": margin,
        }

    def _remember(self, parsed, source):
        confidence = parsed.get(
            "confidence",
            1.0 if parsed["recognized"] else 0.0,
        )
        self.core.cognitive.record_observation(
            category="command_interpretation",
            subject=parsed["intent"],
            data={
                "recognized": parsed["recognized"],
                "decision": parsed.get("decision", "abstain"),
                "reason": parsed.get("reason"),
                "source": source,
                "interpretation_method": parsed.get("method", "exact"),
                "confidence": confidence,
                "margin": parsed.get("margin"),
            },
            source="command_center",
            confidence=confidence,
            limitations=[
                "Classificação neural limitada aos exemplos e ao vocabulário treinados.",
                "Previsões neurais não autorizam operações fora da lista permitida.",
                "Decisões defer e clarify nunca encaminham operações.",
            ],
        )

    def prepare(
        self,
        command,
        *,
        knowledge_query=None,
        knowledge_subject=None,
        knowledge_limit=5,
        facts=None,
        rules=None,
        contradiction_pairs=None,
        include_capability_review=True,
        include_experience_review=True,
    ):
        """Prepara a solicitação pelo núcleo integrado, sem despachar operações."""
        if not isinstance(command, str) or not command.strip():
            return {"status": "rejected", "reason": "Solicitação vazia ou inválida."}
        preparer = getattr(self.core, "prepare_request", None)
        if not callable(preparer):
            return {
                "status": "unavailable",
                "reason": "Pipeline cognitivo integrado indisponível.",
                "execution_performed": False,
            }
        result = preparer(
            command,
            knowledge_query=knowledge_query,
            knowledge_subject=knowledge_subject,
            knowledge_limit=knowledge_limit,
            facts=facts,
            rules=rules,
            contradiction_pairs=contradiction_pairs,
            include_capability_review=include_capability_review,
            include_experience_review=include_experience_review,
        )
        if not isinstance(result, dict):
            raise TypeError("O pipeline cognitivo precisa retornar um dicionário.")
        result["command_center"] = {
            "mode": "preparation_only",
            "dispatch_performed": False,
            "tool_execution_performed": False,
        }
        return result

    def execute(self, command, source="user"):
        if not isinstance(source, str) or not source.strip() or len(source) > 40:
            raise ValueError("Origem do comando inválida.")

        parsed = self.interpret(command)

        if parsed["intent"] == "invalid":
            return {"status": "rejected", "reason": "Comando inválido."}

        self._remember(parsed, source.strip())

        decision = parsed.get(
            "decision",
            "recognize" if parsed["recognized"] else "abstain",
        )

        if decision == "clarify":
            return {
                "status": "clarification_required",
                "intent": parsed["intent"],
                "reason": parsed.get("reason"),
                "message": "A solicitação está ambígua. Nenhuma ação foi executada.",
            }

        if decision == "defer":
            return {
                "status": "deferred",
                "intent": parsed["intent"],
                "reason": parsed.get("reason"),
                "message": "A intenção é futura ou condicional. Nenhuma ação foi executada.",
            }

        if not parsed["recognized"]:
            return {
                "status": "not_recognized",
                "intent": "unknown",
                "message": "Nenhuma ação foi executada.",
            }

        if parsed["intent"] == "status":
            return {
                "status": "completed",
                "intent": "status",
                "result": self.core.build_report(persist=False),
            }

        if parsed["intent"] == "blender.inspect":
            task_id = self.core.blender_bridge.submit_task(
                "scene.inspect", {}
            )
            return {
                "status": "queued",
                "intent": "blender.inspect",
                "task_id": task_id,
            }

        if parsed["intent"] == "blender.create_temple":
            task_id = self.core.blender_bridge.submit_task(
                "mahoraga.generate",
                {
                    "generation": "stone_temple",
                    "name": "Templo_Mahoraga",
                    "columns": 8,
                    "location": [0.0, 0.0, 0.0],
                },
            )
            return {
                "status": "queued",
                "intent": "blender.create_temple",
                "task_id": task_id,
            }

        return {"status": "rejected", "reason": "Intenção sem executor."}
