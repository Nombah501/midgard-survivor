# 05: Network isolation and known-good backup

**What to build:** AFK-сессии идут с OS-level network isolation, чтобы cloud sync не мог гоняться с фармом. Known-good backup публикуется после побайтовой проверки копирования и не вытесняется при повторных сбоях.

**Blocked by:** 02.

**Status:** resolved

- [x] AFK-сервис запускает игру с network isolation.
- [x] Cloud sync недоступен во время AFK-сессии.
- [x] Для known-good backup проверяется целостность скопированных файлов по SHA-256.
- [x] Рестарты после повторных сбоев не вытесняют known-good backup.
- [x] Тесты доказывают изоляцию и сохранность known-good backup.

## Result

- Непустой `FARMER_SESSION_ID` включает для игры `unshare -cn`; supervisor
  остаётся в исходном network namespace. Ошибка предварительной проверки или
  входа в namespace даёт 78 без запуска игры. Разовый запуск не меняет сеть.
  `exec` сохраняет группу процессов, а `tee` и обработка кода 137 сохранены.
- `known-good/` обновляется после чистого финиша только с причиной `finish`,
  `stop`, `max_runs`, `wins`, `goal` или `no_target`. `abort`, `lost_world`
  и неизвестные причины не меняют снимок или код завершения.
- Проверка копирования требует непустых исходных файлов бинарного профиля
  и сравнивает их SHA-256 с файлами, скопированными из снимка во временный
  `user://`. Только затем снимок с `SHA256SUMS` атомарно публикуется
  в `known-good/`. Ротация сохраняет 10 последних обычных снимков с меткой
  времени. В sandbox `install.sh` и `run.sh` пишут снимки в отдельный
  каталог `FARMER_BACKUP_DIR`.
- Принятые ограничения: первая публикация требует чистого финиша, проверка
  не доказывает загрузку профиля официальной игрой. Обновление существующего
  снимка требует GNU `mv --exchange` и поддержки обмена в файловой системе;
  при ошибке остаётся предыдущий снимок.

### Verification

- До изменений, из `farmer/`: `python3 -m pytest -q tests/test_run_sh.py -k 'supervised_game_cannot_route or isolation_failure_is_fatal or failed_restarts_rotate'` — 4 ожидаемых сбоя.
- Из `farmer/`: `python3 -m pytest -q tests/test_run_sh.py` — 11 passed;
  первоначальный полный прогон `python3 -m pytest -q tests` — 29 passed.
  Тест на изоляцию использует реальный Linux namespace: игра даже при
  `offline:false` попадает в отдельный namespace с единственным интерфейсом
  `lo`; разовый запуск остаётся в исходном namespace. Тесты также покрывают
  78, коды игры и `tee`, SIGTERM группе, 12 нештатных рестартов и ошибку
  проверки повреждённой копии.
- После замечаний проверки, из `farmer/`: до исправления `python3 -m pytest -q tests/test_run_sh.py -k 'unsettled_terminal or sandbox_install'` — 4 ожидаемых сбоя.
  После исправления `python3 -m pytest -q tests` — 35 passed, включая
  сохранение known-good backup при `abort`, `lost_world` и неизвестной причине
  с прежним exit 0, а также изоляцию снимков `install.sh` в sandbox.
- Из `farmer/`: `./tools/check.sh` — `check_api: OK`, `check: OK`.
- Реальная игра, из `farmer/`:
  ```bash
  if pgrep -af '[M]idgardSurvivors\.x86_64'; then exit 75; fi
  sb="$(mktemp -d -- "$PWD/../.sandbox/verify-net05.XXXXXXXX")" || exit
  export FARMER_SESSION_ID=verify-net05-isolated FARMER_BACKUP_DIR="$sb/backups" VERIFY_SANDBOX="$sb"
  ./tools/verify.sh --one-run --keep
  ```
  Сам сценарий — `PASS`: `run.sh` вернул 0 после SIGKILL 137, `phase=done`,
  один run; подтверждение — `farmer/logs/verify-20261119-181147-332019/one-run.result.json`.
  После сценария сам `verify.sh` вернул 2 на синтаксической ошибке
  в блоке итоговой сводки (`boot_log,`); владелец файла уведомлён.
- Из `.sandbox/verify-net05.4mcdX3U3/backups/known-good`: `sha256sum --check SHA256SUMS` —
  `profile.json: OK`, `profile.bak.json: OK`.
