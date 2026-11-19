"""Render the Linux user unit, including on hosts without systemd."""

from collections.abc import Sequence

from . import check_argv

UNIT_NAME = "midgard-farm.service"

_UNIT = """\
[Unit]
Description=Midgard Farm background service
StartLimitIntervalSec=1h
StartLimitBurst=3

[Service]
Type=simple
ExecStart={exec_start}
EnvironmentFile=-%h/.config/midgard-farmer.env
Restart=on-failure
RestartSec=30
RestartPreventExitStatus=2 75
# Signal only the service first so it can ask the game to finish and flush.
KillMode=mixed
TimeoutStopSec=90

[Install]
WantedBy=default.target
"""


def _quote(arg: str) -> str:
    arg = arg.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return '"' + arg.replace("%", "%%").replace("$", "$$") + '"'


def render_unit(argv: Sequence[str]) -> str:
    command = check_argv(argv)
    if not command:
        raise ValueError("service command is empty")
    return _UNIT.format(exec_start=" ".join(map(_quote, command)))
