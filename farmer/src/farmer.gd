extends Node
## Midgard Survivors autonomous farmer (v3).
##
## One brain node, loaded by a tiny Save autoload hook. It plays real runs,
## delegates in-run level-ups to the native manual-play picker, keeps loot
## through Save's storage API, and runs maintenance between runs.
##
## Design: docs/design/farmer.md. Game study: docs/analysis/.
## API_VERSION is bumped whenever the expected game symbols change.

const API_VERSION := 3

const CFG_PATH := "user://farmer.cfg"
const STATUS_PATH := "user://farmer_status.json"
const CATALOG_PATH := "user://farmer_catalog.json"
const ARMS_PATH := "user://farmer_arms.json"
const RUNS_PATH := "user://farmer_runs.jsonl"
const CHECKPOINT_PATH := "user://farmer_session.json"
const LOG_PATH := "user://farmer.log"
const COMMAND_PATH := "user://farmer_command"
const STOP_PATH := "user://farmer_stop"
const BUILD_PATH := "user://farmer_build.json"
const TEST_CRASHED_PATH := "user://farmer_test_crashed"

const RESULT_BOSS_WON := "boss_won"

const STATUS_EVERY_MS := 5000
const TICK_MS := 100
const VICTORY_PULL_MS := 1500
const KARMA_PORTAL_WAIT_MS := 20000
const SETTLE_WAIT_MS := 25000
const DIRECT_STALL_MS := 750
const FIELD_STALL_S := 0.65
const FIELD_TURN_RADIUS := 0.19
const FIELD_OPEN := 3
const FIELD_NEIGHBORS := [Vector2i.RIGHT, Vector2i.DOWN, Vector2i.LEFT, Vector2i.UP]
const PORTAL_CLEARANCE := 1.4
const ALTAR_NO_PROGRESS := 5.0 # Allows Baldur's four-second calm window.
const FIELD_CHARGE_SPEED := 17.0
const FIELD_CHARGE_DURATION := 0.85
const HAZARD_MARGIN := 0.3
const FIELD_SLAM_RADIUS := 3.5

# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

var cfg: Dictionary = {}
var world = null
var menus = null
var phase := "boot"
var failed := false
var finish_reason := ""
var last_error := ""
var last_transition := ""
var exit_code := 0
var heartbeat_seq := 0
var session_id := ""
var boot_ms := 0
var session_started_unix := 0
var next_action_ms := 0
var next_status_ms := 0
var last_tick_ms := 0

var runs_started := 0
var runs_done := 0
var wins := 0
var losses := 0
var runs_lost := 0
var total_zeny := 0
var total_kills := 0
var total_xp := 0
var total_coins := 0
var total_ymir := 0
var total_materials: Dictionary = {}
var active_class := ""
var active_stage := ""
var active_danger := 1
var active_oath_points := 0
var next_arm_hint := ""
var _rotating := false
var _last_rotated_stage := ""
var _tower_kind := ""
var _tower_intent: Dictionary = {}

var run_state: Dictionary = {}
var last_run: Dictionary = {}
var arms: Dictionary = {}
var last_maint: Dictionary = {}

var _arena_map_id := 0
var _arena_timing: Dictionary = {}

var _altar_seen: Dictionary = {}
var _altar_channel: Dictionary = {}
var _altar_fill_peak := 0.0
var _altar_progress_clock := 0.0
var _altar_routes: Dictionary = {}
var _altar_route_from := Vector2i(-1, -1)
var _altar_route_at := Vector3.INF
var _altar_route_portal := Vector3.INF

var _time_last := -1.0
var _time_change_ms := 0
var _clock_last := -1.0
var _clock_change_ms := 0
var _stall_tries := 0
var _paused_since_ms := 0
var _pause_tries := 0
var _settle_ms := 0
var _finish_after_run := ""
var _pause_requested := false
var _hard_finished := false
var _test_wait_at_keep := false
var _catalog_written := false
var _test_preparation: Dictionary = {}
var _test_catalog: Dictionary = {}
var _test_oaths: Dictionary = {}
var _test_wishlist_ids: Array[String] = []
var _test_wishlist_runs: Array = []
var _test_verify_wishlist := false
var _test_freeze_run_time := false
var _test_blocked_portal := false
var _test_portal_seeded := false
var _test_valkyrie := false
var _test_raid_ability: Dictionary = {}
var _test_raid_hits := 0
var _test_raid_fails := 0
var _test_raid_end := 0.0
var _test_raid_marks := 0
var _test_navigation := false
var _test_nav: Dictionary = {}
var _test_charge := false
var _test_charge_enemy: Enemy
var _test_mvp_mechanics := false
var _test_mvp_enemy: Enemy
var _test_mvp_waves: Array[Dictionary] = []
var _test_tower_parity := false
var _test_tower_run := false
var _test_tower_board_requests := 0
var _test_tower_finish_sent := false
var _test_tower_evidence: Dictionary = {}

var _potential_script = null
var _vanilla_input_seen := false

var _direct_map_id := 0
var _direct_tile := Vector2i.ZERO
var _direct_progress_ms := -1
var _direct_best_dist := INF
var _direct_grid: AStarGrid2D
var _direct_path: Array[Vector2i] = []
var _direct_step := 1
var _raid_goal := false
var _field_portal := Vector3.INF
var _field_map_id := 0
var _field_path := PackedVector3Array()
var _field_step := 0
var _field_tile := Vector2i(-1, -1)
var _field_path_map_id := 0
var _field_path_portal := Vector3.INF
var _field_progress := 0.0
var _field_best_dist := INF
var _field_replanned := false
var _field_failed: Dictionary = {}
var _field_clearance := PackedByteArray()
var _field_exit := PackedByteArray()

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

class FarmerInput extends HeroInput:
	var brain = null

	func move_vector(hero: Player, w: World) -> Vector2:
		if brain == null or not is_instance_valid(brain):
			return Vector2.ZERO
		return brain.steer(hero)


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	boot_ms = _now()
	session_started_unix = int(Time.get_unix_time_from_system())
	# The supervisor keeps one id for the whole AFK session so a restarted
	# farmer continues its checkpoint; a one-off launch starts a new session.
	session_id = OS.get_environment("FARMER_SESSION_ID")
	_pause_requested = session_id != "" and OS.get_environment("FARMER_PAUSED") == "1"
	if session_id == "":
		session_id = "%s-%d" % [Time.get_datetime_string_from_system().replace(":", "").replace("-", "").replace("T", "-"), OS.get_process_id()]
	_test_wait_at_keep = _test_env("WAIT_AT_KEEP") == "1"
	_test_freeze_run_time = _test_env("FREEZE_RUN_TIME") == "1"
	_test_blocked_portal = _test_env("BLOCKED_PORTAL") == "1"
	_test_valkyrie = _test_env("VALKYRIE") == "1"
	_test_navigation = _test_env("FIELD_NAVIGATION") == "1"
	_test_charge = _test_env("FIELD_CHARGE") == "1"
	_test_mvp_mechanics = _test_env("MVP_MECHANICS") == "1"
	_test_verify_wishlist = _test_env("WISHLIST") == "1"
	_test_tower_parity = _test_env("TOWER_PARITY") == "1"
	_test_tower_run = _test_env("TOWER_RUN") == "1"
	_potential_script = load("res://scripts/core/potential.gd")
	_load_arms()
	_mark_transition("boot")
	if not _load_cfg():
		_fail_session("cfg_invalid")
		return
	_log("BOOT api=%d session=%s zeny=%d cfg=%s" % [API_VERSION, session_id, int(Save.zeny()), JSON.stringify(cfg)])
	if not _restore_checkpoint():
		return
	_write_status()


func _notification(what: int) -> void:
	if what == NOTIFICATION_EXIT_TREE or what == NOTIFICATION_PREDELETE:
		if not failed and not _hard_finished and Save != null:
			Save.flush()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

func _process(_delta: float) -> void:
	if failed or _hard_finished:
		return
	var now := _now()
	if now >= next_status_ms:
		next_status_ms = now + STATUS_EVERY_MS
		_write_status()
	if world == null or not is_instance_valid(world):
		_discover_world()
		return
	if get_tree().current_scene != world:
		# Scene swapped (loading/end screen). Re-acquire next frame.
		world = null
		return
	_check_command(now)
	if failed or _hard_finished:
		return
	_check_limits(now)
	if failed or _hard_finished:
		return
	match phase:
		"idle":
			if now >= next_action_ms:
				_prepare_run()
		"run":
			_tick_run(now)
		"settle":
			_tick_settle(now)
		"keep":
			# Sandbox verification can publish abort before optional keep starts.
			if not _test_wait_at_keep:
				_do_keep()
				if not failed and not _hard_finished:
					phase = "maint"
		"maint":
			_do_maintenance()
			_complete_run(now)
		"done":
			pass


func _discover_world() -> void:
	var scene = get_tree().current_scene
	if scene == null:
		return
	if not scene.has_method("start_run"):
		return
	if scene.get("map") == null or scene.get("menus") == null:
		return
	world = scene
	menus = scene.menus
	_on_world_ready()


func _on_world_ready() -> void:
	if not _catalog_written:
		if _test_tower_parity and not _test_seed_manual_tower_snapshots():
			return
		if not _write_catalog():
			_fail_session("catalog_write_failed")
			return
		_catalog_written = true
		if phase == "tower_recovered":
			_finish("tower_finished")
			return
		if _test_env("CATALOG") == "1":
			_test_catalog = _catalog_evidence()
		if not _validate_run_choice():
			return
		if _test_env("OATHS") == "1":
			_test_oaths["before"] = Save._read(Save.PATH).get("oaths")
	_apply_autopilot()
	_replace_player_input()
	Save.set_setting("onboarded", true)
	# Keep the game from auto-ending the run after the MVP; the farmer decides
	# at the victory point. This meta has no other effect in 0.2.3.
	GameData.set_meta("karma_test", true)
	phase = "paused" if _pause_requested else "idle"
	next_action_ms = _now() + 400
	_log("WORLD_READY map=%s" % str(world.map.map_name))
	_write_status()


func _apply_autopilot() -> void:
	if world == null or not is_instance_valid(world):
		return
	world.autopilot = true
	if world.menus != null and is_instance_valid(world.menus):
		world.menus.auto_pick = true
	if not _tower_kind.is_empty():
		return # The native Tower controller gates speed per floor and forbids fast Hel.
	# Own the engine clock: _frenzy_time_scale() returns early, so the game
	# stops rewriting Engine.time_scale every frame.
	world._mvp_slow = true
	world.fast_now = true
	var want := maxf(1.0, float(cfg.get("speed", 4.0)))
	if not is_equal_approx(Engine.time_scale, want):
		Engine.time_scale = want


func _replace_player_input() -> void:
	if world == null or not is_instance_valid(world):
		return
	var p = world.player
	if p == null or not is_instance_valid(p):
		return
	if p.input is FarmerInput and p.input.brain == self:
		return
	var inp = FarmerInput.new()
	inp.brain = self
	p.input = inp
	_vanilla_input_seen = true


# ---------------------------------------------------------------------------
# Run preparation
# ---------------------------------------------------------------------------

func _prepare_run() -> void:
	if world == null or not is_instance_valid(world) or world.map == null:
		next_action_ms = _now() + 500
		return
	if _tower_kind.is_empty() and _goal_done() and bool(cfg.get("goal_stop", false)):
		_finish("goal")
		return
	var choice: Dictionary = cfg["stage"] if not _tower_kind.is_empty() else {}
	var tower_snapshot := _pick_tower_snapshot() if not choice.is_empty() else {}
	if not choice.is_empty() and tower_snapshot.is_empty():
		_fail_session("tower_no_snapshot", true, "No eligible unlocked Tower snapshot.")
		return
	var target := _choose_target() if choice.is_empty() else {
		"stage": "hel" if _tower_kind == "hel" else "tower",
		"danger": GameData.DANGER_HELL10, "class": tower_snapshot["class"],
	}
	if target.is_empty():
		if not failed:
			_finish("no_target")
		return
	active_stage = str(target.get("stage", ""))
	active_danger = int(target.get("danger", 1))
	active_class = str(target.get("class", ""))
	if active_class == "" or active_stage == "":
		_finish("no_target")
		return
	if _test_env("PREPARATION") == "1":
		# Set up unspent points in the sandbox by earning XP, not by editing allocated stats.
		if Save.free_points(active_class) <= 0:
			Save.add_class_xp(active_class, Save.class_climb_xp(active_class))
		Save.set_setting("endless_auto_pick", true)
		AutoPick.log_picks = true
		_test_preparation["before"] = _preparation_snapshot(Save.data)
	if choice.is_empty():
		_apply_build_settings(active_class)
	var run_id := "%s-r%d" % [session_id, runs_started + 1]
	run_state = _snapshot_run_state()
	run_state["run_id"] = run_id
	if _test_env("PROGRESS") == "1":
		_test_seed_progress()
		run_state["progress"] = {"before": _progress_snapshot(Save.data), "board_requests": 0}
	run_state["class"] = active_class
	run_state["stage"] = active_stage
	run_state["danger"] = active_danger
	run_state["stage_min_danger"] = _stage_min_danger(active_stage)
	run_state["victory"] = false
	run_state["forced"] = false
	run_state["boss_won"] = false
	run_state["won_at"] = 0
	run_state["endless_started_at"] = -1.0
	run_state["endless_mvps"] = 0
	run_state["last_run_mvps"] = 0
	run_state["settle_start"] = 0
	run_state["died"] = false
	run_state["falls_by_mechanic"] = {}
	run_state["arena_timings"] = []
	_arena_map_id = 0
	_arena_timing = {}
	run_state["kills"] = 0
	run_state["run_zeny"] = 0
	run_state["run_mvps"] = 0
	run_state["route_entered"] = false
	_altar_seen.clear()
	_altar_channel = {}
	if choice.is_empty() and cfg["karma_route"] == "valhalla":
		run_state["reginleif_cards"] = int(Save.data.get("cards", {}).get("reginleif_card", 0))
	_time_last = -1.0
	_time_change_ms = _now()
	_clock_last = -1.0
	_clock_change_ms = _now()
	_stall_tries = 0
	_paused_since_ms = 0
	_pause_tries = 0
	_direct_progress_ms = -1
	_direct_grid = null
	_field_map_id = 0
	_set_autopilot_flags(true)
	if choice.is_empty():
		world.set_stage(active_stage)
		world.danger = active_danger
		world.speed = clampi(int(cfg.get("game_speed", 3)), 1, 3)
		Save.set_setting("onboarded", true)
		# The game consumes even an empty override; never inherit the saved set.
		world.oaths_next = cfg["oaths"] if active_danger == GameData.DANGER_MAX else {}
		# 0.2.5 suppresses the finale on autopilot unless this meta is set.
		if _want_endless() and not GameData.has_meta("finale_at"):
			GameData.set_meta("finale_at", GameData.MORROC_FINALE.at)
		if _test_blocked_portal:
			GameData.set_meta("mvp_at", 2.0)
	# The native start resets this manual-run toggle; don't persist its reset.
	var settings: Dictionary = Save.data.settings
	var had_auto_pick := settings.has("endless_auto_pick")
	var auto_pick = settings.get("endless_auto_pick")
	var started := true
	if choice.is_empty():
		world.start_run(active_class)
	else:
		started = _launch_tower(tower_snapshot, 1 if _tower_kind == "hel" else int(choice["floor"]))
	if started and run_state.has("progress"):
		world.board.child_entered_tree.connect(_test_progress_board_request)
	if had_auto_pick:
		settings["endless_auto_pick"] = auto_pick
	else:
		settings.erase("endless_auto_pick")
	if not started:
		return
	if not choice.is_empty() and not _flush_profile_verified("tower_launch"):
		return
	world.player.farmer_fell.connect(_on_player_fell)
	if choice.is_empty() and cfg["karma_route"] == "valhalla" and is_instance_valid(world.karma):
		world.karma.path = "light"
	active_oath_points = int(world.oath_points())
	_test_raid_ability = {}
	_test_mvp_enemy = null
	_test_mvp_waves.clear()
	_replace_player_input()
	_apply_autopilot()
	if choice.is_empty():
		Engine.time_scale = maxf(1.0, float(cfg.get("speed", 4.0)))
	runs_started += 1
	if _rotating:
		_last_rotated_stage = active_stage
	phase = "run"
	_mark_transition("run_start")
	_log("START #%d class=%s stage=%s danger=%d speed=%.1f" % [
		runs_started, active_class, active_stage, active_danger, float(cfg.get("speed", 4.0))])
	if not _write_checkpoint("run"):
		return
	_test_crash("run")
	_write_status()
	if not choice.is_empty():
		_refresh_tower_catalog()


func _launch_tower(snapshot: Dictionary, floor: int) -> bool:
	var id: String = snapshot["id"]
	run_state["tower_floor_start"] = floor
	run_state["tower_floor_best"] = 0
	run_state["snapshot"] = {"id": id, "job": snapshot["job"], "level": snapshot["level"]}
	_tower_intent = {"snapshot_id": id, "run_id": run_state["run_id"]}
	if not _write_checkpoint("tower_intent"):
		return false
	_test_crash("tower_intent")
	# The native writer consumes by array index and flushes before creating the run.
	var index := -1
	var builds: Array = Save.tower_builds()
	for i in builds.size():
		var build: Dictionary = builds[i]
		if _tower_snapshot_id(build) != id:
			continue
		if index != -1 or Save.build_locked(build) or not GameData.CLASSES.has(build.get("class")):
			return _fail_tower_intent()
		index = i
	if index == -1:
		return _fail_tower_intent()
	if _test_tower_run:
		var saved: Dictionary = Save._read(Save.PATH)
		_test_tower_evidence["before"] = _tower_save_evidence(saved)
		_test_tower_evidence["preparation_before"] = _preparation_snapshot(saved)
		world.board.child_entered_tree.connect(_test_observe_tower_request)
	world.oaths_next = null # Use the native Tower rules, including Hel's saved-oath exclusions.
	world._mvp_slow = false
	world._speed_applied = -1.0
	world.start_tower(index, floor, _tower_kind == "hel")
	if not world.running or world.tower == null or not is_instance_valid(world.player) \
			or world.player.class_id != active_class or world.tower.floor != floor \
			or (world.tower.hel != null) != (_tower_kind == "hel"):
		return _fail_tower_intent()
	_test_crash("tower_started")
	_log("TOWER_START run=%s kind=%s floor=%d snapshot=%s" % [run_state["run_id"], _tower_kind, floor, id])
	return true


func _fail_tower_intent() -> bool:
	_fail_session("tower_intent_unresolved", true, "The saved Tower launch cannot be reconciled. No second snapshot will be spent.")
	return false


func _set_autopilot_flags(on: bool) -> void:
	if world == null or not is_instance_valid(world):
		return
	world.autopilot = on
	if world.menus != null and is_instance_valid(world.menus):
		world.menus.auto_pick = on


# ---------------------------------------------------------------------------
# Run tick
# ---------------------------------------------------------------------------

func _tick_run(now: int) -> void:
	_observe_arena_timing(now)
	if not _tower_intent.is_empty():
		_tick_tower(now)
		return
	if _test_blocked_portal and _test_tick_blocked_portal():
		return
	_apply_autopilot()
	_replace_player_input()
	_handle_job_change(world.player)
	_draft_player()
	if _test_valkyrie:
		if world.running:
			_test_tick_valkyrie()
		if not world.running:
			_begin_settle(now)
		return
	if _test_mvp_mechanics:
		if world.running:
			_test_tick_mvp_mechanics()
		if not world.running:
			_begin_settle(now)
		return
	if _test_charge:
		if world.running:
			_test_tick_field_charge()
		if not world.running:
			_begin_settle(now)
		return
	if cfg["altar_policy"] == "map-wide" or not _altar_seen.is_empty():
		_observe_altars()
	if _test_navigation and world.running and _test_tick_navigation():
		return
	if world.running:
		_handle_victory(now)
	if world == null or not is_instance_valid(world):
		return
	if world.running:
		run_state["kills"] = int(world.kills)
		run_state["run_zeny"] = int(world.run_zeny)
		run_state["run_mvps"] = int(world.run_mvps)
		if bool(world.player.fell):
			run_state["died"] = true
		if _test_tower_parity and world.player.level >= GameData.TOWER_BUILD_MIN_LEVEL + (runs_started - 1) * 5:
			_results_forced("tower_parity_fixture", now)
		_check_watchdog(now)
		_check_timeout(now)
	if phase == "run" and not world.running:
		_begin_settle(now)


func _tick_tower(now: int) -> void:
	var tower: TowerRun = world.tower
	if tower == null:
		_fail_tower_intent()
		return
	_apply_autopilot()
	_replace_player_input()
	if tower.best > int(run_state["tower_floor_best"]):
		run_state["tower_floor_best"] = tower.best
		_log("TOWER_FLOOR cleared=%d" % tower.best)
	if not world.running:
		_begin_settle(now)
		return
	run_state["kills"] = int(world.kills)
	run_state["run_zeny"] = int(world.run_zeny)
	run_state["run_mvps"] = int(world.run_mvps)
	if world.raid.state == "won" and world.raid.in_arena():
		world._pull_prizes()
	var collecting := _tower_collecting_prizes()
	if _finish_after_run == "finish" and not collecting:
		_end_run_safe(false)
	elif _test_tower_run and not _test_tower_finish_sent \
			and tower.best >= int(run_state["tower_floor_start"]) + 1:
		_test_tower_finish_sent = _atomic_write(COMMAND_PATH, "finish\n")


func _tower_collecting_prizes() -> bool:
	if world.raid.state != "won" or not world.raid.in_arena():
		return false
	# Naght holds chest pickup for longer than the return portal takes to open.
	return _now() < world._chests_held or world._loot != null or not world.loot_queue.is_empty() \
		or world.pickups.any(func(p): return p.kind in ["chest", "card"])


