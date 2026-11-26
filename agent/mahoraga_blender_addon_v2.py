bl_info = {
    "name": "Mahoraga Bridge V2",
    "author": "Mahoraga",
    "version": (2, 1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Mahoraga",
    "description": "Conexao persistente com Mahoraga",
    "category": "3D View",
}

import bpy
import json
import urllib.request
import traceback
import time
import math
import io
import contextlib
from bpy.props import StringProperty

BASE_URL = "http://127.0.0.1:8766"
TIMER_KEY = "MAHORAGA_BRIDGE_V2_TIMER"
LAST_STATUS = "Desconectado"
LAST_ERROR = ""
PENDING_TASK = None


class MAHORAGA_Preferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    token: StringProperty(
        name="Token V2",
        subtype="PASSWORD"
    )

    def draw(self, context):
        self.layout.prop(self, "token")
        self.layout.label(text="Servidor: " + BASE_URL)


def get_preferences():
    addon = bpy.context.preferences.addons.get(__name__)
    return addon.preferences if addon else None


def api_request(method, path, data=None):
    prefs = get_preferences()
    if not prefs or not prefs.token:
        raise RuntimeError("Configure o token nas preferencias.")

    headers = {
        "Authorization": "Bearer " + prefs.token,
        "Accept": "application/json",
    }

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(req, timeout=4) as response:
        return json.loads(response.read().decode("utf-8"))


def inspect_scene():
    scene = bpy.context.scene
    objects = []

    for obj in scene.objects:
        item = {
            "name": obj.name,
            "type": obj.type,
            "location": list(obj.location),
            "rotation": list(obj.rotation_euler),
            "scale": list(obj.scale),
            "modifiers": [
                {"name": mod.name, "type": mod.type}
                for mod in obj.modifiers
            ],
            "materials": [
                slot.material.name if slot.material else None
                for slot in obj.material_slots
            ],
            "collections": [col.name for col in obj.users_collection],
        }

        if obj.type == "MESH" and obj.data:
            item["mesh"] = {
                "vertices": len(obj.data.vertices),
                "edges": len(obj.data.edges),
                "faces": len(obj.data.polygons),
            }

        objects.append(item)

    active = bpy.context.view_layer.objects.active

    return {
        "blender_version": bpy.app.version_string,
        "scene_name": scene.name,
        "object_count": len(objects),
        "active_object": active.name if active else None,
        "objects": objects,
    }


def _json_safe(value, depth=0):
    if depth > 5:
        return repr(value)[:500]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, dict):
        return {str(k)[:120]: _json_safe(v, depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v, depth + 1) for v in value[:100]]
    return repr(value)[:500]


def execute_python_task(task):
    payload = task.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Payload Python inválido.")
    if payload.get("human_approved") is not True or payload.get("approval_scope") != "blender_python":
        raise PermissionError("Execução bloqueada: aprovação ausente.")

    code = payload.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Código Python vazio ou inválido.")
    if len(code.encode("utf-8")) > 49152:
        raise ValueError("Código excede o limite de 48 KB.")

    started = time.time()
    out, err = io.StringIO(), io.StringIO()
    namespace = {
        "__builtins__": __builtins__, "bpy": bpy, "math": math, "json": json,
        "context": bpy.context, "data": bpy.data, "ops": bpy.ops,
        "scene": bpy.context.scene, "collection": bpy.context.collection,
    }
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exec(compile(code, "<mahoraga_blender_task>", "exec"), namespace, namespace)
        active = bpy.context.view_layer.objects.active
        return {
            "success": True, "task_id": int(task["id"]),
            "purpose": str(payload.get("purpose", ""))[:240],
            "started_at": started, "finished_at": time.time(),
            "stdout": out.getvalue()[-12000:], "stderr": err.getvalue()[-4000:],
            "result": _json_safe(namespace.get("result")),
            "scene_objects": len(bpy.context.scene.objects),
            "active_object": active.name if active else None,
        }
    except Exception as exc:
        return {
            "success": False, "task_id": int(task["id"]),
            "purpose": str(payload.get("purpose", ""))[:240],
            "started_at": started, "finished_at": time.time(),
            "stdout": out.getvalue()[-12000:], "stderr": err.getvalue()[-4000:],
            "error": repr(exc)[:2000], "traceback": traceback.format_exc()[-8000:],
            "scene_objects": len(bpy.context.scene.objects),
        }



