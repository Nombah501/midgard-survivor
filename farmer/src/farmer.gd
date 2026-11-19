extends Node
## Midgard Survivors autonomous farmer (v3).
##
## One brain node, loaded by a tiny Save autoload hook. It plays real runs,
## controls the level-up draft itself, keeps loot through Save's own storage API,
## and spends persistent resources between runs. No game script is patched except
## the Save bootstrap.
##
## Design: docs/design/farmer.md. Game study: docs/analysis/.
## API_VERSION is bumped whenever the expected game symbols change.

const API_VERSION := 3

const CFG_PATH := "user://farmer.cfg"
const STATUS_PATH := "user://farmer_status.json"
const ARMS_PATH := "user://farmer_arms.json"
const RUNS_PATH := "user://farmer_runs.jsonl"
const CHECKPOINT_PATH := "user://farmer_session.json"
const LOG_PATH := "user://farmer.log"
const COMMAND_PATH := "user://farmer_command"
const STOP_PATH := "user://farmer_stop"
const LOCK_PATH := "user://farmer.lock"
const BUILD_PATH := "user://farmer_build.json"

const RESULT_BOSS_WON := "boss_won"

const STATUS_EVERY_MS := 5000
const TICK_MS := 100
const VICTORY_PULL_MS := 1500
const SETTLE_WAIT_MS := 25000
const MAX_DRAFT_PER_TICK := 32

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
var next_arm_hint := ""

var run_state: Dictionary = {}
var last_run: Dictionary = {}
var arms: Dictionary = {}
var last_maint: Dictionary = {}

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
var _lock_pid := 0
var _test_wait_at_keep := false

var _potential_script = null
var _vanilla_input_seen := false

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
	if session_id == "":
		session_id = "%s-%d" % [Time.get_datetime_string_from_system().replace(":", "").replace("-", "").replace("T", "-"), OS.get_process_id()]
	if session_id.begins_with("verify-"):
		_test_wait_at_keep = OS.get_environment("FARMER_TEST_WAIT_AT_KEEP") == "1"
	_potential_script = load("res://scripts/core/potential.gd")
	_load_arms()
	_mark_transition("boot")
	if not _load_cfg():
		_fail_session("cfg_invalid")
		return
	if not _acquire_lock():
		_log("LOCKED by pid %d: another farmer session is alive" % _lock_pid)
		_fail_session("locked")
		return
	_log("BOOT api=%d session=%s zeny=%d cfg=%s" % [API_VERSION, session_id, int(Save.zeny()), JSON.stringify(cfg)])
	if not _restore_checkpoint():
		return
	_write_status()


func _notification(what: int) -> void:
	if what == NOTIFICATION_EXIT_TREE or what == NOTIFICATION_PREDELETE:
		_release_lock()
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
	_apply_autopilot()
	_replace_player_input()
	Save.set_setting("onboarded", true)
	Save.set_setting("endless_auto_pick", false)
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
	# Own the engine clock: _frenzy_time_scale() returns early, so the game
	# stops rewriting Engine.time_scale every frame.
	world._mvp_slow = true
	world.fast_now = true
	if world.menus != null and is_instance_valid(world.menus):
		world.menus.auto_pick = true
	var want := maxf(1.0, float(cfg.get("speed", 4.0)))
	if not is_equal_approx(Engine.time_scale, want):
		Engine.time_scale = want


func _replace_player_input() -> void:
	if world == null or not is_instance_valid(world):
		return
	var p = world.player
	if p == null or not is_instance_valid(p):
		return
	if p.input is FarmerInput:
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
	if _goal_done() and bool(cfg.get("goal_stop", false)):
		_finish("goal")
		return
	var target := _choose_target()
	if target.is_empty():
		_finish("no_target")
		return
	active_stage = str(target.get("stage", ""))
	active_danger = int(target.get("danger", 1))
	active_class = str(target.get("class", ""))
	if active_class == "" or active_stage == "":
		_finish("no_target")
		return
	_apply_build_settings(active_class)
	var run_id := "%s-r%d" % [session_id, runs_started + 1]
	run_state = _snapshot_run_state()
	run_state["run_id"] = run_id
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
	run_state["kills"] = 0
	run_state["run_zeny"] = 0
	run_state["run_mvps"] = 0
	run_state["route_entered"] = false
	_time_last = -1.0
	_time_change_ms = _now()
	_clock_last = -1.0
	_clock_change_ms = _now()
	_stall_tries = 0
	_paused_since_ms = 0
	_pause_tries = 0
	_set_autopilot_flags(true)
	world.set_stage(active_stage)
	world.danger = active_danger
	world.speed = clampi(int(cfg.get("game_speed", 3)), 1, 3)
	Save.set_setting("onboarded", true)
	Save.set_setting("endless_auto_pick", false)
	var job_paths := {}
	if GameData.CLASSES.has(active_class):
		job_paths[active_class] = _job_path(active_class)
	Save.set_meta("farmer_job_paths", job_paths)
	world.start_run(active_class)
	_replace_player_input()
	_apply_autopilot()
	Engine.time_scale = maxf(1.0, float(cfg.get("speed", 4.0)))
	runs_started += 1
	phase = "run"
	_mark_transition("run_start")
	_log("START #%d class=%s stage=%s danger=%d speed=%.1f" % [
		runs_started, active_class, active_stage, active_danger, float(cfg.get("speed", 4.0))])
	if not _write_checkpoint("run"):
		return
	_test_crash("run")
	_write_status()


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
	_apply_autopilot()
	_replace_player_input()
	_handle_job_change(world.player)
	_draft_player()
	_handle_victory(now)
	if world == null or not is_instance_valid(world):
		return
	if world.running:
		run_state["kills"] = int(world.kills)
		run_state["run_zeny"] = int(world.run_zeny)
		run_state["run_mvps"] = int(world.run_mvps)
		if bool(world.player.fell):
			run_state["died"] = true
		_check_watchdog(now)
		_check_timeout(now)
	if phase == "run" and not world.running:
		_begin_settle(now)