func _observe_arena_timing(now: int) -> void:
	var raid: MvpRaid = world.raid
	if not world.running or not is_instance_valid(raid):
		return
	var state := raid.state
	if state != "intro" and state != "fight" and state != "won":
		return
	var map_id: int = world.map.get_instance_id()
	if map_id != _arena_map_id:
		if state != "intro":
			return
		_arena_map_id = map_id
		var timings: Array = run_state["arena_timings"]
		_arena_timing = {
			"arena_n": timings.size() + 1,
			"kind": "valkyrie" if raid.mvp == "reginleif" and world.karma.route == "light" else "mvp",
			"boss": raid.mvp,
			"entry_ms": now,
			"first_damage_ms": null,
			"kill_ms": null,
			"entry_to_first_damage_ms": null,
			"entry_to_kill_ms": null,
			"first_damage_to_kill_ms": null,
		}
		timings.append(_arena_timing)
		_log_arena_timing("ENTRY", now)
	if _arena_timing["kill_ms"] != null:
		return
	# These are first observations on a process frame, not hit callbacks.
	# A lethal first hit can have the same timestamp as the kill.
	if _arena_timing["first_damage_ms"] == null and is_instance_valid(raid.boss) \
			and raid.boss.hp < raid.boss.max_hp and is_instance_valid(raid.boss.last_hit_by):
		_arena_timing["first_damage_ms"] = now
		_arena_timing["entry_to_first_damage_ms"] = now - int(_arena_timing["entry_ms"])
		_log_arena_timing("FIRST_DAMAGE", now)
	if state == "won":
		_arena_timing["kill_ms"] = now
		_arena_timing["entry_to_kill_ms"] = now - int(_arena_timing["entry_ms"])
		if _arena_timing["first_damage_ms"] != null:
			_arena_timing["first_damage_to_kill_ms"] = now - int(_arena_timing["first_damage_ms"])
		_log_arena_timing("KILL", now)


func _log_arena_timing(event: String, now: int) -> void:
	_log("ARENA_%s run=%s arena_n=%d kind=%s boss=%s mono_ms=%d game_s=%.1f" % [
		event, run_state["run_id"], _arena_timing["arena_n"], _arena_timing["kind"],
		_arena_timing["boss"], now, float(world.time)])


func _handle_victory(now: int) -> void:
	if world == null or not is_instance_valid(world):
		return
	# Morroc ends the run itself once the finale's loot has been collected.
	if world.morroc.finale_won():
		return
	var valhalla: bool = cfg["karma_route"] == "valhalla"
	if valhalla and _wait_for_valhalla(now):
		return
	var new_win := false
	# Count field and arena MVPs alike; raid.state stays "won" after leave().
	var mvps := int(world.run_mvps)
	var last_mvps := int(run_state.get("last_run_mvps", 0))
	var mode := ""
	if world.menus != null and is_instance_valid(world.menus):
		mode = str(world.menus._mode)
	# The game can schedule its victory choice after continue_endless(); that
	# menu belongs to the previous MVP. Close it instead of deadlocking paused.
	if mode == "victory" and bool(world.endless) and int(run_state.get("won_at", 0)) == 0 and mvps <= last_mvps:
		_log("STALE_VICTORY close t=%.1f" % float(world.time))
		world.menus.close()
		get_tree().paused = false
		return
	if mvps > last_mvps:
		run_state["last_run_mvps"] = mvps
		new_win = true
	if mode == "victory" and not bool(world.endless):
		new_win = true
	if new_win:
		run_state["boss_won"] = true
		if int(run_state.get("won_at", 0)) == 0:
			run_state["won_at"] = now
			_log("BOSS_WON t=%.1f mvps=%d wall_ms=%d" % [float(world.time), mvps, now])
			if valhalla:
				run_state["regular_mvp"] = mvps
	# A pending victory must survive frames where `new_win` is false (the MVP
	# counter does not grow every frame and the arena exit has no menu).
	if int(run_state.get("won_at", 0)) == 0:
		return
	world._pull_prizes()
	if now - int(run_state.get("won_at", now)) < VICTORY_PULL_MS:
		return
	if valhalla:
		var regular := int(run_state.get("regular_mvp", 0))
		if regular > int(run_state.get("valhalla_for", 0)):
			run_state["valhalla_for"] = regular
			run_state["valhalla_until"] = now + KARMA_PORTAL_WAIT_MS
			run_state["valhalla_entered"] = false
			var karma = world.karma
			run_state["valhalla_boons"] = int(karma.boons) if is_instance_valid(karma) else 0
			if _wait_for_valhalla(now):
				return
	elif world.karma != null and is_instance_valid(world.karma) \
			and world.karma.has_method("can_route") and bool(world.karma.can_route()) \
			and not bool(run_state.get("route_entered", false)):
		run_state["route_entered"] = true
		var side := str(world.karma.route_side())
		var route_mvp := str(GameData.KARMA_ROUTES.get(side, {}).get("mvp", ""))
		_log("KARMA_ROUTE side=%s mvp=%s" % [side, route_mvp])
		if world.menus != null and is_instance_valid(world.menus) and str(world.menus._mode) == "victory":
			world.menus.close()
		get_tree().paused = false
		world.karma.enter_route()
		run_state["won_at"] = 0
		run_state["boss_won"] = false
		_apply_autopilot()
		return
	if _want_endless():
		if _endless_exhausted():
			_log("ENDLESS_DONE time=%.1f mvps=%d" % [float(world.time), int(run_state.get("endless_mvps", 0))])
			_end_run_safe(true)
		else:
			run_state["endless_mvps"] = int(run_state.get("endless_mvps", 0)) + 1
			_log("ENDLESS_START time=%.1f n=%d" % [float(world.time), int(run_state["endless_mvps"])])
			world.continue_endless()
			run_state["endless_started_at"] = float(world.time)
			run_state["won_at"] = 0
			run_state["boss_won"] = false
			_apply_autopilot()
	else:
		_end_run_safe(true)


# True while the regular MVP's route is pending or its Valkyrie is alive.
func _wait_for_valhalla(now: int) -> bool:
	var until := int(run_state.get("valhalla_until", 0))
	if until == 0:
		return false
	var regular := int(run_state["valhalla_for"])
	var karma = world.karma
	var raid = world.raid
	var has_karma := is_instance_valid(karma)
	var valkyrie := is_instance_valid(raid) and str(raid.mvp) == "reginleif"
	var won: bool = has_karma and valkyrie and raid.state == "won" and karma.route == "" \
			and bool(karma.won_here) and karma.boon == "valhalla" and int(karma.boons) > int(run_state["valhalla_boons"])
	if won or (has_karma and valkyrie and karma.route == "light"):
		if not bool(run_state["valhalla_entered"]):
			run_state["valhalla_entered"] = true
			_log("KARMA_ROUTE side=light mvp=reginleif after_mvp=%d t=%.1f revives=%d falls=%d doom=%s" % [
				regular, float(world.time), world.player.revives, world.player.falls, str(world.player.doom)])
		if not won:
			return true
		run_state["valhalla_until"] = 0
		run_state["last_run_mvps"] = int(world.run_mvps)
		run_state["won_at"] = now
		run_state["valkyrie_kills"] = int(run_state.get("valkyrie_kills", 0)) + 1
		_log("VALKYRIE_KILLED mvp=reginleif after_mvp=%d boons=%d t=%.1f revives=%d falls=%d" % [
			regular, int(karma.boons), float(world.time), world.player.revives, world.player.falls])
		return false
	if bool(run_state["valhalla_entered"]):
		return true
	var reason := ""
	if not has_karma or not karma.can_route() or karma.route_side() != "light":
		reason = "cannot_route"
	elif not is_instance_valid(raid):
		reason = "no_raid"
	elif not raid.in_arena():
		# A field MVP has no exit portals to approach.
		world.menus.close()
		get_tree().paused = false
		karma.enter_route()
		if karma.route == "light":
			return true
		reason = "entry_refused"
	elif now >= until:
		reason = "portal_timeout"
	elif world.menus._mode == "victory":
		reason = "return_portal_entered"
	if reason.is_empty():
		world._pull_prizes()
		return true
	run_state["valhalla_until"] = 0
	_log("KARMA_ROUTE_SKIP side=light after_mvp=%d reason=%s t=%.1f" % [regular, reason, float(world.time)])
	return false


func _want_endless() -> bool:
	if not bool(cfg.get("endless", false)):
		return false
	return true


func _endless_exhausted() -> bool:
	if not bool(world.endless):
		return false
	var mins := float(cfg.get("endless_minutes", 0.0))
	var started := float(run_state.get("endless_started_at", -1.0))
	if mins > 0.0 and started >= 0.0 and float(world.time) - started >= mins * 60.0:
		return true
	var max_mvps := int(cfg.get("endless_mvps", 0))
	if max_mvps > 0 and int(run_state.get("endless_mvps", 0)) >= max_mvps:
		return true
	return false


func _end_run_safe(victory: bool) -> void:
	if world == null or not is_instance_valid(world):
		return
	if not world.running:
		return
	run_state["victory"] = victory
	run_state["native_victory"] = victory
	if _test_verify_wishlist:
		_test_seed_wishlist_offer()
	world._end_run(victory)
	if _tower_intent.is_empty():
		_set_autopilot_flags(false)


func _record_local_progress() -> void:
	var run_id: String = run_state["run_id"]
	if run_state.get("native_progress") == run_id:
		return
	# Recovery only journals the settled result, never re-enters keep.
	run_state["native_progress"] = run_id
	var victory := _tower_intent.is_empty() and bool(run_state.get("native_victory",
		bool(world.endless) if run_state["died"] else run_state["victory"]))
	var p = world.player
	if p != null and not world.training and not p.tampered and not p.stats_plausible():
		p.tampered = true
	# Native log_run also posts telemetry; use only its local writer.
	world.board._keep_history(world, victory)
	var altars_taken := int(world.altars.taken.size())
	if altars_taken > 0:
		Save.bump("altars", altars_taken)
		Save.stat_max("altars_run", altars_taken)
	if not world.training and _tower_intent.is_empty():
		var autopilot: bool = world.autopilot
		var channel = world.channel
		var chat = channel.world_chat if is_instance_valid(channel) else null
		# Titles.news records local notifications; don't let it queue or send chat feats.
		if is_instance_valid(channel):
			channel.world_chat = null
		world.autopilot = false
		world.titles.after_run(world, victory)
		world.autopilot = autopilot
		if is_instance_valid(channel):
			channel.world_chat = chat
	if run_state.has("progress"):
		run_state["progress"].merge({
			"run_id": run_id, "altar_takes": altars_taken, "mvps": world.run_mvps,
			"net_mode": world.net.mode, "autopilot_restored": world.autopilot,
		})


func _on_player_fell(cause: Dictionary, piercing: bool, revives_left: int) -> void:
	if phase != "run":
		return
	var by := str(cause.get("by", ""))
	var what := str(cause.get("what", ""))
	if what.is_empty():
		what = "unknown"
	var counts: Dictionary = run_state["falls_by_mechanic"]
	counts[what] = int(counts.get(what, 0)) + 1
	_log("PLAYER_FELL t=%.1f by=%s what=%s piercing=%s revives_left=%d" % [
		float(world.time), by if not by.is_empty() else "unknown", what, str(piercing), revives_left])


func _begin_settle(now: int) -> void:
	if int(run_state.get("settle_start", 0)) == 0:
		run_state["settle_start"] = now
		var died := false
		var p = world.player
		if p != null and is_instance_valid(p):
			died = bool(p.fell)
		run_state["died"] = run_state.get("died", false) or died
		if not _tower_intent.is_empty():
			run_state["tower_floor_best"] = world.tower.best
			run_state["end_cause"] = "death" if died else ("finish" if _finish_after_run == "finish" else "native_end")
			if _test_tower_run:
				_test_tower_evidence["autopilot_at_end"] = world.autopilot
		# The native end resets Morroc's event; the finale kill increments this
		# stat before settlement, independently of the regular MVP counter.
		var finale_won := _tower_intent.is_empty() and Save.stat("morroc_finale") > float(run_state["morroc_finale_before"])
		if _test_valkyrie and not _test_raid_ability.is_empty():
			_test_log_valkyrie(died)
		if _test_mvp_mechanics and not _test_raid_ability.is_empty():
			_test_log_mvp_mechanic(died)
		if _test_charge and is_instance_valid(_test_charge_enemy):
			_log("FIELD_CHARGE run=%d contacts=%d falls=%d died=%s" % [
				runs_started, int(_test_charge_enemy.brain._dash_hit.has(p)), p.falls, str(died)])
			_test_charge_enemy = null
		run_state["finale_won"] = finale_won
		var victory := not bool(run_state["died"]) and not bool(run_state["forced"]) \
			and (finale_won or bool(run_state["victory"]) or bool(run_state["boss_won"]))
		run_state["victory"] = victory
		if bool(run_state["died"]) and p != null and is_instance_valid(p):
			_log("PLAYER_DIED t=%.1f by=%s what=%s revives=%d falls=%d" % [
				float(world.time), str(p.death_by.get("by", "")), str(p.death_by.get("what", "")), p.revives, p.falls])
		_log("SETTLE victory=%s died=%s endless=%s t=%.1f finale_won=%s" % [
			str(victory), str(bool(run_state["died"])), str(bool(world.endless)), float(world.time), str(finale_won)])
	phase = "settle"
	_mark_transition("settle")
	_check_settle()


func _tick_settle(now: int) -> void:
	_check_settle()
	if phase == "settle" and now - int(run_state.get("settle_start", now)) > SETTLE_WAIT_MS:
		_fail_session("settle_timeout")


func _check_settle() -> void:
	if world == null or not is_instance_valid(world):
		return
	if world.menus != null and is_instance_valid(world.menus):
		var mode := str(world.menus._mode)
		if mode == "end":
			_save_tower_snapshot()
			phase = "keep"
			_write_status()
			return
		if mode == "victory" and not bool(run_state["died"]) and _tower_intent.is_empty():
			# We expected to settle but a victory choice is still open.
			if _want_endless() and not _endless_exhausted():
				run_state["endless_mvps"] = int(run_state.get("endless_mvps", 0)) + 1
				world.continue_endless()
				run_state["endless_started_at"] = float(world.time)
				run_state["boss_won"] = false
				phase = "run"
				_apply_autopilot()
			else:
				_end_run_safe(true)


# ---------------------------------------------------------------------------
# Timeout / watchdog / stop
# ---------------------------------------------------------------------------

func _check_timeout(now: int) -> void:
	if world == null or not is_instance_valid(world):
		return
	var minutes := float(cfg.get("run_minutes", 0.0))
	if minutes > 0.0 and float(world.time) >= minutes * 60.0:
		run_state["forced"] = true
		_results_forced("run_timeout", now)
		return
	var arena_max := float(cfg.get("arena_wall_max", 0.0))
	if arena_max > 0.0 and world.raid != null and is_instance_valid(world.raid):
		var st := str(world.raid.state)
		if st == "fight" or st == "intro" or st == "loading":
			if int(run_state.get("arena_since", 0)) == 0:
				run_state["arena_since"] = now
			elif now - int(run_state["arena_since"]) > int(arena_max * 1000.0):
				run_state["forced"] = true
				_log("ARENA_TIMEOUT state=%s wall=%.1fs" % [st, arena_max])
				_end_run_safe(false)
				return
		else:
			run_state["arena_since"] = 0


func _check_watchdog(now: int) -> void:
	if world == null or not is_instance_valid(world):
		return
	if get_tree().paused:
		if _paused_since_ms == 0:
			_paused_since_ms = now
		var mode := ""
		if world.menus != null and is_instance_valid(world.menus):
			mode = str(world.menus._mode)
		# These menus are owned by the phase handlers; closing them here would
		# race the draft/victory logic.
		if mode == "level_up" or mode == "job_change" or mode == "victory" \
				or mode == "end" or mode == "start_skill":
			_paused_since_ms = now
			return
		var pause_stall_s := float(cfg.get("stall_seconds", 45.0))
		if pause_stall_s <= 0.0:
			return
		if now - _paused_since_ms <= int(pause_stall_s * 1000.0):
			return
		_pause_tries += 1
		_log("PAUSE_STALL mode=%s tries=%d t=%.1f" % [mode, _pause_tries, float(world.time)])
		if world.menus != null and is_instance_valid(world.menus):
			world.menus.close()
		get_tree().paused = false
		_paused_since_ms = 0
		if _pause_tries >= 3:
			run_state["forced"] = true
			_end_run_safe(false)
		return
	_paused_since_ms = 0
	var clock := float(world.clock)
	var t := float(world.time)
	if _test_freeze_run_time and _time_last >= 0.0:
		t = _time_last
	if _clock_last < 0.0 or not is_equal_approx(clock, _clock_last):
		_clock_last = clock
		_clock_change_ms = now
	# Only the in-game watchdog gives Morroc a pass. The supervisor still
	# compares the published game time and enforces its finite stall deadline.
	if _time_last < 0.0 or not is_equal_approx(t, _time_last) or bool(world.morroc.freezes_time()):
		_time_last = t
		_time_change_ms = now
	var stall_s := float(cfg.get("stall_seconds", 45.0))
	if stall_s <= 0.0:
		return
	var frozen_reason := ""
	if world.raid != null and is_instance_valid(world.raid):
		var st := str(world.raid.state)
		if st == "portal" or st == "loading" or st == "intro" or st == "fight" or st == "won":
			frozen_reason = "raid"
	if frozen_reason != "":
		return
	# Engine clock frozen, or the run's own time frozen while the clock ticks
	# (2026-11-19: a run sat at t=640 with no enemies for 6.5 h; the clock-only
	# check never fired and the heartbeat stayed healthy).
	var stalled := ""
	if now - _clock_change_ms > int(stall_s * 1000.0):
		stalled = "STALL"
	elif now - _time_change_ms > int(stall_s * 1000.0):
		stalled = "RUN_STALL"
	if stalled == "":
		return
	_stall_tries += 1
	_log("%s clock=%.1f t=%.1f tries=%d" % [stalled, clock, t, _stall_tries])
	if world.menus != null and is_instance_valid(world.menus):
		world.menus.close()
	get_tree().paused = false
	_clock_change_ms = now
	_time_change_ms = now
	if _stall_tries >= 3:
		run_state["forced"] = true
		_end_run_safe(false)


func _check_command(now: int) -> void:
	var command := ""
	if FileAccess.file_exists(COMMAND_PATH):
		# Claim by rename before reading; a concurrent publisher can safely
		# install the next command without it being removed with this one.
		var path := ProjectSettings.globalize_path(COMMAND_PATH)
		var claimed := path + ".claimed"
		if DirAccess.rename_absolute(path, claimed) == OK:
			command = FileAccess.get_file_as_string(claimed).strip_edges()
			DirAccess.remove_absolute(claimed)
	if FileAccess.file_exists(STOP_PATH) and DirAccess.remove_absolute(ProjectSettings.globalize_path(STOP_PATH)) == OK:
		if command != "abort":
			command = "finish"
	match command:
		"finish":
			_request_finish("finish")
		"abort":
			# Native settlement can finish between farmer ticks.
			if phase == "run" and str(menus._mode) == "end":
				_begin_settle(now)
			elif phase == "settle" and str(menus._mode) == "end":
				_check_settle()
			_finish("abort")
		"resume_settings":
			# The service publishes the new cfg before releasing the pause.
			if phase != "paused":
				return
			if not _load_cfg():
				_fail_session("cfg_invalid")
				return
			if not _validate_run_choice():
				return
			_pause_requested = false
			phase = "idle"
			_mark_transition("resume")
			_write_status()
		"pause", "resume":
			_pause_requested = command == "pause"
			if phase == "idle" or phase == "paused":
				phase = "paused" if _pause_requested else "idle"
				_mark_transition(command)
				_write_status()
		"":
			pass
		_:
			_log("COMMAND ignored: " + command)


func _check_limits(now: int) -> void:
	if _finish_after_run != "" or not _tower_kind.is_empty():
		return
	var max_minutes := float(cfg.get("max_minutes", 0.0))
	if max_minutes > 0.0 and now - boot_ms >= int(max_minutes * 60000.0):
		_log("STOP max_minutes")
		_request_finish("stop")
	elif int(cfg.get("max_runs", 0)) > 0 and runs_done >= int(cfg.get("max_runs", 0)):
		_log("STOP max_runs")
		_request_finish("stop")
	elif int(cfg.get("stop_after_wins", 0)) > 0 and wins >= int(cfg.get("stop_after_wins", 0)):
		_log("STOP stop_after_wins")
		_request_finish("stop")


func _request_finish(reason: String) -> void:
	_finish_after_run = reason
	if phase == "run" and world.running:
		run_state["forced"] = true
		run_state["force_reason"] = reason
		if _tower_intent.is_empty():
			_end_run_safe(false)
	elif phase == "idle" or phase == "paused":
		_finish(reason)


func _results_forced(reason: String, now: int) -> void:
	_log("FORCE %s t=%.1f" % [reason, float(world.time)])
	run_state["forced"] = true
	run_state["force_reason"] = reason
	_end_run_safe(false)


# ---------------------------------------------------------------------------
# Level-up draft
# ---------------------------------------------------------------------------

func _draft_player() -> void:
	# Menus.auto_pick is needed for loot and job dialogs, but uses Bot.pick_choice
	# for levels. Run before the World tick and let its native timer pace picks.
	if world.running and world.player.pending_levels > 0 and world._level_up_delay <= 0.0 \
			and not world.busy() and not world.loot_waits_for_me():
		world._auto_pick()

func _handle_job_change(h) -> void:
	if h == null or not is_instance_valid(h):
		return
	if not h.can_job_change():
		return
	var cid := str(h.class_id)
	var path := _job_path(cid)
	if h == world.player:
		world.do_job_change(path)
	else:
		h.job_change(path)
	var want := _preferred_start_skill(h)
	if want != "":
		h.set_job_skill(want)
	_log("JOB class=%s path=%d job=%s skill=%s" % [cid, path, str(h.job2.get("id", "")), want])


func _preferred_start_skill(h) -> String:
	var prio: Array = h.pick_order()
	if prio.is_empty():
		var build = cfg["builds"].get(str(h.class_id), {})
		if build is Dictionary:
			prio = build.get("skills", [])
	var opts: Array = h.job_start_options()
	for id in prio:
		var sid := str(id)
		if opts.has(sid):
			return sid
	return ""


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

func steer(hero) -> Vector2:
	if world == null or not is_instance_valid(world) or not world.running:
		return Vector2.ZERO
	if hero == null or not is_instance_valid(hero):
		return Vector2.ZERO
	if bool(hero.downed) or bool(hero.fell):
		return Vector2.ZERO
	if get_tree().paused:
		return Vector2.ZERO
	var raid: MvpRaid = world.raid
	if world.tower != null:
		return _steer_tower(hero, raid)
	var move := _steer_movement(hero)
	if raid.state == "fight" and is_instance_valid(raid.boss):
		return _avoid_raid_hazards(hero, move, raid)
	if raid.state in ["idle", "won", "portal"] and not raid.in_arena() and not world.morroc.active():
		var safe := _avoid_field_hazards(hero, move)
		if safe != move:
			_field_progress = float(world.clock)
			return safe
	return move


