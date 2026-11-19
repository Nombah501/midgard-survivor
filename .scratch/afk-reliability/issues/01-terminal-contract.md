# 01: Terminal contract + verified flush + honest exit

**What to build:** Каждая AFK-сессия заканчивается терминальным статусом, который говорит, был ли это штатный финиш, остановка или сбой, и exit code, который этому соответствует. `done` означает, что профиль действительно записан; неудачный flush — это сбой, а не чистый финиш. Каждый run несёт стабильный `run_id` в статусе и журнале.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [x] Терминальный статус содержит `failed`, `finish_reason`, `last_error`, `last_transition`, `run_id` и heartbeat sequence.
- [x] Сбой ставит `phase=failed` и терминальную причину.
- [x] `phase=done` пишется только после подтверждённой записи профиля.
- [x] Неудачная запись профиля даёт `phase=failed` и ненулевой exit, без hard kill.
- [x] Launcher пробрасывает терминальный исход; `phase=done` больше не маскирует ненулевой код ребёнка.
- [x] `run_id` генерируется до старта run и попадает в статус и per-run журнал.
- [x] Sandbox-тест покрывает чистый финиш и путь с неудачным flush.

## Result

- Build: `d7a2ded3ff1a9791a3d6a32c266b27d29cffb934ce52e8282ca65aa3ecbbdb03`.
- `./tools/verify.sh --one-run --flush-fail`: PASS. `one-run` — `phase=done`, exit 0; `flush-fail` — `phase=failed`, `finish_reason=flush_failed`, exit 1.
- `./tools/check.sh`: OK.
