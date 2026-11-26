"""Create one isolated, reversible Blender fixture for Mahoraga testing.

The script creates only a dedicated collection containing a cube, camera and
area light. It does not change the active camera, render settings, frame,
selection, world, or existing objects. It does not save the .blend file.
"""
from __future__ import annotations

import json

import bpy
from mathutils import Vector


COLLECTION_NAME = "MAHORAGA_LAB_FIXTURE"
FIXTURE_ID = "mahoraga-blender-fixture-v1"
OWNER_PROPERTY = "mahoraga_fixture_id"


def _data_collection_for(data):
    if isinstance(data, bpy.types.Mesh):
        return bpy.data.meshes
    if isinstance(data, bpy.types.Camera):
        return bpy.data.cameras
    if isinstance(data, bpy.types.Light):
        return bpy.data.lights
    return None


def _rollback_created(created_objects, created_data):
    for obj in reversed(created_objects):
        try:
            current = bpy.data.objects.get(obj.name)
            if current is not None and current.as_pointer() == obj.as_pointer():
                bpy.data.objects.remove(current, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass
    for data_collection, data in reversed(created_data):
        try:
            current = data_collection.get(data.name)
            if (
                current is not None
                and current.as_pointer() == data.as_pointer()
                and current.users == 0
            ):
                data_collection.remove(current)
        except (ReferenceError, RuntimeError):
            pass


def _aim_at(obj, point):
    direction = Vector(point) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def create_fixture():
    if bpy.data.collections.get(COLLECTION_NAME) is not None:
        raise RuntimeError(
            "A coleção MAHORAGA_LAB_FIXTURE já existe. "
            "Inspecione-a ou remova-a com o script 03 antes de repetir."
        )
    if any(obj.get(OWNER_PROPERTY) == FIXTURE_ID for obj in bpy.data.objects):
        raise RuntimeError(
            "Já existem objetos desta fixture. Nenhum objeto foi alterado."
        )

    scene = bpy.context.scene
    collection = bpy.data.collections.new(COLLECTION_NAME)
    collection["mahoraga_fixture_id"] = FIXTURE_ID
    created = []
    created_data = []
    try:
        scene.collection.children.link(collection)
        vertices = [
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        ]
        faces = [
            (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
            (1, 5, 6, 2), (2, 6, 7, 3), (4, 0, 3, 7),
        ]
        mesh = bpy.data.meshes.new("MAHORAGA_LAB_CUBE_MESH")
        created_data.append((bpy.data.meshes, mesh))
        mesh[OWNER_PROPERTY] = FIXTURE_ID
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        cube = bpy.data.objects.new("MAHORAGA_LAB_CUBE", mesh)
        created.append(cube)
        cube[OWNER_PROPERTY] = FIXTURE_ID
        cube.location = (0.0, 0.0, 1.0)
        collection.objects.link(cube)

        camera_data = bpy.data.cameras.new("MAHORAGA_LAB_CAMERA_DATA")
        created_data.append((bpy.data.cameras, camera_data))
        camera_data[OWNER_PROPERTY] = FIXTURE_ID
        camera = bpy.data.objects.new("MAHORAGA_LAB_CAMERA", camera_data)
        created.append(camera)
        camera[OWNER_PROPERTY] = FIXTURE_ID
        camera.location = (4.0, -6.0, 4.0)
        camera_data.lens = 50.0
        _aim_at(camera, (0.0, 0.0, 1.0))
        collection.objects.link(camera)

        light_data = bpy.data.lights.new(
            "MAHORAGA_LAB_AREA_LIGHT_DATA", type="AREA"
        )
        created_data.append((bpy.data.lights, light_data))
        light_data[OWNER_PROPERTY] = FIXTURE_ID
        light = bpy.data.objects.new("MAHORAGA_LAB_AREA_LIGHT", light_data)
        created.append(light)
        light[OWNER_PROPERTY] = FIXTURE_ID
        light.location = (4.0, -4.0, 6.0)
        light_data.energy = 500.0
        light_data.size = 5.0
        _aim_at(light, (0.0, 0.0, 1.0))
        collection.objects.link(light)

        return {
            "status": "created",
            "fixture_id": FIXTURE_ID,
            "collection": COLLECTION_NAME,
            "objects": [
                {"name": obj.name, "type": obj.type}
                for obj in created
            ],
            "side_effects": {
                "existing_objects_modified": False,
                "active_camera_changed": False,
                "render_settings_changed": False,
                "frame_changed": False,
                "blend_saved": False,
                "external_process_started": False,
                "network_access": False,
            },
            "rollback": "Run 03_remove_fixture.py to delete only objects carrying this exact fixture ID.",
        }
    except Exception:
        _rollback_created(created, created_data)
        if collection in scene.collection.children:
            scene.collection.children.unlink(collection)
        if collection.users == 0 and len(collection.objects) == 0:
            bpy.data.collections.remove(collection)
        raise


result = create_fixture()
print("MAHORAGA_BLENDER_FIXTURE_BEGIN")
print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
print("MAHORAGA_BLENDER_FIXTURE_END")