func _handle_victory(now: int) -> void:
	if world == null or not is_instance_valid(world):
		return
	var new_win := false
	# A new MVP kill is the only reliable per-run victory token: raid.state
	# stays "won" after leave(), and a defeated MVP in the field has no raid.
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
	# A pending victory must survive frames where `new_win` is false (the MVP
	# counter does not grow every frame and the arena exit has no menu).
	if int(run_state.get("won_at", 0)) == 0:
		return
	world._pull_prizes()
	if now - int(run_state.get("won_at", now)) < VICTORY_PULL_MS:
		return
	# After the MVP the arena opens a karma portal: Valhalla -> Valkyrie
	# Reginleif, Niflheim -> Randgris. Entering it before endless grants the
	# route boon (+1 revive and +15% XP for Valhalla), which makes the endless
	# run last longer. Without a chosen karma side there is no portal.
	if world.karma != null and is_instance_valid(world.karma) \
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
	world._end_run(victory)
	_set_autopilot_flags(false)


func _begin_settle(now: int) -> void:
	if int(run_state.get("settle_start", 0)) == 0:
		run_state["settle_start"] = now
		var died := false
		var p = world.player
		if p != null and is_instance_valid(p):
			died = bool(p.fell)
		run_state["died"] = run_state.get("died", false) or died
		var victory := bool(run_state.get("boss_won", false))
		if bool(world.endless) and bool(run_state.get("died", false)):
			victory = true
		if bool(run_state.get("forced", false)):
			victory = false
		run_state["victory"] = victory
		_log("SETTLE victory=%s died=%s endless=%s t=%.1f" % [
			str(victory), str(bool(run_state.get("died", false))), str(bool(world.endless)), float(world.time)])
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
			phase = "keep"
			_write_status()
			return
		if mode == "victory":
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
	if _clock_last < 0.0 or not is_equal_approx(clock, _clock_last):
		_clock_last = clock
		_clock_change_ms = now
	if _time_last < 0.0 or not is_equal_approx(t, _time_last):
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
	if frozen_reason == "" and now - _clock_change_ms > int(stall_s * 1000.0):
		_stall_tries += 1
		_log("STALL clock=%.1f t=%.1f tries=%d" % [clock, t, _stall_tries])
		if world.menus != null and is_instance_valid(world.menus):
			world.menus.close()
		get_tree().paused = false
		_clock_change_ms = now
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
	if _finish_after_run != "":
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
	if world == null or not is_instance_valid(world):
		return
	var p = world.player
	if p == null or not is_instance_valid(p):
		return
	_draft_hero(p, MAX_DRAFT_PER_TICK)
	if p.pending_levels <= 0:
		if world.menus != null and is_instance_valid(world.menus) and str(world.menus._mode) == "level_up":
			world.menus.hide_level_up()
			if get_tree().paused:
				get_tree().paused = false


func _draft_hero(h, limit: int) -> void:
	if h == null or not is_instance_valid(h):
		return
	var guard := 0
	while int(h.pending_levels) > 0 and guard < limit:
		guard += 1
		var choices: Array = h.offered_choices()
		if choices.is_empty():
			h.pending_levels = 0
			break
		var pick: Dictionary = _choose_choice(h, choices)
		if pick.is_empty():
			break
		h.apply_choice(pick, world)
		h.offer = []
		h.pending_levels = maxi(0, int(h.pending_levels) - 1)
		_after_choice(h)
	if h == world.player and int(h.pending_levels) <= 0:
		if world.menus != null and is_instance_valid(world.menus) and str(world.menus._mode) == "level_up":
			world.menus.hide_level_up()
			if get_tree().paused:
				get_tree().paused = false


func _after_choice(h) -> void:
	if h == null or not is_instance_valid(h):
		return
	if h.skills.has("call_homunculus") and str(h.homun_type) == "":
		h.homun_type = str(Save.setting("homun_pick", "homun_lif"))
		world.spawn_homun(h)
	world.check_more_homun(h)


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
	var b: Dictionary = _build_for(str(h.class_id))
	var prio: Array = b.get("skills", [])
	var opts: Array = h.job_start_options()
	for id in prio:
		var sid := str(id)
		if opts.has(sid):
			return sid
	return ""


