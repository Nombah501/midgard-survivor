"""Qt adapter for the file-backed session view model.

After editing Main.qml, run from the repository root:
    pyside6-rcc --format-version 1 --compress-algo zlib -o src/midgard_farm/gui/_resources.py src/midgard_farm/gui/window.qrc
"""

import logging
import sys
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, replace
from functools import partial
from typing import Any, cast

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ..core.commands import Control
from ..platform import current
from . import _resources  # noqa: F401  # Qt registers the embedded QML on import.
from .model import SessionModel, SessionView


class _Backend(QObject):
    changed = Signal()

    def __init__(self, model: SessionModel, parent: QObject):
        super().__init__(parent)
        self._model = model
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="farm-window")
        self._pending: deque[Future[SessionView]] = deque()
        executor = self._executor
        parent.destroyed.connect(lambda: executor.shutdown(wait=False))
        self._view = SessionView()
        self._snapshot = asdict(self._view)
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
                self._view = view
                self._snapshot = asdict(view)
                self.changed.emit()
        if not self._pending:
            self._completion.stop()

    @Property(dict, notify=changed)
    def snapshot(self) -> dict[str, Any]:
        return self._snapshot

    @Slot(int)
    def selectCharacter(self, index: int) -> None:
        self._enqueue(partial(self._model.select_character, index))

    @Slot(int)
    def selectPreset(self, index: int) -> None:
        self._enqueue(partial(self._model.select_preset, index))

    @Slot()
    def start(self) -> None:
        self._enqueue(self._model.start)

    @Slot(str, str)
    def control(self, action: str, session_id: str) -> None:
        if action in ("pause", "resume", "finish", "abort"):
            self._enqueue(partial(self._model.control, cast(Control, action), session_id=session_id))

    @Slot()
    def startService(self) -> None:
        self._enqueue(self._model.start_service)


def load_window(model: SessionModel) -> QQmlApplicationEngine:
    if sys.platform == "linux" and QQuickStyle.name() != "Fusion":
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