func _steer_tower(hero: Player, raid: MvpRaid) -> Vector2:
	if raid.state == "won" and raid.in_arena():
		if _tower_collecting_prizes():
			return Vector2.ZERO
		var exit := raid.autopilot_goal(hero)
		if exit != Vector3.INF:
			var direct := (exit - hero.position) * Vector3(1.0, 0.0, 1.0)
			if direct.length_squared() > 0.09:
				return _steer_direct(hero.position, exit, direct)
			return Vector2.ZERO
	var preferred: Vector2 = world.autopilot_input()
	if raid.state == "fight" and is_instance_valid(raid.boss):
		if raid.epic != null and raid.epic.hel != null and raid.autopilot_goal(hero) == Vector3.INF:
			var soul := _tower_soul_goal(hero, raid)
			if soul != Vector3.INF:
				preferred = _field_input(hero, soul)
		return _avoid_raid_hazards(hero, preferred, raid)
	if raid.in_arena():
		return preferred
	var tower: TowerRun = world.tower
	if tower.hel != null and tower.state == "fight":
		var fog = world.hell_late
		var center: Vector3 = fog.fog_center if fog.fog_on else Vector3.INF
		var safe_radius: float = fog.fog_radius - HAZARD_MARGIN if fog.fog_on else 0.0
		var at := hero.position
		var goal := Vector3.INF
		var nearest := INF
		for portal: Dictionary in tower.hel.portals:
			if center != Vector3.INF and _flat_distance(portal.at, center) >= safe_radius:
				continue
			# Finish a channel already underway before choosing another portal.
			var distance := _flat_distance(at, portal.at)
			var rank := distance - float(portal.fill) * GameData.HEL_PORTAL_REACH
			if rank < nearest:
				nearest = rank
				goal = portal.at
		if goal != Vector3.INF:
			preferred = Vector2.ZERO if _flat_distance(at, goal) < GameData.HEL_PORTAL_REACH - HAZARD_MARGIN \
				else _steer_field(hero, world.map, goal)
		return _avoid_field_hazards(hero, preferred, center, Vector3(0.0, safe_radius, 0.0))
	return _avoid_field_hazards(hero, preferred)


func _tower_soul_goal(hero: Player, raid: MvpRaid) -> Vector3:
	var hel = raid.epic.hel
	var best := Vector3.INF
	var nearest := INF
	for soul: Dictionary in hel._souls.values():
		var along: Vector3 = (raid.boss.position - soul.at) * Vector3(1.0, 0.0, 1.0)
		var distance := _flat_distance(hero.position, soul.at)
		var travel := distance / maxf(1.0, hero.move_speed)
		var intercept := minf(along.length(), travel * float(hel.cfg.soul_speed))
		if intercept + raid.boss.radius + 0.8 >= along.length():
			continue # Already too close to Naght to intercept.
		if distance < nearest:
			nearest = distance
			best = soul.at + along.normalized() * intercept
	return best


func _avoid_field_hazards(hero: Player, preferred: Vector2, safe_center := Vector3.INF,
		safe_bound := Vector3.ZERO) -> Vector2:
	var at := hero.position
	var look := clampf(hero.move_speed * 0.35, 2.5, 4.0)
	var threats := PackedVector3Array()
	for foe: Enemy in world.enemies_in_radius(at, 24.0):
		if foe.dead or foe.brain == null:
			continue
		var brain: BossBrain = foe.brain
		match brain._state:
			"slam":
				var reach := clampf(hero.move_speed * 0.65, 4.0, 7.0)
				for target in brain._targets:
					if _flat_distance(at, target) < reach + FIELD_SLAM_RADIUS + HAZARD_MARGIN:
						look = maxf(look, reach)
						_add_hazard(threats, target, target, FIELD_SLAM_RADIUS)
			"windup", "dash":
				if brain._dash_dir.is_zero_approx() or (brain._state == "dash" and brain._dash_hit.has(hero)):
					continue
				var duration := FIELD_CHARGE_DURATION if brain._state == "windup" else brain._state_time
				_add_dash_hazard(threats, at, foe, foe.position, brain._dash_dir, duration, look)
	return _avoid_hazards(hero, preferred, threats, look, null, safe_center, safe_bound)


func _avoid_raid_hazards(hero: Player, preferred: Vector2, raid: MvpRaid) -> Vector2:
	var threats := PackedVector3Array()
	var at := hero.position
	var look := clampf(hero.move_speed * 0.70, 4.0, 7.0)
	var cast: Dictionary = raid._cast
	if not cast.is_empty():
		match str(cast.ab.mech):
			"slam", "rain", "puddles":
				for target in cast.targets:
					_add_hazard(threats, target, target, float(cast.ab.size))
			"charge":
				_add_dash_hazard(threats, at, raid.boss, cast["from"], cast.dir, FIELD_CHARGE_DURATION, look)
			"volley":
				_add_volley_hazards(threats, raid, cast)
			"spokes":
				_add_spoke_hazards(threats, cast["from"], cast.base, raid._spoke_count(cast.ab), cast.ab.width, raid.radius)
	for attack: Dictionary in raid._objects:
		match str(attack.kind):
			"volley_wave":
				_add_volley_hazards(threats, raid, attack)
			"spoke_wave":
				_add_spoke_hazards(threats, attack["from"], attack.base, raid._spoke_count(attack.ab), attack.ab.width, raid.radius)
			"dash":
				if not attack.hit.has(hero):
					_add_dash_hazard(threats, at, raid.boss, raid.boss.position, attack.dir, float(attack.t), look)
			"puddle":
				_add_hazard(threats, attack.pos, attack.pos, float(attack.ab.size))
			"leap":
				if attack.stage in ["air", "lock"]:
					_add_hazard(threats, attack.at, attack.at, float(attack.ab.size) + 0.3)
				elif attack.stage == "rifts":
					_add_spoke_hazards(threats, attack.at, attack.base, attack.ab.rifts, attack.ab.width, raid.radius)
			"starfall":
				preferred = _kite_starfall(hero, raid)
	if raid.epic != null and raid.epic.hel != null:
		var judge: Dictionary = raid.epic.hel._judge
		if not judge.is_empty() and judge.marks.has(hero):
			var safe_normal: Vector3 = -judge.n if judge.marks[hero].kind == "fire" else judge.n
			return _avoid_hazards(hero, preferred, threats, look, raid, raid.center, safe_normal)
	return _avoid_hazards(hero, preferred, threats, look, raid)


func _add_volley_hazards(threats: PackedVector3Array, raid: MvpRaid, wave: Dictionary) -> void:
	var dir: Vector3 = wave.d
	var side := Vector3(-dir.z, 0.0, dir.x)
	for off in wave.lanes:
		var at := raid.center + side * float(off)
		_add_hazard(threats, at - dir * raid.radius, at + dir * raid.radius, float(wave.ab.width) * 0.5)


func _add_spoke_hazards(threats: PackedVector3Array, from: Vector3, base: float, count: int,
		width: float, radius: float) -> void:
	for i in count:
		var angle := base + TAU * i / float(count)
		var dir := Vector3(cos(angle), 0.0, sin(angle))
		_add_hazard(threats, from, from + dir * (radius * 2.2), width * 0.5 + 0.3)


func _add_dash_hazard(threats: PackedVector3Array, hero_at: Vector3, foe: Enemy, from: Vector3,
		dir: Vector3, duration: float, look: float) -> void:
	from.y = 0.0
	var final_tick := 0.05 * GameData.GAME_FAST_SPEED
	var to := from + dir * FIELD_CHARGE_SPEED * (maxf(0.0, duration) + final_tick)
	var radius := foe.radius + 1.0
	if _hazard_clearance(hero_at, from, to, radius + HAZARD_MARGIN) <= look:
		_add_hazard(threats, from, to, radius)


func _add_hazard(threats: PackedVector3Array, from: Vector3, to: Vector3, radius: float) -> void:
	# Every tell is a horizontal segment plus padding; a disc is a zero-length segment.
	threats.append(Vector3(from.x, 0.0, from.z))
	threats.append(Vector3(to.x, 0.0, to.z))
	threats.append(Vector3(radius + HAZARD_MARGIN, 0.0, 0.0))


func _avoid_hazards(hero: Player, preferred: Vector2, threats: PackedVector3Array, look: float,
		raid: MvpRaid = null, safe_center := Vector3.INF, safe_bound := Vector3.ZERO) -> Vector2:
	if threats.is_empty() and safe_center == Vector3.INF:
		return preferred
	var at := hero.position
	var map: RoMap = world.map
	var intended := Vector3(preferred.x, 0.0, preferred.y) * look
	var standing := _hazard_path_clearance(at, Vector3.ZERO, threats, safe_center, safe_bound)
	var escaping := standing < 0.0
	if _hazard_path_clearance(at, intended, threats, safe_center, safe_bound) >= 0.0 \
			and (not escaping or (
				_hazard_path_clearance(at, intended.limit_length(0.75), threats, safe_center, safe_bound) > standing + 0.25
				and not _hazard_step_blocked(map, at, at + intended, raid))):
		return preferred
	var best := Vector2.ZERO
	var score := minf(standing, 0.55) * 4.0
	for i in 24:
		var dir := Vector2.RIGHT.rotated(float(i) * TAU / 24.0)
		var progress := 0.0
		if escaping:
			progress = _hazard_path_clearance(at, Vector3(dir.x, 0.0, dir.y) * 0.75, threats, safe_center, safe_bound) - standing
		for sample in 3:
			var length := look * (1.0 - 0.35 * sample)
			var step := Vector3(dir.x, 0.0, dir.y) * length
			if _hazard_step_blocked(map, at, at + step, raid):
				continue
			var gap := _hazard_path_clearance(at, step, threats, safe_center, safe_bound)
			if standing >= 0.0 and gap < 0.0:
				continue
			# Safe endpoints alone can cause alternating moves without getting clear.
			var candidate := minf(gap, 0.55) * 4.0 + progress * 8.0 + 0.35 * dir.dot(preferred) - 0.025 * length
			if candidate > score:
				score = candidate
				best = _field_input(hero, at + step)
	return best


func _hazard_step_blocked(map: RoMap, at: Vector3, to: Vector3, raid: MvpRaid) -> bool:
	if raid != null:
		if _flat_distance(to, raid.center) > raid.radius \
				and _flat_distance(to, raid.center) >= _flat_distance(at, raid.center):
			return true
		var start := Vector3(at.x, 0.0, at.z)
		var end := Vector3(to.x, 0.0, to.z)
		for pillar: Dictionary in raid._pillars:
			if _hazard_clearance(pillar.pos, start, end, 0.83) < 0.0 and _flat_distance(at, pillar.pos) > 0.83:
				return true
	return _field_line_blocked(map, at, to, Vector3.INF)


func _hazard_path_clearance(at: Vector3, step: Vector3, threats: PackedVector3Array,
		safe_center := Vector3.INF, safe_bound := Vector3.ZERO) -> float:
	at.y = 0.0
	var to := at + step
	var gap := INF
	if safe_center != Vector3.INF:
		# Convex safe zone: a horizontal normal for Judgement, or a radius in y for fog.
		var initial := _safe_zone_clearance(at, safe_center, safe_bound)
		gap = _safe_zone_clearance(to, safe_center, safe_bound)
		if initial >= 0.0:
			gap = minf(initial, gap)
	for i in range(0, threats.size(), 3):
		var start := threats[i]
		var end := threats[i + 1]
		var radius := threats[i + 2].x
		var finish := _hazard_clearance(to, start, end, radius)
		# An escape may start inside a tell, but a safe path must not cross one.
		var initial := _hazard_clearance(at, start, end, radius)
		if initial >= 0.0 and step != Vector3.ZERO:
			finish = minf(finish, initial)
			finish = minf(finish, minf(_hazard_clearance(start, at, to, radius), _hazard_clearance(end, at, to, radius)))
			var line := end - start
			var cross := step.cross(line).y
			if not is_zero_approx(cross):
				var across := (start - at).cross(step).y / cross
				var along := (start - at).cross(line).y / cross
				if along >= 0.0 and along <= 1.0 and across >= 0.0 and across <= 1.0:
					finish = -radius
		gap = minf(gap, finish)
	return gap


func _safe_zone_clearance(at: Vector3, center: Vector3, bound: Vector3) -> float:
	if bound.y > 0.0:
		return bound.y - _flat_distance(at, center)
	return (at - center).dot(bound) - HAZARD_MARGIN


func _hazard_clearance(point: Vector3, start: Vector3, end: Vector3, radius: float) -> float:
	point.y = 0.0
	var nearest := start if start == end else Geometry3D.get_closest_point_to_segment(point, start, end)
	return point.distance_to(nearest) - radius


func _break_guard_goal(hero: Player, raid: MvpRaid) -> Vector3:
	var best := Vector3.INF
	var gap := INF
	for attack: Dictionary in raid._objects:
		if attack.kind != "break":
			continue
		for guard: Enemy in attack.adds:
			if not is_instance_valid(guard) or guard.dead:
				continue
			var distance := _flat_distance(hero.position, guard.position)
			if distance < gap:
				best = guard.position
				gap = distance
	return best


func _steer_movement(hero) -> Vector2:
	var map: RoMap = world.map
	var at: Vector3 = hero.position
	var arena: bool = world.raid.in_arena()
	if not arena and map.get_instance_id() != _field_map_id:
		_field_map_id = map.get_instance_id()
		_field_path.clear()
		_field_failed.clear()
		_field_clearance.clear()
		_field_exit.clear()
		_altar_routes.clear()
	_raid_goal = false
	_field_portal = Vector3.INF
	var goal := _steer_goal(hero)
	if _raid_goal:
		_field_path.clear()
		var to := goal - at
		to.y = 0.0
		if to.length_squared() >= 0.45 * 0.45:
			return _steer_direct(at, goal, to)
		_direct_progress_ms = -1
		return Vector2.ZERO
	_direct_progress_ms = -1
	if goal != Vector3.INF:
		if _flat_distance(at, goal) < FIELD_TURN_RADIUS:
			_field_path.clear()
			return Vector2.ZERO
		var field_move := _steer_field(hero, map, goal)
		if not field_move.is_zero_approx():
			return field_move
	else:
		_field_path.clear()
	return Bot.steer(world, Vector3.INF, hero) if arena else _steer_open_ground(hero, map)


func _kite_starfall(hero: Player, raid) -> Vector2:
	# Each mark locks to the hero's current position. Keep moving along a
	# wide arc inside the arena so the rim cannot force a stop or reversal.
	var offset: Vector3 = hero.position - raid.center
	var radial := Vector2(offset.x, offset.z)
	var distance := radial.length()
	if distance < 0.1:
		return Vector2.RIGHT
	radial /= distance
	# Reginleif's crystals sit at 55% radius; orbit beyond them.
	var turn := clampf((float(raid.radius) * 0.7 - distance) * 0.3, -2.0, 2.0)
	return (Vector2(-radial.y, radial.x) + radial * turn).normalized()


func _steer_direct(at: Vector3, goal: Vector3, direct: Vector3) -> Vector2:
	var map: RoMap = world.map
	var map_id := map.get_instance_id()
	var tile := map.tile_of(goal)
	var now := _now()
	if map_id != _direct_map_id:
		_direct_map_id = map_id
		_direct_grid = null
		_direct_progress_ms = -1
	if _direct_progress_ms < 0 or tile != _direct_tile:
		_direct_tile = tile
		_direct_path.clear()
		_direct_best_dist = INF
	var to := direct
	var detouring := _direct_step < _direct_path.size() - 1
	if detouring:
		var cell := _direct_path[_direct_step]
		to = map.cell_center(cell.x, cell.y) - at
		to.y = 0.0
		if to.length_squared() < 0.35 * 0.35:
			_direct_step += 1
			_direct_best_dist = INF
			detouring = _direct_step < _direct_path.size() - 1
			to = direct
			if detouring:
				cell = _direct_path[_direct_step]
				to = map.cell_center(cell.x, cell.y) - at
				to.y = 0.0
	var distance := to.length()
	if distance <= _direct_best_dist - 0.25:
		_direct_best_dist = distance
		_direct_progress_ms = now
	elif now - _direct_progress_ms >= DIRECT_STALL_MS:
		_direct_best_dist = INF
		var from := map.tile_of(at)
		if detouring or _direct_line_blocked(map, at, direct, from, tile):
			_direct_path = _direct_tile_path(map, from, tile)
			_direct_step = 1
			if _direct_path.size() > 2:
				_log("DIRECT_DETOUR tiles=%d" % _direct_path.size())
	# Slow down at intermediate tile centers so a fast hero can turn there.
	return Vector2(to.x, to.z) / distance * (minf(1.0, distance * 2.0) if detouring else 1.0)


func _field_line_blocked(map: RoMap, at: Vector3, goal: Vector3, avoid: Vector3) -> bool:
	if avoid != Vector3.INF:
		var start := Vector3(at.x, 0.0, at.z)
		var end := Vector3(goal.x, 0.0, goal.z)
		var center := Vector3(avoid.x, 0.0, avoid.z)
		if Geometry3D.get_closest_point_to_segment(center, start, end).distance_squared_to(center) < PORTAL_CLEARANCE * PORTAL_CLEARANCE:
			return true
	return _direct_line_blocked(map, at, goal - at, map.tile_of(at), map.tile_of(goal))


func _field_plan(map: RoMap, at: Vector3, goal: Vector3, avoid := Vector3.INF) -> PackedVector3Array:
	var path := PackedVector3Array()
	if not map.is_walkable(at) or not map.is_walkable(goal):
		return path
	if not _field_line_blocked(map, at, goal, avoid):
		path.append(goal)
		return path
	var cells := _direct_tile_path(map, map.tile_of(at), map.tile_of(goal), avoid)
	if cells.size() < 2:
		return path
	# Keep corners, not each tile. Center the first segment when the actual
	# sub-tile start cannot see its corner without clipping an inner wall.
	var first := map.cell_center(cells[0].x, cells[0].y)
	var last := at
	for i in range(1, cells.size()):
		if i < cells.size() - 1 and cells[i] - cells[i - 1] == cells[i + 1] - cells[i]:
			continue
		var point := map.cell_center(cells[i].x, cells[i].y)
		if i == cells.size() - 1 and not _field_line_blocked(map, last, goal, avoid):
			path.append(goal)
			return path
		if _field_line_blocked(map, last, point, avoid):
			if not path.is_empty() or _field_line_blocked(map, at, first, avoid) \
					or _field_line_blocked(map, first, point, avoid):
				return PackedVector3Array()
			path.append(first)
		path.append(point)
		last = point
	if _field_line_blocked(map, last, goal, avoid):
		return PackedVector3Array()
	path.append(goal)
	return path


func _steer_field(hero: Player, map: RoMap, goal: Vector3) -> Vector2:
	var at := hero.position
	var tile := map.tile_of(goal)
	var now := float(world.clock)
	var map_id := map.get_instance_id()
	var new_goal := _field_path.is_empty() or tile != _field_tile or map_id != _field_path_map_id \
			or _field_portal != _field_path_portal
	var blocked := false
	var stalled := false
	if not new_goal:
		_field_path[_field_path.size() - 1] = goal
		if _field_step < _field_path.size() - 1 and _flat_distance(at, _field_path[_field_step]) < FIELD_TURN_RADIUS \
				and not _field_line_blocked(map, at, _field_path[_field_step + 1], _field_portal):
			_field_step += 1
			_field_best_dist = INF
		blocked = _field_line_blocked(map, at, _field_path[_field_step], _field_portal)
		stalled = now - _field_progress >= FIELD_STALL_S
	if new_goal or blocked or stalled:
		if blocked or stalled:
			# A stalled turn can also mean the next segment changed.
			_direct_grid = null
			_altar_routes.clear()
			_field_clearance.clear()
		var retry := not new_goal and _field_replanned
		_field_replanned = not new_goal
		if retry:
			_field_path.clear()
		elif new_goal and at == _altar_route_at and _field_portal == _altar_route_portal and _altar_routes.has(goal):
			_field_path = _altar_routes[goal]
		else:
			_field_path = _field_plan(map, at, goal, _field_portal)
		_field_step = 0
		_field_tile = tile
		_field_path_map_id = map_id
		_field_path_portal = _field_portal
		_field_best_dist = INF
		if _field_path.is_empty():
			_field_failed[tile] = now + 2.0
			return Vector2.ZERO
	var distance := _flat_distance(at, _field_path[_field_step])
	if distance < _field_best_dist - 0.12:
		_field_best_dist = distance
		_field_progress = now
	# Stay on the centerline at turns even at the game's maximum frame delta.
	return _field_input(hero, _field_path[_field_step])


func _field_input(hero: Player, goal: Vector3) -> Vector2:
	var to := Vector2(goal.x - hero.position.x, goal.z - hero.position.z)
	return to / maxf(to.length(), 0.05 * GameData.GAME_FAST_SPEED * maxf(1.0, hero.move_speed))


func _field_goal_available(goal: Vector3) -> bool:
	if goal == Vector3.INF:
		return false
	var map: RoMap = world.map
	var tile := map.tile_of(goal)
	if _field_failed.has(tile):
		if float(world.clock) < float(_field_failed[tile]):
			return false
		_field_failed.erase(tile)
	return map.cell_walkable(tile.x, tile.y)


func _direct_line_blocked(map: RoMap, at: Vector3, to: Vector3, cell: Vector2i, end: Vector2i) -> bool:
	# Visit the exact tiles crossed by the flat segment, not a sampled ray.
	var center := map.cell_center(cell.x, cell.y)
	var sx := int(signf(to.x))
	var sy := -int(signf(to.z))
	var dx := 1.0 / absf(to.x) if sx != 0 else INF
	var dy := 1.0 / absf(to.z) if sy != 0 else INF
	var x := (0.5 + (center.x - at.x) * sx) * dx if cell.x != end.x else INF
	var y := (0.5 - (center.z - at.z) * sy) * dy if cell.y != end.y else INF
	while cell != end:
		if is_equal_approx(x, y) and (not map.cell_walkable(cell.x + sx, cell.y) \
				or not map.cell_walkable(cell.x, cell.y + sy)):
			return true
		if x <= y:
			cell.x += sx
			x = x + dx if cell.x != end.x else INF
		else:
			cell.y += sy
			y = y + dy if cell.y != end.y else INF
		if not map.cell_walkable(cell.x, cell.y):
			return true
	return false


