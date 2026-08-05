"""The request / retry / backoff engine — the money path.

Retry policy (kept identical to ``shorty-sdk/src/core/http.ts``):

* **Retryable:** connection errors · per-attempt timeout · 408 · 429
  ``rate_limited`` (or a 429 with no parseable code) · 500 / 502 / 503 / 504.
* **Never:** 429 ``quota_exhausted`` · any other 4xx.
* **POST is retried ONLY when it carries an ``Idempotency-Key``** — the same key
  on every attempt. The SDK generates one for every write, so writes are
  retry-safe by default; passing ``idempotency_key=None`` opts out of both.
* **Delay:** ``Retry-After`` honored (delta-seconds *and* HTTP-date, capped at
  60 s); otherwise full-jitter backoff ``random(0, min(0.5 * 2**attempt, 8))``
  seconds.
* **Timeout is per attempt**, not per logical call.

The API key lives in a **closure** captured by the transport, never as a plain
attribute, so a ``vars()`` dump or an accidental ``json.dumps`` of the client
cannot surface it.
"""

from __future__ import annotations

import asyncio
import random
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from ._redaction import redact
from ._retry import capped_retry_after, full_jitter_backoff
from .errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    QuotaExhaustedError,
    RateLimitError,
    create_api_error,
)
from .types import RateLimit

DEFAULT_BASE_URL = "https://aishorty.com"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2

_RETRYABLE_STATUSES = frozenset({408, 500, 502, 503, 504})

DebugSink = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class RequestSpec:
    """One logical HTTP call, before any attempt is made."""

    method: str
    path: str
    query: Mapping[str, Any] | None = None
    body: Any = None
    headers: Mapping[str, str] | None = None
    #: ``None`` means "no key" — which also means a POST will not be retried.
    idempotency_key: str | None = None
    #: Per-attempt timeout override, in seconds.
    timeout: float | None = None


@dataclass(frozen=True, slots=True)
class APIResponse:
    """A successful response plus the metadata callers routinely need."""

    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict)
    #: The decoded JSON body, or ``None`` for an empty body.
    data: Any = None
    #: Quote this in support tickets.
    request_id: str | None = None
    rate_limit: RateLimit | None = None
    #: ``True`` when the server replayed a stored response for this
    #: ``Idempotency-Key`` instead of performing the write again.
    idempotency_replayed: bool = False


def _sf_params(value: str) -> tuple[str | None, dict[str, str]]:
    """Read one IETF draft-11 structured-field item: ``"name";k=v;k=v``.

    A deliberately small hand-rolled reader — the two headers Shorty emits are
    a single sf-string with integer parameters, which does not justify a
    structured-fields dependency.
    """
    parts = [p.strip() for p in value.split(";")]
    if not parts:
        return None, {}
    name = parts[0].strip().strip('"') or None
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, _, raw = part.partition("=")
        params[key.strip()] = raw.strip().strip('"')
    return name, params


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_rate_limit(headers: Mapping[str, str]) -> RateLimit | None:
    """Parse the draft-11 and legacy rate-limit headers into a :class:`RateLimit`.

    Returns ``None`` when the response carried none of them — which is the
    current state of play for some routes, so callers (and the prod smoke test)
    must treat rate-limit data as *conditional*.
    """
    hdrs = {k.lower(): v for k, v in headers.items()}
    policy = hdrs.get("ratelimit-policy")
    live = hdrs.get("ratelimit")
    legacy_limit = hdrs.get("x-ratelimit-limit")
    legacy_remaining = hdrs.get("x-ratelimit-remaining")
    legacy_reset = hdrs.get("x-ratelimit-reset")

    if not any([policy, live, legacy_limit, legacy_remaining, legacy_reset]):
        return None

    name: str | None = None
    limit = remaining = reset_seconds = window_seconds = None

    if policy:
        name, params = _sf_params(policy)
        limit = _as_int(params.get("q"))
        window_seconds = _as_int(params.get("w"))
    if live:
        live_name, params = _sf_params(live)
        name = name or live_name
        remaining = _as_int(params.get("r"))
        reset_seconds = _as_int(params.get("t"))

    return RateLimit(
        name=name,
        limit=limit if limit is not None else _as_int(legacy_limit),
        remaining=remaining if remaining is not None else _as_int(legacy_remaining),
        reset_seconds=reset_seconds,
        reset_at=_as_int(legacy_reset),
        window_seconds=window_seconds,
    )


