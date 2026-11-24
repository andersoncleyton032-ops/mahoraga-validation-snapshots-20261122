"""Read-only structural observer for the Mahoraga experimental lab.

The observer builds a bounded, deterministic inventory from Python source.
Its findings are static signals, not proof of runtime behavior or test coverage.
It never imports project modules, executes inspected code, or writes to disk.
"""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
from typing import Any


class ArchitectureObservationError(ValueError):
    """Invalid root, limits, or inspection request."""


class ArchitectureObserver:
    VERSION = "0.1.0"
    SCAN_DIRECTORIES = ("agent", "experiments", "tests")
    EXCLUDED_DIRECTORIES = {
        ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
        "build", "dist", "node_modules",
    }
    DEFAULT_MAX_FILES = 512
    DEFAULT_MAX_FILE_BYTES = 1_000_000

    def __init__(
        self,
        root: str | Path,
        *,
        max_files: int = DEFAULT_MAX_FILES,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> None:
        self.root = self._validate_root(root)
        self.max_files = self._limit(max_files, "max_files", 1, 4096)
        self.max_file_bytes = self._limit(
            max_file_bytes, "max_file_bytes", 1, 4_000_000
        )

    @staticmethod
    def _limit(value: Any, name: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ArchitectureObservationError(f"{name} must be an integer")
        if not minimum <= value <= maximum:
            raise ArchitectureObservationError(f"{name} is outside permitted bounds")
        return value

    @staticmethod
    def _validate_root(root: str | Path) -> Path:
        try:
            resolved = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ArchitectureObservationError("inspection root is not accessible") from exc
        if not resolved.is_dir():
            raise ArchitectureObservationError("inspection root must be a directory")
        return resolved

    def _python_files(self) -> tuple[list[Path], bool]:
        found: list[Path] = []
        truncated = False
        for directory in self.SCAN_DIRECTORIES:
            start = self.root / directory
            if not start.is_dir() or start.is_symlink():
                continue
            for current, dirs, files in os.walk(start, topdown=True, followlinks=False):
                current_path = Path(current)
                dirs[:] = sorted(
                    name for name in dirs
                    if name not in self.EXCLUDED_DIRECTORIES
                    and not (current_path / name).is_symlink()
                )
                for filename in sorted(files):
                    path = current_path / filename
                    if path.suffix != ".py" or path.is_symlink():
                        continue
                    try:
                        path.resolve(strict=True).relative_to(self.root)
                    except (OSError, RuntimeError, ValueError):
                        continue
                    found.append(path)
                    if len(found) > self.max_files:
                        truncated = True
                        return found[:self.max_files], truncated
        return sorted(found), truncated

    @staticmethod
    def _module_name(root: Path, path: Path) -> str:
        relative = path.relative_to(root).with_suffix("")
        parts = list(relative.parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    @staticmethod
    def _internal_imports(
        tree: ast.AST, module_name: str, known_modules: set[str]
    ) -> set[str]:
        package = module_name.rpartition(".")[0]
        discovered: set[str] = set()

        def add_candidate(candidate: str) -> None:
            candidate = candidate.strip(".")
            if not candidate:
                return
            parts = candidate.split(".")
            for end in range(len(parts), 0, -1):
                prefix = ".".join(parts[:end])
                if prefix in known_modules:
                    discovered.add(prefix)
                    return

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    add_candidate(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base_parts = package.split(".") if package else []
                    trim = max(0, node.level - 1)
                    if trim:
                        base_parts = base_parts[:-trim] if trim <= len(base_parts) else []
                    if node.module:
                        base_parts.extend(node.module.split("."))
                    base = ".".join(base_parts)
                    add_candidate(base)
                    for alias in node.names:
                        if alias.name != "*":
                            add_candidate(".".join(part for part in (base, alias.name) if part))
                elif node.module:
                    base = node.module
                    add_candidate(base)
                    for alias in node.names:
                        if alias.name != "*":
                            add_candidate(base + "." + alias.name)
        return discovered

    @staticmethod
    def _cycles(graph: dict[str, list[str]]) -> list[list[str]]:
        index = 0
        stack: list[str] = []
        on_stack: set[str] = set()
        indices: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        components: list[list[str]] = []

        def visit(node: str) -> None:
            nonlocal index
            indices[node] = index
            lowlinks[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)
            for neighbor in graph.get(node, []):
                if neighbor not in indices:
                    visit(neighbor)
                    lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
                elif neighbor in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[neighbor])
            if lowlinks[node] == indices[node]:
                component: list[str] = []
                while stack:
                    item = stack.pop()
                    on_stack.remove(item)
                    component.append(item)
                    if item == node:
                        break
                if len(component) > 1 or node in graph.get(node, []):
                    components.append(sorted(component))

        for node in sorted(graph):
            if node not in indices:
                visit(node)
        return sorted(components)

    def inspect(self) -> dict[str, Any]:
        paths, truncated = self._python_files()
        module_names = {self._module_name(self.root, path) for path in paths}
        known_modules = set(module_names)
        files: list[dict[str, Any]] = []
        graph: dict[str, list[str]] = {}
        parse_errors: list[dict[str, str]] = []
        oversized: list[str] = []
        test_imports: set[str] = set()
        agent_modules: set[str] = set()

        for path in paths:
            relative = path.relative_to(self.root).as_posix()
            module = self._module_name(self.root, path)
            if relative.startswith("agent/"):
                agent_modules.add(module)
            try:
                stat = path.stat()
                if stat.st_size > self.max_file_bytes:
                    oversized.append(relative)
                    files.append({
                        "path": relative, "module": module, "status": "skipped_size",
                        "size_bytes": stat.st_size,
                    })
                    graph[module] = []
                    continue
                content = path.read_bytes()
                source = content.decode("utf-8")
                tree = ast.parse(source, filename=relative)
            except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
                parse_errors.append({
                    "path": relative,
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:240],
                })
                files.append({"path": relative, "module": module, "status": "parse_error"})
                graph[module] = []
                continue

            imports = sorted(self._internal_imports(tree, module, known_modules))
            graph[module] = imports
            if relative.startswith("tests/"):
                test_imports.update(imports)
            classes = sorted(
                node.name for node in tree.body if isinstance(node, ast.ClassDef)
            )
            functions = sorted(
                node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            files.append({
                "path": relative,
                "module": module,
                "status": "parsed",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "imports": imports,
                "top_level_classes": classes,
                "top_level_functions": functions,
            })

        unreferenced_by_tests = sorted(agent_modules - test_imports)
        cycles = self._cycles(graph)
        findings: list[dict[str, str]] = []
        for item in parse_errors:
            findings.append({
                "kind": "source_parse_error",
                "subject": item["path"],
                "evidence": item["error_type"],
                "confidence": "direct_observation",
            })
        for path in oversized:
            findings.append({
                "kind": "source_not_inspected_size_limit",
                "subject": path,
                "evidence": "file_exceeds_configured_byte_limit",
                "confidence": "direct_observation",
            })
        for module in unreferenced_by_tests:
            findings.append({
                "kind": "agent_module_without_detected_direct_test_import",
                "subject": module,
                "evidence": "static_import_graph_did_not_find_test_reference",
                "confidence": "heuristic",
            })
        for component in cycles:
            findings.append({
                "kind": "internal_import_cycle",
                "subject": ", ".join(component),
                "evidence": "strongly_connected_component_in_static_import_graph",
                "confidence": "static_analysis",
            })

        return {
            "schema": "mahoraga.architecture_observation",
            "schema_version": 1,
            "observer_version": self.VERSION,
            "status": "partial" if truncated or parse_errors or oversized else "completed",
            "root_name": self.root.name,
            "scan_scope": list(self.SCAN_DIRECTORIES),
            "limits": {
                "max_files": self.max_files,
                "max_file_bytes": self.max_file_bytes,
            },
            "inventory": {
                "files_seen": len(files),
                "parsed_files": sum(item["status"] == "parsed" for item in files),
                "parse_errors": len(parse_errors),
                "oversized_files": len(oversized),
                "truncated": truncated,
                "modules": sorted(module_names),
                "dependency_graph": {
                    key: graph[key] for key in sorted(graph)
                },
            },
            "findings": findings,
            "files": files,
            "interpretation_limits": [
                "Static imports do not capture dynamic imports, runtime dependency injection or reflection.",
                "A missing direct test import is not proof that a module is untested.",
                "Import cycles are structural signals and require runtime/contextual review.",
                "The observer does not import, execute, modify or install project code.",
                "This report is not a complete architectural model or a security certification.",
            ],
            "execution_performed": False,
            "filesystem_modified": False,
            "network_accessed": False,
        }


def inspect_architecture(
    root: str | Path,
    *,
    max_files: int = ArchitectureObserver.DEFAULT_MAX_FILES,
    max_file_bytes: int = ArchitectureObserver.DEFAULT_MAX_FILE_BYTES,
) -> dict[str, Any]:
    """Convenience entry point for a bounded, read-only architecture scan."""
    return ArchitectureObserver(
        root, max_files=max_files, max_file_bytes=max_file_bytes
    ).inspect()