func _direct_tile_path(map: RoMap, from: Vector2i, to: Vector2i, avoid := Vector3.INF) -> Array[Vector2i]:
	var bounds := Rect2i(1, 1, map.width - 2, map.height - 2)
	if not bounds.has_point(from) or not bounds.has_point(to):
		return []
	if map.get_instance_id() != _direct_map_id:
		_direct_map_id = map.get_instance_id()
		_direct_grid = null
		_direct_progress_ms = -1
	# Native steering has no waypoint route; use the same walkability as Player.
	if _direct_grid == null:
		_direct_grid = AStarGrid2D.new()
		_direct_grid.region = bounds
		_direct_grid.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_NEVER
		_direct_grid.default_estimate_heuristic = AStarGrid2D.HEURISTIC_MANHATTAN
		_direct_grid.update()
		for y in range(1, map.height - 1):
			for x in range(1, map.width - 1):
				if not map.cell_walkable(x, y):
					_direct_grid.set_point_solid(Vector2i(x, y))
	if _direct_grid.is_point_solid(from) or _direct_grid.is_point_solid(to):
		return []
	if avoid != Vector3.INF:
		# Leave room for a cardinal segment between two safe cell centers.
		var center := map.tile_of(avoid)
		var masked: Array[Vector2i] = []
		for y in range(center.y - 2, center.y + 3):
			for x in range(center.x - 2, center.x + 3):
				var cell := Vector2i(x, y)
				if cell != from and cell != to and bounds.has_point(cell) and not _direct_grid.is_point_solid(cell) \
						and _flat_distance(map.cell_center(x, y), avoid) < PORTAL_CLEARANCE + 0.25:
					_direct_grid.set_point_solid(cell)
					masked.append(cell)
		var path := _direct_grid.get_id_path(from, to)
		for cell in masked:
			_direct_grid.set_point_solid(cell, false)
		return path
	return _direct_grid.get_id_path(from, to)

func _build_field_clearance(map: RoMap) -> void:
	var width := map.width
	var height := map.height
	var size := width * height
	_field_clearance.resize(size)
	_field_exit.resize(size)
	_field_exit.fill(0)
	var queue := PackedInt32Array()
	queue.resize(size)
	var end := 0
	for y in height:
		for x in width:
			var i := y * width + x
			var room := 0
			if map.cell_walkable(x, y):
				room = 1
				if x > 1 and y > 1 and x < width - 2 and y < height - 2 \
						and map.blocked_in(x - 1, y - 1, x + 1, y + 1) == 0:
					room = 2
					if x > 2 and y > 2 and x < width - 3 and y < height - 3 \
							and map.blocked_in(x - 2, y - 2, x + 2, y + 2) == 0:
						room = FIELD_OPEN
						queue[end] = i
						end += 1
			_field_clearance[i] = room
	# Flood outward from open cells so even a long cul-de-sac has an exit
	# direction, not just a local clearance score with a dead-end maximum.
	var start := 0
	var offsets := [1, width, -1, -width]
	while start < end:
		var i := queue[start]
		start += 1
		for dir in offsets.size():
			var n: int = i + offsets[dir]
			if _field_clearance[n] == 0 or _field_clearance[n] == FIELD_OPEN or _field_exit[n] != 0:
				continue
			_field_exit[n] = (dir + 2) % 4 + 1
			queue[end] = n
			end += 1


func _steer_open_ground(hero: Player, map: RoMap) -> Vector2:
	if _field_clearance.is_empty():
		_build_field_clearance(map)
	var at := hero.position
	var cell := map.tile_of(at)
	if not Rect2i(1, 1, map.width - 2, map.height - 2).has_point(cell):
		return Bot.steer(world, Vector3.INF, hero)
	var index := cell.y * map.width + cell.x
	var exit := _field_exit[index]
	if exit != 0 and _field_clearance[index] == 1:
		var next: Vector2i = cell + FIELD_NEIGHBORS[exit - 1]
		var goal := map.cell_center(next.x, next.y)
		if not _field_line_blocked(map, at, goal, Vector3.INF):
			return _field_input(hero, goal)
		_field_clearance.clear()
		return Vector2.ZERO
	var preferred := Bot.steer(world, Vector3.INF, hero)
	if preferred != Vector2.ZERO and _open_room_ahead(map, at, preferred) == FIELD_OPEN:
		return preferred
	var best := Vector2.ZERO
	var best_score := -INF
	for i in 16:
		var dir := Vector2.RIGHT.rotated(float(i) * TAU / 16.0)
		var room := _open_room_ahead(map, at, dir)
		if room == 0:
			continue
		var score := float(room) + 1.6 * dir.dot(preferred)
		if score > best_score:
			best_score = score
			best = dir
	if best != Vector2.ZERO:
		return best
	# An entirely cramped component might not have a five-by-five opening.
	for d in FIELD_NEIGHBORS:
		var next: Vector2i = cell + d
		if map.cell_walkable(next.x, next.y):
			var goal := map.cell_center(next.x, next.y)
			if not _field_line_blocked(map, at, goal, Vector3.INF):
				return _field_input(hero, goal)
	return Vector2.ZERO


func _open_room_ahead(map: RoMap, at: Vector3, dir: Vector2) -> int:
	var step := Vector3(dir.x, 0.0, dir.y)
	var ahead := at + step * 2.5
	if _field_line_blocked(map, at, ahead, Vector3.INF):
		return 0
	var mid := map.tile_of(at + step * 1.25)
	var end := map.tile_of(ahead)
	return mini(_field_clearance[mid.y * map.width + mid.x], _field_clearance[end.y * map.width + end.x])



func _steer_goal(hero) -> Vector3:
	var raid = world.raid
	var map_wide: bool = cfg["altar_policy"] == "map-wide" and not (raid != null and raid.in_arena())
	if raid != null and is_instance_valid(raid):
		var st := str(raid.state)
		if st == "won" and cfg["karma_route"] == "valhalla" and raid._kportal_pos != Vector3.INF:
			_raid_goal = true
			if int(run_state.get("valhalla_until", 0)) > 0:
				return _karma_portal_goal(hero, raid)
			return hero.position
		if map_wide and st == "portal":
			var baldur := _altar_hold_goal(hero, true)
			if baldur == Vector3.INF:
				baldur = _map_altar_goal(hero, true)
			if baldur != Vector3.INF:
				_field_portal = raid.portal_pos
				return baldur
		if st == "fight" or st == "portal" or st == "intro" or st == "loading":
			var g: Vector3 = raid.autopilot_goal(hero)
			if g != Vector3.INF:
				_raid_goal = true
				return g
		if st == "fight":
			var guard := _break_guard_goal(hero, raid)
			if guard != Vector3.INF:
				_raid_goal = true
				return guard
	if map_wide:
		var hold := _altar_hold_goal(hero)
		if hold != Vector3.INF:
			return hold
	var morroc_goal: Vector3 = world.morroc.autopilot_goal()
	if morroc_goal != Vector3.INF:
		_raid_goal = true
		return morroc_goal
	var runner = world.runner
	if runner != null and is_instance_valid(runner) and not bool(runner.dead):
		var rp: Vector3 = runner.position
		if _field_goal_available(rp) and (_flat_distance(rp, hero.position) <= 40.0 or _following_field_goal(rp)):
			return rp
	if map_wide:
		var close_pick := _best_pickup(hero, GameData.ALTAR_RADIUS)
		if close_pick != Vector3.INF:
			return close_pick
		var altar := _map_altar_goal(hero)
		if altar != Vector3.INF:
			return altar
	var pick := _best_pickup(hero)
	if pick != Vector3.INF:
		return pick
	if cfg["altar_policy"] != "map-wide":
		var altar := _best_altar(hero)
		if altar != Vector3.INF:
			return altar
	if world.quest != null and is_instance_valid(world.quest):
		var qg: Vector3 = world.quest.autopilot_goal()
		if _field_goal_available(qg):
			return qg
	var hp_ratio := float(hero.hp) / maxf(1.0, float(hero.max_hp))
	if hp_ratio < 0.25:
		var away := _retreat_point(hero)
		if _field_goal_available(away):
			return away
	return Vector3.INF

func _following_field_goal(goal: Vector3) -> bool:
	var map: RoMap = world.map
	return not _field_path.is_empty() and map.get_instance_id() == _field_path_map_id and map.tile_of(goal) == _field_tile



func _best_pickup(hero, max_dist := INF) -> Vector3:
	var best := Vector3.INF
	var best_score := -1.0e30
	var pickups: Array = world.pickups
	for pk in pickups:
		if not (pk is Dictionary):
			continue
		var node = pk.get("node", null)
		if node == null or not is_instance_valid(node):
			continue
		var kind := str(pk.get("kind", ""))
		var prio := _pickup_priority(kind)
		if prio <= 0.0:
			continue
		var at: Vector3 = node.position
		var dist := Vector2(at.x - hero.position.x, at.z - hero.position.z).length()
		var limit := 10.0
		if kind == "chest":
			limit = 25.0
		elif kind == "card" or kind == "tame" or kind == "unique" or kind == "branch" or kind == "power":
			limit = 22.0
		elif kind == "ore":
			limit = 14.0
		if dist > minf(limit, max_dist) and not (max_dist == INF and _following_field_goal(at)):
			continue
		if not _field_goal_available(at):
			continue
		var score := prio - dist * 2.0
		if kind == "chest":
			score += float(pk.get("value", 1)) * 2.0
		if score > best_score:
			best_score = score
			best = at
	return best


func _pickup_priority(kind: String) -> float:
	match kind:
		"chest":
			return 120.0
		"card", "tame", "unique":
			return 110.0
		"branch", "power":
			return 80.0
		"ore":
			return 60.0
		"loot":
			return 30.0
		"xp":
			return 8.0
	return 0.0


func _best_altar(hero) -> Vector3:
	if hero.hp < float(hero.max_hp) * 0.7:
		return Vector3.INF
	if world.raid != null and world.raid.in_arena():
		return Vector3.INF
	var priority: Array = cfg.get("altar_priority", [])
	var range_max := float(cfg.get("altar_range", 12.0))
	var taken: Array = world.altars.taken
	var best := Vector3.INF
	var best_rank := 9999
	var best_dist := 1.0e30
	for a in world.altars.waiting:
		if not (a is Dictionary):
			continue
		var aid := str(a.get("id", ""))
		var d: Dictionary = GameData.ALTARS.get(aid, {})
		if d.is_empty():
			continue
		if d.has("npc"):
			continue
		var free := str(d.get("bad", "")) == ""
		if not free and taken.size() >= 3:
			continue
		var pos: Vector3 = a.get("pos", hero.position)
		var dist := _flat_distance(pos, hero.position)
		if dist > range_max:
			continue
		if world.enemies_in_radius(pos, 5.0).size() > 8:
			continue
		var rank := priority.find(aid)
		if rank < 0:
			rank = 1000
		var travel := _altar_travel(hero, pos, pos, Vector3.INF)
		if travel == INF or not _altar_lasts(hero, a, travel, world.raid.state == "portal"):
			continue
		if rank < best_rank or (rank == best_rank and travel < best_dist):
			best_rank = rank
			best_dist = travel
			best = hero.position if dist < GameData.ALTAR_RADIUS else pos
	return best


func _karma_portal_goal(hero, raid) -> Vector3:
	return _avoid_portal(hero.position, raid._kportal_pos, raid.portal_pos)


func _avoid_portal(start: Vector3, goal: Vector3, normal: Vector3) -> Vector3:
	if normal == Vector3.INF or start == goal:
		return goal
	normal.y = 0.0
	start.y = 0.0
	var end := Vector3(goal.x, 0.0, goal.z)
	var closest := Geometry3D.get_closest_point_to_segment(normal, start, end)
	if closest.distance_squared_to(normal) < 1.4 * 1.4:
		# Avoid the native 1.2-unit trigger before reaching the intended target.
		var side := (end - normal).cross(Vector3.UP).normalized() * 1.8
		var pass_at := normal + (start - normal).normalized() * 1.4
		return pass_at + (side if (start - normal).dot(side) >= 0.0 else -side)
	return goal


func _altar_skip(entry: Dictionary, reason: String) -> void:
	if reason == "baldur_waits_portal" or reason == "expires_first" or reason == "unreachable":
		# Position and speed can change while we pursue another altar.
		if entry.has(reason):
			return
		entry[reason] = true
	else:
		if entry.has("skip"):
			return
		entry["skip"] = reason
	_log("ALTAR_SKIP id=%s reason=%s t=%.1f raid=%s ref=%d" % [
		str(entry.altar.id), reason, float(world.time), str(world.raid.state), int(entry.ref)])


func _altar_rejection(id: String) -> String:
	if id == "hel":
		return "hel"
	var priority: Array = cfg["altar_priority"]
	return "" if priority.has(id) and GameData.ALTARS.has(id) and not GameData.ALTARS[id].has("npc") else "not_priority"


func _observe_altars() -> void:
	# Keep the game's dictionary: removal with a full channel is acceptance,
	# including Baldur, which isn't counted in world.altars.taken.
	var waiting: Array = world.altars.waiting
	var hero = world.player
	if cfg["altar_policy"] == "map-wide":
		for a in waiting:
			var key: int = a.node.get_instance_id()
			if _altar_seen.has(key):
				continue
			var entry := _altar_entry(hero, a)
			var reason := _altar_rejection(str(a.id))
			if reason != "":
				_altar_skip(entry, reason)
			elif a.id == "baldur" and world.raid.state == "idle":
				_altar_skip(entry, "baldur_waits_portal")
	for key in _altar_seen.keys():
		var entry: Dictionary = _altar_seen[key]
		var a: Dictionary = entry.altar
		if waiting.has(a):
			continue
		if float(a.fill) >= GameData.ALTAR_CHANNEL:
			var nearby: int = world.enemies_in_radius(a.pos, 5.0).size()
			_log("ALTAR_TAKE id=%s from=%.1f nearby=%d t=%.1f raid=%s ref=%d" % [
				str(a.id), float(entry.dist), nearby, float(world.time), str(world.raid.state), key])
		else:
			_altar_skip(entry, "expired" if float(a.life) <= 0.0 else "removed")
		_altar_seen.erase(key)


func _altar_hold_goal(hero, baldur_only := false) -> Vector3:
	if not _altar_channel.is_empty():
		if world.altars.waiting.has(_altar_channel) and (not baldur_only or _altar_channel.id == "baldur"):
			if float(_altar_channel.fill) > _altar_fill_peak:
				_altar_fill_peak = float(_altar_channel.fill)
				_altar_progress_clock = float(world.clock)
			var pos: Vector3 = _altar_channel.pos
			var target := _altar_target(hero, pos, world.raid.portal_pos if baldur_only else Vector3.INF)
			var travel := _altar_travel(hero, pos, target, world.raid.portal_pos if baldur_only else Vector3.INF)
			if travel != INF and _altar_lasts(hero, _altar_channel, travel, baldur_only):
				if float(world.clock) - _altar_progress_clock < ALTAR_NO_PROGRESS:
					return target
				_altar_skip(_altar_entry(hero, _altar_channel), "channel_interrupted")
		_altar_channel = {}
	if not baldur_only:
		for a in world.altars.waiting:
			if _flat_distance(hero.position, a.pos) < GameData.ALTAR_RADIUS \
					and (a.id == "baldur" or _altar_rejection(str(a.id)) != "" \
					or _altar_seen.get(a.node.get_instance_id(), {}).has("skip")):
				# Proximity alone channels altars, even if they aren't a goal.
				var away: Vector3 = hero.position - a.pos
				away.y = 0.0
				var dir := away.normalized() if away != Vector3.ZERO else Vector3.RIGHT
				for angle in [0.0, 0.7, -0.7, 1.4, -1.4, PI]:
					var goal: Vector3 = a.pos + dir.rotated(Vector3.UP, angle) * (GameData.ALTAR_RADIUS + 1.0)
					if _field_goal_available(goal):
						return goal
	return Vector3.INF


func _altar_entry(hero, altar: Dictionary) -> Dictionary:
	var key: int = altar.node.get_instance_id()
	if not _altar_seen.has(key):
		_altar_seen[key] = {"altar": altar, "dist": _flat_distance(hero.position, altar.pos), "ref": key}
	return _altar_seen[key]


func _map_altar_goal(hero, baldur_only := false) -> Vector3:
	var priority: Array = cfg["altar_priority"]
	var avoid: Vector3 = world.raid.portal_pos if baldur_only else Vector3.INF
	var best: Dictionary = {}
	var best_goal := Vector3.INF
	var best_rank := priority.size()
	var best_dist := INF
	# Altars.waiting is the entire map; "near" in the game only drives visuals.
	for a in world.altars.waiting:
		var aid := str(a.id)
		if (aid == "baldur") != baldur_only or _altar_rejection(aid) != "":
			continue
		var entry := _altar_entry(hero, a)
		if entry.has("skip"):
			continue
		var pos: Vector3 = a.pos
		var target := _altar_target(hero, pos, avoid)
		var travel := _altar_travel(hero, pos, target, avoid)
		if travel == INF:
			_altar_skip(entry, "unreachable")
			continue
		if not _altar_lasts(hero, a, travel, baldur_only):
			continue
		var rank := priority.find(aid)
		if rank < best_rank or (rank == best_rank and travel < best_dist):
			best = a
			best_goal = target
			best_rank = rank
			best_dist = travel
	if not best.is_empty() and _flat_distance(hero.position, best.pos) < GameData.ALTAR_RADIUS:
		_altar_channel = best
		_altar_fill_peak = float(best.fill)
		_altar_progress_clock = float(world.clock)
	return best_goal


func _altar_target(hero: Player, pos: Vector3, portal: Vector3) -> Vector3:
	if _flat_distance(hero.position, pos) < GameData.ALTAR_RADIUS:
		return hero.position
	if portal == Vector3.INF or _flat_distance(pos, portal) >= PORTAL_CLEARANCE + 0.25:
		return pos
	var map: RoMap = world.map
	var tile := map.tile_of(pos)
	var best := Vector3.INF
	var distance := INF
	for y in range(tile.y - 2, tile.y + 3):
		for x in range(tile.x - 2, tile.x + 3):
			if not map.cell_walkable(x, y):
				continue
			var spot := map.cell_center(x, y)
			if _flat_distance(spot, pos) >= GameData.ALTAR_RADIUS or _flat_distance(spot, portal) < PORTAL_CLEARANCE + 0.25:
				continue
			var d := _flat_distance(spot, hero.position)
			if d < distance and _field_goal_available(spot):
				distance = d
				best = spot
	return best


func _altar_travel(hero: Player, altar: Vector3, goal: Vector3, avoid: Vector3) -> float:
	var at := hero.position
	if _flat_distance(at, altar) < GameData.ALTAR_RADIUS:
		return 0.0
	if not _field_goal_available(goal):
		return INF
	var map: RoMap = world.map
	var tile := map.tile_of(at)
	if tile != _altar_route_from or avoid != _altar_route_portal:
		_altar_routes.clear()
		_altar_route_from = tile
		_altar_route_portal = avoid
	if _following_field_goal(goal) and _field_path_portal == avoid and _field_path[-1] == goal:
		return _altar_path_distance(at, altar, _field_path, _field_step)
	if not _altar_routes.has(goal):
		_altar_routes[goal] = _field_plan(map, at, goal, avoid)
		_altar_route_at = at
	return _altar_path_distance(at, altar, _altar_routes[goal], 0)


func _altar_path_distance(at: Vector3, altar: Vector3, path: PackedVector3Array, step: int) -> float:
	var distance := 0.0
	for i in range(step, path.size()):
		var goal := path[i]
		var segment := Vector2(goal.x - at.x, goal.z - at.z)
		var length := segment.length()
		if length <= 0.001:
			continue
		var delta := Vector2(altar.x - at.x, altar.z - at.z)
		var projected := segment.dot(delta) / length
		var chord := GameData.ALTAR_RADIUS * GameData.ALTAR_RADIUS - (delta.length_squared() - projected * projected)
		if chord > 0.0:
			var entry := projected - sqrt(chord)
			if entry >= 0.0 and entry < length:
				return distance + entry
		distance += length
		at = goal
	return INF


func _altar_lasts(hero: Player, altar: Dictionary, distance: float, frozen: bool) -> bool:
	if frozen:
		return true
	var travel := distance / maxf(hero.move_speed, 0.1)
	var fill := maxf(0.0, float(altar.fill) - 1.5 * travel)
	if travel + GameData.ALTAR_CHANNEL - fill + 0.1 <= float(altar.life):
		return true
	_altar_skip(_altar_entry(hero, altar), "expires_first")
	return false


func _flat_distance(a: Vector3, b: Vector3) -> float:
	return Vector2(a.x - b.x, a.z - b.z).length()


func _retreat_point(hero) -> Vector3:
	var sum := Vector3.ZERO
	var n := 0
	for e in world.enemies_in_radius(hero.position, 7.0):
		if e == null or not is_instance_valid(e) or bool(e.dead):
			continue
		sum += e.position
		n += 1
	if n == 0:
		return Vector3.INF
	var center: Vector3 = sum / float(n)
	var away: Vector3 = hero.position - center
	away.y = 0.0
	if away.length() < 0.1:
		return Vector3.INF
	return hero.position + away.normalized() * 9.0


# ---------------------------------------------------------------------------
# Loot settlement
# ---------------------------------------------------------------------------

