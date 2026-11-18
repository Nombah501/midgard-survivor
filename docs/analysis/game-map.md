# Midgard Survivors — карта игры и точки автоматизации

Источник: установленная игра `/home/n501/games/midgard-survivors/`, эффективный набор скриптов
собран из трёх PCK в порядке приоритета:

1. `MidgardSurvivors.pck` — база 0.1.259 (116 скриптов);
2. `bridge_old_to_0.2.0.pck` — мост 0.2.0 (164 скрипта, перекрывает базу);
3. `patch_0.2.3.pck` — официальный патч 0.2.3 (58 скриптов, перекрывает всё).

Монтирование задаёт штатный `Updater` через `user://patches/state.json`
(`base`, `bridge.file`, `file`). Декомпиляция: GDRE Tools 2.7.4, bytecode `ebc36a7`
(4.5.0-stable), исходники в `analysis/src/` (167 файлов, 143k строк). Декомпилятор
теряет форматирование и иногда типы — доверять семантике, а не синтаксису.

## Автолоады (порядок важен)

```
Updater, GameData, RoAssets, Save, EOSGRuntime, HPlatform, HAuth, ...
```

`Save` — четвёртый автолоад и единственный, который гарантированно живёт всё время.
Узел, добавленный ребёнком к `Save`, обрабатывается **раньше** главной сцены (`World`),
поэтому фермер может перехватывать события кадра (level-up, job change) до игрового AI.
Это свойство — основа дизайна без патчей игровых скриптов, кроме bootstrap-хука.

## Карта модулей

| Подсистема | Файлы | Что делает |
|---|---|---|
| Мир/забег | `main.gd` (`World`, 20.8k строк) | `start_run`, director, loot, party, `_end_run`, `_bank_run`, арены MVP/Morroc, endless |
| Профиль | `save.gd` (2.3k) | `profile.json` (AES/`GDEC`), валюты, классы, storage, loadout, tower, rebirth, achievements |
| Данные | `game_data.gd` (11.8k) | `STAGES`, `REGIONS`, `MONSTERS`, `ITEMS`, `CARDS`, `PETS`, `CLASSES`, `UPGRADES`, формулы danger |
| Игрок | `player.gd` (5.3k) | статы, скиллы, draft, эволюции, job change, урон |
| AI | `bot.gd` (242), `hero_input.gd` | `Bot.steer`, `Bot.altar_goal`, `HeroInput.Local/BotHero` |
| UI | `menus.gd` (26.4k) | level-up, end screen + keep, Kafra, loadout, town-панели |
| Лут | `loot_roll.gd`, `loot_panel.gd`, `equipment.gd` | роллы, предметы, refit/refine, сумки |
| Город | `town.gd`, `star_smith_panel.gd`, `gacha_panel.gd`, `card_fusion*.gd` | апгрейды, Potential, гача, фьюжн карт |
| Экономика | `equipment.gd`, `game_data.gd` | продажа, ore drop, chest rolls, danger-множители |
| Режимы | `mvp_raid.gd`, `morroc_event.gd`, `tower_run.gd`, `hel_tower.gd`, `hel_naght.gd`, `festival_run.gd` | MVP-арена, поздний hell, Endless Tower, Hel Tower, фестиваль |
| Мета | `karma.gd`, `altars.gd`, `uniques.gd`, `titles.gd`, `achievements.gd` | карма/маршруты, алтари, уникальные предметы, титулы |
| Сеть | `net_sync.gd`, `relay_net.gd`, `town_channel.gd`, `eos*.gd` | кооп/лидерборды/Epic; для фермера отключается |

## Поток забега

```
start_run(class)
  → stage/danger clamp, player.setup(profile_of(class))
  → director: SPAWNS каждые every/rate игровых секунд, EVENTS по времени
  → MVP на stage.mvp_time (база 480 s) → raid.open_portal
  → убийство MVP → _victory_when_collected → _end_run(true)
  → смерть → _on_player_died → _end_run(endless)   (в пати — downed и ревайв)
  → _end_run: продажа сумки, банк ор, daily, _bank_run, show_end + keep screen
```

`_end_run` вызывается и при поражении: частичные награды (zeny, ore, class XP,
kills) банкуются всегда. Поэтому таймаут забега — легальный способ «снять» добычу.

## Ключевые состояния и флаги

- `World.running`, `World.time`, `World.kills`, `World.run_zeny`, `World.run_mvps`,
  `World.endless`, `World.player.pending_levels`, `World.menus._mode`.
- `Player.downed`, `Player.fell`, `Player.skills`, `Player.offer`.
- `Save.data`, `Save.zeny()`, `Save.materials()`, `Save.storage()`, `Save.max_danger()`.
- `GameData.hell_level(d) = max(0, d - 15)`; `DANGER_HELL_FROM = 16`.
- `_end_run` не отдаёт флаг победы наружу; надёжные наблюдаемые признаки:
  `run_mvps` увеличился (MVP убит) и/или `menus._mode == "victory"` (экран
  «продолжить в бесконечный»), иначе — поражение/таймаут.

## Точки перехвата без патчей

| Что нужно | Чем управлять |
|---|---|
| Движение игрока | заменить `player.input` на свой `HeroInput` (autopilot остаётся включённым для прочих эффектов) |
| Level-up | `player.offered_choices()` → свой выбор → `player.apply_choice(choice, world)`; `offer=[]`, `pending_levels-=1` |
| Job change | `player.can_job_change()` → `world.do_job_change(path)` (игрок), `h.job_change(path)` + `h.reborn` (пати) до `_update_party` |
| Саппорт-скиллы пати | `h.add_skill(id)` после job change |
| Loot roll | `world._loot.auto_pick(world.player)` (или свои `picks`) |
| Keep-экран | `menus._keep_offer`, `menus._keep_cost(it)`, `Save.add_to_storage` |
| Endless | `menus._mode == "victory"` → `world.continue_endless()` / `world._end_run(true)` |
| Скорость | `world.speed = 1..3` (официальный frenzy/game_fast) + `Engine.time_scale` при `world._mvp_slow = true` |
| Апгрейды | `Save.spend(GameData.upgrade_cost(id, lv))` → `Save.set_upgrade_level(id, lv+1)` |
| Rebirth | `Save.can_rebirth(class)` → `Save.rebirth(class)`; `Save.rebirth_lv_ready` → `Save.take_rebirth_lv` |
| Potential | `Save.add_material("star_crumb", -Potential.cost(locks))` → `Potential.roll(it, locks)`; `Potential.tear(it, i)` |

## Ограничения и ловушки

- `Save.add_to_storage()` в 0.2.3 **не копирует** `pot`, `trait` копирует только для
  `PURPLE_TRAITS`; после keep предмет теряет Potential, если его не восстановить вручную.
- `run_bans` работают только в пределах `Save.upgrade_active("fly_wing")`; это не
  «чёрный список навсегда», а N банов за забег.
- `menus.auto_pick = true` включает `Bot.pick_choice` на level-up (игнорирует
  `pick_order`) — поэтому фермер должен успевать выбирать сам.
- `RunSave` не пишется при `autopilot = true`; аварийное восстановление забега не нужно.
- `Engine.time_scale` перезаписывается `_frenzy_time_scale()` каждый кадр; обход —
  `world._mvp_slow = true` (используется существующим фермером).
- Профиль зашифрован (`GDEC`, ключ в `save.gd`), читать/править напрямую нельзя;
  всё — через `Save`.
