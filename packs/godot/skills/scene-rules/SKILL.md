---
name: scene-rules
description: Rules for editing Godot 4 scene and resource files (.tscn, .tres) by hand as text. Use before adding, removing or reparenting nodes, adding ext_resources or sub_resources, wiring signal connections, or changing properties directly in a .tscn or .tres file.
---

# Editing .tscn and .tres files by hand

Written for Godot 4.7 (`format=3`). A scene file that breaks these rules fails to load, often with a vague
"Parse error" or with nodes silently missing. Read the whole file before editing it, and look at a recently saved
scene in the same project for the conventions it uses.

## Structure, in this order

1. Header: `[gd_scene format=3 uid="uid://..."]` (or `[gd_resource type="..." format=3 uid="..."]`).
   Godot 4.7 no longer writes `load_steps`; older files still have it. It is only a loading hint, so leave an
   existing value alone and do not add it to new files.
2. `[ext_resource type="..." uid="uid://..." path="res://..." id="..."]` lines: files this scene uses.
3. `[sub_resource type="..." id="..."]` sections: resources embedded in the file. A sub_resource may only use
   ext_resources and sub_resources defined above it.
4. `[node ...]` sections: the root first, then every parent before its children.
5. `[connection ...]` lines at the end.

## Nodes

- Root: `[node name="Main" type="Node2D"]`, with no `parent`.
- Children of the root: `parent="."`. Deeper nodes: the path from the root, without the root's name:
  `parent="UI/Panel"`.
- A node's properties follow its header as `name = value` lines, one per line. Leave out properties at their
  default value; Godot does not write them.
- An instanced scene: `[node name="Enemy" parent="." instance=ExtResource("3_ab12c")]`, with no `type`.
  Properties under it override the instanced scene.
- Node names are unique among siblings and may not contain `. : @ / " %`.
- Renaming or moving a node changes its path: update `parent=` of its children, every `[connection]` that names
  it, `NodePath("...")` values, and `$Path` / `%Name` / `get_node()` uses in scripts (`grep` for the old name).

## Resources and ids

- `id` values are strings unique within the file. New ones: copy the project's style, e.g. `id="5_k2x9p"` for
  ext_resources and `id="StyleBoxFlat_k2x9p"` for sub_resources.
- Refer to them as `ExtResource("id")` and `SubResource("id")`, exactly matching the id.
- Never invent a `uid`. For an existing file, copy its uid from `<file>.uid` (scripts and shaders) or the
  `uid="..."` line in `<file>.import` (textures, sounds, fonts), or the header of a `.tscn` / `.tres`. If you
  cannot find it, leave `uid="..."` out: Godot uses the path and adds the uid on the next save.
- Scripts attach with `script = ExtResource("id")` on the node, right after the header line.

## Values

- Use Godot's text syntax: `Vector2(10, 20)`, `Color(1, 0.5, 0, 1)`, `NodePath("../Label")`,
  `PackedStringArray("a", "b")`, `&"name"` for StringName, `[1, 2]` for arrays, `{ "k": 1 }` for dictionaries.
- Strings are double-quoted with `\"` escapes. Multi-line strings stay inside one pair of quotes.
- Control layout: `layout_mode`, `anchors_preset`, `anchor_*`, `offset_*` work together. Changing one often
  needs the others; prefer copying a working node's layout lines.
- Groups go in the header: `[node name="X" type="Area2D" parent="." groups=["enemies"]]`.
- `%Name` access in scripts needs `unique_name_in_owner = true` on that node.

## Connections

`[connection signal="pressed" from="UI/StartButton" to="." method="_on_start_pressed"]`

`from` and `to` are node paths from the root (`.` is the root). The method must exist in the target node's
script with matching arguments, or the connection fails at runtime.

## After every edit

1. Run the doctor skill to catch broken paths and uids.
2. Run the run skill with `--check` so Godot loads the project; a malformed scene shows up there.
3. For visual changes, use the screenshot skill.

Keep the file's existing line endings, and change only the lines the task needs: Godot rewrites the file in its
own order on the next save, and small diffs keep that harmless.