func _choose_choice(h, choices: Array) -> Dictionary:
	var b: Dictionary = _build_for(str(h.class_id))
	var prio: Array = b.get("skills", [])
	var stat_prio: Array = b.get("stats", [])
	var caps: Dictionary = b.get("caps", {})
	var hp_ratio := float(h.hp) / maxf(1.0, float(h.max_hp))
	var best: Dictionary = {}
	var best_score := -1.0e30
	for c in choices:
		if not (c is Dictionary):
			continue
		var score := _choice_score(h, c, prio, stat_prio, caps, hp_ratio)
		if score > best_score:
			best_score = score
			best = c
	return best


func _choice_score(h, c: Dictionary, prio: Array, stats_prio: Array, caps: Dictionary, hp_ratio: float) -> float:
	var kind := str(c.get("kind", ""))
	var id := str(c.get("id", ""))
	var rarity := float(c.get("rarity", 0))
	if kind == "potion":
		return -1000.0
	if kind == "evolve":
		var base := Player.base_skill(id)
		var idx := prio.find(id)
		if idx < 0:
			idx = prio.find(base)
		if idx >= 0:
			return 10000.0 - float(idx) * 10.0
		return 500.0 + rarity
	if kind == "skill":
		var base := Player.base_skill(id)
		var idx := prio.find(base)
		if idx < 0:
			idx = prio.find(id)
		if caps.has(base) and int(c.get("level", 1)) > int(caps[base]):
			return -500.0
		if idx >= 0:
			return 5000.0 - float(idx) * 10.0 + rarity
		return _fallback_skill_score(h, c, hp_ratio)
	if kind == "stat":
		var sid := id
		var idx := stats_prio.find(sid)
		if idx < 0:
			return 40.0 + rarity
		var limit := 999
		if caps.has(sid):
			limit = int(caps[sid])
		if int(h.stats.get(sid, 0)) >= limit:
			return -800.0
		return 900.0 - float(idx) * 20.0 + rarity
	return 0.0


func _fallback_skill_score(h, c: Dictionary, hp_ratio: float) -> float:
	var id := str(c.get("id", ""))
	var base := Player.base_skill(id)
	var d: Dictionary = GameData.SKILLS.get(base, {})
	if d.is_empty():
		d = GameData.SKILLS.get(id, {})
	if d.is_empty():
		return 10.0
	var typ := str(d.get("type", ""))
	var rarity := float(c.get("rarity", 0)) * 8.0
	var score := 100.0
	if typ in ["aoe_self", "aoe_target", "petal_rain", "ground", "orbit", "summon", "falcon", "bolt"]:
		score = 320.0
	elif typ in ["melee_arc", "melee", "projectile", "dash", "charge", "trap"]:
		score = 260.0
	elif typ == "heal":
		score = 280.0 if hp_ratio < 0.7 else 160.0
	elif typ in ["shield", "buff"]:
		score = 220.0 if hp_ratio < 0.6 else 150.0
	elif typ == "passive":
		score = 170.0
		for base_id in GameData.EVOLUTIONS:
			if str(GameData.EVOLUTIONS[base_id].get("passive", "")) == base and h.skills.has(base_id):
				score = 420.0
				break
	if d.get("evolved", false):
		score += 30.0
	if h.skills.has(base):
		score += 20.0
	return score + rarity


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
	var goal: Vector3 = _steer_goal(hero)
	if goal != Vector3.INF:
		var to: Vector3 = goal - hero.position
		to.y = 0.0
		if to.length() < 0.45:
			return Vector2.ZERO
		if _direct_goal(goal):
			var v := to.normalized()
			return Vector2(v.x, v.z)
	return Bot.steer(world, goal, hero)


func _direct_goal(goal: Vector3) -> bool:
	# Raid mechanics need precise positioning; loot/altars are fine with steering.
	var raid = world.raid
	if raid != null and is_instance_valid(raid):
		var st := str(raid.state)
		if st == "fight" or st == "portal" or st == "intro":
			return true
	return false


func _steer_goal(hero) -> Vector3:
	var raid = world.raid
	if raid != null and is_instance_valid(raid):
		var st := str(raid.state)
		if st == "fight" or st == "portal" or st == "intro" or st == "loading":
			var g: Vector3 = raid.autopilot_goal(hero)
			if g != Vector3.INF:
				return g
	var runner = world.runner
	if runner != null and is_instance_valid(runner) and not bool(runner.dead):
		var rp: Vector3 = runner.position
		if Vector2(rp.x - hero.position.x, rp.z - hero.position.z).length() <= 40.0:
			return rp
	var pick := _best_pickup(hero)
	if pick != Vector3.INF:
		return pick
	var altar := _best_altar(hero)
	if altar != Vector3.INF:
		return altar
	if world.quest != null and is_instance_valid(world.quest):
		var qg: Vector3 = world.quest.autopilot_goal()
		if qg != Vector3.INF:
			return qg
	var hp_ratio := float(hero.hp) / maxf(1.0, float(hero.max_hp))
	if hp_ratio < 0.25:
		var away := _retreat_point(hero)
		if away != Vector3.INF:
			return away
	return Vector3.INF


