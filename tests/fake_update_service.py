"""Run the service with fake game, GDRE and desktop notification transport."""

import importlib
import json
import os
import sys
import time
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from unittest.mock import patch

from midgard_farm import platform, service
from midgard_farm.core import game_update
from midgard_farm.core.farmer_patch import gdre

from fake_notification_service import fixture_shutdown_request


class FakeGamePlatform(type(platform.current())):
    game_exe_name = "midgard-update-fixture.exe" if sys.platform == "win32" else "midgard-update-fixture"

    def game_pids(self):
        if path := os.environ.get("FAKE_UPDATE_POLL_TRACE"):
            with open(path, "a", encoding="utf-8") as trace:
                print(time.monotonic(), file=trace)
        return {1} if Path(os.environ["FAKE_UPDATE_RUNNING"]).exists() else set()

    def check_network_isolation(self):
        return None

    def spawn_tree(self, argv, *, isolate_network=False, **kwargs):
        assert isolate_network and argv[0] == str(self.game_executable())
        tests = Path(__file__).parent
        if "FARMER_SESSION_ID" in kwargs["env"]:
            script = [str(tests / "fake_supervised_game.py")]
        else:
            script = [str(tests / "fake_update_tools.py"), "smoke"]
        return super().spawn_tree([sys.executable, *script, *argv[1:]], **kwargs)

    def notify_desktop(self, title, message, priority):
        with open(os.environ["FAKE_DESKTOP_TRACE"], "a", encoding="utf-8") as trace:
            print(json.dumps({"title": title, "priority": priority}), file=trace)


def main():
    command = (sys.executable, str(Path(__file__).with_name("fake_update_tools.py")), "gdre")
    sources = Path(os.environ["FAKE_FARMER_SOURCES"])
    policy = service.Policy(**json.loads(os.environ["FAKE_SERVICE_POLICY"]))
    with ExitStack() as stack:
        stack.enter_context(patch.object(service, "shutdown_request", fixture_shutdown_request))
        stack.enter_context(patch.object(platform, "current", return_value=FakeGamePlatform()))
        stack.enter_context(patch.object(gdre, "prepare", return_value=gdre.Gdre(command, "fake-update")))
        if grace := os.environ.get("FAKE_UPDATE_CLOSE_GRACE"):
            stack.enter_context(patch.object(game_update, "GameUpdatePipeline",
                                            partial(game_update.GameUpdatePipeline, close_grace_seconds=float(grace))))
        stack.enter_context(patch.object(importlib.import_module("midgard_farm.core.farmer_patch.build"),
                                        "_SOURCE_DIR", sources))
        return service.main(policy=policy)


if __name__ == "__main__":
    raise SystemExit(main())
