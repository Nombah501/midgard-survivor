# AFK Reliability — Spec

Status: ready-for-agent

## Problem Statement

The farmer can play runs, but it cannot be trusted to run a full AFK session. If the game or the farmer process crashes, hangs or exits silently, nothing restarts it and nobody is told. Session totals and settlement can be lost or counted twice across a restart. The operator cannot distinguish a clean finish from a failure, and cloud sync can race the farm. This blocks overnight and multi-day use.

## Solution

Put a small external supervisor around the existing farmer. The supervisor owns the AFK session lifecycle: it starts the farmer, watches a heartbeat and a terminal status, restarts after a crash with backoff, quarantines a crash loop, and notifies the operator. The farmer gains a terminal status contract with a verified save flush and honest exit codes, a durable session checkpoint for idempotent settlement, and explicit operator commands (`finish`, `abort`, `pause`, `resume`). AFK sessions run with OS-level network isolation so cloud sync cannot race the farm. The in-game controller is kept; this is the shell around it, not a rewrite.

## User Stories

1. Как оператор, я хочу запустить AFK-сессию одной командой и уйти, чтобы она работала ночью без меня.
2. Как оператор, я хочу, чтобы supervisor перезапускал фермера после падения, чтобы одна ошибка не заканчивала всю сессию.
3. Как оператор, я хочу, чтобы supervisor прекращал перезапуски после повторяющихся падений, чтобы не крутить crash loop.
4. Как оператор, я хочу получать уведомление при остановке, ошибке, карантине или достижении цели, чтобы не проверять логи вручную.
5. Как оператор, я хочу видеть терминальную причину завершения, чтобы отличать штатный финиш от сбоя.
6. Как оператор, я хочу, чтобы итоги сессии переживали рестарт, чтобы темпы и квоты оставались верными.
7. Как оператор, я хочу, чтобы settlement был идемпотентным, чтобы рестарт не зачислял награды дважды.
8. Как оператор, я хочу, чтобы после падения текущий run считался потерянным и стартовал новый, чтобы не восстанавливать сомнительный run save.
9. Как оператор, я хочу команду `finish`, чтобы текущий run штатно завершился, забрал keep и сделал maintenance.
10. Как оператор, я хочу команду `abort`, чтобы немедленно остановиться в аварийной ситуации без optional keep.
11. Как оператор, я хочу команду `pause`, чтобы завершить текущий run, но не начинать следующий.
12. Как оператор, я хочу команду `resume`, чтобы снять `pause` без перезапуска процесса.
13. Как оператор, я хочу, чтобы `pause` не прерывал текущий run, чтобы не терять прогресс.
14. Как оператор, я хочу, чтобы AFK-сессия шла с отрезанной сетью, чтобы cloud sync не перезаписал профиль во время фарма.
15. Как оператор, я хочу, чтобы `phase=done` означал реально записанный профиль, чтобы не потерять награды при жёстком выходе.
16. Как оператор, я хочу ненулевой exit code при сбое, чтобы systemd и скрипты могли реагировать.
17. Как оператор, я хочу, чтобы зависший процесс определялся по устаревшему heartbeat, а не по факту «процесс жив».
18. Как оператор, я хочу, чтобы supervisor убивал всю группу процессов, чтобы не оставлять orphan-игру.
19. Как оператор, я хочу, чтобы при карантине сохранялись статус и хвост лога, чтобы можно было разобраться.
20. Как оператор, я хочу, чтобы смена официального патча приводила к паузе и уведомлению, а не к бесконечному рестарту.
21. Как оператор, я хочу, чтобы цель (`goal`) завершала сессию штатно, чтобы не фармить после достижения результата.
22. Как оператор, я хочу, чтобы старый one-off запуск через GUI продолжал работать, чтобы можно было сделать один забег без supervisor'а.
23. Как разработчик, я хочу видеть `run_id` и фазу в статусе, чтобы коррелировать логи, отчёты и тесты.
24. Как разработчик, я хочу проверять решения supervisor'а на фейковом ребёнке, чтобы тесты не требовали игры.
25. Как разработчик, я хочу fault-injection тесты, чтобы поведение при падении было доказано, а не предположено.
26. Как разработчик, я хочу 8–12-часовой soak, чтобы проверить стабильность, память, диск и отсутствие двойного settlement.

## Implementation Decisions