class _BaseTransport:
    """Everything the sync and async transports share: no I/O lives here."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        user_agent: str,
        timeout: float,
        max_retries: int,
        debug: DebugSink | None,
        rand: Callable[[], float] = random.random,
    ):
        # The key is captured by this closure and never stored as an attribute.
        def authorization() -> str:
            return f"Bearer {api_key}"

        self._authorization = authorization
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries
        self._debug = debug
        self._rand = rand
        #: Rate-limit signal from the most recent response (success or failure).
        self.last_rate_limit: RateLimit | None = None

    # -- request shaping ---------------------------------------------------

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _build_query(query: Mapping[str, Any] | None) -> dict[str, str]:
        params: dict[str, str] = {}
        for key, value in (query or {}).items():
            if value is None:
                continue
            if isinstance(value, bool):
                params[key] = "true" if value else "false"
            else:
                params[key] = str(value)
        return params

    def _build_headers(self, spec: RequestSpec) -> dict[str, str]:
        headers = {
            "Authorization": self._authorization(),
            "Accept": "application/json",
            "User-Agent": self.user_agent,
            # Twin for environments that forbid overriding User-Agent.
            "X-Shorty-SDK": self.user_agent,
        }
        if spec.body is not None:
            headers["Content-Type"] = "application/json"
        if spec.idempotency_key is not None:
            headers["Idempotency-Key"] = spec.idempotency_key
        for key, value in (spec.headers or {}).items():
            headers[key] = value
        return headers

    # -- response handling -------------------------------------------------

    def _handle(self, spec: RequestSpec, response: httpx.Response, attempt: int) -> APIResponse:
        headers = {k.lower(): v for k, v in response.headers.items()}
        rate_limit = parse_rate_limit(headers)
        self.last_rate_limit = rate_limit
        request_id = headers.get("request-id")

        if response.is_success:
            self._log(spec, str(response.status_code), attempt, request_id)
            return APIResponse(
                status_code=response.status_code,
                headers=headers,
                data=_decode_json(response),
                request_id=request_id,
                rate_limit=rate_limit,
                idempotency_replayed=headers.get("idempotency-replayed", "").lower() == "true",
            )

        body = _decode_json(response)
        error = create_api_error(
            status=response.status_code,
            body=body,
            headers=headers,
            raw_text=None if isinstance(body, Mapping) else _safe_text(response),
            rate_limit=rate_limit,
        )
        self._log(spec, f"{response.status_code} {error.code or ''}".strip(), attempt, request_id)
        raise error

    # -- retry decisions ---------------------------------------------------

    def _should_retry(self, exc: BaseException, spec: RequestSpec, attempt: int) -> bool:
        if attempt >= self.max_retries:
            return False
        # A POST is only replay-safe when the server can deduplicate it.
        if spec.method.upper() == "POST" and spec.idempotency_key is None:
            return False
        if isinstance(exc, QuotaExhaustedError):
            return False  # a blown quota is a hard stop, never a retry storm
        if isinstance(exc, RateLimitError):
            return True
        if isinstance(exc, APIError):
            return exc.status in _RETRYABLE_STATUSES
        # Transport failures (connect reset, DNS, per-attempt timeout).
        return isinstance(exc, APIConnectionError)

    def _delay_for(self, exc: BaseException, attempt: int) -> float:
        if isinstance(exc, APIError) and exc.retry_after is not None:
            return capped_retry_after(exc.retry_after)
        return full_jitter_backoff(attempt, self._rand)

    # -- logging -----------------------------------------------------------

    def _log(
        self, spec: RequestSpec, outcome: str, attempt: int, request_id: str | None = None
    ) -> None:
        if self._debug is None:
            return
        suffix = f" req={request_id}" if request_id else ""
        self._debug(redact(f"{spec.method} {spec.path} -> {outcome} [attempt {attempt}]{suffix}"))

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"


class SyncTransport(_BaseTransport):
    """Blocking transport over a single pooled :class:`httpx.Client`."""

    def __init__(self, *, http_client: httpx.Client | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=self.timeout)

    def request(self, spec: RequestSpec) -> APIResponse:
        attempt = 0
        while True:
            try:
                return self._attempt(spec, attempt)
            except Exception as exc:
                if not self._should_retry(exc, spec, attempt):
                    raise
                delay = self._delay_for(exc, attempt)
                self._log(spec, f"retry in {delay:.3f}s", attempt)
                time.sleep(delay)
                attempt += 1

    def _attempt(self, spec: RequestSpec, attempt: int) -> APIResponse:
        try:
            response = self._client.request(
                spec.method,
                self._build_url(spec.path),
                params=self._build_query(spec.query),
                json=spec.body,
                headers=self._build_headers(spec),
                timeout=spec.timeout if spec.timeout is not None else self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise APITimeoutError() from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError("Connection error.", cause=exc) from exc
        return self._handle(spec, response, attempt)

    def close(self) -> None:
        """Close the underlying connection pool (no-op for an injected client)."""
        if self._owns_client:
            self._client.close()


class AsyncTransport(_BaseTransport):
    """Async transport over a single pooled :class:`httpx.AsyncClient`."""

    def __init__(self, *, http_client: httpx.AsyncClient | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=self.timeout)

    async def request(self, spec: RequestSpec) -> APIResponse:
        attempt = 0
        while True:
            try:
                return await self._attempt(spec, attempt)
            except Exception as exc:
                if not self._should_retry(exc, spec, attempt):
                    raise
                delay = self._delay_for(exc, attempt)
                self._log(spec, f"retry in {delay:.3f}s", attempt)
                await asyncio.sleep(delay)
                attempt += 1

    async def _attempt(self, spec: RequestSpec, attempt: int) -> APIResponse:
        try:
            response = await self._client.request(
                spec.method,
                self._build_url(spec.path),
                params=self._build_query(spec.query),
                json=spec.body,
                headers=self._build_headers(spec),
                timeout=spec.timeout if spec.timeout is not None else self.timeout,
            )
        except httpx.TimeoutException as exc:
            raise APITimeoutError() from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError("Connection error.", cause=exc) from exc
        return self._handle(spec, response, attempt)

    async def aclose(self) -> None:
        """Close the underlying connection pool (no-op for an injected client)."""
        if self._owns_client:
            await self._client.aclose()


def default_user_agent(version: str) -> str:
    """``shorty-py/<sdk> python/<runtime>`` — mirrors the TS SDK's UA shape."""
    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return f"shorty-py/{version} python/{py}"


def _decode_json(response: httpx.Response) -> Any:
    try:
        text = response.text
    except Exception:  # a body we cannot read is not fatal
        return None
    if text is None or text.strip() == "":
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _safe_text(response: httpx.Response) -> str | None:
    try:
        return response.text
    except Exception:
        return None
