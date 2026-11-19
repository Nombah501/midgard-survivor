# 03: Durable checkpoint and idempotent settlement

**What to build:** Итоги сессии, `run_id`, фаза, цель и pre-run snapshot переживают рестарт. Run, который уже был settled, не settle-ится повторно; журнал дедуплицируется по `run_id`. Текущий run после падения считается потерянным, а не возобновляется.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] Checkpoint пишется атомарно на границах фаз и читается при старте.
- [ ] Totals и счётчики сессии продолжаются после рестарта.
- [ ] Уже settled `run_id` не settle-ится повторно; в журнале одна запись на `run_id`.
- [ ] Падение до settlement начинает новый run; падение после settlement пропускает повторный settlement.
- [ ] Sandbox-тесты покрывают падение до и после settlement.
