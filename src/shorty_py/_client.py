"""The ``Shorty`` and ``AsyncShorty`` clients.

The API key is passed straight into the transport, where a closure captures it.
It is never an attribute of the client, ``__repr__`` never prints it, and
pickling is refused outright — a serialized client is a secret at rest that
nobody asked for.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Any

import httpx

from ._transport import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    APIResponse,
    AsyncTransport,
    DebugSink,
    RequestSpec,
    SyncTransport,
    default_user_agent,
)
from ._version import __version__
from .resources.articles import ArticlesResource, AsyncArticlesResource
from .resources.jobs import AsyncJobsResource, JobsResource
from .resources.subtitles import AsyncSubtitlesResource, SubtitlesResource
from .resources.summaries import AsyncSummariesResource, SummariesResource
from .resources.transcriptions import AsyncTranscriptionsResource, TranscriptionsResource
from .resources.usage import AsyncUsageResource, UsageResource
from .types import RateLimit

__all__ = ["AsyncShorty", "Shorty"]

#: The environment variable both SDKs read.
API_KEY_ENV_VAR = "SHORTY_API_KEY"

_MISSING_KEY_MESSAGE = (
    "Missing Shorty API key. Pass Shorty(api_key='shk_live_...') or set the "
    f"{API_KEY_ENV_VAR} environment variable."
)


def _resolve_api_key(api_key: str | None) -> str:
    key = api_key if api_key is not None else os.environ.get(API_KEY_ENV_VAR)
    if not key:
        raise ValueError(_MISSING_KEY_MESSAGE)
    return key


def _resolve_debug(debug: bool | DebugSink | None) -> DebugSink | None:
    if debug is None or debug is False:
        return None
    if debug is True:

        def to_stderr(message: str) -> None:
            sys.stderr.write(f"[shorty] {message}\n")

        return to_stderr
    return debug


class _ClientBase:
    """Repr / pickle guards shared by both clients."""

    base_url: str

    def __repr__(self) -> str:
        # Deliberately minimal: anything more risks printing the key one day.
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    def __getstate__(self) -> Any:
        raise TypeError(
            f"{type(self).__name__} instances cannot be pickled or copied: doing so "
            "would write your API key to disk or across a process boundary. "
            "Construct a new client in the target process instead."
        )

    def __setstate__(self, state: Any) -> None:  # pragma: no cover - unreachable
        raise TypeError(f"{type(self).__name__} instances cannot be unpickled.")


class Shorty(_ClientBase):
    """Synchronous client for the Shorty ``/v1`` API.

    ::

        from shorty_py import Shorty

        with Shorty() as client:            # reads SHORTY_API_KEY
            usage = client.usage.get()
            print(usage.plan.tier)

    :param api_key: Your ``shk_live_...`` key. Falls back to ``SHORTY_API_KEY``;
        raises :class:`ValueError` if neither is set. OAuth 2.1 access tokens
        issued to connected apps are accepted on the same header, so they can be
        passed here unchanged.
    :param base_url: API origin. Paths already include ``/v1``.
    :param timeout: Per-attempt timeout in seconds (not per logical call).
    :param max_retries: Retries *after* the first attempt.
    :param debug: ``True`` logs method/path/status/attempt/request-id to stderr;
        a callable receives the same already-redacted strings. Headers and
        bodies are never logged.
    :param http_client: Bring your own :class:`httpx.Client` (proxies, mounts,
        custom transports). The SDK will not close a client it did not create.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        debug: bool | DebugSink | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._transport = SyncTransport(
            api_key=_resolve_api_key(api_key),
            base_url=self.base_url,
            user_agent=default_user_agent(__version__),
            timeout=timeout,
            max_retries=max_retries,
            debug=_resolve_debug(debug),
            http_client=http_client,
        )

        self.usage = UsageResource(self._transport)
        self.articles = ArticlesResource(self._transport)
        self.transcriptions = TranscriptionsResource(self._transport)
        self.summaries = SummariesResource(self._transport)
        self.subtitles = SubtitlesResource(self._transport)
        self.jobs = JobsResource(self._transport)

    @property
    def last_rate_limit(self) -> RateLimit | None:
        """Rate-limit signal from the most recent response, or ``None``.

        ``None`` is a normal outcome, not a bug: the server-side limiter is
        still being wired up, so some routes emit no rate-limit headers yet.
        """
        return self._transport.last_rate_limit

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
    ) -> APIResponse:
        """Raw escape hatch for paths this SDK version does not model yet.

        Same retry rules apply — in particular, a POST **without** an
        ``idempotency_key`` is never retried.
        """
        return self._transport.request(
            RequestSpec(
                method=method,
                path=path,
                query=query,
                body=body,
                headers=headers,
                idempotency_key=idempotency_key,
                timeout=timeout,
            )
        )

    def close(self) -> None:
        """Close the connection pool. A no-op for an injected ``http_client``."""
        self._transport.close()

    def __enter__(self) -> Shorty:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class AsyncShorty(_ClientBase):
    """Asynchronous client for the Shorty ``/v1`` API.

    ::

        from shorty_py import AsyncShorty

        async with AsyncShorty() as client:
            page = await client.articles.list(limit=50)
            async for article in page:
                print(article.title)

    Accepts the same arguments as :class:`Shorty`, with ``http_client`` taking
    an :class:`httpx.AsyncClient`.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        debug: bool | DebugSink | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._transport = AsyncTransport(
            api_key=_resolve_api_key(api_key),
            base_url=self.base_url,
            user_agent=default_user_agent(__version__),
            timeout=timeout,
            max_retries=max_retries,
            debug=_resolve_debug(debug),
            http_client=http_client,
        )

        self.usage = AsyncUsageResource(self._transport)
        self.articles = AsyncArticlesResource(self._transport)
        self.transcriptions = AsyncTranscriptionsResource(self._transport)
        self.summaries = AsyncSummariesResource(self._transport)
        self.subtitles = AsyncSubtitlesResource(self._transport)
        self.jobs = AsyncJobsResource(self._transport)

    @property
    def last_rate_limit(self) -> RateLimit | None:
        """Rate-limit signal from the most recent response, or ``None``."""
        return self._transport.last_rate_limit

    async def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
        timeout: float | None = None,
    ) -> APIResponse:
        """Raw escape hatch. A POST without an ``idempotency_key`` is never retried."""
        return await self._transport.request(
            RequestSpec(
                method=method,
                path=path,
                query=query,
                body=body,
                headers=headers,
                idempotency_key=idempotency_key,
                timeout=timeout,
            )
        )

    async def aclose(self) -> None:
        """Close the connection pool. A no-op for an injected ``http_client``."""
        await self._transport.aclose()

    async def __aenter__(self) -> AsyncShorty:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
