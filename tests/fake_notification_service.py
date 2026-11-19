"""Run the real service with only desktop notification delivery intercepted."""

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from midgard_farm import platform, service
from midgard_farm.core.launch import shutdown_request


@contextmanager
def fixture_shutdown_request():
    # Keep POSIX signal coverage while Windows can request the same graceful
    # shutdown without terminating the process between outcome and notification.
    with shutdown_request() as signalled_at:
        if not (filename := os.environ.get("FAKE_SERVICE_STOP")):
            yield signalled_at
            return
        stop = Path(filename)
        requested_at = None

        def requested():
            nonlocal requested_at
            if requested_at is None and stop.exists():
                requested_at = time.monotonic()
            return signalled_at() or requested_at

        yield requested


def main():
    os_ = platform.current()
    policy = service.Policy(**json.loads(os.environ.get("FAKE_SERVICE_POLICY", "{}")))
    with (patch.object(type(os_), "notify_desktop", autospec=True),
          patch.object(service, "shutdown_request", fixture_shutdown_request)):
        return service.main(policy=policy)


if __name__ == "__main__":
    raise SystemExit(main())
