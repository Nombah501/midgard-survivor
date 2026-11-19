# 03: Durable checkpoint and idempotent settlement

**What to build:** Итоги сессии, `run_id`, фаза, цель и pre-run snapshot переживают рестарт. Run, который уже был settled, не settle-ится повторно; журнал дедуплицируется по `run_id`. Текущий run после падения считается потерянным, а не возобновляется.

**Blocked by:** 01.

**Status:** resolved

- [x] Checkpoint пишется атомарно на границах фаз и читается при старте.
- [x] Totals и счётчики сессии продолжаются после рестарта.
- [x] Уже settled `run_id` не settle-ится повторно; в журнале одна запись на `run_id`.
- [x] Падение до settlement начинает новый run; падение после settlement пропускает повторный settlement.
- [x] Sandbox-тесты покрывают падение до и после settlement.

## Result

- `farmer_session.json` пишется на границах `run` → `settled` (после keep/flush и ещё раз после maintenance с финальным result) → `idle`. Сессию продолжает только тот же `FARMER_SESSION_ID`; supervisor хранит его в `farmer_supervisor_session` до терминального исхода, так что переживает и свой рестарт systemd'ом.
- Восстановление: `run` → `totals.lost`+1; `settled` → результат засчитывается один раз, в журнал и arms идёт только если `run_id` там нет.
- Сбой записи checkpoint/журнала → `checkpoint_failed`/`journal_failed`; битый checkpoint supervised-сессии → `checkpoint_corrupt` (supervisor: quarantine без retry).
- Принятые окна (ADR 0001, недоучёт, не двойной учёт): падение между `Save.flush()` в keep и checkpoint `settled`; падение между journal append и сохранением arms (arms теряет одну выборку). Цель сессии берётся из пресета, который `run.sh` копирует при каждом рестарте; в checkpoint её нет.
- Проверка: `./tools/verify.sh` — 7/7 PASS (сборка `41e72b82…`), включая `crash-run`, `crash-settled`, `crash-journaled`: totals = журнал, каждый `run_id` один раз, `profile.zeny` сдвинулся ровно на `totals.zeny`. `pytest farmer/tests` — 14 passed.
