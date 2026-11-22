import re
import shutil
import subprocess
from pathlib import Path

import pytest

GUI_DIR = Path(__file__).resolve().parents[1] / "src/midgard_farm/gui"
TEXT_RESOURCES = [name for name in re.findall(r"<file>([^<]+)</file>", (GUI_DIR / "window.qrc").read_text())
                  if not name.endswith((".ttf", ".otf", ".png"))]


@pytest.mark.parametrize("name", TEXT_RESOURCES)
def test_bundled_text_resource_keeps_lf_on_windows_checkouts(name):
    # _resources.py embeds LF bytes; a CRLF checkout on Windows would no longer match its source.
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    path = f"src/midgard_farm/gui/{name}"
    result = subprocess.run(["git", "check-attr", "eol", "--", path], cwd=GUI_DIR.parents[2],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        pytest.skip("not a git checkout")
    assert result.stdout.strip() == f"{path}: eol: lf", f"add {path} to .gitattributes with text eol=lf"
