"""Best-effort desktop and ntfy delivery, independent of supervisor recovery."""

import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from ..platform import NotificationPriority, Platform

_EVENT_PRIORITY: dict[str, NotificationPriority] = {
    "fail": "normal",
    "quarantine": "normal",
    "stop": "normal",
    "goal": "normal",
    "game_update_handled": "low",
    "build_failed": "high",
    "anchors_broken": "high",
    "smoke_failed": "high",
    "app_update_rolled_back": "high",
    "token_rejected": "normal",
}
_NTFY_PRIORITY = {"low": "2", "normal": "3", "high": "4"}


class Notifier:
    def __init__(self, os_: Platform, ntfy_url: str = ""):
        self._os = os_
        self._url = ntfy_url
        self._lock = threading.Lock()
        self._pending: list[threading.Thread] = []

    def notify(self, event: str, message: str) -> None:
        """Enqueue a notification; only emit game_update_handled for unattended updates."""
        print(f"supervisor: notify {event}: {message}", flush=True)
        priority = _EVENT_PRIORITY.get(event, "normal")
        title = f"Midgard farmer: {event}"
        with self._lock:
            self._pending = [thread for thread in self._pending if thread.is_alive()]
            self._start("desktop", self._os.notify_desktop, title, message, priority)
            if self._url:
                self._start("ntfy", self._send_ntfy, title, message, priority)

    def _start(self, transport: str, send: Callable[[str, str, NotificationPriority], None],
               title: str, message: str, priority: NotificationPriority) -> None:
        def deliver() -> None:
            try:
                send(title, message, priority)
            except Exception as exc:
                # URLs (including topic names) and transport internals needn't appear in logs.
                detail = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
                print(f"supervisor: {transport} notification failed: {detail}", flush=True)

        thread = threading.Thread(target=deliver, daemon=True)
        try:
            thread.start()
        except RuntimeError as exc:
            print(f"supervisor: could not start {transport} notification: {exc}", flush=True)
        else:
            self._pending.append(thread)

    def _send_ntfy(self, title: str, message: str, priority: NotificationPriority) -> None:
        request = urllib.request.Request(self._url, data=message.encode(),
                                         headers={"Title": title, "Priority": _NTFY_PRIORITY[priority]})
        urllib.request.urlopen(request, timeout=10).close()

    def drain(self, timeout: float = 25.0) -> None:
        """Give all sends a shared shutdown budget, never waiting on them during recovery."""
        deadline = time.monotonic() + timeout
        with self._lock:
            pending = tuple(self._pending)
        for thread in pending:
            thread.join(max(0.0, deadline - time.monotonic()))