def _mh_create_temple(payload):
    import math

    location = payload.get("location", [0, 0, 0])
    if not isinstance(location, (list, tuple)) or len(location) != 3:
        raise ValueError("Localização inválida.")
    x, y, z = [float(v) for v in location]
    if not all(math.isfinite(v) for v in (x, y, z)):
        raise ValueError("Localização não finita.")

    columns = int(payload.get("columns", 8))
    if not 4 <= columns <= 16:
        raise ValueError("Colunas deve ficar entre 4 e 16.")

    def mat(name, color, metallic=0):
        m = bpy.data.materials.get(name)
        if m is None:
            m = bpy.data.materials.new(name)
        m.diffuse_color = (*color, 1)
        m.use_nodes = True
        shader = m.node_tree.nodes.get("Principled BSDF") if m.node_tree else None
        if shader:
            shader.inputs["Base Color"].default_value = (*color, 1)
            shader.inputs["Metallic"].default_value = metallic
        return m

    stone = mat("Mahoraga_Pedra", (0.34, 0.29, 0.22))
    gold = mat("Mahoraga_Ouro", (0.83, 0.52, 0.12), 0.65)
    made = []

    def cube(name, pos, dims, material):
        bpy.ops.mesh.primitive_cube_add(size=1, location=pos)
        obj = bpy.context.object
        obj.name = name
        obj.dimensions = dims
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        obj.data.materials.append(material)
        made.append(obj)

    def cylinder(name, pos, radius, depth, material):
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=32, radius=radius, depth=depth, location=pos
        )
        obj = bpy.context.object
        obj.name = name
        obj.data.materials.append(material)
        made.append(obj)

    cube("Templo_Base", (x,y,z), (16,1,16), stone)
    cube("Templo_Piso", (x,y,z+0.65), (13,0.3,13), gold)
    cube("Templo_Plataforma", (x,y,z+1), (11,0.5,11), stone)

    for i in range(columns):
        a = 2 * math.pi * i / columns
        px = x + 4.5 * math.cos(a)
        py = y + 4.5 * math.sin(a)
        cylinder("Templo_Coluna_%02d" % i, (px,py,z+3), 0.42, 4, gold)
        cylinder("Templo_BaseColuna_%02d" % i, (px,py,z+1.2), 0.62, 0.35, stone)

    cube("Templo_Telhado", (x,y,z+5.2), (13,0.8,13), stone)
    cube("Templo_Coroamento", (x,y,z+5.85), (8,0.5,8), gold)
    cylinder("Templo_Altar", (x,y,z+1.8), 1.1, 1.1, gold)

    for i in range(4):
        cube("Templo_Escada_%02d" % i,
             (x,y-7+i*0.9,z+0.25+i*0.25),
             (8-i*1.2,1.8,0.5+i*0.15), stone)

    ld = bpy.data.lights.new("Templo_Luz", "AREA")
    light = bpy.data.objects.new("Templo_Luz", ld)
    bpy.context.collection.objects.link(light)
    light.location = (x+1,y-3,z+10)
    ld.energy = 2200
    ld.shape = "DISK"
    ld.size = 8

    cd = bpy.data.cameras.new("Templo_Camera")
    camera = bpy.data.objects.new("Templo_Camera", cd)
    bpy.context.collection.objects.link(camera)
    camera.location = (x+18,y-22,z+16)
    camera.rotation_euler = (1.05,0,0.72)
    bpy.context.scene.camera = camera

    return {
        "success": True,
        "generation": "stone_temple",
        "created_objects": len(made)+2,
        "columns": columns,
        "objects": [o.name for o in made]+[light.name,camera.name]
    }


