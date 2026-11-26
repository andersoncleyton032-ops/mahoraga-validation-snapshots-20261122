import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "blender_lab"


def _read(name):
    return (LAB / name).read_text(encoding="utf-8")


def _assignment_value(source, name):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"assignment not found: {name}")


def test_blender_lab_scripts_are_valid_python_without_importing_bpy():
    names = (
        "01_readonly_scene_probe.py",
        "02_create_reversible_fixture.py",
        "03_remove_reversible_fixture.py",
    )
    for name in names:
        ast.parse(_read(name), filename=name)


def test_readonly_probe_contains_no_scene_mutation_or_external_execution():
    source = _read("01_readonly_scene_probe.py")
    forbidden = (
        "bpy.ops.",
        "bpy.data.objects.new",
        "bpy.data.collections.new",
        "bpy.ops.wm.save",
        "subprocess",
        "requests.",
        "urllib.request",
        "exec(",
        "eval(",
    )
    for token in forbidden:
        assert token not in source


def test_fixture_and_rollback_use_the_same_exact_ownership_markers():
    create = _read("02_create_reversible_fixture.py")
    remove = _read("03_remove_reversible_fixture.py")
    for name in ("COLLECTION_NAME", "FIXTURE_ID", "OWNER_PROPERTY"):
        assert _assignment_value(create, name) == _assignment_value(remove, name)

    assert 'obj.get(OWNER_PROPERTY) != FIXTURE_ID' in create
    assert 'collection.get("mahoraga_fixture_id") != FIXTURE_ID' in remove
    assert 'obj.get(OWNER_PROPERTY) != FIXTURE_ID' in remove


def test_fixture_does_not_change_active_scene_camera_or_save_project():
    source = _read("02_create_reversible_fixture.py")
    assert not re.search(r"scene\.camera\s*=", source)
    assert "bpy.ops.wm.save" not in source
    assert "bpy.ops.render" not in source
    assert "scene.frame_set(" not in source



def test_fixture_registers_datablocks_before_operations_that_can_fail():
    source = _read("02_create_reversible_fixture.py")
    assert source.index("created_data.append((bpy.data.meshes, mesh))") < source.index("mesh.from_pydata")
    assert source.index("created_data.append((bpy.data.cameras, camera_data))") < source.index("camera = bpy.data.objects.new")
    assert source.index("created_data.append((bpy.data.lights, light_data))") < source.index("light = bpy.data.objects.new")
    assert "_rollback_created(created, created_data)" in source
    assert "current.as_pointer() == data.as_pointer()" in source


def test_cleanup_preserves_fixture_objects_relinked_outside_collection():
    source = _read("03_remove_reversible_fixture.py")
    assert "obj.get(OWNER_PROPERTY) != FIXTURE_ID" in source
    assert "collection.get(\"mahoraga_fixture_id\") != FIXTURE_ID" in source
    assert "any(item != collection for item in obj.users_collection)" in source
