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

- Build: `cfbb34b080e947fa1918be2f88f358943978593d60df2ea19b741adf319be503`.
- `./tools/verify.sh --one-run --flush-fail`: PASS. `one-run` — `phase=done`, `terminal=true`, exit 0; `flush-fail` — `phase=failed`, `finish_reason=flush_failed`, `terminal=true`, exit 1.
- `./tools/check.sh`: OK.
- Review follow-up: the flush fingerprint now forces a content change (`farmer_flush_marker`), so a successful write cannot be mistaken for a failed one; status parsing uses a non-whitespace delimiter; the status exposes an explicit `terminal` flag.
