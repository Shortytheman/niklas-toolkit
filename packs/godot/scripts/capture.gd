extends SceneTree
## Loaded by screenshot.py with `godot --path <project> --script capture.gd -- <options>`.
## Runs a scene (autoloads included), saves frames as PNG, then quits. The game's own code is not changed.
##
## User args (after `--`):
##   --scene res://x.tscn    scene to run (default: the project's main scene)
##   --frames 60,180         frames to capture, counted after the scene is ready (frames mode)
##   --steps "<steps>"       drive the UI instead, steps separated by ";" (steps mode):
##                             wait:30            run 30 frames
##                             click:Settings     click a visible control, found by node name, button text,
##                                                or node path from the root ("/root/Main/UI/Start")
##                             hover:Gold         move the mouse over a control (shows tooltips)
##                             key:Escape         press and release a key (names as in Godot: Enter, F1, A)
##                             waitfor:Panel      wait until a control with that name or text is visible
##                                                (up to 600 frames)
##                             shot:name          save shot_name.png
##   --out <folder>          where to write the PNGs
##   --max-width 1280        downscale wider captures to this width (0 keeps full size)

const WAITFOR_LIMIT: int = 600

var _scene: String = ""
var _frames: Array[int] = [60]
var _steps: Array[String] = []
var _out: String = ""
var _max_width: int = 1280
var _count: int = -1
var _done: bool = false
var _steps_started: bool = false


func _initialize() -> void:
	var args: PackedStringArray = OS.get_cmdline_user_args()
	var i: int = 0
	while i < args.size():
		var key: String = args[i]
		var value: String = args[i + 1] if i + 1 < args.size() else ""
		match key:
			"--scene":
				_scene = value
			"--frames":
				_frames.clear()
				for part in value.split(",", false):
					_frames.append(int(part))
				_frames.sort()
			"--steps":
				for part in value.split(";", false):
					if not part.strip_edges().is_empty():
						_steps.append(part.strip_edges())
			"--out":
				_out = value
			"--max-width":
				_max_width = int(value)
		i += 2

	if _scene.is_empty():
		_scene = ProjectSettings.get_setting("application/run/main_scene", "")
	if _scene.is_empty() or _out.is_empty():
		printerr("capture.gd: missing --scene (and no main scene) or --out")
		quit(2)
		return
	DirAccess.make_dir_recursive_absolute(_out)
	var err: Error = change_scene_to_file(_scene)
	if err != OK:
		printerr("capture.gd: cannot load scene %s (error %d)" % [_scene, err])
		quit(2)
		return
	if _steps.is_empty():
		print("capture.gd: running %s, capturing frames %s" % [_scene, _frames])
	else:
		print("capture.gd: running %s with %d step(s)" % [_scene, _steps.size()])


func _process(_delta: float) -> bool:
	if _done:
		return true
	if current_scene == null:
		return false
	if not _steps.is_empty():
		if not _steps_started:
			_steps_started = true
			_run_steps()
		return false
	_count += 1
	if _frames.has(_count):
		_save("%05d" % _count)
	if _count >= _frames.back():
		_done = true
		quit(0)
	return false


# ---------------------------------------------------------------- steps

func _run_steps() -> void:
	for n in _steps.size():
		var step: String = _steps[n]
		var action: String = step.get_slice(":", 0).strip_edges().to_lower()
		var arg: String = step.substr(step.find(":") + 1).strip_edges() if step.contains(":") else ""
		print("capture.gd: step %d: %s" % [n + 1, step])
		var ok: bool = true
		match action:
			"wait":
				await _frames_pass(max(1, int(arg)))
			"shot":
				await _save(arg if not arg.is_empty() else "step%02d" % (n + 1))
			"click", "hover":
				var control: Control = _find_control(arg)
				if control == null:
					ok = false
				else:
					await _mouse_to(control)
					if action == "click":
						await _mouse_click(control)
			"key":
				ok = await _press_key(arg)
			"waitfor":
				var found: Control = null
				for _i in WAITFOR_LIMIT:
					found = _find_control(arg, false)
					if found != null:
						break
					await process_frame
				ok = found != null
			_:
				printerr("capture.gd: step %d: unknown action '%s' (use wait, click, hover, key, waitfor, shot)"
					% [n + 1, action])
				ok = false
		if not ok:
			printerr("capture.gd: step %d failed: %s" % [n + 1, step])
			_print_visible_controls()
			await _save("failed_step%02d" % (n + 1))
			_done = true
			quit(1)
			return
	_done = true
	quit(0)


func _frames_pass(count: int) -> void:
	for _i in count:
		await process_frame


