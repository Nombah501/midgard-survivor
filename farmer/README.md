# Фермер для Midgard Survivors 0.2.3

Автономный соло-фарм-раннер: играет настоящие одиночные забеги, сам ведёт
draft, меняет профессию, добивает MVP, забирает добычу и запускает следующий
забег. Награды начисляет штатный `_end_run()` игры; профиль не редактируется
напрямую.

Патчатся два скрипта: `scripts/autoload/save.gdc` (bootstrap-хук) и
`scripts/core/player.gdc` (`next_job` уважает `Save` meta `farmer_job_paths`,
иначе поведение байт-в-байт штатное). Добавляется `scripts/core/farmer.gdc`.
Никаких изменений в `bot`, `altars`, `auto_pick`, `debug_menu` нет.

## Быстрый старт

```bash
cd /home/n501/orca/projects/midgard-survivor/farmer
./build.sh                 # собрать патч из текущего официального патча
./install.sh               # поставить в слот обновления игры
./run.sh presets/one-run.json   # проверка: один забег, Prontera, danger 1
./tools/farm.py --list          # персонажи и локации
./tools/farm.py --char sinx --stage prontera --danger 25
./tools/farm.py --char sniper --stage payon --danger 20
./run.sh presets/synx-hell.json # solo SinX, Prontera D25 (hell 10)
./run.sh presets/steady.json    # бесконечный авто-фарм
```

Остановка:

```bash
touch "$HOME/.local/share/godot/app_userdata/Midgard Survivors/farmer_stop"
```

Статус и лог:

```bash
cat  "$HOME/.local/share/godot/app_userdata/Midgard Survivors/farmer_status.json"
tail -f "$HOME/.local/share/godot/app_userdata/Midgard Survivors/farmer.log"
```

Игра должна быть закрыта перед `install.sh`/`run.sh`. `run.sh` сам проверяет
SHA официального патча и установленного фермерского патча; при обновлении игры
нужно пересобрать (`./build.sh && ./install.sh`). Exit `run.sh`: 0 — чистый
финиш, 78 — ошибка, которую рестарт не исправит (нет игры/патча, устаревшая
сборка, плохой пресет), прочее — сбой.

## AFK-сессия (supervisor)

```bash
./tools/supervisor.py presets/night.json   # на переднем плане
./tools/supervisor.py --print-unit presets/night.json \
  > ~/.config/systemd/user/midgard-farmer.service
systemctl --user daemon-reload && systemctl --user start midgard-farmer
journalctl --user -fu midgard-farmer
```

Supervisor запускает `run.sh` в отдельной группе процессов и следит за
`heartbeat_seq` в `farmer_status.json`:

| Исход | Действие |
| --- | --- |
| exit 0 и `phase=done` | конец сессии, уведомление `stop`/`goal` |
| crash, выход без терминального статуса, heartbeat не менялся 3×5 с | kill всей группы, уведомление `fail`, рестарт через 15 с × 2ⁿ (до 10 мин) |
| 4 сбоя за час, exit 78, `cfg_invalid` | quarantine: без рестарта, уведомление, exit 2 |
| SIGTERM/SIGINT | SIGTERM группе, через 20 с SIGKILL, уведомление `stop`, exit 0 |

