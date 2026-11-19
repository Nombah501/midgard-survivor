# Baseline надёжности AFK-фармера

Дата обращения: **2026-11-19**. Метод: статическое чтение первичных исходников и документации,
без замеров аптайма. Ссылки на код закреплены за коммитами и строками.
**Наблюдение** — поведение из источника; **вывод** — оценка риска или рекомендация для Midgard Survivors.

Выборка: **MaaAssistantArknights (MAA)** — [очередь][maa-queue] и [таймеры][maa-time];
**AzurLaneAutoScript (ALAS)** — [планировщик и recovery][alas-loop]; **Fate-Grand-Automata (FGA)** —
[ограниченная сессия FGO][fga-battle]; **AutoTrimps** — [мод idle-игры Trimps для браузера и Steam][at-readme]
с [игровым и GUI-циклами][at-loop], аналог внутриигрового контроллера, не внешнего супервизора.

## Checklist

### 1. Супервизор: запуск, зависание, выход

- **Риск (вывод):** запущенный, но зависший процесс выглядит рабочим; бесконечный рестарт
  не исправляет постоянную ошибку.
- **Наблюдение:** ALAS [детектирует зависание][alas-stuck], ставит `Restart` игры в очередь,
  при некоторых ошибках ждёт 10 с и [выходит после трёх последовательных отказов задачи][alas-loop],
  не расходуя бесконечные повторы ([обработка][alas-recover]). MAA [ограничивает повторы подзадачи][maa-retry].
  FGA [повторяет сетевой диалог][fga-retry], но [не перезапускает Android service после смерти процесса][fga-service]:
  нельзя восстановить согласие на MediaProjection.
- **Минимум (вывод):** один `systemd --user` unit ведёт launcher и игру. `Restart=on-failure`,
  `RestartSec=` (при поддержке — `RestartSteps=` / `RestartMaxDelaySec=`), лимит запусков
  `StartLimitIntervalSec=` / `StartLimitBurst=`. Drift, невалидный конфиг и неясный recovery:
  отдельный код выхода в `RestartPreventExitStatus=`. После карантина — диагностика и ручной старт.
- **Минимум (вывод):** `WatchdogSec=` требует `WATCHDOG=1`; launcher посылает его только
  при свежем heartbeat той же игровой сессии и соблюдении дедлайна фазы. При stop не брать
  новые задачи, завершить/штатно прервать забег и сохранить профиль; до принудительной остановки
  есть `TimeoutStopSec=`. `loginctl enable-linger` нужен лишь для работы user manager после logout,
  не предотвращает suspend ([service][systemd-service], [unit][systemd-unit], [loginctl][systemd-login]).

### 2. Crash-safe state: идентичность, checkpoint, settlement

- **Риск (вывод):** сбой между изменением сейва и записью результата оставляет неопределённость;
  слепой повтор может удвоить награду, а сброс счётчика обходит квоту.
- **Наблюдение:** ALAS хранит `NextRun` и остаток проходов в конфиге
  ([планировщик][alas-delay], [декремент][alas-count]); [пишет JSON атомарно][alas-config-write]
  через [синхронизацию temp и замену][alas-write]. FGA [уменьшает лимиты в `finally`][fga-finally],
  не при убийстве процесса. AutoTrimps [вызывает `downloadSave()` до `activatePortal()`][at-portal].
  Это состояние очереди, учёт сессии и экспорт соответственно, не доказательства exactly-once.
- **Минимум (вывод):** сохранить `run_id` **до** старта вместе с `job_id`, `profile_id`,
  ревизией билда/конфига и фазой. `settled` не повторять; `running` возобновлять только
  из проверенного игрового checkpoint, иначе `aborted` и новый ID. Для `settling`
  сначала сверить авторитетный сейв; при неоднозначности остановиться.
- **Минимум (вывод):** идемпотентность награды требует маркера `run_id` в том же коммите,
  что и изменение профиля, либо надёжной сверки по игре. Уникальный `run_id` в отдельной SQLite
  защищает только журнал/квоту, не сейв. Для durable JSON: temp в том же каталоге →
  `fsync(temp)` → `rename` → `fsync(dir)`; атомарная видимость status не равна durability.
  Для нескольких связанных записей журнала — транзакция ([rename(2)][rename], [fsync(2)][fsync], [SQLite][sqlite-atomic]).

