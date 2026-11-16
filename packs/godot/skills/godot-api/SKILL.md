---
name: godot-api
description: Exact Godot engine API (classes, method signatures, properties, signals, enums, theme items) for the Godot version the project uses, plus official descriptions and deprecation notes. Use before writing GDScript that calls engine API you are not sure exists in this version, and when Godot reports a nonexistent function, invalid call, wrong argument count or unknown identifier.
---

# Look up the Godot API of this project's version

Godot changes its API between versions, and much example code online is for Godot 3. Check what this version
has instead of relying on memory. Use the `godot_api` tool of the godot-index MCP server when it is available;
otherwise the script does the same:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/godot_api.py" Tween                   # overview: parents, names, enums
python "${CLAUDE_PLUGIN_ROOT}/scripts/godot_api.py" Tween.tween_method      # exact signature, inherited too
python "${CLAUDE_PLUGIN_ROOT}/scripts/godot_api.py" get_global_mouse_position   # which classes have it
python "${CLAUDE_PLUGIN_ROOT}/scripts/godot_api.py" --search tween           # names containing the text
python "${CLAUDE_PLUGIN_ROOT}/scripts/godot_api.py" TileMap --describe       # official text, deprecation
```

Run it from the project folder (or pass `--project`), so it uses the Godot from `toolkit.json`. The first lookup
for a Godot version takes a few seconds while Godot writes out its API; later ones are instant.

- The answer comes from the Godot executable itself: when it disagrees with what you remember, it is right.
- "is the Godot 3 name: use X" means the code (or the tutorial it came from) is Godot 3; port the call rather
  than looking for a workaround.
- `--describe` downloads the class's official documentation for the exact version tag from the
  godotengine/godot repository (once, then cached). Use it when the signature alone does not say what a call
  does, and before using an API that might be deprecated. Without network it says so; the signature still works.
- The project's own classes and functions are not in the engine API: find them with `godot_find_symbol`.
