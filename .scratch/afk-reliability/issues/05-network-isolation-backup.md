# 05: Network isolation and known-good backup

**What to build:** AFK-сессии идут с OS-level network isolation, чтобы cloud sync не мог гоняться с фармом. Бэкапы профиля проверяются на восстановление, а crash loop не может вытеснить последний known-good snapshot.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] AFK-сервис запускает игру с network isolation.
- [ ] Cloud sync недоступен во время AFK-сессии.
- [ ] Known-good backup проверяется restore-тестом на копии.
- [ ] Рестарты в crash loop не вытесняют known-good snapshot.
- [ ] Тесты доказывают изоляцию и сохранность бэкапа.