func _best_pickup(hero) -> Vector3:
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
		if dist > limit:
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
		var dist := Vector2(pos.x - hero.position.x, pos.z - hero.position.z).length()
		if dist > range_max:
			continue
		if world.enemies_in_radius(pos, 5.0).size() > 8:
			continue
		var rank := priority.find(aid)
		if rank < 0:
			rank = 1000
		if rank < best_rank or (rank == best_rank and dist < best_dist):
			best_rank = rank
			best_dist = dist
			best = pos
	return best


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
	var slots := int(GameData.KEEP_WIN) if free else (1 if bool(cfg.get("keep_on_defeat", false)) else 0)
	var kept: Array = []
	if bool(cfg.get("auto_keep", false)) and slots > 0 and not offer.is_empty():
		var sorted: Array = []
		for it in offer:
			if it is Dictionary and not bool(it.get("_kept", false)):
				sorted.append(it)
		sorted.sort_custom(func(a, b): return _keep_value(a) > _keep_value(b))
		var n := 0
		for it in sorted:
			if n >= slots:
				break
			if not _keep_ok(it):
				continue
			var cost := 0
			if not free:
				cost = int(world.menus._keep_cost(it))
				if cost > 0:
					var max_cost := int(float(Save.zeny()) * float(cfg.get("keep_max_pct", 0.05)))
					if Save.zeny() < cost or cost > max_cost:
						continue
			if Save.storage().size() >= Save.storage_cap():
				if not _make_room(_keep_value(it)):
					_log("KEEP_SKIP_FULL %s" % str(it.get("id", "")))
					continue
			if cost > 0 and not Save.spend(cost):
				continue
			if _append_storage(it):
				it["_kept"] = true
				kept.append(str(it.get("id", "")))
				n += 1
				_log("KEEP %s %s val=%.0f pot=%s trait=%s" % [
					str(it.get("id", "")), "free" if cost == 0 else "paid:%d" % cost,
					_keep_value(it), str(_item_has_pot(it)), str(it.get("trait", ""))])
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
	Save.flush()
	run_state["kept"] = kept
	run_state["settled"] = _reward_snapshot()
	_log("KEEP_DONE kept=%d offer=%d victory=%s" % [kept.size(), offer.size(), str(victory)])
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
	if Equipment.is_perm(it):
		return false
	if bool(it.get("lent", false)):
		return false
	if Equipment.is_unique(it):
		for s in Save.storage():
			if str((s as Dictionary).get("id", "")) == str(it.get("id", "")):
				return false
	return true


func _keep_value(it: Dictionary) -> float:
	var v := float(Equipment.score(it))
	var pot = it.get("pot", null)
	if pot is Dictionary and not (pot as Dictionary).is_empty():
		v += 120.0 + float(int((pot as Dictionary).get("tier", 1))) * 25.0
		var lines = (pot as Dictionary).get("lines", [])
		if lines is Array:
			v += float((lines as Array).size()) * 6.0
	if str(it.get("trait", "")) != "":
		v += 25.0
	if Equipment.is_unique(it):
		v += 200.0
	elif Equipment.is_legendary(it):
		v += 90.0
	return v


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
	Save.flush()
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


func _make_room(need_value: float) -> bool:
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
	if need_value <= victim_score * float(cfg.get("swap_margin", 1.25)):
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
	var cid := active_class
	_claim_achievements()
	if bool(cfg.get("auto_upgrades", true)):
		_buy_upgrades()
	if bool(cfg.get("auto_sage", true)):
		_buy_sage()
	if bool(cfg.get("auto_rebirth", false)):
		_do_rebirth(cid)
	if bool(cfg.get("auto_stats", true)):
		_auto_stats(cid)
	if bool(cfg.get("auto_fuse", true)):
		_auto_fuse()
	if bool(cfg.get("auto_cards", true)):
		_auto_album()
	if bool(cfg.get("auto_loadout", true)):
		_auto_loadout(cid)
	if bool(cfg.get("auto_pet", true)):
		_auto_pet()
	if bool(cfg.get("auto_potential", false)):
		_auto_potential()
	if bool(cfg.get("auto_storage_prune", false)):
		_auto_prune()
	Save.flush()
	last_maint["zeny"] = Save.zeny()
	last_maint["storage"] = Save.storage().size()
	_log("MAINT " + JSON.stringify(last_maint))


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


func _do_rebirth(cid: String) -> void:
	if cid == "":
		return
	if Save.can_rebirth(cid):
		if Save.rebirth(cid):
			last_maint["rebirth"] = cid
			_log("REBIRTH %s ymir=%d" % [cid, Save.ymir_fragments()])
	if bool(cfg.get("auto_rebirth_lv", false)) and Save.rebirth_lv_ready(cid):
		if Save.take_rebirth_lv(cid):
			last_maint["rebirth_lv"] = cid
			_log("REBIRTH_LV %s rlv=%d" % [cid, Save.rebirth_lv(cid)])


func _auto_stats(cid: String) -> void:
	if cid == "" or not GameData.CLASSES.has(cid):
		return
	var free := int(Save.free_points(cid))
	if free <= 0:
		return
	var stats: Dictionary = Save.class_stats(cid).duplicate()
	var order := _stat_order(cid)
	for i in free:
		var st := str(order[i % order.size()]) if not order.is_empty() else "vit"
		stats[st] = int(stats.get(st, 0)) + 1
	Save.set_class_stats(cid, stats)
	last_maint["stats_%s" % cid] = free
	_log("STATS %s +%d %s" % [cid, free, str(order)])


