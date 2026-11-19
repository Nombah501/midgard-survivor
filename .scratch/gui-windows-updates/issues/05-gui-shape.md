# 05: What the operator sees

Type: prototype
Status: resolved
Blocked by: none

## Question

What screens and actions does the GUI have, if it is the operator's only interface?

Candidates:
- status of the current AFK: phase, run, heartbeat, rewards/hour;
- the night's results (like `tools/summary.py`);
- choosing a character and preset, start and stop (finish/abort/pause/resume);
- game update / app update: what was noticed, what the app did itself, what it asks of the operator;
- quarantine and its cause.

Make a cheap clickable mock (independent of the stack) and react to it together. Answer: the list of screens and actions, the mock linked as an asset.

## Prep

Откройте [интерактивный макет](file:///home/n501/orca/projects/midgard-prototype-gui-shape/gui/prototype-gui-shape.html) двойным щелчком или вставьте в адресную строку браузера абсолютный путь `/home/n501/orca/projects/midgard-prototype-gui-shape/gui/prototype-gui-shape.html`. Интернет и игра не нужны. Макет и [снимок Chromium](file:///home/n501/orca/projects/midgard-prototype-gui-shape/gui/prototype-gui-shape.png) сохранены в локальной ветке `prototype/gui-shape`, коммит `4b48a1a307`.

Выбирайте сценарии справа и нажимайте выделенные кнопки действий по порядку: «Пауза и финиш», «Запуск и прерывание», «Обновление игры», «Обновление приложения», «Утро после сбоя». В сценарии запуска смените персонажа и сравните обычный пресет с фиксированным. В свободной пробе можно отдельно провалить проверочный забег после обновления игры. Цифры условные; окно макета не управляет реальной AFK-сессией.

Вопросы для реакции (те же пометки видны на экранах):

1. Что важнее при первом взгляде: фаза и последнее подтверждение жизни или доход и текущий забег?
2. Хватает ли персонажа и пресета? Где менять локацию и сложность, и можно ли переопределять фиксированный пресет?
3. Различаются ли «Пауза», «Завершить» и «Прервать»? Какое подтверждение нужно для прерывания?
4. Хватает ли последних итогов и дохода за час в забегах, или нужна история и сравнение персонажей и пресетов?
5. Хватает ли пояснения, что именно обнаружено и сделано после обновления игры? Понятно ли, когда нужно открыть саму игру?
6. Когда устанавливать обновление приложения: автоматически после сессии или только по согласию оператора?
7. Какое следующее действие нужно в карантине и какой объём диагностики показывать сразу?

После обсуждения запишите в `## Answer`, какие экраны и действия войдут в спецификацию и какие варианты отклонены.

## Answer

Operator reaction to the mock, 2026-11-19. Every recommendation accepted. Mock: branch `prototype/gui-shape`, commit `4b48a1a307`, `gui/prototype-gui-shape.html` (primary source, not merged).

**Four screens, no settings screen:**

1. **AFK session.**
   - Top: phase and the last heartbeat (is it alive). One line below: income and the current run.
   - Before start: character and preset only. Location and difficulty belong to the preset; the window picks a preset and never edits one. The default is the last one picked.
   - Buttons: Start, Pause↔Resume, Finish, Abort (ADR 0004). Only Abort asks for confirmation, in one dialog that names the loss ("the current run settles, keep is skipped").
   - When Start is refused, the reason shows here, including "game not found" (the app finds the game path itself).
2. **History.** One line per session, interleaved with update events ("Game update 0.2.3 → 0.2.4 handled", 06 Q11). The last night expands to its totals. Comparing characters and presets stays in the fog (Night history).
3. **Updates.**
   - Game update: one of the four states and one of the four outcomes from 06. "Open the game" appears only for a Game reinstall.
   - App update: its part is decided by 07.
   - The mock runs the smoke *after* install; 06 Q6 runs it *before*, in the sandbox. The spec follows 06.
4. **Quarantine.**
   - Shown at once: the reason, one line from `quarantine.json`, and one next-action button. It reads "Check again" for `build_failed` / `anchors_broken` / `smoke_failed` and "Start a new session" otherwise.
   - Collapsed: the attempts and the log paths.

Notification settings stay in the fog (Notifications). The mock's question "when to install an App update" moved to 07.
