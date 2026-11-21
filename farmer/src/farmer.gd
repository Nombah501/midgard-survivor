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
const MAX_DRAFT_PER_TICK := 32
const DIRECT_STALL_MS := 750

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

var run_state: Dictionary = {}
var last_run: Dictionary = {}
var arms: Dictionary = {}
var last_maint: Dictionary = {}

var _altar_seen: Dictionary = {}
var _altar_channel: Dictionary = {}
var _altar_direct := false

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

var _potential_script = null
var _vanilla_input_seen := false

var _direct_map_id := 0
var _direct_tile := Vector2i.ZERO
var _direct_progress_ms := -1
var _direct_best_dist := INF
var _direct_grid: AStarGrid2D
var _direct_path: Array[Vector2i] = []
var _direct_step := 1

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
	_test_wait_at_keep = _test_env("WAIT_AT_KEEP") == "1"
	_test_freeze_run_time = _test_env("FREEZE_RUN_TIME") == "1"
	_test_blocked_portal = _test_env("BLOCKED_PORTAL") == "1"
	_test_verify_wishlist = _test_env("WISHLIST") == "1"
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
		if not _write_catalog():
			_fail_session("catalog_write_failed")
			return
		_catalog_written = true
		if _test_env("CATALOG") == "1":
			_test_catalog = _catalog_evidence()
		if not _validate_run_choice():
			return
		if _test_env("OATHS") == "1":
			_test_oaths["before"] = Save._read(Save.PATH).get("oaths")
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
	if _goal_done() and bool(cfg.get("goal_stop", false)):
		_finish("goal")
		return
	var target := _choose_target()
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
		_test_preparation["before"] = _preparation_snapshot(Save.data)
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
	_altar_seen.clear()
	_altar_channel = {}
	if cfg["karma_route"] == "valhalla":
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
	_set_autopilot_flags(true)
	world.set_stage(active_stage)
	world.danger = active_danger
	world.speed = clampi(int(cfg.get("game_speed", 3)), 1, 3)
	Save.set_setting("onboarded", true)
	Save.set_setting("endless_auto_pick", false)
	# The game consumes even an empty override; never inherit the saved set.
	world.oaths_next = cfg["oaths"] if active_danger == GameData.DANGER_MAX else {}
	# 0.2.5 suppresses the finale on autopilot unless this meta is set.
	if _want_endless() and not GameData.has_meta("finale_at"):
		GameData.set_meta("finale_at", GameData.MORROC_FINALE.at)
	if _test_blocked_portal:
		GameData.set_meta("mvp_at", 2.0)
	world.start_run(active_class)
	if cfg["karma_route"] == "valhalla" and is_instance_valid(world.karma):
		world.karma.path = "light"
	active_oath_points = int(world.oath_points())
	_replace_player_input()
	_apply_autopilot()
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
	if _test_blocked_portal and _test_tick_blocked_portal():
		return
	_apply_autopilot()
	_replace_player_input()
	_handle_job_change(world.player)
	_draft_player()
	if cfg["altar_policy"] == "map-wide":
		_observe_altars()
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
		_check_watchdog(now)
		_check_timeout(now)
	if phase == "run" and not world.running:
		_begin_settle(now)


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
			_log("KARMA_ROUTE side=light mvp=reginleif after_mvp=%d t=%.1f" % [regular, float(world.time)])
		if not won:
			return true
		run_state["valhalla_until"] = 0
		run_state["last_run_mvps"] = int(world.run_mvps)
		run_state["won_at"] = now
		run_state["valkyrie_kills"] = int(run_state.get("valkyrie_kills", 0)) + 1
		_log("VALKYRIE_KILLED mvp=reginleif after_mvp=%d boons=%d t=%.1f" % [regular, int(karma.boons), float(world.time)])
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
	if _test_verify_wishlist:
		_test_seed_wishlist_offer()
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
		# The native end resets Morroc's event; the finale kill increments this
		# stat before settlement, independently of the regular MVP counter.
		var finale_won := Save.stat("morroc_finale") > float(run_state["morroc_finale_before"])
		run_state["finale_won"] = finale_won
		var victory := not bool(run_state["died"]) and not bool(run_state["forced"]) \
			and (finale_won or bool(run_state["victory"]) or bool(run_state["boss_won"]))
		run_state["victory"] = victory
		if bool(run_state["died"]) and p != null and is_instance_valid(p):
			_log("PLAYER_DIED t=%.1f by=%s what=%s" % [
				float(world.time), str(p.death_by.get("by", "")), str(p.death_by.get("what", ""))])
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
			phase = "keep"
			_write_status()
			return
		if mode == "victory" and not bool(run_state["died"]):
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
	_altar_direct = false
	var goal: Vector3 = _steer_goal(hero)
	if goal != Vector3.INF:
		var at: Vector3 = hero.position
		var to := goal - at
		to.y = 0.0
		if to.length_squared() < 0.45 * 0.45:
			_direct_progress_ms = -1
			return Vector2.ZERO
		if _altar_direct or _direct_goal():
			return _steer_direct(at, goal, to)
	_direct_progress_ms = -1
	return Bot.steer(world, goal, hero)