func _find_control(what: String, report: bool = true) -> Control:
	if what.begins_with("/"):
		var node: Node = root.get_node_or_null(NodePath(what))
		if node is Control and (node as Control).is_visible_in_tree():
			return node
		if report:
			printerr("capture.gd: no visible control at %s" % what)
		return null
	var by_text: Control = null
	var by_name: Control = null
	var wanted: String = what.to_lower()
	for node in _all_nodes(root):
		if not node is Control or not (node as Control).is_visible_in_tree():
			continue
		var text: String = _control_text(node).strip_edges().to_lower()
		var raw: String = String(node.get("text")).strip_edges().to_lower() if "text" in node else ""
		if by_name == null and String(node.name).to_lower() == wanted:
			by_name = node
		if by_text == null and not text.is_empty() and (text == wanted or raw == wanted):
			by_text = node
	var result: Control = by_text if by_text != null else by_name
	if result == null and report:
		printerr("capture.gd: no visible control named or labelled '%s'" % what)
	return result


## The text as shown on screen: translation keys like "SETTINGS_BUTTON" are translated first.
func _control_text(node: Node) -> String:
	if node is Button or node is Label or node is LineEdit:
		return node.atr(node.text)
	if node is RichTextLabel:
		return (node as RichTextLabel).get_parsed_text()
	return ""


func _all_nodes(start: Node) -> Array[Node]:
	var out: Array[Node] = []
	var stack: Array[Node] = [start]
	while not stack.is_empty():
		var node: Node = stack.pop_back()
		out.append(node)
		var children: Array[Node] = node.get_children()
		children.reverse()
		stack.append_array(children)
	return out


## Lists what can be clicked: buttons with text one per line, buttons without text counted per parent.
func _print_visible_controls() -> void:
	var lines: Array[String] = []
	var textless: Dictionary = {}  # parent path -> [count, example path]
	for node in _all_nodes(root):
		if not (node is BaseButton and (node as Control).is_visible_in_tree()):
			continue
		var text: String = _control_text(node).strip_edges().replace("\n", " ")
		var path: String = String(root.get_path_to(node))
		if text.is_empty() and String(node.name).begins_with("@"):
			var parent: String = String(root.get_path_to(node.get_parent()))
			var entry: Array = textless.get(parent, [0, "/root/" + path])
			entry[0] += 1
			textless[parent] = entry
		elif lines.size() < 30:
			lines.append("  %s%s  (/root/%s)" % [node.name, " \"%s\"" % text if not text.is_empty() else "", path])
	for parent in textless:
		var entry: Array = textless[parent]
		lines.append("  %d unnamed button(s) without text in /root/%s, e.g. %s" % [entry[0], parent, entry[1]])
	printerr("capture.gd: visible buttons:\n" + ("\n".join(lines) if not lines.is_empty() else "  (none)"))


func _screen_center(control: Control) -> Vector2:
	var center_canvas: Vector2 = control.get_global_transform_with_canvas() * (control.size / 2)
	return root.get_screen_transform() * center_canvas


func _mouse_to(control: Control) -> void:
	var pos: Vector2 = _screen_center(control)
	for offset in [Vector2(-3, 0), Vector2.ZERO]:
		var motion: InputEventMouseMotion = InputEventMouseMotion.new()
		motion.position = pos + offset
		motion.global_position = pos + offset
		Input.parse_input_event(motion)
		await process_frame


func _mouse_click(control: Control) -> void:
	var pos: Vector2 = _screen_center(control)
	for pressed in [true, false]:
		var button: InputEventMouseButton = InputEventMouseButton.new()
		button.button_index = MOUSE_BUTTON_LEFT
		button.pressed = pressed
		button.position = pos
		button.global_position = pos
		Input.parse_input_event(button)
		await process_frame
	await process_frame


func _press_key(name: String) -> bool:
	var keycode: Key = OS.find_keycode_from_string(name)
	if keycode == KEY_NONE:
		printerr("capture.gd: unknown key '%s'" % name)
		return false
	for pressed in [true, false]:
		var event: InputEventKey = InputEventKey.new()
		event.keycode = keycode
		event.physical_keycode = keycode
		event.pressed = pressed
		Input.parse_input_event(event)
		await process_frame
	await process_frame
	return true


# ---------------------------------------------------------------- saving

func _save(label: String) -> void:
	await RenderingServer.frame_post_draw
	var image: Image = root.get_texture().get_image()
	if _max_width > 0 and image.get_width() > _max_width:
		var h: int = int(round(image.get_height() * float(_max_width) / image.get_width()))
		image.resize(_max_width, h, Image.INTERPOLATE_LANCZOS)
	var path: String = _out.path_join("shot_%s.png" % label)
	var err: Error = image.save_png(path)
	if err == OK:
		print("capture.gd: saved %s (%dx%d)" % [path, image.get_width(), image.get_height()])
	else:
		printerr("capture.gd: could not save %s (error %d)" % [path, err])