func _stat_order(cid: String) -> Array:
	var b: Dictionary = _build_for(cid)
	var out: Array = []
	var raw = b.get("stats", [])
	if raw is Array:
		for s in raw:
			var sid := str(s)
			if GameData.STATS.has(sid) and not out.has(sid):
				out.append(sid)
	if out.is_empty():
		var base: Dictionary = GameData.CLASSES.get(cid, {}).get("stats", {})
		var keys: Array = base.keys()
		keys.sort_custom(func(a, b2): return int(base[a]) > int(base[b2]))
		for k in keys:
			out.append(str(k))
		if not out.has("vit"):
			out.append("vit")
	return out


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


func _auto_album() -> void:
	var slots := int(GameData.card_slots())
	if slots <= 0:
		return
	var weights := _card_weights()
	var owned: Array = []
	var ids: Array = Save.data.get("cards", {}).keys()
	for id in ids:
		var cid := str(id)
		if GameData.CARDS.has(cid) and Save.has_card(cid):
			owned.append(cid)
	var et: Dictionary = Save.data.get("eternal", {})
	for id in et.keys():
		var cid := str(id)
		if GameData.CARDS.has(cid) and not owned.has(cid):
			owned.append(cid)
	owned.sort_custom(func(a, b): return _card_score(a, weights) > _card_score(b, weights))
	var chosen: Array = owned.slice(0, slots)
	if chosen == Save.equipped_cards():
		return
	Save.set_equipped_cards(chosen)
	last_maint["album"] = chosen.size()
	_log("ALBUM " + str(chosen))


func _card_score(id: String, weights: Dictionary) -> float:
	var d: Dictionary = GameData.CARDS.get(id, {})
	if d.is_empty():
		return 0.0
	var score := 0.0
	var mods: Dictionary = d.get("mods", {})
	for k in mods:
		score += absf(float(mods[k])) * float(weights.get(str(k), weights.get("_default", 1.0))) * 100.0
	var fx: Dictionary = d.get("effects", {})
	for k in fx:
		score += absf(float(fx[k])) * float(weights.get(str(k), weights.get("_default", 1.0))) * 100.0
	if d.has("proc") or d.has("proc_hit"):
		score += float(weights.get("proc", 10.0)) * 50.0
	return score


func _card_weights() -> Dictionary:
	var w := {
		"loot": 3.0, "zeny": 3.0, "card": 2.0, "drop_find": 2.5, "xp": 1.0,
		"dmg": 2.0, "skill_dmg": 1.6, "basic_dmg": 1.4, "proc_dmg": 1.2,
		"crit": 1.0, "crit_dmg": 0.9, "aspd": 0.9, "move": 0.6,
		"max_hp_pct": 0.9, "armor": 0.4, "haste": 0.8, "duration": 0.5,
		"area": 0.5, "count": 1.5, "heal_power": 0.5, "regen": 0.5,
		"proc": 1.2, "_default": 1.0,
	}
	var obj := str(cfg.get("objective", "balanced"))
	match obj:
		"zeny":
			w["loot"] = 6.0
			w["zeny"] = 6.0
			w["drop_find"] = 3.0
			w["card"] = 2.0
			w["dmg"] = 1.5
		"ores":
			w["drop_find"] = 6.0
			w["loot"] = 2.0
			w["dmg"] = 2.0
		"crumbs":
			w["drop_find"] = 3.0
			w["dmg"] = 3.5
			w["skill_dmg"] = 3.0
			w["crit_dmg"] = 2.5
			w["card"] = 2.0
		"xp":
			w["xp"] = 6.0
			w["dmg"] = 2.5
			w["skill_dmg"] = 2.0
		"cards", "pets":
			w["card"] = 6.0
			w["drop_find"] = 4.0
			w["loot"] = 2.0
			w["dmg"] = 2.0
		"progress":
			w["dmg"] = 4.0
			w["skill_dmg"] = 3.0
			w["max_hp_pct"] = 2.5
			w["armor"] = 2.0
	return w


func _auto_loadout(cid: String) -> void:
	if cid == "" or not GameData.CLASSES.has(cid):
		return
	if world.menus == null or not is_instance_valid(world.menus):
		return
	var changes := _loadout_for(cid)
	if changes > 0:
		last_maint["loadout"] = changes
		_log("LOADOUT changes=%d" % changes)


func _loadout_for(cid: String) -> int:
	var cap := int(Save.loadout_cap())
	var lo: Dictionary = Save.loadout(cid)
	var pieces := 0
	for k in lo.keys():
		if not (k in GameData.LOADOUT_FREE_SLOTS):
			pieces += 1
	var candidates: Array = []
	for it in Save.storage():
		if not (it is Dictionary) or (it as Dictionary).is_empty():
			continue
		var uid := str((it as Dictionary).get("uid", ""))
		if uid == "":
			continue
		var owner := str(Save.loadout_owner(uid))
		if owner != "" and owner != cid:
			continue
		candidates.append(it)
	candidates.sort_custom(func(a, b): return _item_value(a) > _item_value(b))
	var changes := 0
	for it in candidates:
		if changes >= 12:
			break
		var uid := str((it as Dictionary).get("uid", ""))
		var key := _loadout_key(it, lo)
		if key == "":
			continue
		var cur := str(lo.get(key, ""))
		if cur == uid:
			continue
		if cur != "":
			var old := Save.storage_item(cur)
			if not old.is_empty() and _item_value(old) >= _item_value(it):
				continue
		elif not (key in GameData.LOADOUT_FREE_SLOTS) and not lo.has(key):
			if pieces >= cap:
				continue
		var why := str(Menus._loadout_block(cid, it, key, lo))
		if why != "":
			continue
		if key == "weapon" and Equipment.two_hands(it) and lo.has("shield"):
			Save.set_loadout_slot(cid, "shield", "")
			lo.erase("shield")
			pieces = maxi(0, pieces - 1)
		Save.set_loadout_slot(cid, key, uid)
		if not (key in GameData.LOADOUT_FREE_SLOTS) and cur == "":
			pieces += 1
		changes += 1
	return changes