func _direct_goal() -> bool:
	# Raid mechanics need precise positioning; loot/altars are fine with steering.
	var raid = world.raid
	if raid != null and is_instance_valid(raid):
		var st := str(raid.state)
		if st == "fight" or st == "portal" or st == "intro":
			return true
		if st == "won" and cfg["karma_route"] == "valhalla" and int(run_state.get("valhalla_until", 0)) > 0:
			return true
	if world.morroc.active():
		return true
	return false


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
		if x <= y:
			cell.x += sx
			x = x + dx if cell.x != end.x else INF
		else:
			cell.y += sy
			y = y + dy if cell.y != end.y else INF
		if not map.cell_walkable(cell.x, cell.y):
			return true
	return false


func _direct_tile_path(map: RoMap, from: Vector2i, to: Vector2i) -> Array[Vector2i]:
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
	return _direct_grid.get_id_path(from, to)


func _steer_goal(hero) -> Vector3:
	var raid = world.raid
	if raid != null and is_instance_valid(raid):
		var st := str(raid.state)
		if st == "won" and cfg["karma_route"] == "valhalla" and raid._kportal_pos != Vector3.INF:
			if int(run_state.get("valhalla_until", 0)) > 0:
				return _karma_portal_goal(hero, raid)
			return hero.position
		if st == "fight" or st == "portal" or st == "intro" or st == "loading":
			var g: Vector3 = raid.autopilot_goal(hero)
			if g != Vector3.INF:
				return g
	var map_wide: bool = cfg["altar_policy"] == "map-wide" and not (raid != null and raid.in_arena())
	if map_wide:
		var hold := _altar_hold_goal(hero)
		if hold != Vector3.INF:
			return hold
	var morroc_goal: Vector3 = world.morroc.autopilot_goal()
	if morroc_goal != Vector3.INF:
		return morroc_goal
	var runner = world.runner
	if runner != null and is_instance_valid(runner) and not bool(runner.dead):
		var rp: Vector3 = runner.position
		if Vector2(rp.x - hero.position.x, rp.z - hero.position.z).length() <= 40.0:
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
		if qg != Vector3.INF:
			return qg
	var hp_ratio := float(hero.hp) / maxf(1.0, float(hero.max_hp))
	if hp_ratio < 0.25:
		var away := _retreat_point(hero)
		if away != Vector3.INF:
			return away
	return Vector3.INF


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
		if dist > minf(limit, max_dist):
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


func _karma_portal_goal(hero, raid) -> Vector3:
	var goal: Vector3 = raid._kportal_pos
	var normal: Vector3 = raid.portal_pos
	var start: Vector3 = hero.position
	normal.y = 0.0
	start.y = 0.0
	var end := Vector3(goal.x, 0.0, goal.z)
	var closest := Geometry3D.get_closest_point_to_segment(normal, start, end)
	if closest.distance_squared_to(normal) < 1.4 * 1.4:
		# The game tests the return portal first; steer around its trigger.
		var side := (end - normal).cross(Vector3.UP).normalized() * 1.8
		var pass_at := normal + (start - normal).normalized() * 1.4
		return pass_at + (side if (start - normal).dot(side) >= 0.0 else -side)
	return goal


func _altar_skip(entry: Dictionary, reason: String) -> void:
	if entry.has("skip"):
		return
	entry["skip"] = reason
	_log("ALTAR_SKIP id=%s reason=%s t=%.1f" % [str(entry.altar.id), reason, float(world.time)])


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
	for a in waiting:
		var key: int = a.node.get_instance_id()
		if _altar_seen.has(key):
			continue
		var entry := {"altar": a, "dist": _flat_distance(hero.position, a.pos)}
		_altar_seen[key] = entry
		var reason := _altar_rejection(str(a.id))
		if reason != "":
			_altar_skip(entry, reason)
	for key in _altar_seen.keys():
		var entry: Dictionary = _altar_seen[key]
		var a: Dictionary = entry.altar
		if waiting.has(a):
			continue
		if float(a.fill) >= GameData.ALTAR_CHANNEL:
			var nearby: int = world.enemies_in_radius(a.pos, 5.0).size()
			_log("ALTAR_TAKE id=%s from=%.1f nearby=%d t=%.1f" % [str(a.id), float(entry.dist), nearby, float(world.time)])
		else:
			_altar_skip(entry, "expired" if float(a.life) <= 0.0 else "removed")
		_altar_seen.erase(key)


