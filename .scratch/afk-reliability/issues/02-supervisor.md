# 02: Supervisor with heartbeat, backoff, quarantine and notifications

**What to build:** Внешний supervisor запускает фермера, следит за heartbeat и терминальным статусом, перезапускает после падения с экспоненциальным backoff, останавливается после повторяющихся сбоев и уведомляет оператора. Supervisor владеет группой процессов и не оставляет orphan-игру.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] User systemd unit запускает supervisor; политика рестарта supervisor'а описана.
- [ ] Supervisor запускает фермера и убивает всю группу процессов при остановке.
- [ ] Heartbeat старше трёх интервалов считается зависанием и ведёт к рестарту.
- [ ] Clean finish/stop/goal не рестартит; crash/hang рестартит.
- [ ] Повторные сбои в окне переводят в quarantine и уведомляют.
- [ ] Уведомления через `notify-send` и опциональный ntfy; сбой уведомления не блокирует recovery.
- [ ] Тесты с фейковым child покрывают restart, backoff, quarantine и clean finish.
