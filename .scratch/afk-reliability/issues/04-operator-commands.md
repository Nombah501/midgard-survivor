# 04: Operator commands finish, abort, pause and resume

**What to build:** Оператор может запросить `finish`, `abort`, `pause` или `resume` через файл команд. Команды читаются на границах фаз; `pause` не прерывает текущий run. Старый stop-файл остаётся алиасом `finish`.

**Blocked by:** 02, 03.

**Status:** ready-for-agent

- [ ] `finish` завершает settlement/keep/maintenance и выходит.
- [ ] `abort` пропускает optional keep и выходит с причиной abort.
- [ ] `pause` даёт текущему run завершиться и запрещает старт следующего.
- [ ] `resume` снимает pause без перезапуска процесса.
- [ ] Supervisor и farmer согласованы по семантике команд; stop-файл означает `finish`.
- [ ] Тесты покрывают каждый переход и чтение файла команд.
