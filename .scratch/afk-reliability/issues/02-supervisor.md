# 02: Supervisor with heartbeat, backoff, quarantine and notifications

**What to build:** Внешний supervisor запускает фермера, следит за heartbeat и терминальным статусом, перезапускает после падения с экспоненциальным backoff, останавливается после повторяющихся сбоев и уведомляет оператора. Supervisor владеет группой процессов и не оставляет orphan-игру.

**Blocked by:** 01.

**Status:** resolved

- [x] User systemd unit запускает supervisor; политика рестарта supervisor'а описана.
- [x] Supervisor запускает фермера и убивает всю группу процессов при остановке.
- [x] Heartbeat старше трёх интервалов считается зависанием и ведёт к рестарту.
- [x] Clean finish/stop/goal не рестартит; crash/hang рестартит.
- [x] Повторные сбои в окне переводят в quarantine и уведомляют.
- [x] Уведомления через `notify-send` и опциональный ntfy; сбой уведомления не блокирует recovery.
- [x] Тесты с фейковым child покрывают restart, backoff, quarantine и clean finish.

## Result

- `farmer/tools/supervisor.py`; unit генерируется `--print-unit` (пути экранированы, `Restart=on-failure`, `RestartPreventExitStatus=2`).
- `run.sh`: preflight, который рестарт не исправит, выходит с 78 → quarantine без retry (как и `cfg_invalid`); lock/второй процесс игры — exit 1, retry.
- Решения сверх тикета: до первого heartbeat даётся `startup_grace` 180 с (загрузка игры), потом действует порог 3×5 с; статус старше spawn игнорируется вместо удаления; при остановке оператором отправляется `stop`.
- Сетевая изоляция (ADR 0002) не входит в 02 — тикет 05.
- Проверка: `python3 -m pytest farmer/tests` — 13 passed; `tools/check.sh` OK; `systemd-analyze --user verify` сгенерированного unit OK. На реальной игре supervisor не запускался — это тикет 06.