func _loadout_key(it: Dictionary, lo: Dictionary) -> String:
	var d: Dictionary = Equipment.item_def(it)
	var slot := str(d.get("slot", ""))
	if slot == "":
		return ""
	if slot == "acc":
		if not lo.has("acc1"):
			return "acc1"
		if not lo.has("acc2"):
			return "acc2"
		return "acc1"
	return slot


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


func _auto_pet() -> void:
	var prio: Array = cfg.get("pet_priority", [])
	var owned: Array = []
	var pets: Dictionary = Save.data.get("pets", {})
	for id in pets.keys():
		var pid := str(id)
		if bool(pets[id]) and GameData.PETS.has(pid):
			owned.append(pid)
	if owned.is_empty():
		return
	var chosen := ""
	if not prio.is_empty():
		for id in prio:
			if owned.has(str(id)):
				chosen = str(id)
				break
	if chosen == "":
		var weights := _card_weights()
		var best := -1.0
		for id in owned:
			var sc := _pet_score(str(id), weights)
			if sc > best:
				best = sc
				chosen = str(id)
	if chosen != "" and Save.active_pet() != chosen:
		Save.set_active_pet(chosen)
		last_maint["pet"] = chosen
		_log("PET %s" % chosen)


func _pet_score(id: String, weights: Dictionary) -> float:
	var d: Dictionary = GameData.PETS.get(id, {})
	if d.is_empty():
		return 0.0
	var score := 0.0
	var mods: Dictionary = d.get("mods", {})
	for k in mods:
		score += absf(float(mods[k])) * float(weights.get(str(k), weights.get("_default", 1.0))) * 100.0
	var fx: Dictionary = d.get("effects", {})
	for k in fx:
		score += absf(float(fx[k])) * float(weights.get(str(k), weights.get("_default", 1.0))) * 100.0
	if d.get("skill", {}) is Dictionary and not (d.get("skill", {}) as Dictionary).is_empty():
		score += 50.0
	return score


func _auto_potential() -> void:
	if _potential_script == null:
		return
	var reserve := int(cfg.get("potential_reserve", 0))
	var max_rolls := int(cfg.get("potential_max_rolls", 0))
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
		Save.flush()
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

func _choose_target() -> Dictionary:
	var stage := ""
	var danger := 0
	var raw = cfg.get("danger", "auto")
	var obj := str(cfg.get("objective", "balanced"))
	if str(cfg.get("stage", "")) != "":
		stage = str(cfg.get("stage", ""))
		if not _stage_ok(stage):
			_log("STAGE_LOCKED %s" % stage)
			return {}
	if stage != "":
		danger = _danger_for(stage)
		if obj == "progress":
			danger = _stage_max_danger(stage)
	elif obj == "progress":
		stage = _fallback_stage()
		danger = _stage_max_danger(stage)
	elif (raw is int or raw is float) or str(raw) in ["max", "best", "stage"]:
		stage = _fallback_stage()
		danger = _danger_for(stage)
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
		danger = _danger_for(stage)
	if stage == "":
		return {}
	var cid := _choose_class()
	if cid == "":
		_log("TARGET_FAIL class")
		return {}
	danger = clampi(danger, _stage_min_danger(stage), mini(_stage_max_danger(stage), int(cfg.get("danger_ceiling", 30))))
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
	var hi := mini(_stage_max_danger(sid), int(cfg.get("danger_ceiling", 30)))
	var raw = cfg.get("danger", "auto")
	if raw is int or raw is float:
		return clampi(int(raw), lo, hi)
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
	var list: Array = cfg.get("classes", [])
	var cands: Array = []
	for c in list:
		var cid := str(c)
		if _class_ok(cid):
			cands.append(cid)
	if cands.is_empty():
		for id in GameData.CLASSES:
			var cid := str(id)
			if _class_ok(cid):
				cands.append(cid)
	if cands.is_empty():
		return "swordsman"
	if bool(cfg.get("class_rotate", false)) and not cands.is_empty():
		return str(cands[runs_started % cands.size()])
	var best := str(cands[0])
	var best_score := -1.0
	for c in cands:
		var prog: Dictionary = Save.class_progress(str(c))
		var score := float(int(prog.get("level", 1))) + 100.0 * float(int(prog.get("rlv", 0)))
		if score > best_score:
			best_score = score
			best = str(c)
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

