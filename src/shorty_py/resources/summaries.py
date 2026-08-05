"""``client.summaries`` — start summarization jobs (youtube / url / text).

Two shapes make this the most ergonomically demanding operation in the API, and
both are handled here rather than pushed onto callers:

* The request body is a **3-branch ``oneOf`` with no ``discriminator``**, so the
  SDK ships three named constructors (:meth:`~SummariesResource.create_from_youtube`,
  ``create_from_url``, ``create_from_text``) alongside the generic ``create``.
* The response is **200 OR 202**. 200 means a cached summary already existed and
  no job was started; 202 means a job was queued. ``create`` returns a
  discriminated result — branch on ``.is_complete``, not on the type.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shorty_py._transport import APIResponse, RequestSpec
from shorty_py.types import SummaryAccepted, SummaryAlreadyComplete, SummaryResult

from ._base import UNSET, AsyncResource, SyncResource, as_mapping, resolve_idempotency_key


def _create_spec(
    *,
    body: Mapping[str, Any],
    idempotency_key: Any,
    timeout: float | None,
    headers: Mapping[str, str] | None,
) -> RequestSpec:
    return RequestSpec(
        method="POST",
        path="/v1/summaries",
        body=dict(body),
        idempotency_key=resolve_idempotency_key(idempotency_key),
        timeout=timeout,
        headers=headers,
    )


def _parse(response: APIResponse) -> SummaryResult:
    """Discriminate the 200/202 split by HTTP status, then by body shape."""
    payload = dict(as_mapping(response.data))
    payload["idempotency_replayed"] = response.idempotency_replayed
    already_complete = response.status_code == 200 or payload.get("status") == "already_complete"
    if already_complete:
        return SummaryAlreadyComplete.from_wire(payload)
    return SummaryAccepted.from_wire(payload)


def _youtube_body(url: str, language: str | None) -> dict[str, Any]:
    return _with_language({"source": "youtube", "url": url}, language)


def _url_body(url: str, language: str | None) -> dict[str, Any]:
    return _with_language({"source": "url", "url": url}, language)


def _text_body(content: str, title: str | None, language: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"source": "text", "content": content}
    if title is not None:
        body["title"] = title
    return _with_language(body, language)


def _with_language(body: dict[str, Any], language: str | None) -> dict[str, Any]:
    if language is not None:
        body["language"] = language
    return body


class SummariesResource(SyncResource):
    """Requires the ``articles:write`` scope."""

    def create(
        self,
        body: Mapping[str, Any],
        *,
        idempotency_key: str | None = UNSET,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> SummaryResult:
        """``POST /v1/summaries`` — operation ``createSummary``.

        ``body`` is discriminated on ``source``::

            {"source": "youtube", "url": "https://youtu.be/..."}
            {"source": "url",     "url": "https://example.com/post"}
            {"source": "text",    "content": "..."}

        Returns :class:`~shorty_py.types.SummaryAlreadyComplete` (HTTP 200, a
        cache hit — read it at ``client.articles.get(result.article_id)``) or
        :class:`~shorty_py.types.SummaryAccepted` (HTTP 202, a queued job).
        Branch on ``result.is_complete``.
        """
        response = self._transport.request(
            _create_spec(
                body=body, idempotency_key=idempotency_key, timeout=timeout, headers=headers
            )
        )
        return _parse(response)

    def create_from_youtube(
        self, url: str, *, language: str | None = None, **options: Any
    ) -> SummaryResult:
        """Summarize a YouTube video. Shorthand for ``source="youtube"``."""
        return self.create(_youtube_body(url, language), **options)

    def create_from_url(
        self, url: str, *, language: str | None = None, **options: Any
    ) -> SummaryResult:
        """Summarize a web page or article. Shorthand for ``source="url"``."""
        return self.create(_url_body(url, language), **options)

    def create_from_text(
        self,
        content: str,
        *,
        title: str | None = None,
        language: str | None = None,
        **options: Any,
    ) -> SummaryResult:
        """Summarize raw text. Shorthand for ``source="text"``."""
        return self.create(_text_body(content, title, language), **options)


class AsyncSummariesResource(AsyncResource):
    """Requires the ``articles:write`` scope."""

    async def create(
        self,
        body: Mapping[str, Any],
        *,
        idempotency_key: str | None = UNSET,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> SummaryResult:
        """``POST /v1/summaries`` — operation ``createSummary``."""
        response = await self._transport.request(
            _create_spec(
                body=body, idempotency_key=idempotency_key, timeout=timeout, headers=headers
            )
        )
        return _parse(response)

    async def create_from_youtube(
        self, url: str, *, language: str | None = None, **options: Any
    ) -> SummaryResult:
        """Summarize a YouTube video. Shorthand for ``source="youtube"``."""
        return await self.create(_youtube_body(url, language), **options)

    async def create_from_url(
        self, url: str, *, language: str | None = None, **options: Any
    ) -> SummaryResult:
        """Summarize a web page or article. Shorthand for ``source="url"``."""
        return await self.create(_url_body(url, language), **options)

    async def create_from_text(
        self,
        content: str,
        *,
        title: str | None = None,
        language: str | None = None,
        **options: Any,
    ) -> SummaryResult:
        """Summarize raw text. Shorthand for ``source="text"``."""
        return await self.create(_text_body(content, title, language), **options)
