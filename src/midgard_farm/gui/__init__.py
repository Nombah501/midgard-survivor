"""Midgard Farm's optional desktop window; the service never imports Qt."""


def main() -> int:
    from .window import main as run_window

    return run_window()
