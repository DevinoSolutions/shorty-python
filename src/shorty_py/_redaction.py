"""Secret redaction for anything the SDK might emit.

The API key and webhook signing secrets must NEVER reach a log sink or a thrown
error verbatim. :func:`redact` is applied at every emit point (debug log lines,
error messages, non-JSON body snippets), not just once at the boundary.

Mirrors ``shorty-sdk/src/core/redaction.ts`` so both SDKs mask identically.
"""

from __future__ import annotations

import re

# shk_live_… / shk_test_… API keys.
_API_KEY_PATTERN = re.compile(r"shk_(live|test)_[A-Za-z0-9]+")
# whsec_… webhook signing secrets.
_WEBHOOK_SECRET_PATTERN = re.compile(r"whsec_[A-Za-z0-9+/=_-]+")
# `Bearer <token>` in any header dump — mask the token, keep the scheme.
_BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def redact(value: str) -> str:
    """Mask every known secret shape in ``value``.

    Idempotent and safe to call on any user- or server-provided text before it
    is logged or attached to an exception.
    """
    # Bearer first: masking the key shape first would leave the pattern's tail
    # unmatched and produce a doubly-masked `Bearer ******`.
    masked = _BEARER_PATTERN.sub(r"\1***", value)
    masked = _API_KEY_PATTERN.sub(lambda m: f"shk_{m.group(1)}_***", masked)
    return _WEBHOOK_SECRET_PATTERN.sub("whsec_***", masked)
