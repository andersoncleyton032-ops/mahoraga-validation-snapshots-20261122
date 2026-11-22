"""Especialidade de autoconhecimento e inspeção do Blender."""

from __future__ import annotations

from typing import Any


class BlenderIntelligenceError(ValueError):
    """Erro de validação da inteligência Blender."""


class BlenderIntelligence:
    VERSION = "0.1.0"

    MAX_OBJECTS = 5000
    MAX_ITEMS = 10000
    MAX_TEXT = 240

    DOMAINS = {
        "internal_structure": "API, dados internos, contexto e operadores",
        "mesh_topology": "vértices, arestas, faces, normais e atributos",
        "geometry": "geometria, modificadores e Geometry Nodes",
        "materials": "materiais, shaders, nós e texturas",
        "uv_mapping": "UVs e organização de mapas",
        "characters": "armatures, rigging e animação",
        "physics": "simulações e sistemas físicos",
        "scene": "objetos, coleções, câmeras e iluminação",
        "rendering": "motores e configurações de renderização",
        "scripting": "Python API e automação autorizada",
        "project_management": "arquivos, dependências e organização"
    }

    LIMITATIONS = [
        "O catálogo de áreas não comprova domínio dessas especialidades.",
        "A inspeção depende dos dados efetivamente enviados pelo Blender.",
        "Campos ausentes não são tratados como valores zero.",
        "A análise não modifica cenas, objetos ou arquivos.",
        "Não há aprendizagem neural nesta versão.",
        "A demonstração utiliza uma cena simulada, não o Blender real."
    ]

    def __init__(self, bridge=None, cognitive=None):
        self.bridge = bridge
        self.cognitive = cognitive

    @staticmethod
    def _text(value, field="valor"):
        if not isinstance(value, str):
            raise BlenderIntelligenceError(
                f"{field} deve ser texto."
            )

        value = " ".join(value.strip().split())

        if not value or len(value) > BlenderIntelligence.MAX_TEXT:
            raise BlenderIntelligenceError(
                f"{field} vazio ou acima do limite."
            )

        return value

    @staticmethod
    def _items(value):
        if not isinstance(value, (list, tuple)):
            return None

        if len(value) > BlenderIntelligence.MAX_ITEMS:
            raise BlenderIntelligenceError(
                "Coleção excede o limite de inspeção."
            )

        return value

    @staticmethod
    def _count(value):
        if isinstance(value, bool):
            return None

        if isinstance(value, int) and value >= 0:
            return value

        if isinstance(value, (list, tuple)):
            return len(value)

        return None

    @classmethod
    def _first_count(cls, sources, aliases):
        for source in sources:
            if not isinstance(source, dict):
                continue

            for key in aliases:
                if key in source:
                    result = cls._count(source[key])

                    if result is not None:
                        return result

        return None

    @staticmethod
    def _first_value(sources, aliases):
        for source in sources:
            if not isinstance(source, dict):
                continue

            for key in aliases:
                value = source.get(key)

                if value is not None:
                    return value

        return None

    def _mesh_summary(self, obj):
        data = obj.get("data")
        mesh = obj.get("mesh")

        sources = [
            mesh if isinstance(mesh, dict) else {},
            data if isinstance(data, dict) else {},
            obj
        ]

        counts = {
            "vertices": self._first_count(
                sources, ("vertices", "vertex_count", "verts")
            ),
            "edges": self._first_count(
                sources, ("edges", "edge_count")
            ),
            "faces": self._first_count(
                sources, ("faces", "face_count", "polygons")
            )
        }

        available = [
            key for key, value in counts.items()
            if value is not None
        ]

        missing = [
            key for key, value in counts.items()
            if value is None
        ]

        return {
            "name": str(obj.get("name", "objeto sem nome"))[:self.MAX_TEXT],
            "counts": counts,
            "available_fields": available,
            "missing_fields": missing,
            "topology_status": (
                "complete" if not missing
                else "partial" if available
                else "unavailable"
            )
        }

    def analyze_snapshot(self, snapshot, persist=False):
        """Analisa um relatório estruturado recebido como entrada."""

        if not isinstance(snapshot, dict):
            raise BlenderIntelligenceError(
                "O relatório do Blender deve ser um objeto."
            )

        scene = snapshot.get("scene")
        if not isinstance(scene, dict):
            scene = {}

        raw_objects = self._first_value(
            [snapshot, scene], ("objects",)
        )

        objects = self._items(raw_objects)

        if objects is None:
            raise BlenderIntelligenceError(
                "O relatório não contém uma lista de objetos reconhecível."
            )

        if len(objects) > self.MAX_OBJECTS:
            raise BlenderIntelligenceError(
                "Quantidade de objetos acima do limite."
            )

        type_counts = {}
        mesh_summaries = []
        modifier_counts = {}
        material_names = set()

        for obj in objects:
            if not isinstance(obj, dict):
                continue

            object_type = self._first_value(
                [obj], ("type", "object_type", "bl_type")
            )

            if isinstance(object_type, str):
                object_type = object_type.upper()
                type_counts[object_type] = (
                    type_counts.get(object_type, 0) + 1
                )

            if object_type == "MESH":
                mesh_summaries.append(self._mesh_summary(obj))

            modifiers = self._items(obj.get("modifiers"))

            if modifiers is not None:
                for modifier in modifiers:
                    if isinstance(modifier, dict):
                        name = modifier.get(
                            "type", modifier.get("name")
                        )

                        if isinstance(name, str):
                            modifier_counts[name] = (
                                modifier_counts.get(name, 0) + 1
                            )

            materials = self._items(obj.get("materials"))

            if materials is not None:
                for material in materials:
                    if isinstance(material, str):
                        material_names.add(material)
                    elif isinstance(material, dict):
                        name = material.get("name")
                        if isinstance(name, str):
                            material_names.add(name)

        mesh_totals = {
            "vertices": 0,
            "edges": 0,
            "faces": 0
        }

        known_totals = {key: 0 for key in mesh_totals}
        missing_mesh_fields = {key: 0 for key in mesh_totals}

        for mesh in mesh_summaries:
            for key, value in mesh["counts"].items():
                if value is None:
                    missing_mesh_fields[key] += 1
                else:
                    mesh_totals[key] += value
                    known_totals[key] += 1

        collections = self._first_value(
            [snapshot, scene], ("collections",)
        )
        collections = self._items(collections)

        materials_data = self._first_value(
            [snapshot, scene], ("materials",)
        )
        materials_data = self._items(materials_data)

        report = {
            "component": "BlenderIntelligence",
            "version": self.VERSION,
            "status": "analyzed",
            "evidence_source": "provided_snapshot",
            "live_blender_verified": False,
            "blender_version": snapshot.get(
                "blender_version", snapshot.get("version")
            ),
            "scene": {
                "object_count": len(objects),
                "object_types": type_counts,
                "mesh_count": len(mesh_summaries),
                "camera_count": type_counts.get("CAMERA", 0),
                "light_count": type_counts.get("LIGHT", 0),
                "collection_count": (
                    len(collections)
                    if collections is not None else None
                ),
                "material_count": (
                    len(materials_data)
                    if materials_data is not None
                    else len(material_names)
                    if material_names else None
                )
            },
            "meshes": {
                "known_totals": mesh_totals,
                "objects_with_known_counts": known_totals,
                "objects_with_missing_counts": missing_mesh_fields,
                "details": mesh_summaries
            },
            "modifiers": modifier_counts,
            "limitations": list(self.LIMITATIONS)
        }

        if persist:
            self._record_analysis(report)

        return report

    def request_python_execution(
        self, code, purpose="Execução solicitada pelo usuário",
        human_approved=False
    ):
        """Enfileira Python para Blender somente com aprovação por tarefa."""
        if self.bridge is None:
            raise RuntimeError("BlenderBridge não conectado.")
        if human_approved is not True:
            raise PermissionError(
                "Execução bloqueada: aprovação humana explícita obrigatória."
            )
        if not isinstance(code, str) or not code.strip():
            raise BlenderIntelligenceError("Código Python vazio ou inválido.")
        try:
            code_size = len(code.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise BlenderIntelligenceError("Código contém texto inválido.") from exc
        if code_size > 65536:
            raise BlenderIntelligenceError("Código excede o limite de 64 KB.")
        purpose = self._text(purpose, "finalidade")
        submit = getattr(self.bridge, "submit_task", None)
        if not callable(submit):
            raise RuntimeError("A ponte não oferece submit_task.")
        task_id = submit(
            "python.execute",
            {
                "code": code,
                "purpose": purpose,
                "human_approved": True,
                "approval_scope": "blender_python",
            },
        )
        return {
            "status": "queued",
            "task_id": task_id,
            "task_type": "python.execute",
            "approval": "explicit_for_this_task",
            "message": "Código enfileirado; aguardando execução no Blender.",
        }

    def collect_completed_python_execution(self, task_id, persist=False):
        """Recupera resultado da execução e registra somente seus metadados."""
        if self.bridge is None:
            raise RuntimeError("BlenderBridge não conectado.")
        if isinstance(task_id, bool) or not isinstance(task_id, int):
            raise BlenderIntelligenceError("ID de tarefa inválido.")
        queue = getattr(self.bridge, "queue", None)
        if queue is None or not callable(getattr(queue, "list_tasks", None)):
            raise RuntimeError("A fila da ponte não oferece list_tasks.")
        task = next(
            (item for item in queue.list_tasks(limit=200)
             if item.get("id") == task_id),
            None,
        )
        if task is None:
            return {"status": "not_found", "task_id": task_id}
        if task.get("task_type") != "python.execute":
            raise BlenderIntelligenceError("A tarefa não é python.execute.")
        if task.get("status") != "completed":
            return {
                "status": task.get("status", "unknown"),
                "task_id": task_id,
                "message": "A execução ainda não foi concluída.",
            }
        result = task.get("result")
        if not isinstance(result, dict):
            raise BlenderIntelligenceError("Resultado de execução inválido.")
        report = {
            "status": "completed",
            "task_id": task_id,
            "success": result.get("success") is True,
            "result": result,
            "evidence_source": "completed_blender_python_task",
            "live_blender_verified": True,
        }
        if persist:
            if self.cognitive is None:
                raise RuntimeError("Núcleo cognitivo não conectado.")
            recorder = getattr(self.cognitive, "record_observation", None)
            if not callable(recorder):
                raise RuntimeError("O núcleo não oferece record_observation.")
            recorder(
                category="blender_execution",
                subject="python_task_result",
                data={
                    "task_id": task_id,
                    "success": report["success"],
                    "evidence_source": report["evidence_source"],
                    "error": str(result.get("error", ""))[:1000],
                    "stdout": str(result.get("stdout", ""))[-2000:],
                    "scene_objects": result.get("scene_objects"),
                    "active_object": result.get("active_object"),
                },
                source="blender_intelligence",
                confidence=1.0,
                limitations=[
                    "Registro descreve uma execução; não valida a qualidade do código.",
                    "Execução Python no Blender não é sandbox do sistema operacional.",
                ],
            )
            report["memory_recorded"] = True
        else:
            report["memory_recorded"] = False
        return report

    def request_live_inspection(self):
        """Solicita uma inspeção usando a tarefa já existente na ponte."""

        if self.bridge is None:
            raise RuntimeError("BlenderBridge não conectado.")

        submit = getattr(self.bridge, "submit_task", None)

        if not callable(submit):
            raise RuntimeError(
                "A ponte não oferece submit_task."
            )

        task_id = submit("scene.inspect", {})

        return {
            "status": "queued",
            "task_id": task_id,
            "task_type": "scene.inspect",
            "message": "Aguardando resposta do Blender."
        }

    def collect_completed_inspection(self, task_id, persist=False):
        """Recupera e analisa o resultado de uma inspeção concluída."""

        if self.bridge is None:
            raise RuntimeError("BlenderBridge não conectado.")

        queue = getattr(self.bridge, "queue", None)

        if queue is None or not callable(
            getattr(queue, "list_tasks", None)
        ):
            raise RuntimeError(
                "A fila da ponte não oferece list_tasks."
            )

        if isinstance(task_id, bool) or not isinstance(task_id, int):
            raise BlenderIntelligenceError("ID de tarefa inválido.")

        task = next(
            (
                item for item in queue.list_tasks(limit=200)
                if item.get("id") == task_id
            ),
            None
        )

        if task is None:
            return {"status": "not_found", "task_id": task_id}

        if task.get("task_type") != "scene.inspect":
            raise BlenderIntelligenceError(
                "A tarefa não é uma inspeção de cena."
            )

        if task.get("status") != "completed":
            return {
                "status": task.get("status", "unknown"),
                "task_id": task_id,
                "message": "A inspeção ainda não foi concluída."
            }

        result = task.get("result")

        if not isinstance(result, dict):
            raise BlenderIntelligenceError(
                "O Blender não retornou um relatório válido."
            )

        report = self.analyze_snapshot(result, persist=False)
        report["evidence_source"] = "completed_blender_task"
        report["live_blender_verified"] = True
        report["task_id"] = task_id

        if persist:
            self._record_analysis(report)

        return report

    def _record_analysis(self, report):
        if self.cognitive is None:
            raise RuntimeError(
                "Núcleo cognitivo não conectado."
            )

        recorder = getattr(
            self.cognitive, "record_observation", None
        )

        if not callable(recorder):
            raise RuntimeError(
                "O núcleo não oferece record_observation."
            )

        recorder(
            category="blender_introspection",
            subject="scene_structure_analysis",
            data={
                "evidence_source": report["evidence_source"],
                "live_blender_verified": report[
                    "live_blender_verified"
                ],
                "scene": report["scene"],
                "mesh_totals": report["meshes"]["known_totals"],
                "modifiers": report["modifiers"]
            },
            source="blender_intelligence",
            confidence=1.0 if report[
                "live_blender_verified"
            ] else 0.5,
            limitations=list(self.LIMITATIONS)
        )

    def demonstrate_capabilities(self):
        """Demonstra análise de uma cena fictícia, sem persistência."""

        sample = {
            "blender_version": "demo",
            "objects": [
                {
                    "name": "Cubo",
                    "type": "MESH",
                    "data": {
                        "vertices": 8,
                        "edges": 12,
                        "polygons": 6
                    },
                    "modifiers": [
                        {"type": "SUBSURF"}
                    ],
                    "materials": ["Material demonstrativo"]
                },
                {
                    "name": "Camera",
                    "type": "CAMERA"
                },
                {
                    "name": "Luz",
                    "type": "LIGHT"
                }
            ],
            "collections": ["Collection"],
            "materials": ["Material demonstrativo"]
        }

        report = self.analyze_snapshot(sample)

        checks = {
            "object_inspection": (
                report["scene"]["object_count"] == 3
            ),
            "mesh_detection": (
                report["scene"]["mesh_count"] == 1
            ),
            "topology_analysis": (
                report["meshes"]["known_totals"] == {
                    "vertices": 8,
                    "edges": 12,
                    "faces": 6
                }
            ),
            "modifier_detection": (
                report["modifiers"].get("SUBSURF") == 1
            ),
            "camera_and_light_detection": (
                report["scene"]["camera_count"] == 1
                and report["scene"]["light_count"] == 1
            ),
            "no_false_live_claim": (
                report["live_blender_verified"] is False
            )
        }

        return {
            "component": "BlenderIntelligence",
            "version": self.VERSION,
            "passed": all(checks.values()),
            "checks": checks,
            "memory_modified": False,
            "blender_scene_modified": False,
            "external_actions": False
        }

    def status(self):
        return {
            "component": "BlenderIntelligence",
            "version": self.VERSION,
            "bridge_connected": self.bridge is not None,
            "cognitive_connected": self.cognitive is not None,
            "domains_catalogued": list(self.DOMAINS.keys()),
            "scene_inspection_task": "scene.inspect",
            "python_execution_task": "python.execute",
            "python_execution_requires_per_task_approval": True,
            "mesh_analysis": True,
            "live_blender_inspection_tested": False,
            "neural_training": False,
            "autonomous_execution": False,
            "limitations": list(self.LIMITATIONS)
        }
