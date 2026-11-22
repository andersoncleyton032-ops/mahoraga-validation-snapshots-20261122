"""Evidence-based discovery and competence registry for local tools.

Discovery is read-only. This module never runs arbitrary discovered executables.
"""
from __future__ import annotations
import importlib.metadata
import os
import re
import shutil
import subprocess
from pathlib import Path
from .memory import get_store


class ToolIntelligence:
    VERSION = "1.1"
    COMMANDS = ("python3", "git", "clang", "gcc", "make", "adb", "rish",
        "termux-battery-status", "vulkaninfo", "trace_processor_shell", "sqlite3",
        "curl", "wget", "pkg", "pip", "ffmpeg", "blender", "node", "java", "gradle")
    COMPETENCE_LEVELS = ("identified", "studied", "experimented", "operational", "specialized", "improver")

    def __init__(self, store=None):
        self.store = store or get_store()

    def discover(self, include_python_packages: bool = True) -> dict:
        found = []
        for command in self.COMMANDS:
            path = shutil.which(command)
            if command == "rish" and not path:
                candidate = Path.home() / "bin" / "rish"
                path = str(candidate) if candidate.is_file() and candidate.stat().st_mode & 0o111 else None
            if path:
                tool_id = f"command:{command}"
                self.store.upsert_tool(tool_id, command, path, source="PATH discovery",
                    competence="identified", metadata={"interface": "cli"})
                found.append({"tool_id": tool_id, "name": command, "path": path,
                              "competence": "identified", "interface": "cli"})
        termux_packages = []
        if shutil.which("pkg") and os.environ.get("PREFIX", "").endswith("/com.termux/files/usr"):
            try:
                result = subprocess.run(["pkg", "list-installed"], capture_output=True,
                    text=True, timeout=12, check=False, env={**os.environ, "LC_ALL": "C"})
                for line in result.stdout.splitlines():
                    match = re.match(r"^([^/\s]+)/[^,]+,now\s+(\S+)", line.strip())
                    if not match:
                        continue
                    name, version = match.groups()
                    tool_id = f"termux-package:{name}:{version}"
                    self.store.upsert_tool(tool_id, name, None, version=version,
                        source="pkg list-installed", competence="identified",
                        metadata={"interface": "termux-package", "package": name})
                    termux_packages.append({"tool_id": tool_id, "name": name, "version": version})
            except (OSError, subprocess.TimeoutExpired):
                pass
        packages = []
        if include_python_packages:
            for distribution in importlib.metadata.distributions():
                name = distribution.metadata.get("Name") or "unknown"
                version = distribution.version
                tool_id = f"python-package:{name.lower().replace('_', '-') }"
                self.store.upsert_tool(tool_id, name, None, version=version,
                    source="Python distribution metadata", competence="identified",
                    metadata={"interface": "python-library"})
                packages.append({"tool_id": tool_id, "name": name, "version": version,
                                 "competence": "identified"})
        self.store.record_event("tools.discovery", {"commands": len(found),
            "termux_packages": len(termux_packages), "python_packages": len(packages)})
        return {"version": self.VERSION, "commands": found, "termux_packages": termux_packages,
                "python_packages": packages,
                "note": "Presença detectada não significa domínio operacional."}

    def register_study(self, tool_id: str, evidence: list[str]) -> None:
        self.store.update_tool_competence(tool_id, "studied", evidence)

    def register_experiment(self, tool_id: str, evidence: list[str]) -> None:
        self.store.update_tool_competence(tool_id, "experimented", evidence)

    def register_operational(self, tool_id: str, evidence: list[str]) -> None:
        self.store.update_tool_competence(tool_id, "operational", evidence)

    def register_specialized(self, tool_id: str, evidence: list[str]) -> None:
        self.store.update_tool_competence(tool_id, "specialized", evidence)

    def register_improver(self, tool_id: str, evidence: list[str]) -> None:
        self.store.update_tool_competence(tool_id, "improver", evidence)

    def catalog(self) -> list[dict]:
        return self.store.list_tools()
