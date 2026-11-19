"""Window bootloader entry point with a bounded QML smoke mode."""

import json
import sys
from pathlib import Path

from midgard_farm import gui


def smoke_test(report: Path) -> int:
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication

    from midgard_farm.gui.model import SessionModel
    from midgard_farm.gui.window import load_window
    from midgard_farm.platform import current

    app = QGuiApplication([sys.argv[0]])
    messages: list[str] = []

    def capture(level, context, message):
        if level in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            messages.append(message)

    previous = qInstallMessageHandler(capture)
    try:
        model = SessionModel(current())
        view = model.poll()
        engine = load_window(model)
        app.processEvents()
        loaded = bool(engine.rootObjects())
    finally:
        qInstallMessageHandler(previous)
    report.write_text(json.dumps({"loaded": loaded, "messages": messages, "presets": view.presets,
                                  "characters": view.characters, "version": view.updates.app_version}),
                      encoding="utf-8")
    return 0 if loaded and not messages else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        raise SystemExit(smoke_test(Path(sys.argv[2])))
    raise SystemExit(gui.main())
