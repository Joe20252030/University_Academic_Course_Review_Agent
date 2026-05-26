from __future__ import annotations

from datetime import datetime, timezone


def safe_timestamp() -> str:
    """Return a filename-safe UTC timestamp (no colons, consistent across timezones)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
