"""Shared plumbing for the resource namespaces.

Each operation is expressed once as a :class:`~shorty_py._transport.RequestSpec`
builder plus a pure parse function; the sync and async resource classes differ
only by an ``await``. That is what keeps shipping two clients from doubling the
surface area (PRD B7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shorty_py._idempotency import new_idempotency_key, validate_idempotency_key
from shorty_py._transport import AsyncTransport, SyncTransport

#: Sentinel meaning "the caller did not pass an idempotency key", which is
#: distinct from explicitly passing ``None`` (opt out of idempotency entirely).
UNSET: Any = object()


class SyncResource:
    """Base for every ``client.<resource>`` namespace."""

    __slots__ = ("_transport",)

    def __init__(self, transport: SyncTransport):
        self._transport = transport


class AsyncResource:
    """Base for every ``aclient.<resource>`` namespace."""

    __slots__ = ("_transport",)

    def __init__(self, transport: AsyncTransport):
        self._transport = transport


def resolve_idempotency_key(key: Any) -> str | None:
    """Turn the caller's ``idempotency_key`` argument into a header value.

    * omitted  -> a fresh UUID v4, so the write is retry-safe by default
    * ``None`` -> no header, and the transport will never retry the POST
    * a string -> validated against the server's 1–255 visible-ASCII rule
    """
    if key is UNSET:
        return new_idempotency_key()
    if key is None:
        return None
    return validate_idempotency_key(str(key))


def as_mapping(data: Any) -> Mapping[str, Any]:
    """Coerce a decoded body to a mapping so ``from_wire`` never sees ``None``."""
    return data if isinstance(data, Mapping) else {}
