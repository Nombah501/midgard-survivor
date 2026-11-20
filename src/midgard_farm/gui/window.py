"""Qt adapter for the file-backed session view model.

After editing Main.qml, run from the repository root:
    pyside6-rcc --format-version 1 --compress-algo zlib -o src/midgard_farm/gui/_resources.py src/midgard_farm/gui/window.qrc
"""

import logging
import sys
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, fields, replace
from functools import partial
from typing import Any, cast

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ..core.commands import Control, PatchCommand
from ..platform import current
from . import _resources  # noqa: F401  # Qt registers the embedded QML on import.
from .model import SessionModel, SessionView

_AFK_FIELDS = tuple(item.name for item in fields(SessionView)
                    if item.name not in ("history", "updates", "quarantine"))


def _snapshot(view: SessionView) -> dict[str, Any]:
    return {**{name: getattr(view, name) for name in _AFK_FIELDS},
            "updates": asdict(view.updates), "quarantine": asdict(view.quarantine)}



class _Backend(QObject):
    changed = Signal()
    historyChanged = Signal()

    def __init__(self, model: SessionModel, parent: QObject):
        super().__init__(parent)
        self._model = model
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="farm-window")
        self._pending: deque[Future[SessionView]] = deque()
        executor = self._executor
        parent.destroyed.connect(lambda: executor.shutdown(wait=False))
        self._view = SessionView()
        self._snapshot = _snapshot(self._view)
        self._history = asdict(self._view.history)
        self._completion = QTimer(self)
        self._completion.setInterval(25)
        self._completion.timeout.connect(self._publish)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._poll()

    def _poll(self) -> None:
        if not self._pending:
            self._enqueue()

    def _enqueue(self, action: Callable[[], object] | None = None) -> None:
        model = self._model

        def sample() -> SessionView:
            if action is not None:
                action()
            return model.poll()

        self._pending.append(self._executor.submit(sample))
        if not self._completion.isActive():
            self._completion.start()

    def _publish(self) -> None:
        # Read only completed futures; all model I/O and actions are serialized on the worker.
        while self._pending and self._pending[0].done():
            try:
                view = self._pending.popleft().result()
            except Exception:
                logging.getLogger(__name__).exception("AFK window refresh failed")
                view = replace(self._view, action_error="Could not refresh the AFK session.")
            if view != self._view:
                history_changed = view.history != self._view.history
                self._view = view
                self._snapshot = _snapshot(view)
                if history_changed:
                    self._history = asdict(view.history)
                    self.historyChanged.emit()
                self.changed.emit()
        if not self._pending:
            self._completion.stop()

    @Property(dict, notify=changed)
    def snapshot(self) -> dict[str, Any]:
        return self._snapshot

    @Property(dict, notify=historyChanged)
    def history(self) -> dict[str, Any]:
        return self._history

    @Slot(int)
    def selectCharacter(self, index: int) -> None:
        self._enqueue(partial(self._model.select_character, index))

    @Slot(int)
    def selectPreset(self, index: int) -> None:
        self._enqueue(partial(self._model.select_preset, index))

    @Slot(str)
    def selectLocation(self, location: str) -> None:
        self._enqueue(partial(self._model.select_location, location or None))

    @Slot(str)
    def selectDifficulty(self, level: str) -> None:
        self._enqueue(partial(self._model.select_difficulty, level))

    @Slot(str, int)
    def selectOath(self, oath_id: str, rank: int) -> None:
        self._enqueue(partial(self._model.select_oath, oath_id, rank))

    @Slot(str, bool)
    def setWishlisted(self, item_id: str, selected: bool) -> None:
        self._enqueue(partial(self._model.set_wishlisted, item_id, selected))

    @Slot(str, bool)
    def setMaintenance(self, name: str, enabled: bool) -> None:
        self._enqueue(partial(self._model.set_maintenance, name, enabled))

    @Slot()
    def start(self) -> None:
        self._enqueue(self._model.start)

    @Slot(str, str)
    def control(self, action: str, session_id: str) -> None:
        if action in ("pause", "resume", "finish", "abort"):
            self._enqueue(partial(self._model.control, cast(Control, action), session_id=session_id))

    @Slot(str)
    def patchCommand(self, action: str) -> None:
        if action in ("check_again", "restore_official"):
            self._enqueue(partial(self._model.patch_command, cast(PatchCommand, action)))

    @Slot()
    def rollbackApp(self) -> None:
        self._enqueue(self._model.rollback_app)

    @Slot()
    def startService(self) -> None:
        self._enqueue(self._model.start_service)


def load_window(model: SessionModel) -> QQmlApplicationEngine:
    if QQuickStyle.name() != "Fusion":
        QQuickStyle.setStyle("Fusion")
    engine = QQmlApplicationEngine()
    backend = _Backend(model, engine)
    engine.setInitialProperties({"backend": backend})
    engine.load(QUrl("qrc:/midgard-farm/Main.qml"))
    return engine


def main() -> int:
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Midgard Farm")
    app.setDesktopFileName("midgard-farm")
    engine = load_window(SessionModel(current()))
    return app.exec() if engine.rootObjects() else 1