### 3. Расписание и полезная работа

- **Риск (вывод):** простой цикл пропускает окна, тратит ресурсы после достижения цели
  или после сна повторяет работу уже закрытого периода.
- **Наблюдение:** ALAS [сортирует готовые задачи по приоритету, отложенные по `next_run`][alas-config],
  учитывает [серверный reset][alas-reset], [переключается между забегами][alas-count] и
  [проверяет weekly rewards по состоянию игры][alas-weekly]. MAA [запускает набор задач по таймеру
  с выбором конфига][maa-time] и [ограничивает походы и дроп][maa-fight]. FGA [ждёт реген AP,
  расходует ограниченный refill или выходит][fga-refill] — это не календарь. AutoTrimps
  сверяет [`recentDailies`][at-daily], [порог зоны и доход/час][at-threshold] при выборе portal.
- **Минимум (вывод):** последовательная очередь, приоритет готовых задач, вытеснение только
  на безопасной границе; лимит минут/забегов/расхода и выход по цели. Для реальных daily/weekly
  reset задать часовой пояс, ключ периода, окно и правило (`skip` или один допустимый catch-up).
  Календарное время — для окон, монотонное — для дедлайнов. `OnCalendar=` + `Persistent=`
  может активировать unit после пропуска, но не переигрывает каждое окно и не перезапускает
  уже активный unit ([systemd.timer][systemd-timer]).

### 4. Наблюдаемость: жив ли и делает ли работу

- **Риск (вывод):** PID и поток сообщений не доказывают прогресс; без retention лог
  и артефакты могут занять диск, нужный сохранениям.
- **Наблюдение:** MAA даёт [callbacks старта, результата, ошибки и stop с `taskid`][maa-callback]
  и [ротацию по размеру][maa-log]. ALAS [сохраняет последние скриншоты и хвост лога][alas-artifact]
  при отказе с обработкой чувствительных данных. FGA [сводит счётчики проходов, refill, дроп
  и среднее время][fga-metrics]; [скриншот дропа][fga-shots] — не watchdog-артефакт.
- **Минимум (вывод):** `status.json`: сессия, `run_id`, фаза, `heartbeat_seq`, `last_progress`,
  `next_due`, `terminal_reason`. Heartbeat — цикл отвечает; progress — ожидаемое изменение фазы.
  `waiting`/`paused` живы без игрового прогресса до своих дедлайнов. Измерять возраст heartbeat
  монотонно снаружи одной сессии, учитывать suspend. На run: исход, длительность, подтверждённые
  дельты, причина; на отказ: последние события, версии, снимок state (PNG только при наличии).
- **Минимум (вывод):** ограничить размер/возраст stdout, JSONL и артефактов. Для stdout
  [journal][journald]: `SystemMaxUse=` / `RuntimeMaxUse=`, `MaxRetentionSec=` ограничивают
  хранилище, не отдельный unit. Для файлов — ротация с переоткрытием; `copytruncate`
  допускает потерю записей между копированием и обрезанием ([logrotate][logrotate]).

### 5. Оповещение, pause и stop

- **Риск (вывод):** ошибка без оповещения обнаружится утром; stop без подтверждения
  не даёт понять, безопасно ли закрывать игру.
- **Наблюдение:** desktop GUI MAA дополняет [HTTP(S)-протокол][maa-remote]: `StopTask` инициирует
  остановку текущей задачи, `HeartBeat` сообщает её ID, не прогресс. [Copilot][maa-copilot] запускает
  JSON-сценарии; сайт обмена ими — не панель управления. Есть [внешние уведомления][maa-notify].
  ALAS даёт [web UI с очередью, логом и Start/Stop][alas-ui], [`kill()` при ручном stop][alas-stop]
  и [push][alas-push]. FGA даёт [Pause/Resume][fga-pause] и [Stop из уведомления][fga-notify].
- **Минимум (вывод):** Qt-панели достаточно, tray необязателен. Раздельно показывать запрос
  и подтверждение `pause after run`/`resume`/`stop`; stop отменяет дальнейшее расписание.
  Сообщать о карантине, drift и цели, без дублей и блокировки recovery доставкой.
  [`notify-send`][notify-send] использует [D-Bus-сервис desktop-сессии][dbus]; вне неё опциональны
  аутентифицированный [ntfy][ntfy] или [Apprise][apprise]. Если нужен удалённый pause/stop —
  тот же локальный интерфейс через доверенный SSH; публичный listener не нужен.