def execute_task(task):
    global PENDING_TASK
    if not isinstance(task, dict):
        raise TypeError("Tarefa inválida.")

    task_id = int(task["id"])
    kind = task.get("task_type")

    if kind != "scene.inspect":
        error = (
            "Política local atual permite somente scene.inspect; "
            "tarefa bloqueada: " + str(kind)
        )
        try:
            api_request("POST", "/fail", {
                "task_id": task_id, "error": error
            })
        except Exception as report_error:
            print("[MAHORAGA V2] Erro ao notificar:", repr(report_error))
        raise RuntimeError(error)

    try:
        result = inspect_scene()

        api_request("POST", "/complete", {"task_id": task_id, "result": result})
        return "Tarefa concluída: " + str(kind)

    except Exception as exc:
        try:
            api_request("POST", "/fail", {
                "task_id": task_id, "error": repr(exc)[:1500]
            })
        except Exception as report_error:
            print("[MAHORAGA V2] Erro ao notificar:", repr(report_error))
        raise


def poll_mahoraga():
    global LAST_STATUS, LAST_ERROR
    if PENDING_TASK is not None:
        LAST_STATUS = "Aguardando aprovacao no painel Mahoraga"
        return 2.0

    prefs = get_preferences()
    if not prefs or not prefs.token:
        LAST_STATUS = "Token nao configurado"
        return None

    try:
        response = api_request("GET", "/next")
        task = response.get("task")

        if task:
            LAST_STATUS = "Executando tarefa " + str(task.get("id"))
            LAST_STATUS = execute_task(task)
        else:
            LAST_STATUS = "Conectado - aguardando tarefas"

        LAST_ERROR = ""

    except Exception as exc:
        LAST_STATUS = "Erro de conexao"
        error = repr(exc)
        if error != LAST_ERROR:
            print("[MAHORAGA V2]", error)
            LAST_ERROR = error

    return 2.0


def stop_client():
    old = bpy.app.driver_namespace.get(TIMER_KEY)
    if old:
        try:
            if bpy.app.timers.is_registered(old):
                bpy.app.timers.unregister(old)
        except Exception:
            pass
    bpy.app.driver_namespace.pop(TIMER_KEY, None)


def start_client():
    stop_client()
    bpy.app.driver_namespace[TIMER_KEY] = poll_mahoraga
    bpy.app.timers.register(
        poll_mahoraga,
        first_interval=1.0,
        persistent=True,
    )


class MAHORAGA_OT_connect(bpy.types.Operator):
    bl_idname = "mahoraga_bridge.connect"
    bl_label = "Conectar ao Mahoraga"

    def execute(self, context):
        global LAST_STATUS
        try:
            api_request("GET", "/health")
            start_client()
            LAST_STATUS = "Conexao iniciada"
            self.report({"INFO"}, "Mahoraga conectado.")
            return {"FINISHED"}
        except Exception as exc:
            LAST_STATUS = "Falha na conexao"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class MAHORAGA_OT_disconnect(bpy.types.Operator):
    bl_idname = "mahoraga_bridge.disconnect"
    bl_label = "Desconectar"

    def execute(self, context):
        global LAST_STATUS
        stop_client()
        LAST_STATUS = "Desconectado"
        self.report({"INFO"}, "Cliente desconectado.")
        return {"FINISHED"}



