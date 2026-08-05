"""Standard Webhooks v1 signature verification for RECEIVERS of Shorty webhooks.

Re-implemented from the server's ``src/lib/webhooks/signing.ts`` (not imported —
this ships to third parties). The semantics mirror it byte for byte::

    signed content = f"{webhook-id}.{webhook-timestamp}.{raw_body}"   (UTF-8)
    key            = base64-DECODED bytes of the secret AFTER the `whsec_` tag
    signature      = "v1," + base64(HMAC-SHA256(key, signed_content))

The ``webhook-signature`` header may carry several space-separated ``v1,``
tokens during a secret rotation — **any** match passes, and non-``v1,`` tokens
are ignored rather than rejected.

**RAW-BODY RULE (load-bearing):** verify the EXACT bytes you received. Parsing
the JSON and re-serializing it reorders keys and changes spacing, and WILL fail
verification. Pass the raw request body (``str`` or ``bytes``).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "DEFAULT_TOLERANCE_SECONDS",
    "WebhookVerifyFailure",
    "WebhookVerifyResult",
    "verify_webhook_signature",
]

_SECRET_PREFIX = "whsec_"
_SIGNATURE_VERSION = "v1"

#: Replay-window tolerance, in seconds (5 minutes) — matches the server.
DEFAULT_TOLERANCE_SECONDS = 300

#: Why verification failed. The last three mirror the server module exactly;
#: ``missing_headers`` is SDK-only (the SDK extracts headers the server takes as
#: separate arguments).
WebhookVerifyFailure = Literal[
    "missing_headers",
    "malformed_timestamp",
    "timestamp_out_of_tolerance",
    "no_matching_signature",
]


@dataclass(frozen=True, slots=True)
class WebhookVerifyResult:
    """A discriminated result, so receivers branch instead of catching.

    ``bool(result)`` is ``result.valid``, so ``if verify(...):`` reads naturally
    while ``result.reason`` stays available for logging the *why*.
    """

    valid: bool
    reason: WebhookVerifyFailure | None = None

    def __bool__(self) -> bool:
        return self.valid


def _header_value(headers: Mapping[str, Any] | Sequence[tuple[str, Any]], name: str) -> str | None:
    """Case-insensitive header lookup that also accepts a list of pairs."""
    items = headers.items() if isinstance(headers, Mapping) else headers
    target = name.lower()
    for key, value in items:
        if str(key).lower() != target:
            continue
        if isinstance(value, (list, tuple)):
            return None if not value else str(value[0])
        if value is None:
            return None
        return str(value)
    return None


def _hmac_digest(secret: str, content: bytes) -> bytes:
    raw = secret[len(_SECRET_PREFIX) :] if secret.startswith(_SECRET_PREFIX) else secret
    try:
        key = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError):
        key = raw.encode("utf-8")
    return hmac.new(key, content, hashlib.sha256).digest()


def verify_webhook_signature(
    *,
    payload: str | bytes | bytearray,
    headers: Mapping[str, Any] | Sequence[tuple[str, Any]],
    secret: str,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now_seconds: float | None = None,
) -> WebhookVerifyResult:
    """Verify a received Shorty webhook.

    :param payload: The RAW request body, exactly as received. Do not re-encode it.
    :param headers: The request headers (``webhook-id``, ``webhook-timestamp``,
        ``webhook-signature``). A dict, a ``Headers``-like mapping, or a list of
        pairs; lookup is case-insensitive.
    :param secret: The endpoint's signing secret (``whsec_...``).
    :param tolerance_seconds: Replay tolerance. Default 300 (5 minutes).
    :param now_seconds: "Now" in epoch seconds — injectable for tests.
    :returns: A :class:`WebhookVerifyResult`; never raises on a malformed input.
    """
    webhook_id = _header_value(headers, "webhook-id")
    timestamp_header = _header_value(headers, "webhook-timestamp")
    signature_header = _header_value(headers, "webhook-signature")

    if webhook_id is None or timestamp_header is None or signature_header is None:
        return WebhookVerifyResult(False, "missing_headers")

    try:
        timestamp = int(timestamp_header.strip())
    except (AttributeError, ValueError):
        return WebhookVerifyResult(False, "malformed_timestamp")

    now = time.time() if now_seconds is None else now_seconds
    if abs(now - timestamp) > tolerance_seconds:
        return WebhookVerifyResult(False, "timestamp_out_of_tolerance")

    raw_body = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    content = f"{webhook_id}.{timestamp}.".encode() + raw_body
    expected = _hmac_digest(secret, content)

    for token in signature_header.split(" "):
        version, comma, encoded = token.partition(",")
        if not comma or version != _SIGNATURE_VERSION:
            # Unknown versions (a future `v2,`) are ignored, not rejected.
            continue
        try:
            candidate = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            continue
        if len(candidate) != len(expected) or not candidate:
            continue
        if hmac.compare_digest(candidate, expected):
            return WebhookVerifyResult(True)

    return WebhookVerifyResult(False, "no_matching_signature")
