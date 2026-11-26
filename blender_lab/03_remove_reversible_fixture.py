"""Remove only the exact objects created by Mahoraga's Blender lab fixture.

Objects are deleted only when both the dedicated collection marker and the
object-level fixture ID match. User-created or modified objects without this
marker are never deleted.
"""
from __future__ import annotations

import json

import bpy


COLLECTION_NAME = "MAHORAGA_LAB_FIXTURE"
FIXTURE_ID = "mahoraga-blender-fixture-v1"
OWNER_PROPERTY = "mahoraga_fixture_id"


def remove_fixture():
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        return {
            "status": "already_absent",
            "removed_objects": [],
            "collection_removed": False,
        }
    if collection.get("mahoraga_fixture_id") != FIXTURE_ID:
        raise RuntimeError(
            "A coleção existe, mas não possui o marcador exato da fixture. "
            "Por segurança, nada foi removido."
        )

    removed = []
    for obj in list(collection.objects):
        if obj.get(OWNER_PROPERTY) != FIXTURE_ID:
            continue
        if any(item != collection for item in obj.users_collection):
            # A fixture object was linked into another collection after creation.
            # Preserve it rather than removing a resource now used elsewhere.
            continue
        data = getattr(obj, "data", None)
        data_collection = None
        if isinstance(data, bpy.types.Mesh):
            data_collection = bpy.data.meshes
        elif isinstance(data, bpy.types.Camera):
            data_collection = bpy.data.cameras
        elif isinstance(data, bpy.types.Light):
            data_collection = bpy.data.lights

        name = str(obj.name)
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data_collection is not None and data.users == 0:
            data_collection.remove(data)
        removed.append(name)

    remaining = [obj.name for obj in collection.objects]
    collection_removed = False
    if not remaining:
        bpy.data.collections.remove(collection)
        collection_removed = True

    return {
        "status": "removed" if removed else "no_owned_objects_found",
        "removed_objects": removed,
        "unowned_objects_preserved": remaining,
        "collection_removed": collection_removed,
        "side_effects": {
            "non_fixture_objects_deleted": False,
            "scene_settings_changed": False,
            "blend_saved": False,
            "external_process_started": False,
            "network_access": False,
        },
    }


result = remove_fixture()
print("MAHORAGA_BLENDER_CLEANUP_BEGIN")
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
print("MAHORAGA_BLENDER_CLEANUP_END")