func _do_keep() -> void:
	_mark_transition("keep")
	if world == null or not is_instance_valid(world):
		_finish("lost_world")
		return
	var offer: Array = []
	if world.menus != null and is_instance_valid(world.menus):
		if world.menus.get("_keep_offer") is Array:
			offer = (world.menus._keep_offer as Array).duplicate()
	var victory := bool(run_state.get("victory", false))
	var free := victory or int(world.run_ymir) > 0
	var slots := int(GameData.KEEP_WIN) if free else 1
	var kept: Array = []
	var skipped: Array = []
	var wishlist: Array = cfg["wishlist"]
	var keep_unowned: bool = cfg["keep_unowned_legendaries"]
	var wishlist_evidence := {}
	if _test_verify_wishlist:
		if keep_unowned and _test_wishlist_ids.size() == 3:
			# Put the non-wishlist fixture first to make the paid-slot priority observable.
			for i in offer.size():
				if offer[i].id == _test_wishlist_ids[2]:
					offer.push_front(offer.pop_at(i))
					break
		wishlist_evidence = _test_wishlist_evidence(offer, free)
	if (not wishlist.is_empty() or keep_unowned) and not offer.is_empty():
		var owned := {}
		for item in Save.storage():
			owned[str(item.id)] = true
		var wanted: Array = []
		var others: Array = []
		for it in offer:
			if not (it is Dictionary) or bool(it.get("_kept", false)):
				continue
			if wishlist.has(str(it.get("id", ""))):
				wanted.append(it)
			elif keep_unowned and Equipment.is_legendary(it):
				others.append(it)
		wanted.append_array(others)
		for it in wanted:
			var id := str(it.get("id", ""))
			var reason := ""
			var cost := 0
			if owned.has(id):
				reason = "already_owned"
			elif not _keep_ok(it):
				reason = "not_keepable"
			elif kept.size() >= slots:
				reason = "no_keep_slots"
			elif not free:
				cost = int(world.menus._keep_cost(it))
				if cost > int(float(Save.zeny()) * float(cfg["keep_max_pct"])):
					reason = "over_zeny_limit"
			if reason.is_empty() and Save.storage().size() >= Save.storage_cap() and not _make_room():
				reason = "storage_full"
			if reason.is_empty() and cost > 0 and not Save.spend(cost):
				reason = "not_enough_zeny"
			if reason.is_empty() and not _append_storage(it):
				reason = "storage_full"
			if not reason.is_empty():
				skipped.append({"id": id, "reason": reason})
				_log("KEEP_SKIP %s reason=%s" % [id, reason])
				continue
			it["_kept"] = true
			owned[id] = true
			kept.append(id)
			_log("KEEP %s %s" % [id, "free" if cost == 0 else "paid:%d" % cost])
	# Native-style settlement for everything that was not kept.
	for it in offer:
		if not (it is Dictionary):
			continue
		if bool(it.get("_kept", false)):
			continue
		if Equipment.legend_coins(it) > 0:
			Equipment.cash_in(it)
		elif bool(it.get("_worn", false)):
			var z := int(Equipment.sell_price(it))
			if z > 0:
				Save.add_zeny(z)
	if world.menus != null and is_instance_valid(world.menus):
		world.menus._keep_offer = []
		world.menus._keep_pending = false
	_record_local_progress()
	if not _flush_profile_verified("keep"):
		return
	if _test_tower_parity:
		_test_tower_evidence[str(runs_started)] = _tower_save_evidence(Save._read(Save.PATH))
	if run_state.has("tower_snapshot_saved") and not _refresh_tower_catalog():
		return
	if run_state.has("progress"):
		world.board.child_entered_tree.disconnect(_test_progress_board_request)
		run_state["progress"]["after"] = _progress_snapshot(Save._read(Save.PATH))
	if _test_verify_wishlist:
		wishlist_evidence["after"] = _keep_snapshot(Save._read(Save.PATH))
		_test_wishlist_runs.append(wishlist_evidence)
	run_state["kept"] = kept
	run_state["keep_skipped"] = skipped
	run_state["settled"] = _reward_snapshot()
	_log("KEEP_DONE kept=%d offer=%d victory=%s free=%s slots=%d" % [
		kept.size(), offer.size(), str(victory), str(free), slots])
	# The profile is flushed: the run is settled. A crash from here on must
	# account this result once, never lose or repeat it. A crash between the
	# flush and this write loses the run's accounting (ADR 0001), never
	# doubles it.
	if not _write_checkpoint("settled", _build_result()):
		return
	_test_crash("settled")


func _reward_snapshot() -> Dictionary:
	var prog: Dictionary = Save.class_progress(active_class)
	return {
		"zeny": int(Save.zeny()),
		"materials": Save.materials().duplicate(true),
		"coins": int(Save.coins()) if Save.has_method("coins") else 0,
		"ymir": int(Save.ymir_fragments()) if Save.has_method("ymir_fragments") else 0,
		"cards": _total_card_copies(),
		"pets": int((Save.data.get("pets", {}) as Dictionary).size()),
		"storage": int(Save.storage().size()),
		"class_level": int(prog.get("level", 1)),
		"class_rlv": int(prog.get("rlv", 0)),
	}


func _keep_ok(it: Dictionary) -> bool:
	return Equipment.is_legendary(it) and not Equipment.is_perm(it) and not bool(it.get("lent", false))


func _item_has_pot(it: Dictionary) -> bool:
	var pot = it.get("pot", null)
	return pot is Dictionary and not (pot as Dictionary).is_empty()


func _append_storage(it: Dictionary) -> bool:
	var st: Array = Save.storage()
	if st.size() >= Save.storage_cap():
		return false
	var copy := {
		"id": str(it.get("id", "")),
		"slots": int(it.get("slots", 0)),
		"extra_slots": int(it.get("extra_slots", 0)),
		"refine": 0,
		"cards": [],
		"uid": "%d_%d" % [int(Time.get_unix_time_from_system()), randi() % 1000000],
	}
	var tr := str(it.get("trait", ""))
	if GameData.PURPLE_TRAITS.has(tr):
		copy["trait"] = tr
	var pot := _clean_pot(it.get("pot", null))
	if not pot.is_empty():
		copy["pot"] = pot
	st.append(copy)
	Save.mark_dirty()
	return true


func _clean_pot(p) -> Dictionary:
	if p is not Dictionary:
		return {}
	var out: Array = []
	var lines = (p as Dictionary).get("lines", [])
	if not (lines is Array):
		return {}
	for l in lines:
		if out.size() >= 3:
			break
		if not (l is Dictionary):
			continue
		var k := str((l as Dictionary).get("k", ""))
		if not GameData.POTENTIAL_LINES.has(k):
			continue
		var line := {"k": k, "t": clampi(int((l as Dictionary).get("t", 1)), 1, 3)}
		if bool((l as Dictionary).get("p", false)):
			line["p"] = true
		out.append(line)
	if out.is_empty():
		return {}
	return {"tier": clampi(int((p as Dictionary).get("tier", 1)), 1, 3), "lines": out}


func _make_room() -> bool:
	var victim := ""
	var victim_score := 1.0e30
	for it in Save.storage():
		if not (it is Dictionary):
			continue
		var uid := str((it as Dictionary).get("uid", ""))
		if uid == "" or Save.loadout_owner(uid) != "":
			continue
		if Equipment.is_unique(it) or Equipment.is_legendary(it):
			continue
		if bool(Equipment.item_def(it).get("wings", false)):
			continue
		if _item_has_pot(it) or str((it as Dictionary).get("trait", "")) != "":
			continue
		var sc := float(Equipment.score(it))
		if sc < victim_score:
			victim_score = sc
			victim = uid
	if victim == "":
		return false
	Save.remove_from_storage(victim)
	_log("STORAGE_SWAP removed=%s score=%.0f" % [victim, victim_score])
	return true


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

func _do_maintenance() -> void:
	_mark_transition("maint")
	last_maint = {}
	if world == null or not is_instance_valid(world):
		return
	_claim_achievements()
	if bool(cfg.get("auto_upgrades", true)):
		_buy_upgrades()
	if bool(cfg.get("auto_sage", true)):
		_buy_sage()
	if bool(cfg.get("auto_fuse", true)):
		_auto_fuse()
	if bool(cfg.get("auto_potential", false)):
		_auto_potential()
	if bool(cfg.get("auto_storage_prune", false)):
		_auto_prune()


func _claim_achievements() -> void:
	if not bool(cfg.get("auto_achievements", true)):
		return
	var got := 0
	var coins := 0
	for id in Save.unclaimed_achievements():
		var c := int(Save.claim_achievement(str(id)))
		if c > 0:
			got += 1
			coins += c
	if got > 0:
		last_maint["achievements"] = got
		last_maint["ach_coins"] = coins
		total_coins += coins
		_log("ACH +%d coins +%d" % [got, coins])


func _buy_upgrades() -> void:
	if not GameData.has_method("upgrade_cost"):
		return
	var prio: Array = cfg.get("upgrade_priority", [])
	var reserve := int(cfg.get("upgrade_reserve", 0))
	var bought: Array = []
	var limit := 60
	for id in prio:
		var uid := str(id)
		if not GameData.UPGRADES.has(uid):
			continue
		var maxlv := int(GameData.UPGRADES[uid].get("max", 0))
		var lv := int(Save.upgrade_level(uid))
		while lv < maxlv and limit > 0:
			var cost := int(GameData.upgrade_cost(uid, lv))
			if Save.zeny() - cost < reserve:
				break
			if not Save.spend(cost):
				break
			Save.set_upgrade_level(uid, lv + 1)
			lv += 1
			limit -= 1
			bought.append(uid)
			if uid == "kafra_storage" and Save.storage_cap() >= int(cfg.get("storage_target", 0)):
				break
	# Storage target is a hard requirement even if not in the priority list.
	var target := int(cfg.get("storage_target", 0))
	if target > 0:
		var lv2 := int(Save.upgrade_level("kafra_storage"))
		while Save.storage_cap() < target and lv2 < int(GameData.UPGRADES["kafra_storage"].get("max", 0)):
			var cost2 := int(GameData.upgrade_cost("kafra_storage", lv2))
			if Save.zeny() - cost2 < reserve:
				break
			if not Save.spend(cost2):
				break
			Save.set_upgrade_level("kafra_storage", lv2 + 1)
			lv2 += 1
			bought.append("kafra_storage")
	if not bought.is_empty():
		last_maint["upgrades"] = bought
		_log("UPGRADES " + str(bought))


func _buy_sage() -> void:
	if not GameData.has_method("sage_cost"):
		return
	var prio: Array = cfg.get("sage_priority", [])
	var reserve := int(cfg.get("upgrade_reserve", 0))
	var bought: Array = []
	for id in prio:
		var sid := str(id)
		if not GameData.SAGE_UPGRADES.has(sid):
			continue
		var maxlv := int(GameData.SAGE_UPGRADES[sid].get("max", 0))
		var lv := int(Save.upgrade_level(sid))
		while lv < maxlv:
			var cost := int(GameData.sage_cost(sid, lv))
			if Save.zeny() - cost < reserve:
				break
			if not Save.spend(cost):
				break
			Save.set_upgrade_level(sid, lv + 1)
			lv += 1
			bought.append(sid)
	if not bought.is_empty():
		last_maint["sage"] = bought
		_log("SAGE " + str(bought))


func _auto_fuse() -> void:
	var keep: Dictionary = cfg.get("fuse_keep", {})
	var fused := 0
	var ids: Array = Save.data.get("cards", {}).keys()
	for id in ids:
		var cid := str(id)
		if not GameData.CARDS.has(cid):
			continue
		var reserve := int(keep.get(cid, 0))
		while Save.can_fuse(cid):
			if Save.card_copies(cid) < int(GameData.fuse_cost(cid)) + reserve:
				break
			if not Save.fuse_card(cid):
				break
			fused += 1
	if fused > 0:
		last_maint["fused"] = fused
		_log("FUSE +%d" % fused)


func _item_value(it: Dictionary) -> float:
	var v := float(Equipment.score(it))
	var pot = it.get("pot", null)
	if pot is Dictionary:
		v += float(int((pot as Dictionary).get("tier", 1))) * 20.0
		var lines = (pot as Dictionary).get("lines", [])
		if lines is Array:
			v += float((lines as Array).size()) * 5.0
	if str(it.get("trait", "")) != "":
		v += 15.0
	return v


func _auto_potential() -> void:
	if _potential_script == null:
		return
	var reserve := int(cfg.get("potential_reserve", 0))
	var max_rolls := int(cfg["potential_max_rolls"])
	if max_rolls <= 0:
		return
	var rolls := 0
	var candidates: Array = []
	for it in Save.storage():
		if not (it is Dictionary) or (it as Dictionary).is_empty():
			continue
		var d: Dictionary = Equipment.item_def(it)
		if not d.has("refine") or d.get("fixed", false) or d.get("unique", false):
			continue
		var uid := str(it.get("uid", ""))
		if uid == "" or Save.loadout_owner(uid) != "":
			continue
		candidates.append(it)
	candidates.sort_custom(func(a, b): return _item_value(a) > _item_value(b))
	for it in candidates:
		if rolls >= max_rolls:
			break
		var pot = it.get("pot", null)
		var tier := 0
		var lines: Array = []
		if pot is Dictionary:
			tier = int((pot as Dictionary).get("tier", 0))
			lines = (pot as Dictionary).get("lines", []) if (pot as Dictionary).get("lines", []) is Array else []
		if tier >= 3 and lines.size() >= 3:
			var perfect := 0
			for l in lines:
				if l is Dictionary and bool((l as Dictionary).get("p", false)):
					perfect += 1
			if perfect >= 3:
				continue
		var locks: Array = []
		for i in lines.size():
			var l = lines[i]
			if l is Dictionary and int((l as Dictionary).get("t", 0)) >= 3:
				locks.append(i)
				if locks.size() >= 2:
					break
		var cost := 1 + 3 * locks.size()
		if Save.material("star_crumb") < reserve + cost:
			continue
		Save.add_material("star_crumb", -cost)
		_potential_script.roll(it, locks)
		Save.mark_dirty()
		rolls += 1
	if rolls > 0:
		last_maint["pot_rolls"] = rolls
		_log("POTENTIAL rolls=%d crumbs=%d" % [rolls, Save.material("star_crumb")])


func _auto_prune() -> void:
	var cap := Save.storage_cap()
	var reserve := int(cfg.get("keep_reserve_slots", 2))
	if Save.storage().size() < cap - reserve:
		return
	var removed := 0
	while Save.storage().size() > maxi(0, cap - reserve - 2):
		var victim := ""
		var victim_score := 1.0e30
		for it in Save.storage():
			if not (it is Dictionary):
				continue
			var uid := str((it as Dictionary).get("uid", ""))
			if uid == "" or Save.loadout_owner(uid) != "":
				continue
			if Equipment.is_unique(it) or Equipment.is_legendary(it):
				continue
			if bool(Equipment.item_def(it).get("wings", false)):
				continue
			if _item_has_pot(it) or str((it as Dictionary).get("trait", "")) != "":
				continue
			var sc := float(Equipment.score(it))
			if sc < victim_score:
				victim_score = sc
				victim = uid
		if victim == "":
			break
		Save.remove_from_storage(victim)
		removed += 1
	if removed > 0:
		last_maint["pruned"] = removed
		_log("PRUNE %d" % removed)


# ---------------------------------------------------------------------------
# Target / arm selection
# ---------------------------------------------------------------------------

func _validate_run_choice() -> bool:
	var location = cfg.get("stage")
	_tower_kind = ""
	if location is Dictionary and location.get("mode") == "tower":
		_rotating = false
		return _validate_tower_choice(location)
	_rotating = (location is Dictionary and location.size() == 1
		and location.get("mode") is String and location["mode"] == "rotation")
	if not _rotating:
		if not (location is String):
			_fail_session("invalid_location", true, "Location must be a location id, Automatic or All locations in turn.")
			return false
		var stage := str(location)
		if stage != "" and not _stage_ok(stage):
			var problem := "is locked or unavailable" if GameData.STAGES.has(stage) else "is unknown"
			_fail_session("invalid_location", true, "Location '%s' %s." % [stage, problem])
			return false
	var difficulty = cfg.get("danger")
	var fixed_difficulty := difficulty is int or difficulty is float
	if not fixed_difficulty and (not (difficulty is String) or difficulty not in ["auto", "max", "best", "stage"]):
		_fail_session("invalid_difficulty", true, "Difficulty must be an integer or Automatic.")
		return false
	if _rotating:
		if _rotation_stage(difficulty) == "":
			return false
	elif fixed_difficulty:
		var stage := str(location)
		if not _validate_location_difficulty(difficulty, _fallback_stage() if stage == "" else stage):
			return false
	var oaths = cfg["oaths"]
	if not (oaths is Dictionary):
		_fail_session("invalid_oath", true, "Oaths must map oath ids to ranks.")
		return false
	if not oaths.is_empty() and (not fixed_difficulty or int(difficulty) != GameData.DANGER_MAX):
		_fail_session("invalid_oath", true, "Oaths require fixed difficulty %d." % GameData.DANGER_MAX)
		return false
	for id in oaths:
		var oath := GameData.oath_def(str(id))
		if oath.is_empty():
			_fail_session("invalid_oath", true, "Unknown oath '%s'." % id)
			return false
		var rank = oaths[id]
		if not (rank is int or rank is float) or rank < 1 or rank > oath.pts.size() or rank != floorf(float(rank)):
			_fail_session("invalid_oath", true, "Oath '%s' has no rank %s." % [id, str(rank)])
			return false
	return true


func _validate_tower_choice(choice: Dictionary) -> bool:
	var kind = choice.get("kind")
	if kind not in ["normal", "hel"] or choice.size() != 3 or not choice.has("floor"):
		_fail_session("invalid_location", true, "Tower requires a kind and a start floor.")
		return false
	if not Save.tower_open():
		_fail_session("tower_closed", true, "Endless Tower is not open in this profile.")
		return false
	if kind == "hel":
		if not Save.hel_open():
			_fail_session("tower_hel_locked", true, _tower_hel_reason())
			return false
	else:
		var f = choice["floor"]
		if not (f is int or f is float) or not Save.tower_checkpoints().has(int(f)) or float(f) != floorf(float(f)):
			_fail_session("tower_invalid_floor", true, "Tower start floor %s is not an unlocked checkpoint." % str(f))
			return false
	_tower_kind = kind
	return true


func _validate_location_difficulty(difficulty: float, stage: String) -> bool:
	var bounds: Vector2i = GameData.stage_danger_range(stage, Save.max_danger())
	if difficulty != floorf(difficulty) or difficulty < bounds.x or difficulty > bounds.y:
		_fail_session("invalid_difficulty", true,
			"Difficulty %s is outside the allowed integer range %d–%d for location '%s'." % [difficulty, bounds.x, bounds.y, stage])
		return false
	return true


func _rotation_stage(difficulty: Variant, choose_start: bool = false) -> String:
	var unlocked: Array[String] = []
	var next_stage := ""
	var after_cursor := not GameData.STAGES.has(_last_rotated_stage)
	var fixed_difficulty := difficulty is int or difficulty is float
	for id in GameData.STAGES:
		var stage := str(id)
		# The cursor is in catalog order even if that location is no longer unlocked.
		var is_cursor := stage == _last_rotated_stage
		if _stage_ok(stage):
			if fixed_difficulty and not _validate_location_difficulty(difficulty, stage):
				return ""
			unlocked.append(stage)
			if after_cursor and next_stage == "":
				next_stage = stage
		if is_cursor:
			after_cursor = true
	if unlocked.is_empty():
		_fail_session("invalid_location", true, "No unlocked locations for All locations in turn.")
		return ""
	if choose_start and not GameData.STAGES.has(_last_rotated_stage):
		var start: String = unlocked[randi_range(0, unlocked.size() - 1)]
		_log("ROTATION_START stage=" + start)
		return start
	return next_stage if next_stage != "" else unlocked[0]


func _choose_target() -> Dictionary:
	var raw = cfg.get("danger", "auto")
	var stage := _rotation_stage(raw, true) if _rotating else str(cfg.get("stage", ""))
	if _rotating and stage == "":
		return {}
	var danger := 0
	var obj := str(cfg.get("objective", "balanced"))
	var fixed_difficulty := raw is int or raw is float
	if stage != "" or fixed_difficulty or obj == "progress" or str(raw) in ["max", "best", "stage"]:
		if stage == "":
			stage = _fallback_stage()
		if stage == "":
			return {}
		if fixed_difficulty:
			danger = int(raw)
		else:
			danger = _stage_max_danger(stage) if obj == "progress" else _danger_for(stage)
	else:
		var arm := _pick_arm()
		if not arm.is_empty():
			stage = str(arm.get("stage", ""))
			danger = int(arm.get("danger", 1))
		else:
			stage = _fallback_stage()
			danger = _danger_for(stage)
		if stage == "" or not _stage_ok(stage):
			stage = _fallback_stage()
			if stage == "":
				return {}
			danger = _danger_for(stage)
	var cid := active_class if active_class != "" else _choose_class()
	if cid == "":
		_log("TARGET_FAIL class")
		return {}
	if not fixed_difficulty:
		var lo := _stage_min_danger(stage)
		danger = clampi(danger, lo, maxi(lo, mini(_stage_max_danger(stage), int(cfg.get("danger_ceiling", 30)))))
	_log("TARGET stage=%s danger=%d class=%s" % [stage, danger, cid])
	return {"stage": stage, "danger": danger, "class": cid}


func _pick_arm() -> Dictionary:
	var best := ""
	var best_rate := -1.0
	var keys: Array = arms.keys()
	for k in keys:
		var arm: Dictionary = arms[k]
		var st := str(arm.get("stage", ""))
		if not _stage_ok(st):
			continue
		if int(arm.get("runs", 0)) <= 0:
			continue
		if int(arm.get("cooldown_until", 0)) > runs_done:
			continue
		var rate := float(arm.get("rate", 0.0))
		if rate > best_rate:
			best_rate = rate
			best = str(k)
	var explore := false
	if runs_done > 0:
		var every := maxi(1, int(cfg.get("explore_every", 5)))
		explore = (runs_done % every) == 0
	if best != "" and not explore:
		return _arm_by_key(best)
	if explore:
		var ex := _explore_arm(best)
		if not ex.is_empty():
			return ex
	if best != "":
		return _arm_by_key(best)
	return _explore_arm("")


func _arm_by_key(key: String) -> Dictionary:
	if not arms.has(key):
		return {}
	var a: Dictionary = arms[key]
	var st := str(a.get("stage", ""))
	if not _stage_ok(st):
		return {}
	var d := clampi(int(a.get("danger", 1)), _stage_min_danger(st), _stage_max_danger(st))
	return {"stage": st, "danger": d}


func _explore_arm(from_key: String) -> Dictionary:
	var step := maxi(1, int(cfg.get("danger_step", 1)))
	if from_key != "" and arms.has(from_key):
		var a: Dictionary = arms[from_key]
		var st := str(a.get("stage", ""))
		var d := int(a.get("danger", 1))
		var lo := _stage_min_danger(st)
		var hi := mini(_stage_max_danger(st), int(cfg.get("danger_ceiling", 30)))
		if d + step <= hi:
			return {"stage": st, "danger": d + step}
		if d - step >= lo:
			return {"stage": st, "danger": d - step}
		var other := _fallback_stage(st)
		if other != "":
			return {"stage": other, "danger": _danger_for(other)}
		return {}
	return {"stage": _fallback_stage(), "danger": -1}


func _fallback_stage(exclude: String = "") -> String:
	var best := ""
	var best_score := -1.0e30
	for id in GameData.STAGES:
		var sid := str(id)
		if sid == exclude or not _stage_ok(sid):
			continue
		var tier := float(GameData.STAGES[sid].get("tier", 0))
		var score := tier * 1000.0
		if bool(cfg.get("featured_bonus", true)) and sid == str(GameData.featured_stage()):
			score += 500.0
		var goal_stage := _goal_stage()
		if goal_stage != "":
			if sid == goal_stage:
				score += 5000.0
			else:
				score -= 500.0
		if score > best_score:
			best_score = score
			best = sid
	return best


