"""``client.articles`` — list, search, and fetch summarized articles."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote

from shorty_py._pagination import AsyncPage, Page
from shorty_py._transport import RequestSpec
from shorty_py.types import Article, ArticleDetail, ArticleListResponse, ArticleSearchResponse

from ._base import AsyncResource, SyncResource, as_mapping


def _list_spec(
    *,
    limit: int | None,
    cursor: str | None,
    timeout: float | None,
    headers: Mapping[str, str] | None,
) -> RequestSpec:
    return RequestSpec(
        method="GET",
        path="/v1/articles",
        query={"limit": limit, "cursor": cursor},
        timeout=timeout,
        headers=headers,
    )


def _search_spec(
    *,
    q: str,
    limit: int | None,
    article_type: str | None,
    timeout: float | None,
    headers: Mapping[str, str] | None,
) -> RequestSpec:
    return RequestSpec(
        method="GET",
        path="/v1/articles/search",
        query={"q": q, "limit": limit, "article_type": article_type},
        timeout=timeout,
        headers=headers,
    )


def _get_spec(
    *, article_id: str, timeout: float | None, headers: Mapping[str, str] | None
) -> RequestSpec:
    return RequestSpec(
        method="GET",
        path=f"/v1/articles/{quote(article_id, safe='')}",
        timeout=timeout,
        headers=headers,
    )


class ArticlesResource(SyncResource):
    """Requires the ``articles:read`` scope."""

    def list(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Page[Article]:
        """``GET /v1/articles`` — operation ``listArticles``. Cursor-paginated.

        Walk every article with ``page.auto_paging_iter()``; the original
        ``limit`` is reused on every follow-up request.
        """

        def fetch(next_cursor: str | None) -> Page[Article]:
            response = self._transport.request(
                _list_spec(limit=limit, cursor=next_cursor, timeout=timeout, headers=headers)
            )
            envelope = ArticleListResponse.from_wire(as_mapping(response.data))
            return Page(
                data=envelope.data,
                has_more=envelope.has_more,
                next_cursor=envelope.next_cursor,
                fetch_next=fetch,
            )

        return fetch(cursor)

    def search(
        self,
        q: str,
        *,
        limit: int | None = None,
        article_type: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ArticleSearchResponse:
        """``GET /v1/articles/search`` — operation ``searchArticles``.

        Relevance-ranked and ``limit``-capped, **not** cursor-paginated: this
        returns a plain response object, not a :class:`~shorty_py.Page`.
        """
        response = self._transport.request(
            _search_spec(
                q=q,
                limit=limit,
                article_type=article_type,
                timeout=timeout,
                headers=headers,
            )
        )
        return ArticleSearchResponse.from_wire(as_mapping(response.data))

    def get(
        self,
        article_id: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ArticleDetail:
        """``GET /v1/articles/{articleId}`` — operation ``getArticle``."""
        response = self._transport.request(
            _get_spec(article_id=article_id, timeout=timeout, headers=headers)
        )
        return ArticleDetail.from_wire(as_mapping(response.data))


class AsyncArticlesResource(AsyncResource):
    """Requires the ``articles:read`` scope."""

    async def list(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncPage[Article]:
        """``GET /v1/articles`` — operation ``listArticles``. Cursor-paginated."""

        async def fetch(next_cursor: str | None) -> AsyncPage[Article]:
            response = await self._transport.request(
                _list_spec(limit=limit, cursor=next_cursor, timeout=timeout, headers=headers)
            )
            envelope = ArticleListResponse.from_wire(as_mapping(response.data))
            return AsyncPage(
                data=envelope.data,
                has_more=envelope.has_more,
                next_cursor=envelope.next_cursor,
                fetch_next=fetch,
            )

        return await fetch(cursor)

    async def search(
        self,
        q: str,
        *,
        limit: int | None = None,
        article_type: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ArticleSearchResponse:
        """``GET /v1/articles/search`` — operation ``searchArticles``."""
        response = await self._transport.request(
            _search_spec(
                q=q,
                limit=limit,
                article_type=article_type,
                timeout=timeout,
                headers=headers,
            )
        )
        return ArticleSearchResponse.from_wire(as_mapping(response.data))

    async def get(
        self,
        article_id: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ArticleDetail:
        """``GET /v1/articles/{articleId}`` — operation ``getArticle``."""
        response = await self._transport.request(
            _get_spec(article_id=article_id, timeout=timeout, headers=headers)
        )
        return ArticleDetail.from_wire(as_mapping(response.data))