До первого heartbeat даётся 180 с на загрузку игры. Логи и диагностика —
`farmer/logs/supervisor-<stamp>/`: `attempt-NN.log` (вывод `run.sh`),
`attempt-NN.status.json` (статус упавшей попытки), `quarantine.json`.
Уведомления: `notify-send` и, если задан `FARMER_NTFY_URL` (в
`~/.config/midgard-farmer.env` для unit'а или `--ntfy-url`), ntfy; они идут в
фоне и не задерживают рестарт.

systemd держит только сам supervisor: `Restart=on-failure`,
`RestartPreventExitStatus=2` (quarantine не перезапускается), не больше 3
рестартов в час. `systemctl --user enable` включает автозапуск при входе.
Тесты на фейковом child, без игры: `python3 -m pytest farmer/tests`.

## Проверка

```bash
./tools/check.sh                 # статический чек; один раз: ./tools/install_hooks.sh
./tools/verify.sh --one-run      # быстрый smoke в sandbox
./tools/verify.sh                # one-run + stop + endless, у каждого свой timeout
```

`verify.sh` читает реальный `user://`, но запускает игру на копии профиля в
`.sandbox/verify-*`; реальный профиль не изменяется. Артефакты —
`farmer/logs/verify-*`: `summary.json`, `*.log`, `*.status.json`. Сценарий
считается пройденным только при exit 0, `phase=done` и выполненных assert'ах;
таймаут — FAIL.

## GUI

`../gui` — Qt Quick панель управления: персонаж, локация, опасность,
старт/стоп, живые карточки и лог. Тема берётся из Omarchy (цвета, accent,
скругления).

```bash
cd ../gui
./bin/build
./build/midgardfarm
./bin/install   # по желанию: пункт меню и иконка
```

Панель запускает `tools/farm.py`, показывает `farmer_status.json` и
`farmer.log`, а при закрытии окна штатно останавливает фермера.

## Пресеты

| Файл | Что делает |
|---|---|
| `presets/one-run.json` | один забег Swordsman/Prontera/D1, без трат — smoke-тест |
| `presets/steady.json` | авто-класс, авто-стадия/danger, апгрейды, карты, loadout, питомец |
| `presets/zeny.json` | цель — зеньги; авто-подбор danger по измеренной доходности |
| `presets/crumbs.json` | цель — Star Crumb: danger 25+, endless до 6 минут / 8 MVP |
| `presets/synx-hell.json` | соло SinX, Rachel Sanctuary danger 25 (hell 10), speed 4, AFK-цикл |
| `presets/sniper-hell.json` | соло Sniper (archer/0), Rachel Sanctuary, те же настройки; включится после прокачки archer |
| `presets/progress.json` | продавливание максимального danger, rebirth |
| `presets/night.json` | ночной сбалансированный фарм, 8 часов, короткий endless |

## Выбор персонажа и локации

`tools/farm.py` берёт базу `presets/synx-hell.json`, подставляет выбранного
персонажа и стадию и запускает `run.sh`:

```bash
./tools/farm.py --list
./tools/farm.py --char sinx --stage prontera --danger 25
./tools/farm.py --char sniper --stage payon --danger 20
./tools/farm.py --class archer --job-path 0 --stage orc --danger 15
./tools/farm.py --char sinx --stage prontera --dry-run
```

Персонажи и стадии — в `targets.json`; `--list` печатает id и названия.
Профильные приоритеты скиллов/статов берутся для выбранного класса. Если
класс или стадия ещё не открыты, фермер пишет `CLASS_LOCKED`/`STAGE_LOCKED`
и не подменяет выбор другим классом/локацией.

AFK-цикл: забег идёт до смерти/победы (на SinX D25 обычно ~25 game-min),
награды банкуются, следующий забег стартует сам. Гарантии 30–40 минут без
смерти нет — это осознанно не критично.

## Как это работает

1. `Save._process` вызывает `_farmer_tick()`; только при `FARMER_SESSION=1`,
   `user://farmer.cfg` и headless/`display:true` создаётся узел `Farmer`.
   `run.sh` не передаёт пользовательских аргументов вида `--...`: Updater игры
   при таком аргументе отключает все патчи (`updater.gd:_enabled`).
2. Фермер ждёт `World`, включает `world.autopilot` (для авто-refine/стрел и
   подавления лишних событий) и `menus.auto_pick` (для loot roll).
3. Движение игрока заменяется своим `HeroInput`: приоритеты — механики MVP →
   Golden Poring → ценный пикап → алтарь → квест → бой/отступление.
4. Level-up: `offered_choices()` → собственный планировщик → `apply_choice()`
   без UI. Приоритеты берутся из профиля (`pick_order`/`pick_limits`), если
   конфиг не задаёт `builds` явно.
5. Job change: микро-патч `Player.next_job` читает `Save` meta
   `farmer_job_paths`, поэтому штатное меню выбирает заданную ветку.
6. Победа: `raid.state=="won"` своей арены или `menus._mode=="victory"`.
   Игра не завершает забег сама (мета `GameData.karma_test`), поэтому фермер
   решает: `continue_endless()` или `_end_run(true)`.
7. Экран конца: keep по ценности (до 3 бесплатных после победы; 1 платный после
   поражения), затем штатная уборка невзятых worn/legendary (зеньги/legend_coin).
8. Между забегами: достижения, апгрейды Kafra/Sage, rebirth, статы, fusion карт,
   альбом, loadout, питомец, (опционально) Star Smith и очистка склада.
9. Метрики каждого забега пишутся в `farmer_status.json` и
   `farmer_runs.jsonl`; выбор (stage, danger) адаптируется по фактической
   доходности, а не по «максимальной сложности».

## Конфиг

`$DATA/farmer.cfg` — JSON. Все поля необязательны. Основные:

| Поле | По умолчанию | Смысл |
|---|---|---|
| `objective` | `balanced` | `zeny`, `ores`, `crumbs`, `xp`, `cards`, `pets`, `coins`, `progress`, `balanced` |
| `weights` | см. код | ценность единицы ресурса для выбора руки |
| `class`/`classes`/`class_rotate` | `""`/`[]`/`false` | класс игрока |
| `job_paths` | `{}` | ветка класса; для archer `0`=Sniper, `1`=Bard; thief `0`=SinX |
| `builds` | `{}` | билды по классам: `job_path`, `skills`, `stats`, `caps`, `junk` |
| `stage`/`danger` | `""`/`auto` | фиксация цели; `danger`: `auto`, число, `best`, `max` |
| `danger_ceiling` | 30 | верхняя граница автоподбора |
| `explore_every` | 5 | как часто пробовать соседнюю руку |
| `speed` | 4.0 | `Engine.time_scale` (реальное ускорение) |
| `game_speed` | 3 | штатный режим игры 1–3 (frenzy/game_fast) |
| `run_minutes` | 12 | таймаут забега по игровому времени |
| `arena_wall_max` | 180 | таймаут арены MVP по реальному времени |
| `stall_seconds` | 45 | watchdog: часы игры не идут |
| `endless` | false | продолжать после MVP |
| `endless_minutes`/`endless_mvps` | 4/0 | бюджет endless |
| `max_runs`/`max_minutes`/`stop_after_wins` | 0 | лимиты сессии |
| `auto_keep`/`keep_on_defeat`/`keep_max_pct` | true/false/0.05 | политика Kafra |
| `auto_stats`/`auto_rebirth`/`auto_rebirth_lv` | true/false/false | прокачка |
| `auto_upgrades`/`upgrade_reserve`/`storage_target` | true/500000/120 | Kafra |
| `auto_sage` | true | Sage-апгрейды |
| `auto_fuse`/`fuse_keep`/`auto_cards` | true/{}/true | карты |
| `auto_loadout`/`auto_pet`/`pet_priority` | true/true/[] | снаряжение и питомец |
| `auto_potential`/`potential_reserve`/`potential_max_rolls` | false/20/0 | Star Smith |
| `auto_storage_prune` | false | удалять мусор при полном складе |
| `offline`/`display`/`hard_exit` | true/false/true | режим запуска |
| `goals`/`goal_stop` | `{}`/false | остановка по целям (карты/питомцы/зеньги) |

## Статус

`farmer_status.json` содержит: `session`, `phase`, `target`, `totals`, `rates`
(зеньги/час, убийства/мин, руда/час, крошки/час), `arms` (статистика по
`stage|danger`), `last` (последний забег), `maint` (что куплено/слито),
`profile` (зеньги, склад, материалы) и `game` (hp/level/time).

Терминальный контракт: `terminal`, `failed`, `finish_reason`, `last_error`,
`last_transition`, `exit_code`, `run_id`, `heartbeat_seq`. При сбое статус
получает `phase=failed` и `exit_code!=0`; `phase=done` пишется только после
подтверждённой записи профиля. `run.sh` возвращает 0 только для чистого
финиша (включая headless SIGKILL 137 после успешного flush), иначе — ненулевой
код.

`farmer_runs.jsonl` — по строке на забег: победа, время (wall/game), убийства,
зеньги, XP, дельты материалов/карт/питомцев/coins/ymir, keep, `job`.
`farmer_status.json.run` показывает незавершённую победу (`won_at`, `boss_won`,
`endless_*`) — это отладочный срез, а не результат забега.

## Безопасность

- `install.sh`/`run.sh` делают уникальные бэкапы `profile.json`,
  `profile.bak.json`, `profile.run` в `farmer/backups/` (10 последних +
  `official-state.json`).
- `run.sh` держит `flock`, проверяет отсутствие второго процесса игры, сверяет
  SHA официального патча и собранного фермера.
- Фермер держит `user://farmer.lock`, пишет статус атомарно, а при
  `hard_exit` убивает процесс только после `Save.flush()`.
- `uninstall.sh` возвращает официальный патч и удаляет только фермерский pck;
  профиль/конфиг/логи остаются.

## Ограничения

- Endless Tower, Hel Tower и Emperium Festival **не автоматизируются** в v1:
  это отдельные режимы со своим UI и сохранёнными билдами.
- Karma-маршрут после MVP запускается автоматически: Valhalla → Valkyrie
  Reginleif (+1 жизнь, +15% XP), Niflheim → Randgris. Если сторона karma не
  выбрана (нет алтаря Baldur/Hel), портала нет и фермер идёт в endless.
- **Кафра:** `auto_keep: false` по умолчанию — дроп забегов не сохраняется в
  кафру (продаётся/остаётся в награде). Включать только вручную и следить за
  местом.
- Гача, town-refine с риском слома, grades/sockets и ролл traits не трогаются.
- На danger 26–30 кумулятивные механики Hell могут убивать: автоподбор отступит
  по метрикам, но гарантий выживания нет.
- Онлайн-функции отключены при `offline:true` (лидерборды/Epic/cloud).
- `synx-hell` рассчитан на профиль с уже собранным SinX: фермер не покупает
  снаряжение и не перекладывает loadout, только играет забеги и забирает лут.
  Автопилот на D25 умирает около 25.5 game-min; забег закрывается как endless
  victory, банкуется и перезапускается. Это AFK-цикл, а не гарантия 30–40 минут
  без смертей.

## Обновление игры

```bash
./build.sh && ./install.sh
```

`build.sh` берёт текущий официальный патч из `user://patches/state.json`,
пересобирает `save.gdc` с хуком, `player.gdc` с micro-patch и `farmer.gdc`,
проверяет наличие всех трёх файлов в pck и пишет `patch_farmer.info`
(SHA/bytecode/API). Если якоря в `save.gd` изменились, сборка упадёт с понятной
ошибкой — тогда нужно обновить `tools/inject_hook.py`.

## Файлы

```
src/farmer.gd        драйвер (один файл, один патч)
src/save_hook.gd     bootstrap, добавляется в Save
tools/inject_hook.py идемпотентная вставка хука
tools/patch_player.py next_job: путь профессии из Save meta
tools/check.sh       статические проверки
tools/verify.sh      bounded one-run/stop/endless в sandbox
tools/supervisor.py  AFK supervisor: heartbeat, рестарт, quarantine, уведомления
tests/               pytest supervisor'а на фейковом farmer
tools/install_hooks.sh  git core.hooksPath=.githooks
presets/*.json       конфиги
patch_farmer.pck     собранный патч
patch_farmer.info    манифест (SHA, bytecode, API)
backups/             профили и baseline state.json
docs/design/farmer.md   дизайн
docs/analysis/*.md      исследование игры 0.2.3
```