func _stage_ok(sid: String) -> bool:
	if not GameData.STAGES.has(sid):
		return false
	if world != null and is_instance_valid(world) and world.has_method("is_stage_exported"):
		if not bool(world.is_stage_exported(sid)):
			return false
	if world != null and is_instance_valid(world) and world.has_method("is_stage_unlocked"):
		if not bool(world.is_stage_unlocked(sid)):
			return false
	return true


func _stage_min_danger(sid: String) -> int:
	var r: Vector2i = GameData.stage_danger_range(sid, Save.max_danger())
	return int(r.x)


func _stage_max_danger(sid: String) -> int:
	var r: Vector2i = GameData.stage_danger_range(sid, Save.max_danger())
	return int(r.y)


func _danger_for(sid: String) -> int:
	var lo := _stage_min_danger(sid)
	var hi := maxi(lo, mini(_stage_max_danger(sid), int(cfg.get("danger_ceiling", 30))))
	var raw = cfg.get("danger", "auto")
	var s := str(raw)
	if s == "best":
		var d := int(Save.danger_best(sid))
		if d <= 0:
			d = int(Save.stage_danger(sid))
		if d <= 0:
			d = lo
		return clampi(d, lo, hi)
	if s == "max":
		return clampi(Save.max_danger(), lo, hi)
	if s == "stage":
		var d2 := int(Save.stage_danger(sid))
		if d2 <= 0:
			d2 = lo
		return clampi(d2, lo, hi)
	var d3 := int(Save.danger_best(sid))
	if d3 <= 0:
		d3 = lo
	if bool(cfg.get("auto_danger", true)):
		d3 = maxi(d3, lo)
	# First run at a stage: one above the floor is a safe probe.
	if int(arms.get("%s|%d" % [sid, d3], {}).get("runs", 0)) <= 0 and d3 == lo:
		d3 = mini(lo + 1, hi)
	return clampi(d3, lo, hi)


func _choose_class() -> String:
	var b: Dictionary = cfg.get("builds", {})
	var bclass := str(b.get("class", "")) if b.has("class") else ""
	if bclass != "":
		if _class_ok(bclass):
			return bclass
		_log("CLASS_LOCKED %s" % bclass)
		return ""
	var fixed := str(cfg.get("class", ""))
	if fixed != "":
		if _class_ok(fixed):
			return fixed
		_log("CLASS_LOCKED %s" % fixed)
		return ""
	var best := "swordsman"
	var best_score := -1.0
	for id in GameData.CLASSES:
		var cid := str(id)
		if not _class_ok(cid):
			continue
		var prog: Dictionary = Save.class_progress(cid)
		var score := float(int(prog.get("level", 1))) + 100.0 * float(int(prog.get("rlv", 0)))
		if score > best_score:
			best_score = score
			best = cid
	return best


func _class_ok(cid: String) -> bool:
	if not GameData.CLASSES.has(cid):
		return false
	if not Save.has_method("class_unlocked"):
		return true
	return bool(Save.class_unlocked(cid))


func _goal_stage() -> String:
	var cards: Array = _goal_cards()
	var pets: Array = _goal_pets()
	if cards.is_empty() and pets.is_empty():
		return ""
	var best := ""
	var best_score := -1
	for id in GameData.STAGES:
		var sid := str(id)
		if not _stage_ok(sid):
			continue
		var score := 0
		for mob in _stage_mobs(sid):
			var md: Dictionary = GameData.MONSTERS.get(mob, {})
			var card := str(md.get("card", ""))
			if card != "" and cards.has(card):
				score += 2
			if pets.has(mob):
				score += 5
		if score > best_score:
			best_score = score
			best = sid
	return best if best_score > 0 else ""


func _stage_mobs(sid: String) -> Array:
	var out: Array = []
	var s: Dictionary = GameData.STAGES.get(sid, {})
	for key in ["spawns", "events"]:
		var list = s.get(key, [])
		if list is Array:
			for e in list:
				if e is Dictionary:
					var mob := str(e.get("mob", ""))
					if mob != "" and not out.has(mob):
						out.append(mob)
	var mvp := str(s.get("mvp", ""))
	if mvp != "" and not out.has(mvp):
		out.append(mvp)
	return out


func _goal_cards() -> Array:
	var out: Array = []
	var g = cfg.get("goals", {})
	if not (g is Dictionary):
		return out
	var raw = g.get("cards", [])
	if raw is Array:
		for id in raw:
			var cid := str(id)
			if GameData.CARDS.has(cid) and not Save.has_card(cid):
				out.append(cid)
	return out


func _goal_pets() -> Array:
	var out: Array = []
	var g = cfg.get("goals", {})
	if not (g is Dictionary):
		return out
	var raw = g.get("pets", [])
	if raw is Array:
		for id in raw:
			var pid := str(id)
			if GameData.PETS.has(pid) and not Save.has_pet(pid):
				out.append(pid)
	return out


func _goal_done() -> bool:
	var g = cfg.get("goals", {})
	if not (g is Dictionary) or g.is_empty():
		return false
	var any := false
	var raw_cards = g.get("cards", [])
	if raw_cards is Array:
		for id in raw_cards:
			any = true
			if not Save.has_card(str(id)):
				return false
	var raw_pets = g.get("pets", [])
	if raw_pets is Array:
		for id in raw_pets:
			any = true
			if not Save.has_pet(str(id)):
				return false
	var et = g.get("eternal", {})
	if et is Dictionary:
		for id in et:
			any = true
			if Save.eternal(str(id)) < int(et[id]):
				return false
	var z := int(g.get("zeny", 0))
	if z > 0:
		any = true
		if Save.zeny() < z:
			return false
	return any


# ---------------------------------------------------------------------------
# Build settings
# ---------------------------------------------------------------------------

func _job_path(cid: String) -> int:
	var builds: Dictionary = cfg.get("builds", {})
	var b: Dictionary = builds.get(cid) if builds.get(cid) is Dictionary else {}
	if b.has("job_path"):
		return clampi(int(b["job_path"]), 0, maxi(0, GameData.job_paths(cid).size() - 1))
	var paths = cfg.get("job_paths", {})
	if paths is Dictionary and paths.has(cid):
		return clampi(int(paths[cid]), 0, maxi(0, GameData.job_paths(cid).size() - 1))
	return 0


func _apply_build_settings(cid: String) -> void:
	var orders = Save.setting("pick_order", {})
	var order = orders.get(cid, []) if orders is Dictionary else []
	var limits = Save.setting("pick_limits", {})
	var caps = limits.get(cid, {}) if limits is Dictionary else {}
	_log("PROFILE_BUILD class=%s order=%s limits=%s" % [cid, str(order), str(caps)])
	Save.set_meta("farmer_job_paths", {cid: _job_path(cid)})


# ---------------------------------------------------------------------------
# Run accounting
# ---------------------------------------------------------------------------

func _snapshot_run_state() -> Dictionary:
	var p = world.player
	var cid := active_class
	var prog: Dictionary = Save.class_progress(cid)
	return {
		"wall_start": _now(),
		"game_start": float(world.time),
		"zeny": int(Save.zeny()),
		"materials": Save.materials().duplicate(true),
		"coins": int(Save.coins()) if Save.has_method("coins") else 0,
		"ymir": int(Save.ymir_fragments()) if Save.has_method("ymir_fragments") else 0,
		"morroc_finale_before": Save.stat("morroc_finale"),
		"cards": _total_card_copies(),
		"pets": int((Save.data.get("pets", {}) as Dictionary).size()),
		"storage": int(Save.storage().size()),
		"class_level": int(prog.get("level", 1)),
		"class_rlv": int(prog.get("rlv", 0)),
		"max_danger": int(Save.max_danger()) if Save.has_method("max_danger") else 0,
		"player_level": int(p.level) if p != null and is_instance_valid(p) else 0,
		"hp": float(p.hp) if p != null and is_instance_valid(p) else 0.0,
	}


func _total_card_copies() -> int:
	var n := 0
	var cards: Dictionary = Save.data.get("cards", {})
	for id in cards.keys():
		n += int(cards[id])
	return n


func _record_run() -> bool:
	_mark_transition("run_complete")
	var r := _build_result()
	if not _write_checkpoint("settled", r):
		return false
	if not _account_run(r, true):
		return false
	_test_crash("journaled")
	if not _write_checkpoint("idle"):
		return false
	_log("END " + JSON.stringify(r))
	return true


func _complete_run(now: int) -> void:
	if not _flush_profile_verified("maintenance"):
		return
	last_maint["zeny"] = Save.zeny()
	last_maint["storage"] = Save.storage().size()
	_log("MAINT " + JSON.stringify(last_maint))
	# Refresh the pending result after maintenance before it goes to the journal.
	if not _record_run():
		return
	if not _tower_intent.is_empty():
		_finish("tower_finished")
		return
	if _finish_after_run == "finish":
		_finish("finish")
		return
	if int(cfg.get("max_runs", 0)) > 0 and runs_done >= int(cfg.get("max_runs", 0)):
		_finish("max_runs")
		return
	if int(cfg.get("stop_after_wins", 0)) > 0 and wins >= int(cfg.get("stop_after_wins", 0)):
		_finish("wins")
		return
	if _goal_done() and bool(cfg.get("goal_stop", false)):
		_finish("goal")
		return
	if _finish_after_run != "":
		_finish(_finish_after_run)
		return
	next_action_ms = now + int(float(cfg.get("restart_seconds", 1.0)) * 1000.0)
	phase = "paused" if _pause_requested else "idle"
	if phase == "paused":
		_mark_transition("paused")
	_write_status()


# Adds one settled run to the session totals. append_log=false is the
# recovery path for a run that is already in the journal (and in arms).
func _account_run(r: Dictionary, append_log: bool) -> bool:
	if append_log and not _append_run_log(r):
		_fail_session("journal_failed")
		return false
	last_run = r
	runs_done += 1
	if bool(r.get("victory", false)):
		wins += 1
	elif bool(r.get("died", true)) or not r.has("tower_floor_start"):
		losses += 1
	total_zeny += int(r.get("zeny_gain", 0))
	total_kills += int(r.get("kills", 0))
	total_xp += int(r.get("xp_gain", 0))
	var mats: Dictionary = r.get("materials", {})
	for k in mats:
		total_materials[str(k)] = int(total_materials.get(str(k), 0)) + int(mats[k])
	total_coins += int(r.get("coins_gain", 0))
	total_ymir += int(r.get("ymir_gain", 0))
	if append_log and not r.has("tower_floor_start"):
		_update_arm(r)
	return true


func _totals() -> Dictionary:
	return {
		"started": runs_started, "runs": runs_done, "wins": wins, "losses": losses,
		"lost": runs_lost,
		"zeny": total_zeny, "kills": total_kills, "xp": total_xp,
		"coins": total_coins, "ymir": total_ymir, "materials": total_materials.duplicate(true),
	}


# Checkpoint phases: "run" (started, nothing banked by the farmer yet),
# "settled" (profile flushed, result not yet in the journal), "idle"
# (result accounted). Written atomically at each boundary.
func _write_checkpoint(stage: String, pending: Dictionary = {}) -> bool:
	var ok := _atomic_write(CHECKPOINT_PATH, JSON.stringify({
		"session": session_id,
		"started_unix": session_started_unix,
		"phase": stage,
		"run_id": str(run_state.get("run_id", "")),
		"tower_intent": _tower_intent,
		"target": {"stage": active_stage, "danger": active_danger, "class": active_class, "oath_points": active_oath_points},
		"last_rotated_stage": _last_rotated_stage,
		"totals": _totals(),
		"pre_run": run_state,
		"result": pending,
		"written_unix": int(Time.get_unix_time_from_system()),
	}))
	if not ok:
		_fail_session("checkpoint_failed")
	return ok


# Returns false (after failing the session) when a supervised session's
# checkpoint is unreadable: silently starting over would reuse run ids.
func _restore_checkpoint() -> bool:
	if not FileAccess.file_exists(CHECKPOINT_PATH):
		return true
	var cp = JSON.parse_string(FileAccess.get_file_as_string(CHECKPOINT_PATH))
	var supervised := OS.get_environment("FARMER_SESSION_ID") != ""
	if not (cp is Dictionary):
		if supervised:
			_fail_session("checkpoint_corrupt")
			return false
		return true
	if str(cp.get("session", "")) != session_id:
		return true  # another session's checkpoint; the first boundary replaces it
	if not (cp.get("totals") is Dictionary and cp.get("target") is Dictionary and cp.get("result") is Dictionary):
		_fail_session("checkpoint_corrupt")
		return false
	session_started_unix = int(cp.get("started_unix", session_started_unix))
	boot_ms = _now() - maxi(0, int(Time.get_unix_time_from_system()) - session_started_unix) * 1000
	var t: Dictionary = cp["totals"]
	runs_started = int(t.get("started", 0))
	runs_done = int(t.get("runs", 0))
	wins = int(t.get("wins", 0))
	losses = int(t.get("losses", 0))
	runs_lost = int(t.get("lost", 0))
	total_zeny = int(t.get("zeny", 0))
	total_kills = int(t.get("kills", 0))
	total_xp = int(t.get("xp", 0))
	total_coins = int(t.get("coins", 0))
	total_ymir = int(t.get("ymir", 0))
	total_materials = {}
	var mats = t.get("materials", {})
	if mats is Dictionary:
		for k in mats:
			total_materials[str(k)] = int(mats[k])
	var target: Dictionary = cp["target"]
	active_stage = str(target.get("stage", ""))
	_last_rotated_stage = str(cp.get("last_rotated_stage", ""))
	active_danger = int(target.get("danger", 1))
	active_oath_points = int(target.get("oath_points", 0))
	active_class = str(target.get("class", ""))
	var run_id := str(cp.get("run_id", ""))
	var boundary := str(cp.get("phase", ""))
	var intent = cp.get("tower_intent", {})
	if intent is Dictionary and not intent.is_empty():
		_tower_intent = intent
		run_state = cp.get("pre_run", {}) if cp.get("pre_run") is Dictionary else {}
		if run_id.is_empty() or intent.get("run_id") != run_id or str(intent.get("snapshot_id", "")).is_empty():
			return _fail_tower_intent()
		if boundary == "settled":
			var result: Dictionary = cp["result"]
			if result.get("run_id") != run_id or not result.has("tower_floor_start") \
					or result.get("snapshot", {}).get("id") != intent["snapshot_id"]:
				return _fail_tower_intent()
			if not _account_run(result, not _journal_has(run_id)):
				return false
		elif boundary != "idle" or not _journal_has(run_id):
			# Native RunSave does not serialize Tower. Only a settled result proves
			# the run is recoverable; a missing snapshot doesn't prove settlement.
			return _fail_tower_intent()
		phase = "tower_recovered"
		return _write_checkpoint("idle")
	if boundary == "tower_intent" or active_stage in ["tower", "hel"]:
		return _fail_tower_intent()
	match boundary:
		"run":
			# ADR 0001: a run that crashed before settlement is lost, not resumed.
			runs_lost += 1
			_log("RUN_LOST %s crashed before settlement" % run_id)
		"settled":
			var journaled := _journal_has(run_id)
			if not _account_run(cp["result"], not journaled):
				return false
			_log("RECOVER %s settled journal=%s" % [run_id, "present" if journaled else "appended"])
	_log("SESSION_RESUMED %s runs=%d lost=%d" % [session_id, runs_done, runs_lost])
	return _write_checkpoint("idle")


func _journal_has(run_id: String) -> bool:
	if run_id == "" or not FileAccess.file_exists(RUNS_PATH):
		return false
	var f := FileAccess.open(RUNS_PATH, FileAccess.READ)
	if f == null:
		return false
	var needle := "\"run_id\":\"%s\"" % run_id
	while not f.eof_reached():
		var line := f.get_line()
		if needle in line:
			var d = JSON.parse_string(line)
			if d is Dictionary and str(d.get("run_id", "")) == run_id:
				return true
	return false


# Test-only seams for verify.sh. _test_env is the single reader of
# FARMER_TEST_* (enforced by tools/check.sh): it answers only in verify-*
# sessions, so a leaked variable cannot change a real session.
func _test_env(name: String) -> String:
	if not session_id.begins_with("verify-"):
		return ""
	return OS.get_environment("FARMER_TEST_" + name)


func _test_tick_blocked_portal() -> bool:
	var state := str(world.raid.state)
	if not _test_portal_seeded and state == "portal":
		# Prontera Field: an intervening tile is blocked, but the portal is
		# reachable around it. Keep the native portal entry and collision.
		var start := Vector3(-98.5, 0.0, 135.5)
		var goal := Vector3(-90.5, 0.0, 135.5)
		if not world.map.is_walkable(start) or not world.map.is_walkable(goal) \
				or world.map.is_walkable(start + Vector3.RIGHT) or world.raid.portal_sealed:
			_fail_session("invalid_blocked_portal_fixture")
			return true
		world.player.position = Vector3(start.x, world.map.height_at(start), start.z)
		world.raid.portal_pos = goal
		_test_portal_seeded = true
		_log("BLOCKED_PORTAL seeded")
	elif _test_portal_seeded and (state == "intro" or state == "fight"):
		_log("BLOCKED_PORTAL entered")
		_test_blocked_portal = false
		_end_run_safe(false)
		return true
	return false

func _test_tick_field_charge() -> void:
	if get_tree().paused:
		return
	if is_instance_valid(_test_charge_enemy):
		if _test_charge_enemy.brain._state == "chase":
			_end_run_safe(false)
		return
	var map: RoMap = world.map
	var hero: Player = world.player
	if not hero.doom or active_oath_points != 37 or map.blocked_in(220, 28, 249, 59) > 0:
		_fail_session("invalid_field_charge_fixture")
		return
	var at := map.cell_center(235, 43)
	var dir := Vector3.RIGHT.rotated(Vector3.UP, float(runs_started - 1) * PI * 0.5)
	var origin := at - dir * 6.0
	hero.position = Vector3(at.x, map.height_at(at), at.z)
	hero.hp = minf(hero.hp, hero.max_hp * 0.15)
	hero.revives = 0
	hero._invuln = 0.0
	# An altar underfoot makes the existing goal hold position through the tell.
	world.altars.spawn("loki", at)
	var foe: Enemy = world.spawn_enemy("baphomet", origin, true)
	if not is_instance_valid(foe) or foe.brain == null:
		_fail_session("missing_field_charge_enemy")
		return
	_test_charge_enemy = foe
	foe._immovable = true
	foe.max_hp *= 100.0
	foe.hp = foe.max_hp
	# Exclude summon to deterministically select charge via the native starter.
	foe.brain.kind = "summoner"
	foe.brain._last = "summon"
	foe.brain._start_attack(world)
	if foe.brain._state != "windup":
		_fail_session("missing_field_charge_windup")


func _test_tick_navigation() -> bool:
	if get_tree().paused:
		return false
	var map: RoMap = world.map
	var hero: Player = world.player
	var start := map.cell_center(225, 50)
	var now := float(world.clock)
	if _test_nav.is_empty():
		# An open Prontera patch with an added one-tile-wide, 25-tile cul-de-sac.
		if map.blocked_in(220, 28, 249, 59) > 0:
			_fail_session("invalid_field_navigation_fixture")
			return true
		for y in range(29, 55):
			map.block_cell(224, y)
			map.block_cell(226, y)
		map.block_cell(225, 54)
		_direct_grid = null
		_field_map_id = 0
		hero.position = Vector3(start.x, map.height_at(start), start.z)
		var bait := map.cell_center(229, 50)
		world.altars.spawn("freyja", bait)
		var short: Dictionary = world.altars.waiting.back()
		# Straight-line ETA fits; the trip around the end of the wall does not.
		short.life = GameData.ALTAR_CHANNEL + 4.0 / hero.move_speed + 0.5
		world.altars.spawn("loki", map.cell_center(241, 50))
		_test_nav = {"stage": "altar", "altar": world.altars.waiting.back(), "until": now + 30.0}
		_log("FIELD_NAVIGATION seeded")
		return false
	if now > float(_test_nav.until):
		_log("FIELD_NAVIGATION timed_out stage=%s" % str(_test_nav.stage))
		_end_run_safe(false)
		return true
	match str(_test_nav.stage):
		"altar":
			var altar: Dictionary = _test_nav.altar
			if float(altar.fill) >= GameData.ALTAR_CHANNEL:
				hero.position = Vector3(start.x, map.height_at(start), start.z)
				world._drop_item(map.cell_center(237, 50), "card", "poring_card")
				_test_nav = {"stage": "loot", "pickup": world.pickups.back(),
					"until": now + 24.0, "progress": now, "at": start}
		"loot":
			if not world.pickups.has(_test_nav.pickup):
				_log("FIELD_NAVIGATION collected")
				hero.position = Vector3(start.x, map.height_at(start), start.z)
				_test_nav = {"stage": "roam", "until": now + 10.0}
			elif _flat_distance(hero.position, _test_nav.at) >= 0.25:
				_test_nav.at = hero.position
				_test_nav.progress = now
			elif now - float(_test_nav.progress) > 1.25:
				_log("FIELD_NAVIGATION stalled")
				_end_run_safe(false)
				return true
		"roam":
			if map.tile_of(hero.position).y < 28:
				_log("FIELD_NAVIGATION escaped")
				_end_run_safe(false)
				return true
	return false



