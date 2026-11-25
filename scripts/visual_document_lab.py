"""Headless VisualDocumentLab: author, persist, compile and gate visual tasks.

The lab never enables capabilities and never calls a renderer unless --execute
is explicitly supplied and the existing VisualBackendSelector selects a backend.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

if TYPE_CHECKING:
    from agent.integration_core import IntegratedCore

from agent.visual_creation import (
    TransformSpec,
    VisualDocumentEditor,
    VisualDocumentSpec,
    VisualElementSpec,
    VisualLayerSpec,
)
from agent.visual_scene_compiler import compile_visual_image_task


class VisualDocumentLab:
    """A thin orchestration harness over Mahoraga's existing shared components."""

    def __init__(self, core: IntegratedCore):
        self.core = core

    def create_demo(self, document_id: str) -> dict[str, Any]:
        if self.core.visual_documents.get(document_id) is not None:
            raise ValueError(f"O documento {document_id!r} já existe; não será sobrescrito.")

        document = VisualDocumentSpec(
            document_id=document_id,
            title="VisualDocumentLab — cena de validação",
            coordinate_space="3d",
            canvas_width=64,
            canvas_height=64,
            layers=(VisualLayerSpec("layer.main", "Main", 0, "geometry"),),
            metadata={"created_by": "visual_document_lab", "purpose": "headless_validation"},
        )
        saved = self.core.visual_documents.save(document)

        camera = VisualElementSpec(
            element_id="camera.main",
            kind="camera",
            layer_id="layer.main",
            name="Camera",
            data={"origin": [0.0, 0.0, 5.0], "target": [0.0, 0.0, 0.0]},
        )
        document = VisualDocumentEditor.add_element(document, camera)
        saved = self.core.visual_documents.save(
            document, expected_parent_sha256=saved.sha256,
        )

        sphere = VisualElementSpec(
            element_id="element.sphere",
            kind="shape",
            layer_id="layer.main",
            name="Validation sphere",
            role="primary_subject",
            transform=TransformSpec(),
            data={"primitive": "sphere", "radius": 0.8, "albedo": [0.25, 0.55, 0.8]},
        )
        document = VisualDocumentEditor.add_element(document, sphere)
        saved = self.core.visual_documents.save(
            document, expected_parent_sha256=saved.sha256,
        )
        return self._stored_payload(saved)

    def edit_transform(
        self, document_id: str, element_id: str, translation: tuple[float, float, float],
    ) -> dict[str, Any]:
        current = self.core.visual_documents.get(document_id)
        if current is None:
            raise ValueError(f"Documento {document_id!r} não encontrado.")
        element = next(
            (item for item in current.document.elements if item.element_id == element_id),
            None,
        )
        if element is None:
            raise ValueError(f"Elemento {element_id!r} não encontrado.")
        transform = TransformSpec(
            translation=translation,
            rotation_degrees=element.transform.rotation_degrees,
            scale=element.transform.scale,
        )
        edited = VisualDocumentEditor.set_element_transform(
            current.document, element_id, transform,
        )
        saved = self.core.visual_documents.save(
            edited, expected_parent_sha256=current.sha256,
        )
        return self._stored_payload(saved)

    @staticmethod
    def _stored_payload(stored: Any) -> dict[str, Any]:
        return {
            "document_id": stored.document.document_id,
            "revision": stored.revision,
            "sha256": stored.sha256,
            "parent_sha256": stored.parent_sha256,
            "status": stored.status,
            "layer_count": len(stored.document.layers),
            "element_count": len(stored.document.elements),
        }

    def inspect(self, document_id: str) -> dict[str, Any]:
        stored = self.core.visual_documents.get(document_id)
        if stored is None:
            raise ValueError(f"Documento {document_id!r} não encontrado.")
        return {
            **self._stored_payload(stored),
            "schema": stored.document.SCHEMA,
            "document": stored.document.to_dict(),
            "revisions": list(self.core.visual_documents.list_revisions(document_id)),
        }

    def run(
        self,
        document_id: str,
        *,
        task_id: str,
        width: int = 64,
        height: int = 64,
        seed: int = 0,
        execute: bool = False,
        estimated_ram_mb: float | None = None,
        estimated_seconds: float | None = None,
    ) -> dict[str, Any]:
        stored = self.core.visual_documents.get(document_id)
        if stored is None:
            raise ValueError(f"Documento {document_id!r} não encontrado.")

        compiled = compile_visual_image_task(
            stored.document,
            task_id=task_id,
            width=width,
            height=height,
            seed=seed,
        )
        selection = (
            self.core.inspect_visual_backend_selection(compiled.task_spec)
            if compiled.task_spec is not None else None
        )
        execution: dict[str, Any] = {
            "status": "not_requested",
            "execution_performed": False,
        }

        if execute:
            if compiled.task_spec is None or compiled.scene is None:
                execution = {
                    "status": "compile_blocked",
                    "execution_performed": False,
                }
            elif not isinstance(selection, dict) or selection.get("status") != "selected":
                execution = {
                    "status": "backend_not_governed",
                    "reason": "visual_backend_selector_did_not_select_a_backend",
                    "execution_performed": False,
                }
            elif estimated_ram_mb is None or estimated_seconds is None:
                raise ValueError(
                    "--execute exige --estimated-ram-mb e --estimated-seconds explícitos."
                )
            else:
                execution = self.core.execute_image_task(
                    compiled.task_spec,
                    compiled.scene,
                    estimated_ram_mb=estimated_ram_mb,
                    estimated_seconds=estimated_seconds,
                    visual_provenance=compiled.render_provenance(),
                )

        return {
            "document": self._stored_payload(stored),
            "compile": {
                "status": compiled.status,
                "source_document_sha256": compiled.source_document_sha256,
                "scene_spec_sha256": compiled.scene_spec_sha256,
                "task_spec": (
                    compiled.task_spec.to_dict()
                    if compiled.task_spec is not None else None
                ),
                "unsupported_element_ids": list(compiled.unsupported_element_ids),
                "skipped_hidden_element_ids": list(compiled.skipped_hidden_element_ids),
                "element_bindings": [list(pair) for pair in compiled.element_bindings],
                "execution_started": compiled.execution_started,
                "reason": compiled.reason,
                "render_provenance": (
                    compiled.render_provenance().to_dict()
                    if compiled.status == "ready_for_governed_executor" else None
                ),
            },
            "backend_selection": selection,
            "execution": execution,
            "capability_activation_performed": False,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_REPOSITORY_ROOT)
    parser.add_argument("--database", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-demo", help="create a versioned camera+sphere document")
    create.add_argument("--document-id", default="lab.visual.demo")

    edit = commands.add_parser("edit-transform", help="append a transform revision")
    edit.add_argument("--document-id", default="lab.visual.demo")
    edit.add_argument("--element-id", default="element.sphere")
    edit.add_argument("--x", type=float, required=True)
    edit.add_argument("--y", type=float, required=True)
    edit.add_argument("--z", type=float, required=True)

    inspect = commands.add_parser("inspect", help="inspect a document and its revision history")
    inspect.add_argument("--document-id", default="lab.visual.demo")

    run = commands.add_parser("run", help="compile and inspect the governed backend gate")
    run.add_argument("--document-id", default="lab.visual.demo")
    run.add_argument("--task-id", default="task.visual.lab")
    run.add_argument("--width", type=int, default=64)
    run.add_argument("--height", type=int, default=64)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--execute", action="store_true")
    run.add_argument("--estimated-ram-mb", type=float)
    run.add_argument("--estimated-seconds", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from agent.integration_core import IntegratedCore
    from agent.store import KnowledgeStore
    root = args.root.expanduser().resolve()
    database = args.database.expanduser().resolve()
    core = IntegratedCore(root=root, store=KnowledgeStore(database))
    lab = VisualDocumentLab(core)

    if args.command == "create-demo":
        result = lab.create_demo(args.document_id)
    elif args.command == "edit-transform":
        result = lab.edit_transform(
            args.document_id, args.element_id, (args.x, args.y, args.z),
        )
    elif args.command == "inspect":
        result = lab.inspect(args.document_id)
    else:
        result = lab.run(
            args.document_id,
            task_id=args.task_id,
            width=args.width,
            height=args.height,
            seed=args.seed,
            execute=args.execute,
            estimated_ram_mb=args.estimated_ram_mb,
            estimated_seconds=args.estimated_seconds,
        )

    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
