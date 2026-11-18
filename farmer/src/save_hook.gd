## FARMER: appended to the game's Save autoload by build.sh.
## Starts the farming driver only for an explicit farmer launch.
## A normal game launch (even with farmer.cfg/display:true left over) stays inert.
func _farmer_tick() -> void:
	if _farmer != null or _farmer_failed:
		return
	if OS.get_environment("FARMER_SESSION") != "1":
		_farmer_failed = true
		return
	if not FileAccess.file_exists("user://farmer.cfg"):
		_farmer_failed = true
		return
	var parsed = JSON.parse_string(FileAccess.get_file_as_string("user://farmer.cfg"))
	if not (parsed is Dictionary):
		_farmer_failed = true
		push_error("Farmer: user://farmer.cfg is not a JSON object")
		return
	var allow_window := bool((parsed as Dictionary).get("display", false))
	if DisplayServer.get_name() != "headless" and not allow_window:
		_farmer_failed = true
		return
	if bool((parsed as Dictionary).get("offline", true)):
		# TownChannel/leaderboards/cloud use Save._name as their online gate.
		# The profile path was already fixed in Save._ready(), so the farmer
		# still reads and writes user://profile.json, just without Epic services.
		_name = "profile_test"
	var script = load("res://scripts/core/farmer.gdc")
	if script == null:
		_farmer_failed = true
		push_error("Farmer: cannot load res://scripts/core/farmer.gdc")
		return
	_farmer = script.new()
	if _farmer == null:
		_farmer_failed = true
		push_error("Farmer: script.new() returned null (parse/runtime error)")
		return
	_farmer.name = "Farmer"
	add_child.call_deferred(_farmer)
	print("FARMER_LOADED api=%d" % int(_farmer.API_VERSION))