func _test_tick_mvp_mechanics() -> void:
	if get_tree().paused:
		return
	var raid: MvpRaid = world.raid
	var hero: Player = world.player
	var trial := (runs_started - 1) % 5
	var ability := "spears" if runs_started <= 5 else ("quake" if runs_started <= 10 else "slam")
	if ability == "slam" and not _test_raid_ability.is_empty():
		if not is_instance_valid(_test_mvp_enemy) or _test_mvp_enemy.dead:
			_fail_session("field_slam_attacker_missing")
			return
		if _test_mvp_enemy.brain._state == "chase":
			_test_raid_marks = int(_test_mvp_enemy.brain._state_time <= 0.0)
			for at in _test_mvp_enemy.brain._targets:
				if _flat_distance(hero.position, at) < FIELD_SLAM_RADIUS:
					_test_raid_fails = 1
					break
			_end_run_safe(false)
		elif float(world.clock) > _test_raid_end:
			_fail_session("field_slam_did_not_resolve")
		return
	if not _test_raid_ability.is_empty():
		if ability == "spears" and _test_mvp_waves.size() == 1:
			for wave: Dictionary in raid._objects:
				if wave.kind == "volley_wave":
					_test_mvp_waves.append(wave)
					break
		_test_raid_marks = 0
		for wave: Dictionary in _test_mvp_waves:
			_test_raid_marks += int(float(wave.t) <= 0.0)
		if float(raid.stats.time) >= _test_raid_end:
			_end_run_safe(false)
		return
	if ability != "slam":
		if raid.state == "idle":
			raid.start_route("reginleif" if ability == "spears" else "orc_lord")
			return
		if raid.state != "fight":
			return
	if not hero.doom or active_danger != 30 or active_oath_points != 37:
		_fail_session("invalid_mvp_mechanics_fixture")
		return
	_test_raid_marks = 0
	hero.revives = 0
	hero._invuln = 0.0
	hero.hp = minf(hero.hp, hero.max_hp * 0.15)
	if ability == "slam":
		_test_start_field_slam(hero, trial)
		return
	raid.boss.max_hp *= 100.0
	raid.boss.hp = raid.boss.max_hp
	raid.boss.hold = 20.0
	raid.boss.hit_cd = 20.0
	for ab: Dictionary in raid.data.abilities:
		raid._timers[ab.id] = 999.0
		if ab.id == ability:
			_test_raid_ability = ab
	if _test_raid_ability.is_empty():
		_fail_session("mvp_mechanics_ability_missing")
		return
	var dir := Vector3.RIGHT.rotated(Vector3.UP, float(trial) * TAU / 5.0)
	if ability == "quake" and trial == 0:
		# The native zero-offset dodge points +Z, into the rim at this start.
		dir = Vector3(0.0, 0.0, 1.0)
	var near_rim := raid.center + dir * (raid.radius - 0.4)
	var at: Vector3 = raid._walkable(near_rim)
	hero.position = Vector3(at.x, world.map.height_at(at), at.z)
	_test_raid_hits = _test_mvp_hits()
	_test_raid_fails = int(raid.stats.fails)
	_test_raid_end = float(raid.stats.time) + 4.0
	raid._start(_test_raid_ability)
	if raid._cast.is_empty():
		_fail_session("mvp_mechanics_telegraph_missing")
		return
	_test_mvp_waves.append(raid._cast)
	if ability == "spears":
		_test_place_near_volley_crystal(hero, raid, trial)


func _test_place_near_volley_crystal(hero: Player, raid: MvpRaid, trial: int) -> void:
	# Try the path where the native nearest-lane goal leads through a crystal.
	# The real cast direction and all native collision checks remain unchanged.
	var start := hero.position
	var d: Vector3 = raid._cast.d
	var side := Vector3(-d.z, 0.0, d.x)
	for i in raid._pillars.size():
		var pillar: Dictionary = raid._pillars[(i + trial) % raid._pillars.size()]
		for sign_index in 2:
			var dir := side * (1.0 if sign_index == 0 else -1.0)
			var at: Vector3 = pillar.pos - dir * 0.85
			if not world.map.is_walkable(at):
				continue
			hero.position = Vector3(at.x, world.map.height_at(at), at.z)
			if (raid.autopilot_goal(hero) - hero.position).dot(dir) > 1.6:
				return
	hero.position = start


func _test_start_field_slam(hero: Player, trial: int) -> void:
	var map: RoMap = world.map
	if map.blocked_in(220, 28, 249, 59) > 0:
		_fail_session("invalid_field_slam_ground")
		return
	var at := map.cell_center(235 + trial, 43)
	var dir := Vector3.RIGHT.rotated(Vector3.UP, float(trial) * TAU / 5.0)
	hero.position = Vector3(at.x, map.height_at(at), at.z)
	world.altars.spawn("loki", at)
	var foe: Enemy = world.spawn_enemy("fallen_bishop", at - dir * 6.0, true)
	if not is_instance_valid(foe) or foe.brain == null:
		_fail_session("missing_field_slam_enemy")
		return
	foe._immovable = true
	foe.max_hp *= 100.0
	foe.hp = foe.max_hp * (0.45 if trial % 2 == 0 else 1.0)
	foe.hold = 20.0
	foe.hit_cd = 20.0
	for _attempt in 12:
		# The native starter picks slam or summon when charge is excluded.
		foe.brain._last = "charge"
		foe.brain._start_attack(world)
		if foe.brain._state == "slam":
			_test_mvp_enemy = foe
			_test_raid_ability = {"id": "slam"}
			_test_raid_hits = _test_mvp_hits()
			_test_raid_fails = 0
			_test_raid_end = float(world.clock) + 5.0
			return
		for add: Enemy in world.enemies.duplicate():
			if add.summoned:
				world.banish_enemy(add)
	_fail_session("missing_field_slam_telegraph")


func _test_mvp_hits() -> int:
	var key := "fallen_bishop" if is_instance_valid(_test_mvp_enemy) else "mechanics:" + str(world.raid.mvp)
	return int(world.meter_taken.get(key, {}).get("hits", 0))


func _test_log_mvp_mechanic(died: bool) -> void:
	var contacts := _test_raid_fails if is_instance_valid(_test_mvp_enemy) else int(world.raid.stats.fails) - _test_raid_fails
	_log("MVP_DRILL run=%d ability=%s danger=%d oaths=%d strikes=%d contacts=%d hits=%d died=%s" % [
		runs_started, _test_raid_ability.id, active_danger, active_oath_points, _test_raid_marks,
		contacts, _test_mvp_hits() - _test_raid_hits, str(died)])


func _test_tick_valkyrie() -> void:
	var raid = world.raid
	var hero = world.player
	if raid.state == "idle" and _test_raid_ability.is_empty() and not get_tree().paused:
		world.karma.enter_route()
		return
	if raid.state != "fight":
		return
	if _test_raid_ability.is_empty():
		# Isolate one native ability per fight so collision and damage meter
		# deltas are attributable even for delayed strikes.
		var abilities: Array = raid.data.abilities
		var index := runs_started - 1
		var ab: Dictionary = abilities[index] if index < abilities.size() else {}
		if ab.is_empty():
			for attack in abilities:
				if attack.id == "starfall":
					ab = attack
					break
		_test_raid_marks = 0
		raid.boss.max_hp *= 100.0
		raid.boss.hp = raid.boss.max_hp
		raid.boss.hold = 20.0
		for other in abilities:
			raid._timers[other.id] = 999.0
		if ab.id == "starfall":
			if not hero.doom:
				_fail_session("valkyrie_drill_missing_doom")
				return
			# Stress a depleted late-run hero without changing native damage.
			hero.hp = minf(hero.hp, hero.max_hp * 0.2)
			hero.revives = 0
			var trial := 0 if index < abilities.size() else index - abilities.size() + 1
			var d := Vector3.RIGHT.rotated(Vector3.UP, float(trial) * TAU / 10.0)
			var at: Vector3 = raid.center + d * (raid.radius - 1.0)
			if world.map.is_walkable(at):
				hero.position = Vector3(at.x, world.map.height_at(at), at.z)
				var boss_at: Vector3 = at - d * 3.0
				raid.boss.position = Vector3(boss_at.x, world.map.height_at(boss_at), boss_at.z)
		_test_raid_ability = ab
		_test_raid_hits = _test_valkyrie_hits()
		_test_raid_fails = int(raid.stats.fails)
		_test_raid_end = float(raid.stats.time) + maxf(6.0, float(ab.get("time", 0.0)) + 3.0)
		raid._start(ab)
	else:
		if _test_raid_ability.id == "starfall":
			for attack in raid._objects:
				if attack.kind == "starfall":
					_test_raid_marks = int(attack.n)
					break
		if float(raid.stats.time) >= _test_raid_end:
			_end_run_safe(false)


func _test_valkyrie_hits() -> int:
	return int(world.meter_taken.get("mechanics:reginleif", {}).get("hits", 0))


func _test_log_valkyrie(died: bool) -> void:
	_log("VALKYRIE_DRILL run=%d ability=%s danger=%d oaths=%d marks=%d contacts=%d hits=%d died=%s cause=%s" % [
		runs_started, _test_raid_ability.id, active_danger, active_oath_points, _test_raid_marks,
		int(world.raid.stats.fails) - _test_raid_fails, _test_valkyrie_hits() - _test_raid_hits,
		str(died), str(world.player.death_by.get("what", "")) if died else ""])


func _test_seed_wishlist_offer() -> void:
	# Avoid random drops; the game's own end screen still builds the keep offer.
	if _test_wishlist_ids.is_empty():
		var owned: Array = Save.storage().map(func(it): return str(it.id))
		var regular: Array[String] = []
		var unique := ""
		for id in GameData.ITEMS:
			var item := Equipment.make(id, 0)
			if not Equipment.is_legendary(item) or Equipment.is_perm(item):
				continue
			if Equipment.is_unique(item):
				if unique.is_empty() and not owned.has(id):
					unique = id
			elif not owned.has(id):
				regular.append(id)
			if regular.size() >= 2 and not unique.is_empty():
				break
		if regular.size() < 2 or unique.is_empty():
			return
		_test_wishlist_ids.assign([unique, regular[0], regular[1]])
		cfg["wishlist"] = [unique, regular[0]]
		# Keep the native minimum price from making both offers unaffordable.
		Save.add_zeny(maxi(0, 100000 - int(Save.zeny())))
	for id in _test_wishlist_ids:
		world.player.equipment.bag.append(Equipment.make(id, 0))


func _test_wishlist_evidence(offer: Array, free: bool) -> Dictionary:
	var items: Array = []
	for item in offer:
		var coins := int(Equipment.legend_coins(item))
		items.append({
			"id": str(item.id), "legend_coins": coins,
			"cost": 0 if free else int(world.menus._keep_cost(item)),
			"sell_zeny": int(Equipment.sell_price(item)) if coins == 0 and item.get("_worn", false) else 0,
		})
	return {
		"fixture_ids": _test_wishlist_ids, "offer": items, "free": free,
		"wishlist": cfg["wishlist"], "before": _keep_snapshot(Save.data),
	}


func _keep_snapshot(profile: Dictionary) -> Dictionary:
	var storage: Array = profile.get("storage", [])
	var materials: Dictionary = profile.get("materials", {})
	return {
		"stored_ids": storage.map(func(item): return str(item.id)),
		"legend_coins": int(materials.get("legend_coin", 0)), "zeny": int(profile.get("zeny", 0)),
	}


# Only the sandbox verifier captures these fields; ordinary status stays unchanged.
func _preparation_snapshot(profile: Dictionary) -> Dictionary:
	if profile.is_empty():
		return {}
	var loadouts := {}
	var worn := {}
	for cid in profile.get("loadouts", {}):
		var loadout: Dictionary = profile["loadouts"][cid]
		if not loadout.is_empty():
			loadouts[cid] = loadout
			for uid in loadout.values():
				worn[str(uid)] = true
	var potentials := {}
	for item in profile.get("storage", []):
		var uid := str(item.get("uid", ""))
		if worn.has(uid):
			potentials[uid] = item.get("pot")
	var stats := {}
	var rebirth_levels := {}
	var progress: Dictionary = profile.get("classes", {})
	for cid in GameData.CLASSES:
		var entry: Dictionary = progress.get(cid, {})
		stats[cid] = entry.get("stats", {})
		rebirth_levels[cid] = int(entry.get("rlv", 0))
	var settings: Dictionary = profile.get("settings", {})
	return {
		"loadouts": loadouts, "potentials": potentials, "pet": profile.get("pet", ""),
		"album": profile.get("card_slots", []), "stats": stats, "free_points": Save.free_points(active_class),
		"rebirths": profile.get("rebirths", {}), "rebirth_levels": rebirth_levels,
		"pick_order": settings.get("pick_order", {}), "pick_limits": settings.get("pick_limits", {}),
		"pick_fill": settings.get("pick_fill"), "pick_bans": settings.get("pick_bans"),
		"endless_auto_pick": settings.get("endless_auto_pick"),
	}.duplicate(true)


func _test_progress_board_request(child: Node) -> void:
	if child is HTTPRequest and not world.running:
		run_state["progress"]["board_requests"] += 1


func _test_seed_progress() -> void:
	# Make the fixture observable even if the copied profile already holds the records.
	var seen: Dictionary = Save.data.get("seen", {})
	seen.get("title_hell_classes", {}).erase(active_class)
	seen.get("title_hell_maps", {}).erase(active_stage)
	Save.data.get("oath_best", {}).erase(active_stage)
	Save.data["stats"]["altars_run"] = 0
	Save.mark_dirty()


func _progress_snapshot(profile: Dictionary) -> Dictionary:
	var seen: Dictionary = profile.get("seen", {})
	var stats: Dictionary = profile.get("stats", {})
	return {
		"history": profile.get("history", []), "hell_classes": seen.get("title_hell_classes", {}),
		"hell_maps": seen.get("title_hell_maps", {}), "titles": seen.get("titles", {}),
		"oath_best": profile.get("oath_best", {}), "altars": stats.get("altars", 0),
		"altars_run": stats.get("altars_run", 0), "cloud_rev": profile.get("settings", {}).get("cloud_rev"),
		"world_feats": profile.get("settings", {}).get("world_feats"),
	}.duplicate(true)


# One-shot per sandbox: the relaunch (or supervisor restart) passes the same point.
func _test_crash(point: String) -> void:
	if _test_env("CRASH_AT") != point or FileAccess.file_exists(TEST_CRASHED_PATH):
		return
	var f := FileAccess.open(TEST_CRASHED_PATH, FileAccess.WRITE)
	if f != null:
		f.store_string(point)
		f.close()
	_log("TEST_CRASH " + point)
	OS.kill(OS.get_process_id())


func _build_result() -> Dictionary:
	var p = world.player if world != null and is_instance_valid(world) else null
	var snap: Dictionary = run_state.get("settled", {})
	var mats_now: Dictionary = (snap.get("materials", Save.materials()) as Dictionary).duplicate(true)
	var mats_delta: Dictionary = {}
	var mats_start: Dictionary = run_state.get("materials", {})
	for k in mats_now:
		var d := int(mats_now[k]) - int(mats_start.get(k, 0))
		if d != 0:
			mats_delta[str(k)] = d
	var zeny_now := int(snap.get("zeny", Save.zeny()))
	var coins_now := int(snap.get("coins", Save.coins() if Save.has_method("coins") else 0))
	var ymir_now := int(snap.get("ymir", Save.ymir_fragments() if Save.has_method("ymir_fragments") else 0))
	var cards_now := int(snap.get("cards", _total_card_copies()))
	var pets_now := int(snap.get("pets", (Save.data.get("pets", {}) as Dictionary).size()))
	var level_now := int(snap.get("class_level", Save.class_progress(active_class).get("level", 1)))
	var rlv_now := int(snap.get("class_rlv", Save.class_progress(active_class).get("rlv", 0)))
	var xp_gain := 0
	if p != null and is_instance_valid(p):
		xp_gain = int(round(float(p.xp_gained) * (1.0 + 0.08 * float(maxi(0, active_danger - 1)))))
	var wall := float(_now() - int(run_state.get("wall_start", _now()))) / 1000.0
	var game := float(world.time) if world != null and is_instance_valid(world) else 0.0
	var result := {
		"run": runs_done + 1,
		"run_id": str(run_state.get("run_id", "")),
		"session": session_id,
		"class": active_class,
		"stage": active_stage,
		"danger": active_danger,
		"oath_points": active_oath_points,
		"victory": bool(run_state.get("victory", false)),
		"finale_won": bool(run_state.get("finale_won", false)),
		"died": bool(run_state.get("died", false)),
		"falls_by_mechanic": run_state["falls_by_mechanic"],
		"arena_timings": run_state["arena_timings"],
		"forced": bool(run_state.get("forced", false)),
		"force_reason": str(run_state.get("force_reason", "")),
		"endless": bool(world.endless) if world != null and is_instance_valid(world) else false,
		"endless_mvps": int(run_state.get("endless_mvps", 0)),
		"wall_s": wall,
		"game_s": game,
		"kills": int(run_state.get("kills", 0)),
		"run_mvps": int(run_state.get("run_mvps", 0)),
		"zeny_gain": zeny_now - int(run_state.get("zeny", zeny_now)),
		"run_zeny": int(run_state.get("run_zeny", 0)),
		"xp_gain": xp_gain,
		"materials": mats_delta,
		"coins_gain": coins_now - int(run_state.get("coins", coins_now)),
		"ymir_gain": ymir_now - int(run_state.get("ymir", ymir_now)),
		"cards_gain": cards_now - int(run_state.get("cards", cards_now)),
		"pets_gain": pets_now - int(run_state.get("pets", pets_now)),
		"storage_gain": int(snap.get("storage", Save.storage().size())) - int(run_state.get("storage", 0)),
		"class_level": level_now,
		"class_rlv": rlv_now,
		"class_ups": maxi(0, level_now - int(run_state.get("class_level", level_now))) + maxi(0, rlv_now - int(run_state.get("class_rlv", rlv_now))) * 50,
		"player_level": int(p.level) if p != null and is_instance_valid(p) else 0,
		"job": str(p.job2.get("id", "")) if p != null and is_instance_valid(p) else "",
		"max_danger": int(Save.max_danger()) if Save.has_method("max_danger") else 0,
		"kept": run_state.get("kept", []),
		"keep_skipped": run_state.get("keep_skipped", []),
		"value": 0.0,
		"rate": 0.0,
	}
	if run_state.has("progress"):
		result["progress"] = run_state["progress"]
	if run_state.has("tower_floor_start"):
		for key in ["tower_floor_start", "tower_floor_best", "end_cause", "snapshot"]:
			result[key] = run_state.get(key)
	elif cfg["karma_route"] == "valhalla":
		result["valkyrie_kills"] = int(run_state.get("valkyrie_kills", 0))
		result["reginleif_cards_gain"] = int(Save.data.get("cards", {}).get("reginleif_card", 0)) \
				- int(run_state.get("reginleif_cards", 0))
	result["value"] = _run_value(result)
	result["rate"] = float(result["value"]) / maxf(1.0, wall)
	return result


func _run_value(r: Dictionary) -> float:
	var w: Dictionary = cfg.get("weights", {})
	var mats: Dictionary = r.get("materials", {})
	var ore := float(mats.get("oridecon", 0)) + float(mats.get("elunium", 0))
	ore += 2.0 * (float(mats.get("enriched_oridecon", 0)) + float(mats.get("enriched_elunium", 0)))
	ore += 4.0 * (float(mats.get("hd_oridecon", 0)) + float(mats.get("hd_elunium", 0)))
	var v := float(r.get("zeny_gain", 0)) * float(w.get("zeny", 1.0))
	v += ore * float(w.get("ore", 1500.0))
	v += float(mats.get("star_crumb", 0)) * float(w.get("crumb", 100000.0))
	v += float(mats.get("hel_tear", 0)) * float(w.get("tear", 300000.0))
	v += float(r.get("xp_gain", 0)) * float(w.get("xp", 1.0))
	v += float(r.get("cards_gain", 0)) * float(w.get("card", 30000.0))
	v += float(r.get("pets_gain", 0)) * float(w.get("pet", 100000.0))
	v += float(r.get("coins_gain", 0)) * float(w.get("coin", 15000.0))
	v += float(r.get("ymir_gain", 0)) * float(w.get("ymir", 50000.0))
	v += float(r.get("class_ups", 0)) * float(w.get("class_up", 20000.0))
	return v


func _update_arm(r: Dictionary) -> void:
	var key := "%s|%d" % [str(r.get("stage", "")), int(r.get("danger", 1))]
	var arm: Dictionary = arms.get(key, {})
	if arm.is_empty():
		arm = {"stage": str(r.get("stage", "")), "danger": int(r.get("danger", 1)), "runs": 0, "wins": 0, "deaths": 0, "timeouts": 0, "kills": 0, "wall": 0.0, "value": 0.0, "rate": 0.0, "cooldown_until": 0, "win_streak": 0}
	arm["runs"] = int(arm.get("runs", 0)) + 1
	arm["kills"] = int(arm.get("kills", 0)) + int(r.get("kills", 0))
	arm["wall"] = float(arm.get("wall", 0.0)) + float(r.get("wall_s", 0.0))
	arm["value"] = float(arm.get("value", 0.0)) + float(r.get("value", 0.0))
	var wall_sum := maxf(1.0, float(arm["wall"]))
	var rate := float(arm["value"]) / wall_sum
	arm["rate"] = rate
	if bool(r.get("victory", false)):
		arm["wins"] = int(arm.get("wins", 0)) + 1
		arm["win_streak"] = int(arm.get("win_streak", 0)) + 1
		arm["cooldown_until"] = 0
	else:
		arm["win_streak"] = 0
		if bool(r.get("died", false)):
			arm["deaths"] = int(arm.get("deaths", 0)) + 1
		if bool(r.get("forced", false)):
			arm["timeouts"] = int(arm.get("timeouts", 0)) + 1
		arm["cooldown_until"] = runs_done + 3
	arms[key] = arm
	_save_arms()


func _append_run_log(r: Dictionary) -> bool:
	var f := FileAccess.open(RUNS_PATH, FileAccess.READ_WRITE)
	if f == null:
		f = FileAccess.open(RUNS_PATH, FileAccess.WRITE)
	if f == null:
		return false
	f.seek_end()
	f.store_line(JSON.stringify(r))
	f.flush()
	var ok := f.get_error() == OK
	f.close()
	return ok


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

