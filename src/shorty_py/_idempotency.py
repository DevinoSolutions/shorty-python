"""``Idempotency-Key`` generation for the three ``/v1`` create operations.

A UUID v4, generated **once per logical call** and reused across every retry
attempt of that call, so a retried POST is deduplicated by the server's
idempotency ledger instead of starting a second billable job.
"""

from __future__ import annotations

import uuid

#: The server accepts 1–255 visible ASCII characters.
MAX_IDEMPOTENCY_KEY_LENGTH = 255


def new_idempotency_key() -> str:
    """Return a fresh UUID v4 idempotency key."""
    return str(uuid.uuid4())


def validate_idempotency_key(key: str) -> str:
    """Validate a caller-supplied key against the server's constraints.

    Raises :class:`ValueError` locally rather than letting the server reject the
    write with a 400 after the round trip.
    """
    if not key:
        raise ValueError("idempotency_key must be a non-empty string.")
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError(
            f"idempotency_key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters "
            f"(got {len(key)})."
        )
    if any(not (0x21 <= ord(ch) <= 0x7E) for ch in key):
        raise ValueError("idempotency_key must contain only visible ASCII characters (0x21-0x7E).")
    return key