class MAHORAGA_OT_approve_python(bpy.types.Operator):
    bl_idname = "mahoraga_bridge.approve_python"
    bl_label = "Autorizar execucao Python"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        global PENDING_TASK, LAST_STATUS
        task = PENDING_TASK
        if task is None:
            self.report({"WARNING"}, "Nenhuma tarefa pendente.")
            return {"CANCELLED"}

        PENDING_TASK = None
        task_id = int(task["id"])
        try:
            result = execute_python_task(task)
            api_request("POST", "/complete", {
                "task_id": task_id,
                "result": result,
            })
            LAST_STATUS = (
                "Python executado com sucesso"
                if result.get("success")
                else "Falha Python enviada ao Mahoraga"
            )
            return {"FINISHED"}
        except Exception as exc:
            try:
                api_request("POST", "/fail", {
                    "task_id": task_id,
                    "error": "Falha no executor: " + repr(exc)[:1500],
                })
            except Exception as report_error:
                print("[MAHORAGA V2] Falha ao notificar servidor:", repr(report_error))
            LAST_STATUS = "Falha na execucao Python"
            self.report({"ERROR"}, str(exc)[:200])
            return {"CANCELLED"}


class MAHORAGA_OT_cancel_python(bpy.types.Operator):
    bl_idname = "mahoraga_bridge.cancel_python"
    bl_label = "Cancelar tarefa Python"

    def execute(self, context):
        global PENDING_TASK, LAST_STATUS
        task = PENDING_TASK
        if task is None:
            self.report({"WARNING"}, "Nenhuma tarefa pendente.")
            return {"CANCELLED"}

        PENDING_TASK = None
        try:
            api_request("POST", "/fail", {
                "task_id": int(task["id"]),
                "error": "Execucao cancelada pelo usuario no painel Blender.",
            })
            LAST_STATUS = "Execucao cancelada pelo usuario"
            return {"FINISHED"}
        except Exception as exc:
            PENDING_TASK = task
            LAST_STATUS = "Falha ao comunicar cancelamento"
            self.report({"ERROR"}, str(exc)[:200])
            return {"CANCELLED"}

class MAHORAGA_PT_panel(bpy.types.Panel):
    bl_label = "Mahoraga"
    bl_idname = "MAHORAGA_PT_bridge_v2"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mahoraga"

    def draw(self, context):
        layout = self.layout
        layout.label(text=LAST_STATUS)

        if PENDING_TASK is not None:
            payload = PENDING_TASK.get("payload", {})
            layout.separator()
            layout.label(text="TAREFA AGUARDANDO SUA DECISAO", icon="QUESTION")
            layout.label(text="Finalidade: " + str(payload.get("purpose", "Nao informada"))[:100])
            layout.label(text="Codigo Python:")
            code_lines = str(payload.get("code", "")).splitlines()
            for code_line in code_lines[:6]:
                layout.label(text=code_line[:90] if code_line.strip() else " ")
            if len(code_lines) > 6:
                layout.label(text="... restante do codigo")
            layout.label(text="Acesso ao processo Blender; nao e sandbox.")
            row = layout.row(align=True)
            row.operator("mahoraga_bridge.approve_python", icon="CHECKMARK")
            row.operator("mahoraga_bridge.cancel_python", icon="CANCEL")
        layout.operator(
            "mahoraga_bridge.connect",
            icon="LINKED",
        )
        layout.operator(
            "mahoraga_bridge.disconnect",
            icon="UNLINKED",
        )
        layout.label(text="Token nas preferencias do complemento.")


CLASSES = (
    MAHORAGA_Preferences,
    MAHORAGA_OT_connect,
    MAHORAGA_OT_disconnect,
    MAHORAGA_OT_approve_python,
    MAHORAGA_OT_cancel_python,
    MAHORAGA_PT_panel,
)


def auto_start():
    try:
        prefs = get_preferences()
        if prefs and prefs.token:
            api_request("GET", "/health")
            start_client()
            print("[MAHORAGA V2] Conexao automatica iniciada.")
    except Exception as exc:
        print("[MAHORAGA V2] Inicializacao automatica:", repr(exc))
    return None


def register():
    stop_client()
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    if not bpy.app.timers.is_registered(auto_start):
        bpy.app.timers.register(auto_start, first_interval=3.0)

    print("[MAHORAGA V2] Complemento registrado.")


def unregister():
    stop_client()

    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    print("[MAHORAGA V2] Complemento removido.")


if __name__ == "__main__":
    register()
