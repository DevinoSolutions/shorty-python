"""Pure retry-delay math.

Factored out of the transport so the caps are unit-testable without waiting on a
real clock. Constants are identical to ``shorty-sdk/src/core/retryPolicy.ts``.
"""

from __future__ import annotations

import email.utils
import random
import time
from collections.abc import Callable

#: Full-jitter exponential backoff cap, in seconds.
BACKOFF_CAP_SECONDS = 8.0
#: A ``Retry-After`` is honored but never blocks longer than this, in seconds.
RETRY_AFTER_CAP_SECONDS = 60.0


def full_jitter_backoff(attempt: int, rand: Callable[[], float] = random.random) -> float:
    """Full-jitter backoff for a 0-based ``attempt`` index, in seconds.

    A uniform draw in ``[0, min(0.5 * 2**attempt, 8))`` seconds. ``rand`` is
    injectable so tests can pin the draw.
    """
    cap = min(0.5 * (2**attempt), BACKOFF_CAP_SECONDS)
    return rand() * cap


def capped_retry_after(seconds: float) -> float:
    """Clamp a ``Retry-After`` delay to the 60-second ceiling."""
    return min(seconds, RETRY_AFTER_CAP_SECONDS)


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Parse a ``Retry-After`` header value into seconds.

    Accepts both forms the RFC allows: delta-seconds (``"12"``) and an HTTP-date
    (``"Wed, 21 Oct 2026 07:28:00 GMT"``). Returns ``None`` when the value is
    absent or unparseable — never raises.
    """
    if value is None:
        return None
    trimmed = value.strip()
    if trimmed == "":
        return None
    try:
        return max(0.0, float(trimmed))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(trimmed)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    reference = time.time() if now is None else now
    return max(0.0, parsed.timestamp() - reference)
