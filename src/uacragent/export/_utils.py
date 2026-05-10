from __future__ import annotations

from datetime import datetime


def safe_timestamp() -> str:
    """Return a filename-safe local timestamp (no colons, works on Windows)."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