func _load_cfg() -> bool:
	if not FileAccess.file_exists(CFG_PATH):
		_log("CFG missing")
		return false
	var text := FileAccess.get_file_as_string(CFG_PATH)
	var parsed = JSON.parse_string(text)
	if not (parsed is Dictionary):
		_log("CFG parse error")
		return false
	var raw: Dictionary = parsed
	var errors: Array = []
	var out := {
		"objective": "balanced",
		"weights": {},
		"class": "",
		"builds": {},
		"stage": "", "danger": "auto", "danger_ceiling": 30,
		"oaths": {},
		"wishlist": [],
		"keep_unowned_legendaries": false,
		"auto_danger": true, "explore_every": 5, "danger_step": 1,
		"featured_bonus": true,
		"speed": 4.0, "game_speed": 3,
		"run_minutes": 12.0, "arena_wall_max": 180.0, "stall_seconds": 45.0,
		"endless": false, "endless_minutes": 4.0, "endless_mvps": 0,
		"max_runs": 0, "max_minutes": 0.0, "stop_after_wins": 0,
		"display": false, "offline": true, "hard_exit": true,
		"keep_reserve_slots": 2, "keep_max_pct": 0.05,
		"auto_achievements": true,
		"auto_upgrades": true, "upgrade_reserve": 500000, "storage_target": 120,
		"upgrade_priority": ["bubble_gum", "battle_manual", "greed", "blessing", "increase_agi", "yggdrasil_fruit", "fury", "gloria", "magnificat", "angelus", "hp_recovery", "telescope", "kafra_status", "kafra_summon", "kafra_area", "kafra_amount", "kafra_blow", "vultures_eye", "memorize", "card_slot", "kafra_cart", "kafra_storage"],
		"auto_sage": true, "sage_priority": ["passive_slot", "sage_book", "sage_root", "sage_start", "fly_wing", "magnifier"],
		"auto_fuse": true, "fuse_keep": {},
		"auto_potential": false, "potential_reserve": 20, "potential_max_rolls": 10,
		"auto_storage_prune": false,
		"altar_priority": ["freyja", "loki", "niflheim", "thor", "yggdrasil", "valkyrie", "baldur", "odin", "emperium"],
		"altar_range": 12.0,
		"altar_policy": "cautious", "karma_route": "natural",
		"goals": {}, "goal_stop": false,
	}
	for k in raw.keys():
		var key := str(k)
		out[key] = raw[k]
	cfg = out
	_check_num(errors, "speed", 1.0, 30.0)
	_check_num(errors, "game_speed", 1.0, 3.0)
	_check_num(errors, "run_minutes", 0.0, 1440.0)
	_check_num(errors, "arena_wall_max", 0.0, 3600.0)
	_check_num(errors, "stall_seconds", 0.0, 600.0)
	_check_num(errors, "endless_minutes", 0.0, 1440.0)
	_check_num(errors, "max_minutes", 0.0, 100000.0)
	_check_num(errors, "keep_max_pct", 0.0, 1.0)
	_check_num(errors, "danger_ceiling", 1.0, 30.0)
	_check_num(errors, "explore_every", 1.0, 1000.0)
	if not (cfg.get("weights") is Dictionary):
		errors.append("weights must be an object")
	if not (cfg.get("builds") is Dictionary):
		errors.append("builds must be an object")
	if not (cfg.get("goals") is Dictionary):
		errors.append("goals must be an object")
	if cfg["altar_policy"] not in ["cautious", "map-wide"]:
		errors.append("altar_policy must be cautious or map-wide")
	if cfg["karma_route"] not in ["natural", "valhalla"]:
		errors.append("karma_route must be natural or valhalla")
	if not (cfg["wishlist"] is Array):
		errors.append("wishlist must be an array of item ids")
	else:
		var ids := {}
		for id in cfg["wishlist"]:
			if not (id is String) or id.strip_edges().is_empty() or ids.has(id):
				errors.append("wishlist must be an array of distinct item ids")
				break
			ids[id] = true
	if not (cfg["keep_unowned_legendaries"] is bool):
		errors.append("keep_unowned_legendaries must be a boolean")
	if not errors.is_empty():
		_log("CFG invalid: " + str(errors))
		return false
	cfg["speed"] = clampf(float(cfg.get("speed", 4.0)), 1.0, 30.0)
	cfg["game_speed"] = clampi(int(cfg.get("game_speed", 3)), 1, 3)
	cfg["run_minutes"] = maxf(0.0, float(cfg.get("run_minutes", 12.0)))
	cfg["arena_wall_max"] = maxf(0.0, float(cfg.get("arena_wall_max", 180.0)))
	cfg["stall_seconds"] = maxf(0.0, float(cfg.get("stall_seconds", 45.0)))
	cfg["endless_minutes"] = maxf(0.0, float(cfg.get("endless_minutes", 4.0)))
	cfg["max_minutes"] = maxf(0.0, float(cfg.get("max_minutes", 0.0)))
	cfg["keep_max_pct"] = clampf(float(cfg.get("keep_max_pct", 0.05)), 0.0, 1.0)
	cfg["danger_ceiling"] = clampi(int(cfg.get("danger_ceiling", 30)), 1, int(GameData.DANGER_MAX))
	cfg["explore_every"] = maxi(1, int(cfg.get("explore_every", 5)))
	cfg["max_runs"] = maxi(0, int(cfg.get("max_runs", 0)))
	cfg["stop_after_wins"] = maxi(0, int(cfg.get("stop_after_wins", 0)))
	cfg["keep_reserve_slots"] = maxi(0, int(cfg.get("keep_reserve_slots", 2)))
	cfg["storage_target"] = clampi(int(cfg.get("storage_target", 120)), 20, 500)
	cfg["upgrade_reserve"] = maxi(0, int(cfg.get("upgrade_reserve", 500000)))
	cfg["potential_reserve"] = maxi(0, int(cfg.get("potential_reserve", 20)))
	cfg["potential_max_rolls"] = maxi(0, int(cfg["potential_max_rolls"]))
	return true


func _check_num(errors: Array, key: String, lo: float, hi: float) -> void:
	if not cfg.has(key):
		return
	var v = cfg[key]
	if not (v is int or v is float):
		errors.append("%s must be a number" % key)
		return
	if float(v) < lo or float(v) > hi:
		errors.append("%s out of range" % key)


# ---------------------------------------------------------------------------
# Status / logging / lifecycle
# ---------------------------------------------------------------------------

func _write_status() -> void:
	heartbeat_seq += 1
	var p = null
	if world != null and is_instance_valid(world):
		p = world.player
	var data := {
		"session": session_id,
		"pid": OS.get_process_id(),
		"phase": phase,
		"terminal": phase == "done" or phase == "failed",
		"failed": failed,
		"finish_reason": finish_reason,
		"last_error": last_error,
		"last_transition": last_transition,
		"exit_code": exit_code,
		"run_id": str(run_state.get("run_id", "")),
		"heartbeat": int(Time.get_unix_time_from_system()),
		"heartbeat_seq": heartbeat_seq,
		"uptime_s": float(_now() - boot_ms) / 1000.0,
		"api": API_VERSION,
		"build": _build_info(),
		"objective": str(cfg.get("objective", "")),
		"target": {"stage": active_stage, "danger": active_danger, "class": active_class, "oath_points": active_oath_points},
		"totals": _totals(),
		"rates": _rates(),
		"arms": arms,
		"last": last_run,
		"run": {
			"victory": bool(run_state.get("victory", false)),
			"boss_won": bool(run_state.get("boss_won", false)),
			"forced": bool(run_state.get("forced", false)),
			"won_at": int(run_state.get("won_at", 0)),
			"last_run_mvps": int(run_state.get("last_run_mvps", 0)),
			"endless_started_at": float(run_state.get("endless_started_at", -1.0)),
			"endless_mvps": int(run_state.get("endless_mvps", 0)),
		},
		"maint": last_maint,
		"game": {
			"running": bool(world.running) if world != null and is_instance_valid(world) else false,
			"mode": str(world.menus._mode) if world != null and is_instance_valid(world) and world.menus != null else "",
			"paused": get_tree().paused,
			"fps": Engine.get_frames_per_second(),
			"time": float(world.time) if world != null and is_instance_valid(world) else 0.0,
			"kills": int(world.kills) if world != null and is_instance_valid(world) else 0,
			"hp": float(p.hp) if p != null and is_instance_valid(p) else 0.0,
			"max_hp": float(p.max_hp) if p != null and is_instance_valid(p) else 0.0,
			"level": int(p.level) if p != null and is_instance_valid(p) else 0,
			"danger": int(world.danger) if world != null and is_instance_valid(world) else 0,
			"stage": str(world.stage_id) if world != null and is_instance_valid(world) else "",
			"in_raid": bool(world.raid.in_arena()) if world != null and is_instance_valid(world) and world.raid != null else false,
		},
		"profile": {
			"zeny": int(Save.zeny()),
			"coins": int(Save.coins()) if Save.has_method("coins") else 0,
			"max_danger": int(Save.max_danger()) if Save.has_method("max_danger") else 0,
			"storage": int(Save.storage().size()),
			"storage_cap": int(Save.storage_cap()),
			"materials": Save.materials().duplicate(true),
			"ymir": int(Save.ymir_fragments()) if Save.has_method("ymir_fragments") else 0,
		},
	}
	if _test_preparation.has("after"):
		data["preparation"] = _test_preparation
	if not _test_catalog.is_empty():
		data["catalog_evidence"] = _test_catalog
	if _test_oaths.has("after"):
		data["oath_evidence"] = _test_oaths
	if not _test_wishlist_runs.is_empty():
		data["wishlist_evidence"] = _test_wishlist_runs
	if phase == "done" and _test_env("PROGRESS") == "1":
		data["progress_saved"] = _progress_snapshot(Save._read(Save.PATH))
	if not _test_tower_evidence.is_empty():
		data["tower_evidence"] = _test_tower_evidence
	_atomic_write(STATUS_PATH, JSON.stringify(data))


func _rates() -> Dictionary:
	var wall_min := float(_now() - boot_ms) / 60000.0
	var out := {"zeny_h": 0.0, "kills_min": 0.0, "ore_h": 0.0, "crumbs_h": 0.0, "xp_h": 0.0}
	if wall_min <= 0.01:
		return out
	var ore := 0
	for k in total_materials:
		if str(k) == "oridecon" or str(k) == "elunium":
			ore += int(total_materials[k])
	out["zeny_h"] = float(total_zeny) / wall_min * 60.0
	out["kills_min"] = float(total_kills) / wall_min
	out["ore_h"] = float(ore) / wall_min * 60.0
	out["crumbs_h"] = float(total_materials.get("star_crumb", 0)) / wall_min * 60.0
	out["xp_h"] = float(total_xp) / wall_min * 60.0
	return out


func _write_catalog() -> bool:
	var unlocked_max := int(Save.max_danger())
	var locations: Array = []
	for id in GameData.STAGES:
		if not world.is_stage_exported(id):
			continue
		var bounds: Vector2i = GameData.stage_danger_range(id, unlocked_max)
		locations.append({
			"id": id, "name": TranslationServer.translate(str(GameData.STAGES[id].name)),
			"unlocked": bool(world.is_stage_unlocked(id)), "min_difficulty": bounds.x, "max_difficulty": bounds.y,
		})
	var oaths: Array = []
	for oath in GameData.OATHS:
		var ranks: Array = []
		for i in (oath.pts as Array).size():
			ranks.append({
				"rank": i + 1, "description": TranslationServer.translate(str(oath.ranks[i])), "points": oath.pts[i],
			})
		oaths.append({
			"id": oath.id, "name": TranslationServer.translate(str(oath.name)),
			"description": TranslationServer.translate(str(oath.desc)), "ranks": ranks,
		})
	var legendaries: Array = []
	for id in GameData.ITEMS:
		var item: Dictionary = GameData.ITEMS[id]
		if bool(item.get("legendary", false)):
			legendaries.append({"id": id, "name": TranslationServer.translate(str(item.name))})
	var owned: Dictionary = {}
	for item in Save.storage():
		owned[str(item.id)] = true
	return _atomic_write(CATALOG_PATH, JSON.stringify({
		"schema": 1, "written_at": Time.get_unix_time_from_system(),
		"max_difficulty": GameData.DANGER_MAX, "unlocked_max_difficulty": unlocked_max,
		"locations": locations, "oaths": oaths, "legendaries": legendaries, "owned_item_ids": owned.keys(),
		"tower": _tower_catalog(),
	}))


func _refresh_tower_catalog() -> bool:
	if _write_catalog():
		return true
	_fail_session("catalog_write_failed")
	return false


func _tower_hel_reason() -> String:
	if Save.hel_open():
		return ""
	if not Save.hel_earned():
		return "Clear Endless Tower floor %d to unlock Torre de Hel." % GameData.TOWER_FLOORS
	return "Torre de Hel is not yet released."


func _tower_catalog() -> Dictionary:
	var snapshots: Array = []
	var builds: Array = Save.tower_builds()
	for i in builds.size():
		if _valid_tower_build(builds[i]):
			snapshots.append(_tower_snapshot_entry(builds[i], i))
	return {
		"open": Save.tower_open(), "hel_unlocked": Save.hel_open(), "hel_reason": _tower_hel_reason(),
		"checkpoints": Save.tower_checkpoints(), "snapshots": snapshots,
	}


func _valid_tower_build(build: Variant) -> bool:
	return build is Dictionary and GameData.CLASSES.has(build.get("class")) and int(build.get("level", 0)) > 0


func _tower_snapshot_id(build: Dictionary) -> String:
	return JSON.stringify([
		str(build.get("class", "")), bool(build.get("job2", false)), int(build.get("job_path", 0)),
		str(build.get("name", "")), int(build.get("level", 0)), float(build.get("xp", 0.0)),
		str(build.get("saved", "")),
	]).sha256_text()


func _tower_snapshot_entry(build: Dictionary, index: int) -> Dictionary:
	# Native snapshots store local ISO datetime without an offset.
	var saved := str(build.get("saved", ""))
	var saved_at := 0.0
	if not saved.is_empty():
		saved_at = float(Time.get_unix_time_from_datetime_string(saved)) - float(Time.get_time_zone_from_system().bias) * 60.0
	var cid: String = build["class"]
	return {
		"index": index, "id": _tower_snapshot_id(build), "class": cid,
		"job": str(build.get("name", GameData.CLASSES[cid].get("name", cid))),
		"level": int(build["level"]), "xp_progress": _tower_xp_progress(build), "saved_at": maxf(0.0, saved_at),
		"locked": Save.build_locked(build), "farmer": build.has("farmer_run_id"),
	}


func _tower_xp_progress(build: Dictionary) -> float:
	return clampf(float(build.get("xp", 0.0)) / maxf(1.0, float(build.get("xp_need", 1.0))), 0.0, 1.0)


func _tower_build_better(a: Dictionary, b: Dictionary) -> bool:
	if int(a["level"]) != int(b["level"]):
		return int(a["level"]) > int(b["level"])
	var xp_a := _tower_xp_progress(a)
	var xp_b := _tower_xp_progress(b)
	if xp_a != xp_b:
		return xp_a > xp_b
	return str(a.get("saved", "")) > str(b.get("saved", ""))


func _pick_tower_snapshot() -> Dictionary:
	var best: Dictionary = {}
	var index := -1
	var builds: Array = Save.tower_builds()
	for i in builds.size():
		var build = builds[i]
		if _valid_tower_build(build) and not Save.build_locked(build) \
				and (best.is_empty() or _tower_build_better(build, best)):
			best = build
			index = i
	return {} if index == -1 else _tower_snapshot_entry(best, index)


func _save_tower_snapshot() -> void:
	var hero: Player = world.player
	if not is_instance_valid(hero) or world.tower != null or world.training or hero.has_meta("tower_snap") \
			or hero.level < GameData.TOWER_BUILD_MIN_LEVEL or not (Save.tower_open() or Save.tower_ready()):
		return
	var builds: Array = Save.tower_builds()
	var farmer_index := -1
	var farmer_locked := false
	var manual_unlocked := 0
	for i in builds.size():
		var build: Dictionary = builds[i]
		if build.has("farmer_run_id"):
			if build["farmer_run_id"] == run_state["run_id"]:
				return
			farmer_locked = farmer_locked or Save.build_locked(build)
			farmer_index = i
		elif not Save.build_locked(build):
			manual_unlocked += 1
	if manual_unlocked >= Save.TOWER_BUILDS_MAX:
		_log("TOWER_SNAPSHOT_SKIPPED full")
		return
	# Do not replace a snapshot the Operator explicitly protected.
	if farmer_locked:
		return
	var snap := RunSave.hero_snapshot(world)
	if farmer_index != -1:
		if not _tower_build_better(snap, builds[farmer_index]):
			return
		builds.remove_at(farmer_index)
	snap["farmer_run_id"] = run_state["run_id"]
	hero.set_meta("tower_snap", snap)
	hero.set_meta("tower_saved", [true])
	Save.add_tower_build(snap)
	run_state["tower_snapshot_saved"] = true
	_log("TOWER_SNAPSHOT_SAVED run=%s level=%d replaced=%s" % [
		run_state["run_id"], hero.level, str(farmer_index != -1)])


func _test_seed_manual_tower_snapshots() -> bool:
	# Fill all but one unlocked slot in this disposable sandbox, plus a locked entry.
	var builds: Array = Save.tower_builds()
	builds.clear()
	for i in Save.TOWER_BUILDS_MAX:
		Save.add_tower_build({
			"class": "swordsman", "name": "Manual fixture", "level": 20 + i,
			"saved": "2026-01-01T00:00:00", "locked": i == 0, "label": "manual-%d" % i,
		})
	if not _flush_profile_verified("tower_fixture"):
		return false
	_test_tower_evidence["before"] = _tower_save_evidence(Save._read(Save.PATH))
	return true


func _tower_save_evidence(profile: Dictionary) -> Array:
	var builds: Array = profile.get("tower", {}).get("builds", [])
	var out: Array = []
	for i in builds.size():
		var entry := _tower_snapshot_entry(builds[i], i)
		entry.erase("index")
		entry["digest"] = JSON.stringify(builds[i]).sha256_text()
		out.append(entry)
	return out


func _test_observe_tower_request(child: Node) -> void:
	if child is HTTPRequest and not world.running:
		_test_tower_board_requests += 1


func _catalog_evidence() -> Dictionary:
	# Verify against the profile's progress and the game's own item and oath rules.
	var locations: Dictionary = {}
	for id in GameData.STAGES:
		if world.is_stage_exported(id):
			locations[id] = str(GameData.STAGES[id].get("unlock", ""))
	var oath_points: Dictionary = {}
	for oath in GameData.OATHS:
		var points: Array = []
		for rank in range(1, (oath.ranks as Array).size() + 1):
			points.append(GameData.oath_points({oath.id: rank}))
		oath_points[oath.id] = points
	var legendaries: Array = []
	for id in GameData.ITEMS:
		if Equipment.is_legendary({"id": id}):
			legendaries.append(id)
	return {
		"before_run": Time.get_unix_time_from_system(), "location_prerequisites": locations,
		"cleared_locations": Save.data.stages.duplicate(), "oath_points": oath_points, "legendary_ids": legendaries,
		"unlocked_max_difficulty": Save.max_danger(),
		"stored_ids": Save.storage().map(func(item): return str(item.id)),
	}


func _build_info() -> Dictionary:
	if not FileAccess.file_exists(BUILD_PATH):
		return {}
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(BUILD_PATH))
	return parsed if parsed is Dictionary else {}


func _atomic_write(path: String, text: String) -> bool:
	var tmp := path + ".tmp"
	var f := FileAccess.open(tmp, FileAccess.WRITE)
	if f == null:
		return false
	f.store_string(text)
	f.flush()
	var ok := f.get_error() == OK
	f.close()
	if not ok:
		return false
	return DirAccess.rename_absolute(ProjectSettings.globalize_path(tmp), ProjectSettings.globalize_path(path)) == OK


func _log(text: String) -> void:
	var line := "FARMER %s %s" % [Time.get_datetime_string_from_system(), text]
	print(line)
	var f := FileAccess.open(LOG_PATH, FileAccess.READ_WRITE)
	if f == null:
		f = FileAccess.open(LOG_PATH, FileAccess.WRITE)
	if f == null:
		return
	f.seek_end()
	f.store_line(line)
	f.close()


func _mark_transition(label: String) -> void:
	last_transition = "%s@%d" % [label, int(Time.get_unix_time_from_system())]


func _flush_profile_verified(boundary: String) -> bool:
	# The native flush returns no outcome; require this write's unique marker
	# in the readable final profile, not just a changed file or a cleared flag.
	var marker := Crypto.new().generate_random_bytes(16).hex_encode()
	Save.set_setting("farmer_flush_marker", marker)
	var temp_path: String = Save.TMP_PATH
	var fault := _test_env("FLUSH_FAIL")
	if fault == boundary or (fault == "1" and boundary == "finish"):
		Save.TMP_PATH = Save.PATH.path_join("unwritable-test-save")
	Save.flush()
	Save.TMP_PATH = temp_path
	var settings = Save._read(Save.PATH).get("settings")
	if settings is Dictionary and settings.get("farmer_flush_marker") == marker and not marker.is_empty():
		return true
	last_maint = {}
	_fail_session("flush_failed", false, "Could not verify the profile save at %s." % boundary)
	return false


func _now() -> int:
	return Time.get_ticks_msec()


func _load_arms() -> void:
	if not FileAccess.file_exists(ARMS_PATH):
		return
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(ARMS_PATH))
	if parsed is Dictionary:
		arms = parsed


func _save_arms() -> void:
	_atomic_write(ARMS_PATH, JSON.stringify(arms))


func _fail_session(reason: String, allow_hard_exit := true, detail := "") -> void:
	if failed:
		return
	failed = true
	finish_reason = reason
	last_error = detail if detail != "" else reason
	phase = "failed"
	exit_code = 1
	_mark_transition("fail:" + reason)
	_log("FAIL " + reason)
	_write_status()
	if allow_hard_exit and bool(cfg.get("hard_exit", true)) and DisplayServer.get_name() == "headless":
		OS.kill(OS.get_process_id())
		return
	get_tree().quit(1)


func _finish(reason: String) -> void:
	if phase == "done" or _hard_finished:
		return
	finish_reason = reason
	exit_code = 0
	if not _flush_profile_verified("finish"):
		return
	if not _tower_intent.is_empty() and not _refresh_tower_catalog():
		return
	if _test_tower_run and not _tower_intent.is_empty():
		var saved: Dictionary = Save._read(Save.PATH)
		_test_tower_evidence["after"] = _tower_save_evidence(saved)
		_test_tower_evidence["preparation_after"] = _preparation_snapshot(saved)
		_test_tower_evidence["board_requests"] = _test_tower_board_requests
	if _test_preparation.has("before"):
		_test_preparation["after"] = _preparation_snapshot(Save._read(Save.PATH))
	if _test_oaths.has("before"):
		_test_oaths["after"] = Save._read(Save.PATH).get("oaths")
	if reason == "abort":
		if phase == "keep":
			run_state["settled"] = _reward_snapshot()
		if runs_started > runs_done + runs_lost and run_state.has("settled"):
			# Journal what was already banked, including any keep already done.
			if not _record_run():
				return
		elif phase == "run" or phase == "settle":
			runs_lost += 1
			if not _write_checkpoint("idle"):
				return
	_mark_transition("finish:" + reason)
	_log("FINISH %s runs=%d wins=%d losses=%d zeny=%d" % [reason, runs_done, wins, losses, total_zeny])
	phase = "done"
	_write_status()
	_hard_finished = true
	if bool(cfg.get("hard_exit", true)) and DisplayServer.get_name() == "headless":
		print("FARMER HARD_EXIT")
		OS.kill(OS.get_process_id())
		return
	get_tree().quit(0)
