"""Read-only Blender scene probe for Mahoraga's first grounded-world experiment.

Run inside Blender's Text Editor or Python Console. It does not edit the
scene, save the .blend file, start a render, or call the Mahoraga executor.
The result is printed as bounded JSON for manual inspection.
"""
from __future__ import annotations

import json
from collections import Counter

import bpy


MAX_OBJECTS = 250


def _vector(value):
    try:
        return [round(float(component), 6) for component in value]
    except (TypeError, ValueError, OverflowError):
        return None


def _object_record(obj):
    data = getattr(obj, "data", None)
    record = {
        "name": str(obj.name),
        "type": str(obj.type),
        "parent": obj.parent.name if obj.parent else None,
        "location": _vector(obj.location),
        "rotation_euler": _vector(obj.rotation_euler),
        "scale": _vector(obj.scale),
        "dimensions": _vector(obj.dimensions),
        "data_name": getattr(data, "name", None),
        "modifiers": [
            {"name": str(item.name), "type": str(item.type)}
            for item in list(obj.modifiers)[:32]
        ],
        "materials": [
            str(material.name) if material else None
            for material in list(getattr(data, "materials", []))[:32]
        ],
    }

    if obj.type == "MESH" and data is not None:
        record["geometry"] = {
            "vertices": len(data.vertices),
            "edges": len(data.edges),
            "polygons": len(data.polygons),
        }
    elif obj.type == "CAMERA" and data is not None:
        record["camera"] = {
            "lens_mm": round(float(data.lens), 4),
            "sensor_width_mm": round(float(data.sensor_width), 4),
            "clip_start": round(float(data.clip_start), 6),
            "clip_end": round(float(data.clip_end), 4),
            "type": str(data.type),
        }
    elif obj.type == "LIGHT" and data is not None:
        record["light"] = {
            "type": str(data.type),
            "energy": round(float(data.energy), 4),
            "color": _vector(data.color),
        }
    return record


def snapshot_scene():
    scene = bpy.context.scene
    objects = sorted(list(scene.objects), key=lambda item: item.name.casefold())
    type_counts = Counter(str(obj.type) for obj in objects)
    selected = objects[:MAX_OBJECTS]

    return {
        "schema": "mahoraga.blender_scene_probe",
        "schema_version": 1,
        "probe_version": "0.1.0",
        "blender": {
            "version": bpy.app.version_string,
            "version_tuple": list(bpy.app.version),
            "build_branch": (
                bpy.app.build_branch.decode("utf-8", errors="replace")
                if isinstance(bpy.app.build_branch, bytes)
                else str(bpy.app.build_branch)
            ),
            "background_mode": bool(bpy.app.background),
        },
        "scene": {
            "name": str(scene.name),
            "frame_current": int(scene.frame_current),
            "frame_start": int(scene.frame_start),
            "frame_end": int(scene.frame_end),
            "fps": int(scene.render.fps),
            "render_engine": str(scene.render.engine),
            "resolution": {
                "x": int(scene.render.resolution_x),
                "y": int(scene.render.resolution_y),
                "percentage": int(scene.render.resolution_percentage),
            },
            "unit_system": str(scene.unit_settings.system),
            "active_camera": (
                str(scene.camera.name) if scene.camera else None
            ),
        },
        "collections": sorted(
            str(collection.name)
            for collection in scene.collection.children
        ),
        "objects_total": len(objects),
        "object_type_counts": dict(sorted(type_counts.items())),
        "objects_returned": len(selected),
        "objects_truncated": len(objects) > len(selected),
        "objects": [_object_record(obj) for obj in selected],
        "side_effects": {
            "scene_modified": False,
            "blend_saved": False,
            "render_started": False,
            "external_process_started": False,
            "network_access": False,
        },
    }


result = snapshot_scene()
print("MAHORAGA_BLENDER_PROBE_BEGIN")
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
print("MAHORAGA_BLENDER_PROBE_END")
