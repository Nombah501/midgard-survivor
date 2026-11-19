"""Mechanical architecture rules, checked on the source instead of in review.

- The OS is decided only behind the platform seam (ADR 0006).
- Bundled files are found only through `midgard_farm.assets`, never relative to
  a module's own location (that breaks in the frozen build).
- The service side never loads Qt: the Windows service is windowless and its
  build excludes PySide6.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "midgard_farm"
SOURCES = sorted(PACKAGE.rglob("*.py"))
OS_PROBES = {("sys", "platform"), ("os", "name")}
QT_FREE = ("core", "service.py", "platform", "verify")


def module_name(path: Path) -> str:
    parts = ["midgard_farm", *path.relative_to(PACKAGE).with_suffix("").parts]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imported_modules(path: Path, tree: ast.AST) -> set[str]:
    package = module_name(path) if path.name == "__init__.py" else module_name(path).rpartition(".")[0]
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                prefix = ".".join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module or ""
            found.add(prefix)
            found.update(f"{prefix}.{alias.name}" for alias in node.names)
    return found


def parsed(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def label(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def test_the_rules_see_the_sources():
    assert len(SOURCES) > 20
    assert module_name(PACKAGE / "core" / "launch.py") == "midgard_farm.core.launch"
    window = PACKAGE / "gui" / "window.py"
    assert any(name.startswith("PySide6") for name in imported_modules(window, parsed(window)))
    supervisor = PACKAGE / "core" / "supervisor.py"
    assert "midgard_farm.core.launch" in imported_modules(supervisor, parsed(supervisor))


@pytest.mark.parametrize("path", SOURCES, ids=label)
def test_os_is_decided_only_behind_the_platform_seam(path):
    if path.relative_to(PACKAGE).parts[0] == "platform":
        return
    probes = [
        f"{label(path)}:{node.lineno} {node.value.id}.{node.attr}"
        for node in ast.walk(parsed(path))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and (node.value.id, node.attr) in OS_PROBES
    ]
    assert not probes, f"{probes}: ask the platform (e.g. Platform.release_os) instead"


@pytest.mark.parametrize("path", SOURCES, ids=label)
def test_files_are_located_only_through_assets(path):
    if label(path) == "assets.py":
        return
    uses = [
        f"{label(path)}:{node.lineno}"
        for node in ast.walk(parsed(path))
        if isinstance(node, ast.Name) and node.id == "__file__"
    ]
    assert not uses, f"{uses}: resolve bundled files with midgard_farm.assets"


@pytest.mark.parametrize(
    "path", [p for p in SOURCES if label(p).split("/")[0] in QT_FREE], ids=label)
def test_service_side_never_loads_qt(path):
    qt = sorted(
        name for name in imported_modules(path, parsed(path))
        if name.split(".")[0] == "PySide6" or name.startswith("midgard_farm.gui")
    )
    assert not qt, f"{label(path)} imports {qt}"