### 6. Ограничители, профили, backup и update drift

- **Риск (вывод):** рестарт не исправляет ошибочную покупку, порчу ручного профиля или несовместимый API.
- **Наблюдение:** ALAS откладывает кампанию ниже порога oil и [отключает её по лимиту проходов][alas-budget],
  использует [именованные конфиги][alas-profile] и [worker'ы][alas-stop]. AutoTrimps [сравнивает версию мода
  и опционально сохраняет игру перед reload][at-version], но не проверяет совместимость API игры.
- **Минимум (вывод):** бюджет и резерв на профиль/период, проверка до трат, kill switch
  без autorestart, отдельный каталог данных для тестового профиля. [`flock`][flock] на стабильном
  lock-файле на время жизни игры: блокировка advisory, все launcher'ы должны её уважать.
  Перед сменой билда/профиля — backup остановленного профиля, несколько поколений, restore на копии;
  для БД есть [SQLite Backup API][sqlite-backup]. До мутаций сверять fingerprints игры/патча
  и версию интерфейса; при drift блокировать автозапуск до smoke на копии.

### 7. Конфиг: проверка, режимы, безопасное применение

- **Риск (вывод):** частично применённая правка меняет условия на ходу; тихий fallback снимает лимит.
- **Наблюдение:** MAA [валидирует JSON/параметры при постановке и обновляет задачу по ID][maa-queue];
  ALAS [проверяет изменения в ожидании][alas-wait] и [перечитывает при переключении][alas-switch].
  AutoTrimps имеет [именованные профили настроек в `localStorage`][at-profiles] и
  [live-правки по universe][at-settings], не изоляцию игровых сейвов.
- **Минимум (вывод):** версия схемы, типы/диапазоны/enum и зависимые поля, пресеты по режиму.
  Фиксировать цельную валидную ревизию на run. Hot reload — на следующем run/в idle;
  невалидную правку отклонить с причиной и сохранить последний валидный снимок.

### 8. Испытания: smoke, soak, fault injection, replay

- **Риск (вывод):** один успешный забег не выявляет долгий stall, двойной settlement и сбои записи.
- **Наблюдение:** MAA [гоняет smoke и сохраняет debug в CI][maa-smoke]; ALAS тестирует
  [коллизии сроков/повторов][alas-test] и [сохранённые кадры][alas-fixture]; FGA —
  [round-trip и отказ на JSON не-объекте][fga-test]. Это не доказательство soak или replay игры.
  Пример fault injection из runtime — [SQLite с симуляцией сбоев записи][sqlite-test].
- **Минимум (вывод):** smoke на копии: run → подтверждённый итог → штатный stop.
  Soak длиной с целевую AFK-сессию: зависания, память, диск, награда/час. Инъекции:
  `SIGSTOP` (watchdog), `SIGKILL` до/после коммита (recovery), отказ записи (fail closed),
  скачок часов/suspend (окна), несовместимый билд (нет мутаций). Replay решений по записанным
  профилю, версиям, seed, событиям и времени; не обещать идентичную физику Godot.

## Что отделяет типичный бот от demo loop (ранг, вывод)

1. **Recover-or-stop:** различает зависание, отказ и штатный выход; backoff и карантин ([ALAS][alas-loop], [systemd][systemd-service]).
2. **Безопасный итог:** durable `run_id`, отсутствие дубликатов, `resume`/`abort`/сверка ([ALAS][alas-write], [SQLite][sqlite-atomic]).
3. **Защита профиля:** резерв, эксклюзивный писатель, отказ при drift ([ALAS][alas-budget], [flock][flock]).
4. **Полезная работа:** задачи с окнами и целями, приоритет на безопасной границе ([ALAS][alas-config], [MAA][maa-fight]).
5. **Видимость и override:** различимы idle/stall/failed, есть причина и stop ([MAA][maa-callback], [ALAS][alas-ui]).
6. **Испытанный recovery:** свойства выше проверены не только на happy path ([MAA][maa-smoke], [SQLite][sqlite-test]).

