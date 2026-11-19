# 06: Fault injection and 8–12 hour soak

**What to build:** AFK-цикл проверен под отказами и на длительности ночи: падения, зависания, полный диск, битый конфиг/статус, stale lock, второй инстанс и обновление игры. Сессия выживает или уходит в quarantine с диагностикой и никогда не делает двойной settlement молча.

**Blocked by:** 03, 04, 05.

**Status:** ready-for-human (осталось провести ночной soak)

- [x] `SIGKILL` до/после settlement восстанавливается по abort-политике.
- [x] `SIGSTOP` срабатывает на heartbeat watchdog.
- [x] Полный диск / read-only профиль — терминальный сбой с уведомлением.
- [x] Битый конфиг/статус, stale lock и второй инстанс обрабатываются.
- [x] Смена официального патча уходит в quarantine без crash loop.
- [ ] 8–12-часовой soak проходит с проверками heartbeat, памяти, диска и settlement.

## Result

- Supervisor: SIGSTOP на группу даёт `heartbeat_stale`, после чего группа убивается и farmer перезапускается. Нечитаемый status не считается чистым финишем. `farmer_supervisor.lock` защищает от второго supervisor'а: он выходит с кодом 1 и не трогает `farmer_stop` и session file первого. Если каталог профиля недоступен на запись, сам supervisor уходит в quarantine (exit 2, уведомление), а не в рестарты systemd. При preflight-quarantine в `quarantine.json` и в уведомление попадает строка `run: …` (`detail`).
- `run.sh` даёт exit 78 (quarantine без retry) в четырёх новых случаях: каталог профиля недоступен на запись (уникальный `mktemp`-probe), свободного места меньше `FARMER_MIN_FREE_MB` (200 MiB), `farmer.cfg` не JSON-объект, сменился официальный патч (последнее только покрыто тестом). Lock-файл, оставшийся от мёртвого launcher'а, не мешает: `flock` снимает ядро. Удерживаемый flock даёт exit 1 (busy).
- `farmer.lock` удалён из `farmer.gd` по решению оператора. `_pid_alive` проверял `FileAccess.file_exists("/proc/PID")`, а для каталогов это всегда false, поэтому lock никогда ничего не блокировал. Единственная защита от второго инстанса — `flock` и `pgrep` в `run.sh`.
- `FARMER_TEST_CRASH_AT` теперь одноразовый (`user://farmer_test_crashed`), чтобы рестарт supervisor'а не падал в той же точке.
- verify.sh: добавлены `--checkpoint-corrupt`, `--supervised-kill-run` (внешний SIGKILL игры в run r1 через `tools/drive_supervisor.py`), `--supervised-crash-settled` и `--soak=HOURS [--soak-preset=…]`. Вердикт soak выносит `tools/soak_check.py`. Он фейлит: heartbeat gap > 15 с или ни одного heartbeat; рост RSS > 50% после первого часа; рост диска > 200 MiB; ноль settled runs; дубль `run_id`; любой total, расходящийся с журналом; quarantine или нечистый финиш; длительность меньше HOURS. В summary пишется zeny/hour.
- Внешний SIGKILL «ровно после settlement» снаружи недостижим: keep→maint→settled checkpoint проходят внутри кадров без записи status. Поэтому эта точка покрыта in-farmer хуком.

### Verification

- Из `farmer/`: `python3 -m pytest -q tests` — 59 passed; `./tools/check.sh` — OK. До исправлений красными были тесты второго supervisor'а, read-only профиля (run.sh и supervisor), свободного места, битого cfg, `detail` при quarantine и новых проверок soak_check.
- Реальная игра, `./tools/verify.sh --checkpoint-corrupt --flush-fail` — PASS (exit 1, профиль не изменён).
- `./tools/verify.sh --supervised-kill-run --supervised-crash-settled --crash-run --crash-settled --crash-journaled --soak=0.03 --soak-preset=presets/zeny.json`: все пять сценариев PASS. Soak-smoke ожидаемо FAIL только на «no game RSS sample after the first hour»: heartbeat gap 5,05 с, диск +0,06 MiB, totals == журнал. Артефакты — `farmer/logs/verify-20261119-200202-570022/`.
- Не выполнено: ночной soak `./tools/verify.sh --soak=8` (или до 12). Его проводит оператор, вердикт — в `soak.verdict.log`.
