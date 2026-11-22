"""Qt adapter for the file-backed session view model.

After editing the QML or the assets in window.qrc, run from the repository root:
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
                    if item.name not in ("history", "updates", "quarantine", "diagnostics"))


def _snapshot(view: SessionView) -> dict[str, Any]:
    return {**{name: getattr(view, name) for name in _AFK_FIELDS},
            "updates": asdict(view.updates), "quarantine": asdict(view.quarantine)}



class _Backend(QObject):
    changed = Signal()
    historyChanged = Signal()
    diagnosticsChanged = Signal()
    diagnosticsBusyChanged = Signal()

    def __init__(self, model: SessionModel, parent: QObject):
        super().__init__(parent)
        self._model = model
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="farm-window")
        self._diagnostics_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="farm-diagnostics")
        self._pending: deque[Future[SessionView]] = deque()
        self._diagnostics_job: Future[Callable[[], None]] | None = None
        self._diagnostics_refresh: Future[SessionView] | None = None
        executor, diagnostics_executor = self._executor, self._diagnostics_executor
        parent.destroyed.connect(lambda: executor.shutdown(wait=False))
        parent.destroyed.connect(lambda: diagnostics_executor.shutdown(wait=False))
        self._view = SessionView()
        self._snapshot = _snapshot(self._view)
        self._history = asdict(self._view.history)
        self._diagnostics = asdict(self._view.diagnostics)
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

    def _enqueue(self, action: Callable[[], object] | None = None) -> Future[SessionView]:
        model = self._model

        def sample() -> SessionView:
            if action is not None:
                action()
            return model.poll()

        future = self._executor.submit(sample)
        self._pending.append(future)
        if not self._completion.isActive():
            self._completion.start()
        return future

    def _publish(self) -> None:
        # Adopt diagnostics without waiting; the model worker still owns mutable model state.
        if self._diagnostics_job is not None and self._diagnostics_job.done():
            job, self._diagnostics_job = self._diagnostics_job, None
            try:
                self._diagnostics_refresh = self._enqueue(job.result())
            except Exception:
                logging.getLogger(__name__).exception("AFK diagnostics failed")
                self.diagnosticsBusyChanged.emit()
        while self._pending and self._pending[0].done():
            future = self._pending.popleft()
            try:
                view = future.result()
            except Exception:
                logging.getLogger(__name__).exception("AFK window refresh failed")
                view = replace(self._view, action_error="Could not refresh the AFK session.")
            if view != self._view:
                history_changed = view.history != self._view.history
                diagnostics_changed = view.diagnostics != self._view.diagnostics
                self._view = view
                self._snapshot = _snapshot(view)
                if history_changed:
                    self._history = asdict(view.history)
                    self.historyChanged.emit()
                if diagnostics_changed:
                    self._diagnostics = asdict(view.diagnostics)
                    self.diagnosticsChanged.emit()
                self.changed.emit()
            if future is self._diagnostics_refresh:
                self._diagnostics_refresh = None
                self.diagnosticsBusyChanged.emit()
        if not self._pending and self._diagnostics_job is None:
            self._completion.stop()

    @Property(dict, notify=changed)
    def snapshot(self) -> dict[str, Any]:
        return self._snapshot

    @Property(dict, notify=historyChanged)
    def history(self) -> dict[str, Any]:
        return self._history

    @Property(dict, notify=diagnosticsChanged)
    def diagnostics(self) -> dict[str, Any]:
        return self._diagnostics

    @Property(bool, notify=diagnosticsBusyChanged)
    def diagnosticsBusy(self) -> bool:
        return self._diagnostics_job is not None or self._diagnostics_refresh is not None

    def _run_diagnostics_job(self, action: Callable[[], Callable[[], None]]) -> None:
        if not self.diagnosticsBusy:
            self._diagnostics_job = self._diagnostics_executor.submit(action)
            if not self._completion.isActive():
                self._completion.start()
            self.diagnosticsBusyChanged.emit()

    @Slot()
    def runDiagnostics(self) -> None:
        self._run_diagnostics_job(self._model.run_diagnostics)

    @Slot()
    def repairFarmerPack(self) -> None:
        if self._view.diagnostics.can_repair:
            self._run_diagnostics_job(self._model.repair_farmer_pack)

    @Slot(int)
    def selectCharacter(self, index: int) -> None:
        self._enqueue(partial(self._model.select_character, index))

    @Slot(int)
    def selectPreset(self, index: int) -> None:
        self._enqueue(partial(self._model.select_preset, index))

    @Slot(int)
    def selectLocation(self, index: int) -> None:
        if 0 <= index < len(self._view.locations):
            location = self._view.locations[index]["id"]
            self._enqueue(partial(self._model.select_location, location))

    @Slot(int)
    def selectTowerFloor(self, floor: int) -> None:
        self._enqueue(partial(self._model.select_tower_floor, floor))

    @Slot(str)
    def selectDifficulty(self, level: str) -> None:
        self._enqueue(partial(self._model.select_difficulty, level))

    @Slot(str, int)
    def selectOath(self, oath_id: str, rank: int) -> None:
        self._enqueue(partial(self._model.select_oath, oath_id, rank))

    @Slot(str, bool)
    def setWishlisted(self, item_id: str, selected: bool) -> None:
        self._enqueue(partial(self._model.set_wishlisted, item_id, selected))

    @Slot(bool)
    def setKeepUnownedLegendaries(self, enabled: bool) -> None:
        self._enqueue(partial(self._model.set_keep_unowned_legendaries, enabled))

    @Slot(str, bool)
    def setMaintenance(self, name: str, enabled: bool) -> None:
        self._enqueue(partial(self._model.set_maintenance, name, enabled))

    @Slot(bool)
    def setShowGameWindow(self, enabled: bool) -> None:
        self._enqueue(partial(self._model.set_show_game_window, enabled))

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
    def checkAppUpdates(self) -> None:
        self._enqueue(self._model.check_app_updates)

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
