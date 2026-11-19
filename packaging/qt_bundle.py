"""Qt files used by Main.qml, Fusion (including Basic), and desktop backends."""

import re
from pathlib import PurePosixPath

_QT_LIBS = frozenset("""
    Core DBus Gui Network OpenGL Qml QmlCompiler QmlMeta QmlModels QmlWorkerScript
    Quick QuickLayouts QuickTemplates2 QuickControls2 QuickControls2Impl
    QuickControls2Basic QuickControls2BasicStyleImpl QuickControls2Fusion QuickControls2FusionStyleImpl
    Svg WaylandClient WlShellIntegration XcbQpa
""".lower().split())
_QT_LIBRARY = re.compile(r"(?:lib)?qt6([a-z0-9]+)(?:\.dll|\.so(?:\.\d+)*)$")
_QT_BINDINGS = frozenset("core dbus gui network opengl qml quick quickcontrols2".split())
_QML_DIRS = frozenset("""
    QtQml QtQml/Models QtQml/WorkerScript
    QtQuick QtQuick/Window QtQuick/Layouts QtQuick/Templates
    QtQuick/Controls QtQuick/Controls/impl QtQuick/Controls/Basic QtQuick/Controls/Fusion
    QtQuick/Controls/Basic/impl QtQuick/Controls/Fusion/impl
""".lower().split())
_PLATFORM_PLUGINS = frozenset("qoffscreen qxcb qwayland qwayland-egl qwindows".split())
_PLUGIN_DIRS = frozenset("""
    platforminputcontexts wayland-decoration-client wayland-graphics-integration-client
    wayland-shell-integration xcbglintegrations
""".split())


def keep_qt_file(destination: str) -> bool:
    """Accept a PyInstaller TOC destination (also relative to _internal at runtime)."""
    parts = PurePosixPath(destination.lower().replace("\\", "/")).parts
    name = parts[-1]
    if match := _QT_LIBRARY.fullmatch(name):
        return match[1] in _QT_LIBS
    if parts[0] != "pyside6":
        return True
    qt = parts[2:] if len(parts) > 1 and parts[1] == "qt" else parts[1:]
    if qt[0] == "qml":
        return ("/".join(qt[1:-1]) in _QML_DIRS
                or len(qt) == 2 and name in {"builtins.qmltypes", "jsroot.qmltypes"})
    if qt[0] == "plugins":
        if qt[1] == "platforms":
            return name.split(".", 1)[0].removeprefix("lib") in _PLATFORM_PLUGINS
        return qt[1] in _PLUGIN_DIRS
    if len(qt) == 1 and name.startswith("qt") and name.endswith((".so", ".pyd")):
        return name[2:].split(".", 1)[0] in _QT_BINDINGS
    return qt[0] not in {"libexec", "resources", "translations"}
