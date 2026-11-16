extends Control


func _ready() -> void:
	$OpenButton.pressed.connect(func() -> void: $Settings.visible = true)
	for i in $Icons.get_child_count():
		$Icons.get_child(i).pressed.connect(func() -> void: print("menu: icon %d pressed" % (i + 1)))


func _unhandled_key_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		$Settings.visible = false
		print("menu: settings closed")
