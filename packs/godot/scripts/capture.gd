extends SceneTree
## Loaded by screenshot.py with `godot --path <project> --script capture.gd -- <options>`.
## Runs a scene (autoloads included), saves the frames asked for as PNG, then quits.
##
## User args (after `--`):
##   --scene res://x.tscn    scene to run (default: the project's main scene)
##   --frames 60,180         frames to capture, counted after the scene is ready
##   --out <folder>          where to write shot_<frame>.png
##   --max-width 1280        downscale wider captures to this width (0 keeps full size)

var _scene: String = ""
var _frames: Array[int] = [60]
var _out: String = ""
var _max_width: int = 1280
var _count: int = -1
var _done: bool = false


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
	print("capture.gd: running %s, capturing frames %s" % [_scene, _frames])


func _process(_delta: float) -> bool:
	if _done:
		return true
	if current_scene == null:
		return false
	_count += 1
	if _frames.has(_count):
		_save(_count)
	if _count >= _frames.back():
		_done = true
		quit(0)
	return false


func _save(frame: int) -> void:
	await RenderingServer.frame_post_draw
	var image: Image = root.get_texture().get_image()
	if _max_width > 0 and image.get_width() > _max_width:
		var h: int = int(round(image.get_height() * float(_max_width) / image.get_width()))
		image.resize(_max_width, h, Image.INTERPOLATE_LANCZOS)
	var path: String = _out.path_join("shot_%05d.png" % frame)
	var err: Error = image.save_png(path)
	if err == OK:
		print("capture.gd: saved %s (%dx%d)" % [path, image.get_width(), image.get_height()])
	else:
		printerr("capture.gd: could not save %s (error %d)" % [path, err])