## С чем сравнить текущий Midgard (не аудит)

Уже есть [`flock`/SHA](../../farmer/run.sh#L25-L46), [backup/stop-файл](../../farmer/run.sh#L65-L86),
[stall и квоты](../../farmer/src/farmer.gd#L535-L582), [статус](../../farmer/src/farmer.gd#L2361-L2417)
и [JSONL](../../farmer/src/farmer.gd#L2246-L2254), [индикатор свежести в Qt](../../gui/src/backend.cpp#L238-L250),
[sandbox smoke](../../farmer/README.md#L44-L56). **Вывод:** начать сравнение с двух границ:
индикатор панели не заменяет внешний watchdog, а атомарный status не доказывает crash-safe settlement.

## Здесь не нужно (вывод)

- **Account farm, эмуляторы, ADB/MediaProjection:** игра локальная, клиентов не нужно размножать;
  переносить стоит изоляцию данных, не [Android-инфраструктуру][fga-service].
- **OCR/template matching:** [Godot state](../../farmer/src/farmer.gd#L2393-L2405) доступен напрямую;
  не нужен [скриншот как сенсор FGA][fga-loop], достаточно артефактов для диагностики.
- **Anti-detection/humanization:** нет сервера и античита. Также не нужны отдельный web-сервер
  и внешняя база метрик, пока локальная панель и файлы отвечают на операционные вопросы.

[maa-queue]: https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/bea205dca4730533c1d43c1fc46e778ef3975e84/src/MaaCore/Assistant.cpp#L317-L415
[maa-time]: https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/bea205dca4730533c1d43c1fc46e778ef3975e84/docs/en-us/manual/introduction/others.md#L47-L62
[maa-retry]: https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/bea205dca4730533c1d43c1fc46e778ef3975e84/src/MaaCore/Task/AbstractTask.cpp#L31-L61
[maa-fight]: https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/bea205dca4730533c1d43c1fc46e778ef3975e84/docs/en-us/manual/introduction/combat.md#L10-L39
[maa-remote]: https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/bea205dca4730533c1d43c1fc46e778ef3975e84/docs/en-us/protocol/remote-control-schema.md#L6-L88
[maa-copilot]: https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/bea205dca4730533c1d43c1fc46e778ef3975e84/docs/en-us/manual/introduction/copilot.md#L6-L36
[maa-notify]: https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/bea205dca4730533c1d43c1fc46e778ef3975e84/src/MaaWpfGui/Services/ExternalNotification/ExternalNotificationService.cs#L28-L89
[maa-callback]: https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/bea205dca4730533c1d43c1fc46e778ef3975e84/docs/en-us/protocol/callback-schema.md#L207-L238
[maa-log]: https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/bea205dca4730533c1d43c1fc46e778ef3975e84/src/MaaCore/Utils/Logger.hpp#L779-L801
[maa-smoke]: https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/bea205dca4730533c1d43c1fc46e778ef3975e84/.github/workflows/smoke-testing.yml#L105-L129
[alas-loop]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/alas.py#L553-L619
[alas-recover]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/alas.py#L65-L133
[alas-stuck]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/device/device.py#L234-L263
[alas-config]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/config/config.py#L204-L263
[alas-profile]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/config/config.py#L68-L126
[alas-delay]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/config/config.py#L381-L439
[alas-reset]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/config/utils.py#L387-L408
[alas-weekly]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/reward/reward.py#L189-L246
[alas-write]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/deploy/atomic.py#L172-L278
[alas-config-write]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/config/utils.py#L99-L118
[alas-budget]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/campaign/run.py#L69-L105
[alas-count]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/campaign/run.py#L442-L474
[alas-artifact]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/alas.py#L135-L163
[alas-ui]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/webui/app.py#L432-L481
[alas-stop]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/webui/process_manager.py#L28-L84
[alas-push]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/notify/notify.py#L14-L76
[alas-wait]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/alas.py#L470-L546
[alas-switch]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/module/config/config.py#L603-L632
[alas-test]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/tests/island/test_business_scheduling.py#L71-L126
[alas-fixture]: https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d01f18b05696a312dc88c5894f81f83fb6fd9478/tests/island/transport/test_transport_refresh_screenshots.py#L5-L31
[fga-battle]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/wiki/Battle.md#L28-L42
[fga-loop]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/scripts/src/main/java/io/github/fate_grand_automata/scripts/entrypoints/AutoBattle.kt#L176-L218
[fga-retry]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/scripts/src/main/java/io/github/fate_grand_automata/scripts/modules/ConnectionRetry.kt#L10-L21
[fga-service]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/app/src/main/java/io/github/fate_grand_automata/runner/ScriptRunnerService.kt#L61-L68
[fga-finally]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/scripts/src/main/java/io/github/fate_grand_automata/scripts/entrypoints/AutoBattle.kt#L98-L125
[fga-refill]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/scripts/src/main/java/io/github/fate_grand_automata/scripts/modules/Refill.kt#L18-L57
[fga-metrics]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/scripts/src/main/java/io/github/fate_grand_automata/scripts/entrypoints/AutoBattle.kt#L144-L173
[fga-shots]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/scripts/src/main/java/io/github/fate_grand_automata/scripts/modules/ScreenshotDrops.kt#L18-L41
[fga-pause]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/app/src/main/java/io/github/fate_grand_automata/ui/runner/ScriptRunnerUI.kt#L85-L125
[fga-notify]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/app/src/main/java/io/github/fate_grand_automata/runner/ScriptRunnerNotification.kt#L79-L115
[fga-test]: https://github.com/Fate-Grand-Automata/FGA/blob/c825c1aff4f4d0dc70e1af06efe9cf46ab9d0a28/prefs/src/test/java/io/github/fate_grand_automata/prefs/BattleConfigFileTest.kt#L13-L71
[at-readme]: https://github.com/SadAugust/AutoTrimps/blob/0cf73d429bfa9141a857cc5b060a13ee06400c09/README.md#L1-L14
[at-loop]: https://github.com/SadAugust/AutoTrimps/blob/0cf73d429bfa9141a857cc5b060a13ee06400c09/AutoTrimps2.js#L311-L456
[at-daily]: https://github.com/SadAugust/AutoTrimps/blob/0cf73d429bfa9141a857cc5b060a13ee06400c09/modules/portal.js#L475-L501
[at-threshold]: https://github.com/SadAugust/AutoTrimps/blob/0cf73d429bfa9141a857cc5b060a13ee06400c09/modules/portal.js#L73-L115
[at-portal]: https://github.com/SadAugust/AutoTrimps/blob/0cf73d429bfa9141a857cc5b060a13ee06400c09/modules/portal.js#L553-L574
[at-version]: https://github.com/SadAugust/AutoTrimps/blob/0cf73d429bfa9141a857cc5b060a13ee06400c09/AutoTrimps2.js#L537-L559
[at-profiles]: https://github.com/SadAugust/AutoTrimps/blob/0cf73d429bfa9141a857cc5b060a13ee06400c09/modules/import-export.js#L120-L174
[at-settings]: https://github.com/SadAugust/AutoTrimps/blob/0cf73d429bfa9141a857cc5b060a13ee06400c09/SettingsGUI.js#L5385-L5430
[systemd-service]: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
[systemd-unit]: https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html
[systemd-login]: https://www.freedesktop.org/software/systemd/man/latest/loginctl.html
[systemd-timer]: https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html
[journald]: https://www.freedesktop.org/software/systemd/man/latest/journald.conf.html
[flock]: https://man7.org/linux/man-pages/man2/flock.2.html
[rename]: https://man7.org/linux/man-pages/man2/rename.2.html
[fsync]: https://man7.org/linux/man-pages/man2/fsync.2.html
[logrotate]: https://github.com/logrotate/logrotate/blob/main/logrotate.8.in
[sqlite-atomic]: https://www.sqlite.org/atomiccommit.html
[sqlite-test]: https://www.sqlite.org/atomiccommit.html#_testing_atomic_commit_behavior
[sqlite-backup]: https://www.sqlite.org/backup.html
[notify-send]: https://gitlab.gnome.org/GNOME/libnotify/-/blob/master/tools/notify-send.c
[dbus]: https://specifications.freedesktop.org/notification-spec/latest/protocol.html
[ntfy]: https://docs.ntfy.sh/publish/
[apprise]: https://github.com/caronc/apprise
