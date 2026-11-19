"""Run the real service with only desktop notification delivery intercepted."""

import json
import os
from unittest.mock import patch

from midgard_farm import platform, service


def main():
    os_ = platform.current()
    policy = service.Policy(**json.loads(os.environ.get("FAKE_SERVICE_POLICY", "{}")))
    with patch.object(type(os_), "notify_desktop", autospec=True):
        return service.main(policy=policy)


if __name__ == "__main__":
    raise SystemExit(main())
