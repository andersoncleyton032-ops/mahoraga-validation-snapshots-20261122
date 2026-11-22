"""Context-aware, risk-based action assessment for Mahoraga.

Unknown actions remain blocked. Read-only inspection and research are allowed;
project writes, installation, deletion, security changes and external effects
require explicit review according to scope and reversibility.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json


@dataclass(frozen=True)
class Decision:
    allowed: bool
    requires_approval: bool
    reason: str
    risk_score: int = 0
    category: str = "unknown"
    reversible: bool = True
    discovery_allowed: bool = False
    experiment_allowed: bool = False
    promotion_allowed: bool = False


class Dharma:
    VERSION = "1.1"
    SAFE_ACTIONS = {
        "read_project", "inspect_hardware", "inspect_tools",
        "introspect", "analyze_perfetto", "list_memory", "list_events",
        "research_public_information", "blender_local_task",
    }
    INTERNAL_PERSISTENCE_ACTIONS = {
        "record_learning", "record_observation", "record_experiment",
    }
    CAPABILITY_ACTIONS = {
        "read_only_capability", "local_compute",
    }
    SANDBOX_ACTIONS = {"create_sandbox_file", "run_sandbox_test"}
    APPROVAL_ACTIONS = {"modify_project", "install_package", "delete_data", "network_access",
        "android_permission", "publish_product", "send_message", "external_purchase",
        "modify_user_data", "run_unverified_tool", "blender_python_execute"}
    PROTECTED_ACTIONS = {"modify_core", "modify_policy", "disable_security", "root_device",
        "unlock_bootloader", "change_selinux", "execute_exploit"}

    def __init__(
        self, project_root: str | Path | None = None, approval_verifier=None
    ):
        self.project_root = Path(project_root or Path(__file__).resolve().parent.parent).resolve()
        self.sandbox_root = self.project_root / "sandbox"
        self.approval_verifier = approval_verifier

    def _valid_sandbox_target(self, target) -> bool:
        if not isinstance(target, str) or not target or "\x00" in target or "\\" in target:
            return False
        parts = target.split("/")
        if len(parts) < 3 or parts[0] != "sandbox" or any(p in ("", ".", "..") for p in parts):
            return False
        relative = Path(target)
        if relative.is_absolute() or self.sandbox_root.is_symlink() or not self.sandbox_root.is_dir():
            return False
        current = self.project_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        try:
            return current.resolve(strict=False).is_relative_to(self.sandbox_root.resolve())
        except (OSError, RuntimeError):
            return False

    def evaluate(self, action, target="", context: dict | None = None) -> Decision:
        context = context if isinstance(context, dict) else {}
        if not isinstance(action, str) or not action:
            return Decision(False, False, "Ação inválida.", 100, "invalid", False)
        if action == "blender_python_execute":
            scope = context.get("scope")
            attestation = context.get("approval_attestation")
            approval_payload = context.get("approval_payload")
            verifier = self.approval_verifier
            consume = getattr(verifier, "consume_attestation", None)
            try:
                if not isinstance(approval_payload, dict):
                    raise ValueError("approval_payload ausente.")
                canonical = json.dumps(
                    {
                        "action": action,
                        "target": target,
                        "scope": scope,
                        "payload": approval_payload,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                subject_sha256 = hashlib.sha256(canonical).hexdigest()
                consumed = (
                    consume(
                        attestation=attestation,
                        action=action,
                        subject_sha256=subject_sha256,
                    )
                    if callable(consume) and attestation is not None
                    else False
                )
            except Exception:
                consumed = False
            if scope == "blender_python" and consumed is True:
                return Decision(
                    True, False,
                    "Execução Python no Blender autorizada por atestado verificado e consumido.",
                    80, "attested-execution", False,
                )
            return Decision(
                False, True,
                "Execução Python bloqueada: exige atestado humano verificável, vinculado ao conteúdo e de uso único.",
                80, "approval-required", False,
            )
        if action in self.PROTECTED_ACTIONS:
            return Decision(False, True, "Ação protegida; exige análise e autorização humana explícita.",
                            100, "protected", False)
        if action in self.INTERNAL_PERSISTENCE_ACTIONS:
            flags = ("external_side_effect", "writes_project", "deletes_data",
                     "sensitive_data", "irreversible")
            raised = [flag for flag in flags if context.get(flag)]
            if raised:
                return Decision(
                    False, True,
                    "Persistência com contexto elevado: " + ", ".join(raised),
                    65 if "irreversible" not in raised else 90,
                    "context-escalated",
                    not context.get("irreversible", False),
                )
            return Decision(
                True, False,
                "Persistência interna controlada permitida.",
                8, "internal_persistence", True,
            )
        if action in self.CAPABILITY_ACTIONS:
            flags = (
                "external_side_effect", "writes_project", "deletes_data",
                "sensitive_data", "irreversible",
            )
            raised = [flag for flag in flags if context.get(flag)]
            if raised:
                return Decision(
                    False, True,
                    "Capacidade com contexto elevado: " + ", ".join(raised),
                    65 if "irreversible" not in raised else 90,
                    "context-escalated",
                    not context.get("irreversible", False),
                )
            if action == "read_only_capability":
                return Decision(
                    True, False,
                    "Capacidade de consulta sem efeitos colaterais permitida.",
                    5, "capability-read-only", True,
                    discovery_allowed=True,
                )
            return Decision(
                True, False,
                "Computação local controlada permitida.",
                20, "local-compute", True,
                discovery_allowed=True,
                experiment_allowed=True,
            )
        if action in self.SAFE_ACTIONS:
            # Context can raise risk; it cannot silently lower the base risk.
            flags = ("external_side_effect", "writes_project", "deletes_data", "sensitive_data", "irreversible")
            raised = [flag for flag in flags if context.get(flag)]
            if raised:
                return Decision(False, True, "Contexto elevou o risco: " + ", ".join(raised),
                                65 if "irreversible" not in raised else 90, "context-escalated",
                                not context.get("irreversible", False))
            return Decision(True, False, "Inspeção/pesquisa de baixo risco permitida.", 5, "read-only", True)
        if action in self.SANDBOX_ACTIONS:
            if self._valid_sandbox_target(target):
                return Decision(
                    True, False,
                    "Ação confinada ao laboratório validada.",
                    15, "sandbox", True,
                    discovery_allowed=True,
                    experiment_allowed=True,
                )
            return Decision(False, True, "Destino fora do laboratório, inválido ou com link simbólico.",
                            70, "sandbox-boundary", False)
        if action in self.APPROVAL_ACTIONS:
            return Decision(False, True, "Ação com efeitos externos ou alteração persistente exige aprovação.",
                            70, "approval-required", action not in {"delete_data", "external_purchase"})
        return Decision(
            False, False,
            "Execução desconhecida bloqueada; investigação permitida.",
            100, "unknown", False,
            discovery_allowed=True,
        )
