extends Node2D

var _frames: int = 0


func _ready() -> void:
	print("mini project ready")
	if OS.get_cmdline_user_args().has("--fail"):
		push_error("deliberate error from main.gd")
		push_warning("deliberate warning from main.gd")
		var missing: Node = get_node("DoesNotExist")
		missing.queue_free()
