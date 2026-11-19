# 04: Operator commands finish, abort, pause and resume

**What to build:** Оператор может запросить `finish`, `abort`, `pause` или `resume` через файл команд. Команды читаются на границах фаз; `pause` не прерывает текущий run. Старый stop-файл остаётся алиасом `finish`.

**Blocked by:** 02, 03.

**Status:** resolved

- [x] `finish` завершает settlement/keep/maintenance и выходит.
- [x] `abort` пропускает optional keep и выходит с причиной abort.
- [x] `pause` даёт текущему run завершиться и запрещает старт следующего.
- [x] `resume` снимает pause без перезапуска процесса.
- [x] Supervisor и farmer согласованы по семантике команд; stop-файл означает `finish`.
- [x] Тесты покрывают каждый переход и чтение файла команд.

## Result

- `farmer_command` забирается атомарным переименованием перед чтением. `finish` и старый `farmer_stop` дают `finish_reason=finish`; GUI не менялся. `pause` не прерывает текущий run: после maintenance остаётся heartbeat с `phase=paused`, `resume` начинает следующий run с тем же PID.
- `abort` не запускает settlement, keep или maintenance. До settlement учитывается один потерянный run; после settlement сохранённый результат проходит через существующие checkpoint и журнал один раз. `phase=done` для обеих терминальных команд требует подтверждённого flush.
- При SIGTERM/SIGINT supervisor запрашивает `finish` через `farmer_stop` даже до первого heartbeat (и повторяет после запуска, если запрос был отправлен до очистки файла в `run.sh`). Лимит — 45 с на весь выход и не более 20 с после терминального статуса; затем SIGKILL группы без рестарта. Unit: `KillMode=mixed`, `TimeoutStopSec=90`. Отдельный CLI не нужен: README описывает атомарную публикацию в `farmer_command`.
- Границы: файл хранит один запрос, не очередь; падение после атомарного захвата может потерять ещё не обработанный запрос. Pause действует в текущем процессе, не сохраняется при рестарте и не отменяет лимиты сессии. Уже выполненные действия не откатываются.
- `cmd-finish` и `cmd-legacy` намеренно заканчивают run примерно через 0,1 с: согласно ADR 0004, `finish` сразу передаёт текущий run игре на settlement, затем выполняет keep и maintenance. Тестовые инъекции разрешены только в сессиях `verify-*`.
- Проверка из `farmer/`: `./build.sh` — OK (`b090c3ca…`); `./tools/verify.sh --cmd-finish --cmd-abort --cmd-abort-settled --cmd-pause-resume --cmd-legacy` — 5/5 PASS; `./tools/verify.sh` — 12/12 PASS, включая статический `check: OK` и три сценария восстановления. Артефакты полного прогона: `farmer/logs/verify-20261119-181506-340677/summary.json`.
- `python3 -m pytest -q tests` — 29 passed. До реализации целевой `python3 -m pytest -q tests/test_supervisor.py::test_supervisor_stop_requests_finish_before_signalling_child` ожидаемо падал: SIGTERM завершал процесс до `finish`. `./tools/supervisor.py --print-unit presets/night.json | grep -E '^(KillMode|TimeoutStopSec)='` — `mixed`, `90`.
- После правок по ревью: `python3 -m pytest -q tests/test_supervisor.py -k supervisor_stop_requests_finish_before_signalling_child` до исправления — 2 ожидаемых падения (до первого статуса / зависание после терминального статуса), 1 passed. После правок `python3 -m pytest -q tests` — 35 passed; `./tools/check.sh` — OK. Повторная сборка и sandbox-прогон оставлены на интеграцию.
