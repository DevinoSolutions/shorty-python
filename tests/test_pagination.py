"""Cursor pagination: page walking, termination, and sync/async equivalence."""

from __future__ import annotations

import httpx
import respx

from shorty_py import AsyncShorty, Shorty
from tests.conftest import BASE_URL, TEST_API_KEY


def _article(article_id: str) -> dict[str, object]:
    return {
        "id": article_id,
        "title": f"Article {article_id}",
        "description": None,
        "article_type": "YOUTUBE_ARTICLE",
        "source_url": "https://youtu.be/x",
        "created_at": "2026-07-20T12:00:00.000Z",
    }


PAGE_ONE = {"data": [_article("a1"), _article("a2")], "has_more": True, "next_cursor": "cur_2"}
PAGE_TWO = {"data": [_article("a3")], "has_more": False, "next_cursor": None}


@respx.mock(base_url=BASE_URL)
def test_a_single_page_is_iterable_and_sized(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/articles").mock(return_value=httpx.Response(200, json=PAGE_TWO))
    with Shorty(TEST_API_KEY) as client:
        page = client.articles.list(limit=10)

    assert len(page) == 1
    assert [a.id for a in page] == ["a3"]
    assert page.has_more is False
    assert page.next_cursor is None
    assert page.next_page() is None
    assert "Page(rows=1, has_more=False)" == repr(page)


@respx.mock(base_url=BASE_URL)
def test_auto_paging_walks_every_row_across_pages_in_order(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/articles").mock(
        side_effect=[httpx.Response(200, json=PAGE_ONE), httpx.Response(200, json=PAGE_TWO)]
    )
    with Shorty(TEST_API_KEY) as client:
        page = client.articles.list(limit=2)
        collected = [article.id for article in page.auto_paging_iter()]

    assert collected == ["a1", "a2", "a3"]
    assert route.call_count == 2


@respx.mock(base_url=BASE_URL)
def test_paging_reuses_the_original_filters_and_only_advances_the_cursor(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get("/v1/articles").mock(
        side_effect=[httpx.Response(200, json=PAGE_ONE), httpx.Response(200, json=PAGE_TWO)]
    )
    with Shorty(TEST_API_KEY) as client:
        list(client.articles.list(limit=2).auto_paging_iter())

    first, second = route.calls
    assert "cursor" not in first.request.url.params
    assert first.request.url.params["limit"] == "2"
    # The cursor is filter-bound server-side, so `limit` must be carried over.
    assert second.request.url.params["cursor"] == "cur_2"
    assert second.request.url.params["limit"] == "2"


@respx.mock(base_url=BASE_URL)
def test_an_explicit_next_page_walk_terminates_on_has_more_false(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/articles").mock(
        side_effect=[httpx.Response(200, json=PAGE_ONE), httpx.Response(200, json=PAGE_TWO)]
    )
    with Shorty(TEST_API_KEY) as client:
        page = client.articles.list()
        seen: list[str] = []
        walked = 0
        current = page
        while current is not None:
            seen.extend(a.id for a in current.data)
            current = current.next_page()
            walked += 1

    assert seen == ["a1", "a2", "a3"]
    assert walked == 2


@respx.mock(base_url=BASE_URL)
def test_a_null_next_cursor_terminates_even_when_has_more_is_true(
    respx_mock: respx.MockRouter,
) -> None:
    """Defensive: a truthy has_more with no cursor must not loop forever."""
    respx_mock.get("/v1/articles").mock(
        return_value=httpx.Response(
            200, json={"data": [_article("a1")], "has_more": True, "next_cursor": None}
        )
    )
    with Shorty(TEST_API_KEY) as client:
        page = client.articles.list()
        assert page.next_page() is None
        assert [a.id for a in page.auto_paging_iter()] == ["a1"]


@respx.mock(base_url=BASE_URL)
def test_an_empty_page_is_falsy_so_while_page_loops_terminate(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/articles").mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False, "next_cursor": None})
    )
    with Shorty(TEST_API_KEY) as client:
        assert not client.articles.list()


@respx.mock(base_url=BASE_URL)
def test_transcriptions_are_paginated_the_same_way(respx_mock: respx.MockRouter) -> None:
    row = {
        "id": "t1",
        "status": "SUCCESS",
        "progress": 100,
        "model_type": "whisper",
        "language": "english",
        "input_file": "a.mp3",
        "error": None,
        "created_at": "2026-07-20T12:00:00.000Z",
    }
    respx_mock.get("/v1/transcriptions").mock(
        side_effect=[
            httpx.Response(200, json={"data": [row], "has_more": True, "next_cursor": "c2"}),
            httpx.Response(200, json={"data": [], "has_more": False, "next_cursor": None}),
        ]
    )
    with Shorty(TEST_API_KEY) as client:
        rows = list(client.transcriptions.list(limit=1).auto_paging_iter())

    assert [t.id for t in rows] == ["t1"]
    assert rows[0].status == "SUCCESS"


@respx.mock(base_url=BASE_URL)
async def test_the_async_page_yields_the_same_rows_as_the_sync_page(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/articles").mock(
        side_effect=[httpx.Response(200, json=PAGE_ONE), httpx.Response(200, json=PAGE_TWO)]
    )
    async with AsyncShorty(TEST_API_KEY) as client:
        page = await client.articles.list(limit=2)
        collected = [article.id async for article in page]

    assert collected == ["a1", "a2", "a3"]


@respx.mock(base_url=BASE_URL)
async def test_the_async_page_supports_explicit_next_page(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/articles").mock(
        side_effect=[httpx.Response(200, json=PAGE_ONE), httpx.Response(200, json=PAGE_TWO)]
    )
    async with AsyncShorty(TEST_API_KEY) as client:
        first = await client.articles.list()
        assert len(first) == 2
        second = await first.next_page()
        assert second is not None
        assert await second.next_page() is None
        assert repr(second) == "AsyncPage(rows=1, has_more=False)"


@respx.mock(base_url=BASE_URL)
def test_search_returns_a_plain_response_not_a_page(respx_mock: respx.MockRouter) -> None:
    """searchArticles is relevance-ranked and limit-capped — the server does not
    paginate it, so the SDK must not pretend otherwise."""
    route = respx_mock.get("/v1/articles/search").mock(
        return_value=httpx.Response(200, json={"data": [_article("a9")], "count": 1})
    )
    with Shorty(TEST_API_KEY) as client:
        result = client.articles.search("transformers", limit=5, article_type="YOUTUBE_ARTICLE")

    assert not hasattr(result, "next_page")
    assert result.count == 1
    assert result.data[0].id == "a9"
    params = route.calls.last.request.url.params
    assert params["q"] == "transformers"
    assert params["limit"] == "5"
    assert params["article_type"] == "YOUTUBE_ARTICLE"