func _build_for(cid: String) -> Dictionary:
	var builds = cfg.get("builds", {})
	if builds is Dictionary and builds.get(cid) is Dictionary:
		return builds[cid]
	# The game stores the player's level-up order in Save; use it unless the
	# config explicitly provides a build. This keeps a customized SinX build.
	var orders = Save.setting("pick_order", {})
	if orders is Dictionary:
		var raw_order = orders.get(cid, [])
		if raw_order is Array and not raw_order.is_empty():
			var pskills: Array = []
			var pstats: Array = []
			for id in raw_order:
				var sid := str(id)
				if GameData.STATS.has(sid):
					pstats.append(sid)
				else:
					pskills.append(sid)
			var pcaps: Dictionary = {}
			var limits = Save.setting("pick_limits", {})
			if limits is Dictionary and limits.get(cid) is Dictionary:
				pcaps = (limits[cid] as Dictionary).duplicate()
			return {"skills": pskills, "stats": pstats, "caps": pcaps}
	var out := {"skills": [], "stats": []}
	var d: Dictionary = GameData.CLASSES.get(cid, {})
	if d.is_empty():
		return out
	var junk: Array = cfg.get("junk_skills", ["throw_stone", "steal"])
	var skills: Array = []
	for id in d.get("skills", []):
		if not junk.has(str(id)):
			skills.append(str(id))
	for id in d.get("passives", []):
		skills.append(str(id))
	var j2 = d.get("job2", {})
	if j2 is Dictionary:
		for id in j2.get("skills", []):
			skills.append(str(id))
		for id in j2.get("passives", []):
			skills.append(str(id))
		var tr = j2.get("trans", {})
		if tr is Dictionary:
			for id in tr.get("skills", []):
				skills.append(str(id))
			for id in tr.get("passives", []):
				skills.append(str(id))
	var alt = d.get("job2_alt", {})
	if alt is Dictionary:
		for id in alt.get("skills", []):
			skills.append(str(id))
		for id in alt.get("passives", []):
			skills.append(str(id))
		var tr2 = alt.get("trans", {})
		if tr2 is Dictionary:
			for id in tr2.get("skills", []):
				skills.append(str(id))
			for id in tr2.get("passives", []):
				skills.append(str(id))
	out["skills"] = skills
	var base: Dictionary = d.get("stats", {})
	var keys: Array = base.keys()
	keys.sort_custom(func(a, b): return int(base[a]) > int(base[b]))
	var stats: Array = []
	for k in keys:
		stats.append(str(k))
	if not stats.has("vit"):
		stats.append("vit")
	out["stats"] = stats
	return out


func _job_path(cid: String) -> int:
	var b: Dictionary = _build_for(cid)
	if b.has("job_path"):
		return clampi(int(b["job_path"]), 0, maxi(0, GameData.job_paths(cid).size() - 1))
	var paths = cfg.get("job_paths", {})
	if paths is Dictionary and paths.has(cid):
		return clampi(int(paths[cid]), 0, maxi(0, GameData.job_paths(cid).size() - 1))
	return 0


func _apply_build_settings(cid: String) -> void:
	var b: Dictionary = _build_for(cid)
	var orders: Dictionary = Save.setting("pick_order", {})
	if not (orders is Dictionary):
		orders = {}
	var existing = orders.get(cid, [])
	if existing is Array and not existing.is_empty() and not bool(cfg.get("override_pick_order", false)):
		var limits = Save.setting("pick_limits", {})
		var mine = limits.get(cid, {}) if limits is Dictionary else {}
		_log("PROFILE_BUILD class=%s order=%s limits=%s" % [cid, str(existing), str(mine)])
		return
	var order: Array = b.get("pick_order", [])
	if order.is_empty():
		order = (b.get("skills", []) as Array) + (b.get("stats", []) as Array)
	orders[cid] = order
	Save.set_setting("pick_order", orders)
	var limits: Dictionary = b.get("caps", {})
	if not limits.is_empty():
		var all: Dictionary = Save.setting("pick_limits", {})
		if not (all is Dictionary):
			all = {}
		all[cid] = limits
		Save.set_setting("pick_limits", all)


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
	# Refresh the pending result after maintenance before it goes to the journal.
	if not _record_run():
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
	else:
		losses += 1
	total_zeny += int(r.get("zeny_gain", 0))
	total_kills += int(r.get("kills", 0))
	total_xp += int(r.get("xp_gain", 0))
	var mats: Dictionary = r.get("materials", {})
	for k in mats:
		total_materials[str(k)] = int(total_materials.get(str(k), 0)) + int(mats[k])
	total_coins += int(r.get("coins_gain", 0))
	total_ymir += int(r.get("ymir_gain", 0))
	if append_log:
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
		"target": {"stage": active_stage, "danger": active_danger, "class": active_class},
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
	active_danger = int(target.get("danger", 1))
	active_class = str(target.get("class", ""))
	var run_id := str(cp.get("run_id", ""))
	match str(cp.get("phase", "")):
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


