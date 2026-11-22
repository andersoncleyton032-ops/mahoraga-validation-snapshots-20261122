from dataclasses import dataclass
from pathlib import Path


@dataclass
class Decision:
    allowed: bool
    requires_approval: bool
    reason: str


class Dharma:
    VERSION = "0.1"

    SAFE_ACTIONS = {
        "read_project",
        "record_learning",
    }

    SANDBOX_ACTIONS = {
        "create_sandbox_file",
        "run_sandbox_test",
    }

    APPROVAL_ACTIONS = {
        "modify_project",
        "install_package",
        "delete_data",
        "network_access",
        "android_permission",
    }

    PROTECTED_ACTIONS = {
        "modify_core",
        "modify_policy",
        "disable_security",
    }


    def _valid_sandbox_target(self, target):
        if not isinstance(target, str) or not target:
            return False
        if "\x00" in target or "\\" in target:
            return False

        parts = target.split("/")

        if any(part in ("", ".", "..") for part in parts):
            return False
        if len(parts) < 3 or parts[0] != "sandbox":
            return False

        relative = Path(target)

        if relative.is_absolute():
            return False

        project_root = Path(__file__).resolve().parent.parent
        sandbox_root = project_root / "sandbox"

        if sandbox_root.is_symlink() or not sandbox_root.is_dir():
            return False

        current = project_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False

        try:
            return current.resolve(strict=False).is_relative_to(
                sandbox_root.resolve()
            )
        except (OSError, RuntimeError):
            return False

    def evaluate(self, action, target=""):
        if action in self.PROTECTED_ACTIONS:
            return Decision(
                False, True,
                "Alteracao protegida. Requer avaliacao humana."
            )

        if action in self.SAFE_ACTIONS:
            return Decision(
                True, False,
                "Acao de baixo risco autorizada."
            )

        if action in self.SANDBOX_ACTIONS:
            if self._valid_sandbox_target(target):
                return Decision(
                    True, False,
                    "Acao permitida dentro do laboratorio."
                )

            return Decision(
                False, True,
                "Destino fora do laboratorio ou invalido."
            )

        if action in self.APPROVAL_ACTIONS:
            return Decision(
                False, True,
                "Aprovacao humana necessaria."
            )

        return Decision(
            False, False,
            "Acao desconhecida. Bloqueada por seguranca."
        )
