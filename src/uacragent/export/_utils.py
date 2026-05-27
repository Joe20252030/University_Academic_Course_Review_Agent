from __future__ import annotations

from datetime import datetime, timezone


def safe_timestamp() -> str:
    """Return a filename-safe UTC timestamp (no colons, consistent across timezones).

    Includes microseconds so that two exports triggered within the same second
    (e.g. two rapid export calls in a test or a batch pipeline) always produce
    unique filenames without requiring a collision-avoidance loop.
    """
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S_%f")
