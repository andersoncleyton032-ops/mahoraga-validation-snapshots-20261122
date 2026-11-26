"""Backend-neutral generation boundary owned by the Mahoraga cognitive core.

Implementations may use a loopback server or an on-device runtime, but they
must expose the same narrow text-generation contract. This port grants no
memory, tool execution, persistence, or policy authority to the backend.
"""
from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ModelGenerationPort(Protocol):
    @property
    def enabled(self) -> bool:
        """Whether policy/configuration permits text generation."""

    def status(self) -> dict[str, Any]:
        """Return an explicit, non-probing status snapshot."""

    def close(self) -> None:
        """Release the backend runtime if it exposes an explicit close hook."""
        ...

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Generate text only; never execute tools or persist conversations."""


class ModelRuntimeGenerationAdapter:
    """Adapt the governed prompt/runtime API to IntegratedCore's text-only port.

    The runtime and ResourceRequest factory are injected; this module does not
    import or own the inference engine, model file, memory, tools or lifecycle.
    """

    MAX_MESSAGES = 32
    MAX_MESSAGE_CHARS = 20_000
    MAX_TOTAL_CHARS = 50_000
    MAX_OUTPUT_TOKENS = 2_048

    def __init__(
        self,
        runtime: Any,
        request_factory,
        *,
        enabled: bool = False,
        task_class: str = "interactive",
    ):
        if runtime is None or not callable(getattr(runtime, "generate", None)):
            raise TypeError("runtime precisa expor generate(prompt, request=...).")
        if not callable(request_factory):
            raise TypeError("request_factory precisa ser chamável.")
        if not isinstance(enabled, bool):
            raise TypeError("enabled precisa ser booleano explícito.")
        if not isinstance(task_class, str) or task_class not in {
            "interactive", "reasoning", "maintenance"
        }:
            raise ValueError("task_class inválida para a porta cognitiva.")
        self._runtime = runtime
        self._request_factory = request_factory
        self._enabled = enabled
        self._task_class = task_class

    @property
    def enabled(self) -> bool:
        return self._enabled

    def close(self) -> None:
        """Close the injected runtime without transferring lifecycle ownership."""
        closer = getattr(self._runtime, "close", None)
        if callable(closer):
            closer()

    def status(self) -> dict[str, Any]:
        spec = getattr(self._runtime, "spec", None)
        return {
            "component": "ModelRuntimeGenerationAdapter",
            "configured": self._runtime is not None and spec is not None,
            "enabled": self.enabled,
            "loaded": bool(getattr(self._runtime, "loaded", False)),
            "provider": "litertlm_local",
            "model": getattr(spec, "model_id", None),
            "offline_only": True,
            "remote_fallback": False,
            "tool_calls_enabled": False,
            "streaming_enabled": False,
            "conversation_persisted": False,
            "operationally_verified": False,
        }

    @classmethod
    def _validate_messages(cls, messages: Any) -> list[dict[str, str]]:
        if not isinstance(messages, list) or not 1 <= len(messages) <= cls.MAX_MESSAGES:
            raise ValueError("messages deve conter de 1 a 32 mensagens.")
        total = 0
        validated: list[dict[str, str]] = []
        for item in messages:
            if not isinstance(item, dict):
                raise ValueError("mensagem inválida.")
            role = item.get("role")
            if not isinstance(role, str) or role not in {
                "system", "user", "assistant"
            }:
                raise ValueError("role inválido.")
            content = item.get("content")
            if (
                not isinstance(content, str)
                or not content.strip()
                or len(content) > cls.MAX_MESSAGE_CHARS
            ):
                raise ValueError("conteúdo de mensagem inválido ou excessivo.")
            total += len(content)
            validated.append({"role": role, "content": content})
        if total > cls.MAX_TOTAL_CHARS:
            raise ValueError("contexto total excede o limite de 50000 caracteres.")
        if validated[-1]["role"] != "user":
            raise ValueError("a última mensagem precisa ser do usuário.")
        seen_conversation_turn = False
        for item in validated:
            if item["role"] == "system" and seen_conversation_turn:
                raise ValueError("mensagens system precisam preceder o histórico da conversa.")
            if item["role"] != "system":
                seen_conversation_turn = True
        return validated

    @staticmethod
    def _serialize_messages(messages: list[dict[str, str]]) -> str:
        """Encode role/content pairs without ambiguous role-marker delimiters."""
        return json.dumps(
            {"format": "mahoraga_messages_v1", "messages": messages},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("local_model_runtime_disabled")
        if max_tokens is not None and (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= self.MAX_OUTPUT_TOKENS
        ):
            raise ValueError(
                f"max_tokens precisa estar entre 1 e {self.MAX_OUTPUT_TOKENS}."
            )
        if temperature is not None and (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not 0 <= temperature <= 2
        ):
            raise ValueError("temperature precisa estar entre 0 e 2.")
        validated = self._validate_messages(messages)
        prompt = self._serialize_messages(validated)
        spec = getattr(self._runtime, "spec", None)
        prompt_limit = getattr(spec, "max_prompt_chars", None)
        if (
            isinstance(prompt_limit, int)
            and not isinstance(prompt_limit, bool)
            and len(prompt) > prompt_limit
        ):
            raise ValueError(
                f"prompt serializado excede o limite do runtime ({prompt_limit} caracteres)."
            )
        request = self._request_factory(
            task_class=self._task_class,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        generated = self._runtime.generate(prompt, request=request)
        if not isinstance(generated, str) or not generated.strip():
            raise RuntimeError("local_model_empty_or_invalid_output")
        status = self.status()
        return {
            "status": "generated",
            "text": generated,
            "provider": status["provider"],
            "model": status["model"],
            "offline_only": True,
            "remote_fallback": False,
            "tool_calls_allowed": False,
            "execution_performed": False,
            "conversation_persisted": False,
            "usage": None,
        }