- **Supervisor shape.** Внешний Python-supervisor, запускаемый user systemd unit. systemd держит автозапуск и рестарт supervisor'а; Python владеет политикой: heartbeat, backoff, crash-loop cap, quarantine, notifications. Supervisor запускает фермера как отдельную группу процессов.
- **Terminal contract.** Статус получает `failed`, `finish_reason`, `last_error`, `last_transition`, `run_id`, `heartbeat_seq` и признак терминального исхода. `phase=failed` ставится при сбое; `phase=done` — только после подтверждённой записи профиля. `finish_reason` обязателен для любого терминального состояния.
- **Exit codes.** Launcher пробрасывает терминальный исход и код ребёнка. `phase=done` больше не маскирует ненулевой код; сбой flush или игры даёт ненулевой exit.
- **Verified flush.** После `Save.flush` фермер подтверждает, что профиль действительно записан (mtime/size или явный boolean-контракт). Если подтверждения нет — терминальный сбой, без hard exit.
- **Checkpoint.** Атомарный `farmer_session.json` на границах фаз: `session_id`, `run_id`, фаза, цель, totals, pre-run snapshot, `settled` marker. Resume самого run не делается; после рестарта сессия продолжает totals и начинает новый run. Повторный settlement для `run_id`, уже присутствующего в журнале, запрещён.
- **Run ID.** Генерируется до старта run, пишется в статус и журнал; используется для дедупликации и корреляции.
- **Commands.** Файл команд с `finish|abort|pause|resume`, читается на границе фазы. `finish` = settlement → keep → maintenance → выход; `abort` = без optional keep, только уже забанкованное; `pause` = завершить текущий run, не начинать следующий; `resume` = снять pause. Старый stop-файл — алиас `finish`.
- **Heartbeat semantics.** Статус обновляется каждые 5 секунд. Supervisor считает heartbeat устаревшим после трёх пропущенных интервалов, убивает группу процессов, фиксирует сбой и перезапускает с backoff. Heartbeat доказывает только живость цикла, не прогресс run.
- **Failure policy.** Clean finish/stop/goal → без рестарта. Crash/hang → рестарт с экспоненциальным backoff. Повторные сбои в окне → quarantine + notify. Несовместимый билд или смена официального патча → quarantine без retry.
- **Notifications.** `notify-send` при наличии desktop-сессии; опциональный ntfy URL в конфиге. Уведомления на stop/fail/quarantine/goal; отправка не блокирует recovery.
- **Network isolation.** Игра запускается с `PrivateNetwork=yes` или `unshare -n`; cloud sync выключен на время AFK-сессии. Ручной sync — между сессиями, если нужен.
- **Backup.** Supervisor архивирует терминальный статус и хвост лога при сбое; known-good backup не вытесняется во время crash loop.
- **GUI.** В v1 GUI остаётся one-off launcher'ом и не запускает supervisor. Интеграция GUI с AFK-сессией — отдельная итерация.
- **Existing controller.** Игровой цикл, draft, keep, maintenance и адаптивный выбор цели не переписываются.

## Testing Decisions

Хороший тест проверяет внешнее поведение: терминальный статус, exit code, решение supervisor'а о рестарте, идемпотентность settlement, семантику команд и сетевую изоляцию. Внутренние функции и структуры не тестируются напрямую.

Seams:

1. **Supervisor boundary.** Фейковый child + статус-файлы; проверяются restart, backoff, crash-loop cap, quarantine, notification и убийство группы процессов. Игра не нужна.
2. **Terminal contract.** Sandbox-запуск или stub, который пишет статус и выходит; проверяются `phase`, `finish_reason`, `exit code` и поведение при неудачном flush.
3. **Checkpoint/settlement.** Копия sandbox-профиля; падение до и после settlement; проверяются totals, `run_id`, отсутствие повторного начисления и дедуп журнала.
4. **Command boundary.** Файл команд; проверяются переходы `finish`, `abort`, `pause`, `resume` на границах фаз.

Prior art: существующий sandbox verification harness с сценариями one-run/stop/endless; расширять его, а не строить второй harness.

Fault injection: `SIGKILL` до и после settlement, `SIGSTOP` для проверки heartbeat, read-only/полный диск, битый конфиг/статус, stale lock, второй инстанс, смена официального патча.

Soak: 8–12 часов с проверкой heartbeat, памяти, диска, rewards/hour и отсутствия двойного settlement.

## Out of Scope

- Resume незавершённого run через `RunSave`.
- Интеграция GUI с AFK-сессией.
- Inventory lifecycle: sell/salvage/refine, политика полного склада сверх alert.
- Scheduler/calendar, daily/weekly rotation.
- Towers/Hel/Festival automation.
- Автоматическая пересборка при обновлении игры.
- Multi-account, OCR/ADB, anti-detection/humanization.
- Управление cloud sync сверх сетевой изоляции.

## Further Notes

- Research baseline: `docs/research/afk-bot-baseline.md`.
- Existing audit: `docs/analysis/farmer-audit.md`.
- Decisions: `docs/adr/0001-crash-abort-not-resume.md`, `0002-isolate-farmer-network.md`, `0003-supervisor-owns-terminal-outcome.md`, `0004-finish-abort-pause.md`.
- Если позже понадобится resume, начать с prototype, который докажет безопасность `RunSave.resume` на sandbox-профиле.