# Test-only seam used by verify.sh; never set in a real session.
func _test_crash(point: String) -> void:
	if session_id.begins_with("verify-") and OS.get_environment("FARMER_TEST_CRASH_AT") == point:
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
		"victory": bool(run_state.get("victory", false)),
		"died": bool(run_state.get("died", false)),
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
		"value": 0.0,
		"rate": 0.0,
	}
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
		"class": "", "classes": [], "class_rotate": false,
		"builds": {},
		"stage": "", "danger": "auto", "danger_ceiling": 30,
		"auto_danger": true, "explore_every": 5, "danger_step": 1,
		"featured_bonus": true,
		"speed": 4.0, "game_speed": 3,
		"run_minutes": 12.0, "arena_wall_max": 180.0, "stall_seconds": 45.0,
		"endless": false, "endless_minutes": 4.0, "endless_mvps": 0,
		"max_runs": 0, "max_minutes": 0.0, "stop_after_wins": 0,
		"display": false, "offline": true, "hard_exit": true,
		"auto_keep": false, "keep_on_defeat": false, "keep_reserve_slots": 2,
		"keep_max_pct": 0.05, "swap_margin": 1.25,
		"auto_stats": true, "auto_rebirth": false, "auto_rebirth_lv": false,
		"auto_achievements": true,
		"auto_upgrades": true, "upgrade_reserve": 500000, "storage_target": 120,
		"upgrade_priority": ["bubble_gum", "battle_manual", "greed", "blessing", "increase_agi", "yggdrasil_fruit", "fury", "gloria", "magnificat", "angelus", "hp_recovery", "telescope", "kafra_status", "kafra_summon", "kafra_area", "kafra_amount", "kafra_blow", "vultures_eye", "memorize", "card_slot", "kafra_cart", "kafra_storage"],
		"auto_sage": true, "sage_priority": ["passive_slot", "sage_book", "sage_root", "sage_start", "fly_wing", "magnifier"],
		"auto_cards": true, "auto_fuse": true, "fuse_keep": {},
		"auto_loadout": true, "auto_pet": true, "pet_priority": [],
		"auto_potential": false, "potential_reserve": 20, "potential_max_rolls": 0,
		"auto_storage_prune": false,
		"altar_priority": ["freyja", "loki", "niflheim", "thor", "yggdrasil", "valkyrie", "baldur", "odin", "emperium"],
		"altar_range": 12.0,
		"junk_skills": ["throw_stone", "steal"],
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
	if not (cfg.get("classes") is Array):
		errors.append("classes must be an array")
	if not (cfg.get("goals") is Dictionary):
		errors.append("goals must be an object")
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
	cfg["potential_max_rolls"] = maxi(0, int(cfg.get("potential_max_rolls", 0)))
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
		"target": {"stage": active_stage, "danger": active_danger, "class": active_class},
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


func _profile_fingerprint() -> String:
	if not FileAccess.file_exists(Save.PATH):
		return ""
	var bytes := FileAccess.get_file_as_bytes(Save.PATH)
	if bytes.is_empty():
		return ""
	return "%d:%d:%d" % [FileAccess.get_modified_time(Save.PATH), bytes.size(), hash(bytes)]


func _flush_profile_verified() -> bool:
	# Test-only seam used by verify.sh; never set in a real session.
	if session_id.begins_with("verify-") and OS.get_environment("FARMER_TEST_FLUSH_FAIL") == "1":
		return false
	var before := _profile_fingerprint()
	# Force a content change so a successful write must alter the fingerprint.
	Save.set_setting("farmer_flush_marker", "%s-%d" % [session_id, _now()])
	Save.mark_dirty()
	Save.flush()
	var after := _profile_fingerprint()
	return after != "" and after != before


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


func _pid_alive(pid: int) -> bool:
	if pid <= 0:
		return false
	if OS.get_name() == "Linux":
		return FileAccess.file_exists("/proc/%d" % pid)
	return OS.is_process_running(pid)


func _acquire_lock() -> bool:
	if FileAccess.file_exists(LOCK_PATH):
		var txt := FileAccess.get_file_as_string(LOCK_PATH)
		var pid := txt.to_int()
		if pid > 0 and pid != OS.get_process_id() and _pid_alive(pid):
			_lock_pid = pid
			return false
	var f := FileAccess.open(LOCK_PATH, FileAccess.WRITE)
	if f == null:
		return false
	f.store_string(str(OS.get_process_id()))
	f.close()
	_lock_pid = OS.get_process_id()
	return true


func _release_lock() -> void:
	if _lock_pid != OS.get_process_id():
		return
	if FileAccess.file_exists(LOCK_PATH):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(LOCK_PATH))


func _fail_session(reason: String, allow_hard_exit := true) -> void:
	if failed:
		return
	failed = true
	finish_reason = reason
	last_error = reason
	phase = "failed"
	exit_code = 1
	_mark_transition("fail:" + reason)
	_log("FAIL " + reason)
	_write_status()
	_release_lock()
	if allow_hard_exit and bool(cfg.get("hard_exit", true)) and DisplayServer.get_name() == "headless":
		OS.kill(OS.get_process_id())
		return
	get_tree().quit(1)


func _finish(reason: String) -> void:
	if phase == "done" or _hard_finished:
		return
	finish_reason = reason
	exit_code = 0
	if not _flush_profile_verified():
		_fail_session("flush_failed", false)
		return
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
	_release_lock()
	_hard_finished = true
	if bool(cfg.get("hard_exit", true)) and DisplayServer.get_name() == "headless":
		print("FARMER HARD_EXIT")
		OS.kill(OS.get_process_id())
		return
	get_tree().quit(0)
