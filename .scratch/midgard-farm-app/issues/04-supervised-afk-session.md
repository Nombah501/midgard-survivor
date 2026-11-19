# 04: Supervised AFK session in the service, with commands

**What to build:** An AFK session runs under the service with today's supervisor policy (heartbeat, backoff, quarantine, terminal outcome per ADR 0003). The operator controls it with start (character + preset), pause, resume, finish and abort through command files. The systemd user unit runs the new service.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] Every scenario of the current supervisor test suite is ported to the service seam and passes.
- [ ] Start takes a character and a preset; pause/resume/finish/abort keep ADR 0004 semantics.
- [ ] The terminal outcome comes from the farmer's status, never from the exit code alone.
- [ ] The generated systemd user unit starts the new service; a real overnight session on Linux completes under it.
- [ ] The old supervisor stays in place until cutover (15).
