"""Shared UTC timestamps (bugs/023)."""

import datetime
from datetime import UTC

__all__ = ["now_iso"]


def now_iso() -> str:
    """Current UTC timestamp as an ISO string (spec §5.1)."""
    return datetime.datetime.now(UTC).isoformat(timespec="seconds")