func _altar_hold_goal(hero) -> Vector3:
	for a in world.altars.waiting:
		if _altar_rejection(str(a.id)) != "" and _flat_distance(hero.position, a.pos) < GameData.ALTAR_RADIUS:
			# Proximity alone channels altars, even if they aren't a goal.
			var away: Vector3 = hero.position - a.pos
			away.y = 0.0
			return a.pos + (away.normalized() if away != Vector3.ZERO else Vector3.RIGHT) * (GameData.ALTAR_RADIUS + 1.0)
	if not _altar_channel.is_empty():
		if world.altars.waiting.has(_altar_channel):
			return _channel_altar_at(hero, _altar_channel.pos)
		_altar_channel = {}
	return Vector3.INF


func _channel_altar_at(hero, pos: Vector3) -> Vector3:
	_altar_direct = true
	return hero.position if _flat_distance(hero.position, pos) < GameData.ALTAR_RADIUS else pos


func _map_altar_goal(hero) -> Vector3:
	var priority: Array = cfg["altar_priority"]
	var map: RoMap = world.map
	var from := map.tile_of(hero.position)
	var best: Dictionary = {}
	var best_rank := priority.size()
	var best_dist := INF
	for a in world.altars.waiting:
		var aid := str(a.id)
		if _altar_rejection(aid) != "":
			continue
		var rank := priority.find(aid)
		var pos: Vector3 = a.pos
		var dist := _flat_distance(hero.position, pos)
		if rank > best_rank or (rank == best_rank and dist >= best_dist):
			continue
		var key: int = a.node.get_instance_id()
		var entry: Dictionary = _altar_seen.get(key, {})
		if entry.get("skip") == "unreachable":
			continue
		if dist >= GameData.ALTAR_RADIUS and not entry.get("reachable", false):
			var tile := map.tile_of(pos)
			if _direct_line_blocked(map, hero.position, pos - hero.position, from, tile) \
					and _direct_tile_path(map, from, tile).is_empty():
				_altar_skip(entry if not entry.is_empty() else {"altar": a}, "unreachable")
				continue
			entry["reachable"] = true
		best = a
		best_rank = rank
		best_dist = dist
	if best.is_empty():
		return Vector3.INF
	if best_dist < GameData.ALTAR_RADIUS:
		_altar_channel = best
	return _channel_altar_at(hero, best.pos)


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
	var wishlist_evidence := {}
	if _test_verify_wishlist:
		wishlist_evidence = _test_wishlist_evidence(offer, free)
	if not wishlist.is_empty() and not offer.is_empty():
		var owned := {}
		for item in Save.storage():
			owned[str(item.id)] = true
		for it in offer:
			if not (it is Dictionary) or bool(it.get("_kept", false)):
				continue
			var id := str(it.get("id", ""))
			if not wishlist.has(id):
				continue
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
	Save.flush()
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

func _validate_run_choice() -> bool:
	var location = cfg.get("stage")
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


func _validate_location_difficulty(difficulty: float, stage: String) -> bool:
	var bounds: Vector2i = GameData.stage_danger_range(stage, Save.max_danger())
	if difficulty != floorf(difficulty) or difficulty < bounds.x or difficulty > bounds.y:
		_fail_session("invalid_difficulty", true,
			"Difficulty %s is outside the allowed integer range %d–%d for location '%s'." % [difficulty, bounds.x, bounds.y, stage])
		return false
	return true


func _rotation_stage(difficulty: Variant) -> String:
	var first := ""
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
			if first == "":
				first = stage
			if after_cursor and next_stage == "":
				next_stage = stage
		if is_cursor:
			after_cursor = true
	if first == "":
		_fail_session("invalid_location", true, "No unlocked locations for All locations in turn.")
	return next_stage if next_stage != "" else first


func _choose_target() -> Dictionary:
	var raw = cfg.get("danger", "auto")
	var stage := _rotation_stage(raw) if _rotating else str(cfg.get("stage", ""))
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

func _build_for(cid: String) -> Dictionary:
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
	var builds = cfg.get("builds", {})
	if builds is Dictionary and builds.get(cid) is Dictionary:
		return builds[cid]
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
	if cfg["karma_route"] == "valhalla":
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
	}))


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


func _profile_fingerprint() -> String:
	if not FileAccess.file_exists(Save.PATH):
		return ""
	var bytes := FileAccess.get_file_as_bytes(Save.PATH)
	if bytes.is_empty():
		return ""
	return "%d:%d:%d" % [FileAccess.get_modified_time(Save.PATH), bytes.size(), hash(bytes)]


func _flush_profile_verified() -> bool:
	# Test-only seam used by verify.sh.
	if _test_env("FLUSH_FAIL") == "1":
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
	if not _flush_profile_verified():
		_fail_session("flush_failed", false)
		return
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
