---
name: screenshot
description: Capture frames of a running Godot 4 scene as PNG and look at them. Use after changing anything visual (UI, layout, sprites, shaders, themes, fonts, scenes) to check how it really looks, or when the user asks what a scene looks like or reports a visual bug.
---

# Look at your own visual work

A headless run cannot tell whether UI or art looks right. After a visual change, capture the scene and read the
PNG with the Read tool before saying the change is done.

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/screenshot.py" "<project folder>" --scene res://path/to/scene.tscn --frames 60
```

- `--scene` defaults to the main scene. Use the scene you changed when it can run on its own.
- `--frames 30,120,300` saves several moments: early frames show the layout, later ones animations and timers.
  Frame 60 is about one second in.
- Frames are scaled down to 1280 px wide. Use `--max-width 0` only when a detail is too small to judge.
- Arguments after `--` go to the game (`OS.get_cmdline_user_args()`).

The script prints the saved paths (`<project>/.godot/toolkit/shots/shot_<frame>.png`). Read each one and compare
it with what the change should look like. Describe what you see, fix what is off, and capture again.

A game window opens for a few seconds while this runs; tell the user so they are not surprised.

## Saves are sandboxed

The run uses its own user data folder (`<project>/.godot/toolkit/userdata`), so a fresh profile appears and the
user's real saves are never read or overwritten. When a scene needs real progress to show something, ask the user
before passing `--real-user-data`, because the game may write to their saves.

## When it fails

- Exit code 1 with `MISSING shot_...`: the scene quit or crashed before that frame; the lines after the summary
  and `capture.log` show why. Errors from the run are listed the same way as in the run skill.
- `cannot load scene`: check the `res://` path.
- A scene that needs setup from another scene (a level that expects a game state) may show an empty or broken
  screen. Capture the scene that sets it up instead, or ask the user how to reach that screen.
