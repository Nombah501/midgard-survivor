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

Команды `finish`, `abort`, `pause`, `resume` описаны в
[управлении сессией](#управление-сессией).

Статус и лог:

```bash
cat  "$HOME/.local/share/godot/app_userdata/Midgard Survivors/farmer_status.json"
tail -f "$HOME/.local/share/godot/app_userdata/Midgard Survivors/farmer.log"
```

Игра должна быть закрыта перед `install.sh`/`run.sh`. `run.sh` сам проверяет
SHA официального патча и установленного фермерского патча; при обновлении игры
нужно пересобрать (`./build.sh && ./install.sh`). Exit `run.sh`: 0 — чистый
финиш, 78 — ошибка, которую рестарт не исправит (нет игры/патча, обновился
официальный патч, устаревшая сборка, плохой пресет, `farmer.cfg` не JSON-объект,
каталог профиля недоступен на запись или на его диске меньше
`FARMER_MIN_FREE_MB`, по умолчанию 200 MiB), 1 — второй `run.sh` или уже
запущенная игра, прочее — сбой.

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
| 4 сбоя за час, exit 78, `cfg_invalid`, `checkpoint_corrupt` | quarantine: без рестарта, уведомление с причиной из `run.sh`, exit 2 |
| SIGTERM/SIGINT | запрос `finish` даже при загрузке; до 45 с на весь выход и до 20 с после терминального статуса, затем SIGKILL всей группе, без рестарта |

Все рестарты одного supervisor'а — одна AFK-сессия: он передаёт фермеру
`FARMER_SESSION_ID`, и фермер продолжает `farmer_session.json` (checkpoint):
totals, счётчики, `run_id`, цель, pre-run snapshot. Checkpoint пишется
атомарно на границах `run` (забег начат), `settled` (профиль записан и
результат готов; обычно после keep, при `abort` — только settlement) и
`idle` (завершённый run учтён). При старте:
`run` → забег потерян (`totals.lost`, ADR 0001), `settled` → результат
засчитывается один раз; в `farmer_runs.jsonl` он дописывается, только если
его `run_id` там ещё нет. Разовый запуск без `FARMER_SESSION_ID` (GUI,
`run.sh`) начинает новую сессию.

До первого heartbeat даётся 180 с на загрузку игры. Логи и диагностика —
`farmer/logs/supervisor-<stamp>/`: `attempt-NN.log` (вывод `run.sh`),
`attempt-NN.status.json` (статус упавшей попытки), `quarantine.json`
(`detail` — строка `run: …`, которой `run.sh` объяснил exit 78).
Второй supervisor на том же профиле сразу выходит с кодом 1 и не трогает
сессию первого (`farmer_supervisor.lock`).
Уведомления: `notify-send` и, если задан `FARMER_NTFY_URL` (в
`~/.config/midgard-farmer.env` для unit'а или `--ntfy-url`), ntfy; они идут в
фоне и не задерживают рестарт.

systemd держит только сам supervisor: `Restart=on-failure`,
`RestartPreventExitStatus=2` (quarantine не перезапускается), не больше 3
рестартов в час. `systemctl --user enable` включает автозапуск при входе.
Тесты на фейковом child, без игры: `python3 -m pytest farmer/tests`.

### Управление сессией

Команды работают и в AFK-сессии, и при разовом запуске. Отправляйте их
активному фермеру по одной: `farmer_command` — один запрос, не очередь.
Пишите во временный файл в том же каталоге, затем переименуйте его:

```bash
data="${XDG_DATA_HOME:-$HOME/.local/share}/godot/app_userdata/Midgard Survivors"
cmd=pause  # finish | abort | pause | resume
tmp="$(mktemp "$data/.farmer-command.XXXXXX")" &&
  printf '%s\n' "$cmd" > "$tmp" &&
  mv -f -- "$tmp" "$data/farmer_command"
```

| Команда | Что происходит |
| --- | --- |
| `finish` | Если run ещё идёт, передаёт его игре на settlement, затем выполняет keep и maintenance. Выход с `finish_reason=finish`. |
| `abort` | Выход с `finish_reason=abort` без новых keep или maintenance. Если settlement ещё не произошло, run помечается потерянным; если произошло — учитывается один раз, без повторного settlement. |
| `pause` | Текущий run продолжается до settlement, keep и maintenance. Новые run не стартуют; `phase=paused` и heartbeat продолжают обновляться. |
| `resume` | Снимает pause без перезапуска процесса. |

`touch "$data/farmer_stop"` и кнопка GUI — алиасы `finish`, тоже
с `finish_reason=finish`. Из `paused` команды `finish` и `abort` не запускают
run. Pause действует в текущем процессе; она не отменяет лимиты сессии.
`finish` и `abort` штатны только после подтверждённого flush профиля:
supervisor уведомляет `stop` и не перезапускает фермера.

Для штатного `systemctl --user stop` обновите ранее сгенерированный unit
через `--print-unit` и `systemctl --user daemon-reload`: `KillMode=mixed`
оставляет фермеру время на подтверждённый flush, `TimeoutStopSec=90`
покрывает ожидание и отправку уведомлений.

### Сетевая изоляция и known-good backup

Непустой `FARMER_SESSION_ID` включает сетевую изоляцию для процесса игры:
`run.sh` запускает его через `unshare -cn` в отдельном network namespace
без внешних интерфейсов и маршрутов. Cloud sync недоступен даже при
`offline:false`; при необходимости синхронизируйте профиль вручную между
AFK-сессиями. Supervisor остаётся в обычной сети и может отправлять ntfy.
Для `unshare -c` нужен util-linux 2.38 или новее. Если `unshare` недоступен
или Linux запрещает создать user/network namespace, игра не запускается:
код 78 ведёт к карантину.
Разовый запуск из GUI или `run.sh` без `FARMER_SESSION_ID` не меняет сеть.

Known-good backup обновляется только после чистого финиша AFK-сессии с
причиной `finish`, `stop`, `max_runs`, `wins`, `goal` или `no_target`.
`abort`, `lost_world` и другие причины не заменяют существующий снимок.
`run.sh` выполняет побайтовую проверку копирования: `profile.json` и
присутствующие сопутствующие файлы должны быть непустыми, а SHA-256
файлов, скопированных из снимка во временный `user://`, — совпадать с
исходными. Это не проверка загрузки профиля игрой. Только после неё новый
снимок атомарно публикуется в `farmer/backups/known-good/` с `SHA256SUMS`;
обновление использует GNU `mv --exchange` на поддерживающей обмен файловой
системе. При ошибке проверки копирования или публикации `run.sh`
предупреждает и оставляет прежний known-good backup. Рестарты после сбоя
обновляют только обычные снимки; до первого подходящего финиша known-good
backup может отсутствовать.

Для sandbox-запуска `FARMER_BACKUP_DIR` задаёт отдельный каталог для снимков
`install.sh` и `run.sh`, чтобы не затрагивать снимки основного профиля.

## Проверка

```bash
./tools/check.sh                 # статический чек; один раз: ./tools/install_hooks.sh
./tools/verify.sh --one-run      # быстрый smoke в sandbox
./tools/verify.sh                # все сценарии, у каждого свой timeout
./tools/verify.sh --crash-settled  # падение после settlement + рестарт сессии
./tools/verify.sh --cmd-abort-settled --cmd-pause-resume
./tools/verify.sh --soak=8       # ночной soak под supervisor'ом (не входит в --all)
```

`verify.sh` читает реальный `user://`, но запускает игру на копии профиля в
`.sandbox/verify-*`; реальный профиль не изменяется. Артефакты —
`farmer/logs/verify-*`: `summary.json`, `*.log`, `*.status.json`. Сценарий
считается пройденным только при exit 0, `phase=done` и выполненных assert'ах;
таймаут — FAIL. `--crash-run|--crash-settled|--crash-journaled` убивают фермера
на границе checkpoint (`FARMER_TEST_CRASH_AT`), перезапускают ту же сессию и
проверяют, что totals совпадают с журналом и каждый `run_id` в нём один раз.
`--supervised-kill-run` и `--supervised-crash-settled` делают то же под
настоящим supervisor'ом: SIGKILL игры снаружи во время run или одноразовым
хуком после settlement, рестарт — уже решение supervisor'а.
`--checkpoint-corrupt` проверяет терминальный `checkpoint_corrupt` без
изменения профиля. Сценарии `--cmd-*` отправляют запросы в sandbox: проверяют
терминальную причину, журнал при `abort` до и после settlement, heartbeat во
время pause и `resume` с тем же PID.

`--soak=HOURS [--soak-preset=PRESET]` запускает пресет (по умолчанию
`presets/night.json`, `max_minutes=HOURS×60`) под supervisor'ом и каждые 5 с
пишет heartbeat, RSS игры и занятый диск в `soak.samples.jsonl`. Вердикт —
`tools/soak_check.py`: FAIL при heartbeat gap > 15 с, росте RSS > 50% после
первого часа, росте диска > 200 MiB, дубле `run_id`, расхождении totals с
журналом, quarantine или нечистом финише; в `soak.verdict.log` — rewards/hour.
Soak занимает машину (одна игра) на HOURS + до 30 мин.

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
| `stall_seconds` | 45 | watchdog: не идут часы игры (`STALL`) или время забега (`RUN_STALL`); после 3 попыток забег завершается принудительно |
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

- `install.sh`/`run.sh` сохраняют снимки профиля и сопутствующих файлов.
  `run.sh` хранит 10 последних обычных снимков в `farmer/backups/`; ротация
  не затрагивает `official-state.json` и `known-good/`.
- `run.sh` держит `flock` (снимается ядром при смерти процесса, stale lock
  не бывает), проверяет отсутствие второго процесса игры, сверяет
  SHA официального патча и собранного фермера.
- Фермер пишет статус атомарно, а при `hard_exit` убивает процесс только
  после `Save.flush()`.
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
tools/verify.sh      bounded сценарии и soak в sandbox
tools/supervisor.py  AFK supervisor: heartbeat, рестарт, quarantine, уведомления
tools/drive_supervisor.py  supervisor в sandbox: SIGKILL или сэмплы для verify.sh
tools/soak_check.py  вердикт soak по сэмплам, журналу и статусу
tests/               pytest supervisor'а, run.sh и soak_check без игры
tools/install_hooks.sh  git core.hooksPath=.githooks
presets/*.json       конфиги
patch_farmer.pck     собранный патч
patch_farmer.info    манифест (SHA, bytecode, API)
backups/             профили и baseline state.json
docs/design/farmer.md   дизайн
docs/analysis/*.md      исследование игры 0.2.3
```
