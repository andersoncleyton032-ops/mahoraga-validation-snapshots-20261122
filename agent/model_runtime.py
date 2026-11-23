"""Loopback-only local language-model adapter.

No remote fallback, server startup, model download or tool execution occurs here.
The adapter speaks the OpenAI-compatible chat-completions subset used by
llama.cpp and compatible local runtimes.
"""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_local(request, timeout: float):
    opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
    return opener.open(request, timeout=timeout)


class LocalModelAdapter:
    VERSION = "0.1.0"
    MAX_MESSAGES = 32
    MAX_MESSAGE_CHARS = 20000
    MAX_TOTAL_CHARS = 50000
    MAX_RESPONSE_LIMIT = 2 * 1024 * 1024

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path).expanduser()
        self.config: dict[str, Any] | None = None
        self.error: str | None = None
        self._load()

    def _load(self) -> None:
        try:
            if not self.config_path.is_file():
                self.error = "model_runtime_config_missing"
                return
            if self.config_path.stat().st_size > 16 * 1024:
                self.error = "model_runtime_config_too_large"
                return
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            self._validate_config(data)
            self.config = data
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self.error = f"invalid_config:{type(exc).__name__}"

    @staticmethod
    def _validate_config(config: Any) -> None:
        if not isinstance(config, dict) or config.get("schema") != "mahoraga.local_model_runtime":
            raise ValueError("unknown model runtime schema")
        if config.get("provider") != "openai_compatible_loopback":
            raise ValueError("unsupported provider")
        if not isinstance(config.get("enabled"), bool):
            raise ValueError("enabled must be boolean")
        if config.get("allow_remote") is not False:
            raise ValueError("remote endpoints are prohibited")
        if config.get("stream") is not False or config.get("tool_calls_enabled") is not False:
            raise ValueError("streaming and tool calls are disabled in this adapter")
        base_url = config.get("base_url")
        if not isinstance(base_url, str) or len(base_url) > 240:
            raise ValueError("base_url invalid")
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
        ):
            raise ValueError("base_url must be a plain local HTTP origin")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise ValueError("base_url must use a loopback IP literal") from exc
        if not address.is_loopback:
            raise ValueError("base_url must resolve to a loopback IP literal")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("base_url port invalid") from exc
        if port is None or not 1 <= port <= 65535:
            raise ValueError("base_url must include a valid port")
        if config.get("model") is not None and (
            not isinstance(config["model"], str)
            or not config["model"].strip()
            or len(config["model"]) > 128
        ):
            raise ValueError("model invalid")
        timeout = config.get("timeout_seconds", 30)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 120:
            raise ValueError("timeout_seconds must be between 1 and 120")
        max_tokens = config.get("max_tokens", 1024)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 4096:
            raise ValueError("max_tokens must be between 1 and 4096")
        temperature = config.get("temperature", 0.7)
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        response_limit = config.get("max_response_bytes", 1048576)
        if isinstance(response_limit, bool) or not isinstance(response_limit, int):
            raise ValueError("max_response_bytes must be an integer")
        if not 1024 <= response_limit <= LocalModelAdapter.MAX_RESPONSE_LIMIT:
            raise ValueError("max_response_bytes outside permitted bounds")

    @property
    def configured(self) -> bool:
        return self.config is not None

    @property
    def enabled(self) -> bool:
        return bool(self.config and self.config.get("enabled") is True)

    def status(self) -> dict:
        return {
            "component": "LocalModelAdapter",
            "version": self.VERSION,
            "configured": self.configured,
            "enabled": self.enabled,
            "provider": "openai_compatible_loopback",
            "base_url": self.config.get("base_url") if self.config else None,
            "model": self.config.get("model") if self.config else None,
            "offline_only": True,
            "remote_fallback": False,
            "tool_calls_enabled": False,
            "streaming_enabled": False,
            "network_probe_performed": False,
            "error": self.error,
        }

    def _endpoint(self, suffix: str) -> str:
        if not self.config:
            raise RuntimeError(self.error or "model_runtime_not_configured")
        return self.config["base_url"].rstrip("/") + suffix

    @classmethod
    def _validate_messages(cls, messages: Any) -> list[dict[str, str]]:
        if not isinstance(messages, list) or not 1 <= len(messages) <= cls.MAX_MESSAGES:
            raise ValueError("messages deve conter de 1 a 32 mensagens.")
        total = 0
        result = []
        for item in messages:
            if not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant"}:
                raise ValueError("mensagem ou role inválido.")
            content = item.get("content")
            if not isinstance(content, str) or not content.strip() or len(content) > cls.MAX_MESSAGE_CHARS:
                raise ValueError("conteúdo de mensagem inválido ou excessivo.")
            total += len(content)
            result.append({"role": item["role"], "content": content})
        if total > cls.MAX_TOTAL_CHARS:
            raise ValueError("contexto total excede o limite de 50000 caracteres.")
        return result

    def _read_json(self, response) -> dict:
        limit = self.config["max_response_bytes"]
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise RuntimeError("local_model_response_too_large")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("local_model_invalid_json") from exc
        if not isinstance(data, dict):
            raise RuntimeError("local_model_invalid_response_shape")
        return data

    def health_check(self) -> dict:
        if not self.enabled:
            return {"status": "disabled", "probe_performed": False}
        request = Request(self._endpoint("/v1/models"), headers={"Accept": "application/json"})
        try:
            with _open_local(request, timeout=float(self.config["timeout_seconds"])) as response:
                data = self._read_json(response)
            models = data.get("data")
            if not isinstance(models, list):
                raise RuntimeError("local_model_invalid_models_response")
            return {
                "status": "available",
                "model_count": len(models),
                "models": [
                    item.get("id") for item in models[:20]
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                ],
                "probe_performed": True,
                "remote_network_used": False,
            }
        except HTTPError as exc:
            raise RuntimeError(f"local_model_http_error:{exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"local_model_unreachable:{type(exc).__name__}") from exc

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict:
        if not self.enabled:
            raise RuntimeError("local_model_runtime_disabled")
        messages = self._validate_messages(messages)
        if max_tokens is None:
            max_tokens = self.config["max_tokens"]
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 4096:
            raise ValueError("max_tokens deve estar entre 1 e 4096.")
        if temperature is None:
            temperature = self.config["temperature"]
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError("temperature deve estar entre 0 e 2.")

        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": float(temperature),
            "stream": False,
        }
        if self.config.get("model"):
            payload["model"] = self.config["model"]
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._endpoint("/v1/chat/completions"),
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with _open_local(request, timeout=float(self.config["timeout_seconds"])) as response:
                data = self._read_json(response)
        except HTTPError as exc:
            raise RuntimeError(f"local_model_http_error:{exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"local_model_unreachable:{type(exc).__name__}") from exc

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise RuntimeError("local_model_missing_choices")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("local_model_missing_text_content")
        return {
            "status": "generated",
            "text": content,
            "provider": "openai_compatible_loopback",
            "model": data.get("model") or self.config.get("model"),
            "offline_only": True,
            "remote_fallback": False,
            "tool_calls_allowed": False,
            "usage": data.get("usage") if isinstance(data.get("usage"), dict) else None,
            "execution_performed": False,
            "conversation_persisted": False,
        }
