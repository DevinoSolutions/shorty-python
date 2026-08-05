"""``POST /v1/summaries`` — the dual 200/202 result and the three source shapes."""

from __future__ import annotations

import json

import httpx
import respx

from shorty_py import AsyncShorty, Shorty, SummaryAccepted, SummaryAlreadyComplete
from tests.conftest import BASE_URL, TEST_API_KEY

ALREADY_COMPLETE = {"status": "already_complete", "article_id": "a1b2c3d4"}
ACCEPTED = {
    "job_id": "j1b2c3d4",
    "status": "queued",
    "tracking_url": "/v1/jobs/j1b2c3d4",
}


@respx.mock(base_url=BASE_URL)
def test_a_200_means_the_summary_already_existed_and_no_job_was_started(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("/v1/summaries").mock(return_value=httpx.Response(200, json=ALREADY_COMPLETE))
    with Shorty(TEST_API_KEY) as client:
        result = client.summaries.create_from_youtube("https://youtu.be/dQw4w9WgXcQ")

    assert isinstance(result, SummaryAlreadyComplete)
    assert result.is_complete is True
    assert result.article_id == "a1b2c3d4"
    assert result.status == "already_complete"


@respx.mock(base_url=BASE_URL)
def test_a_202_means_a_job_was_queued_and_must_be_polled(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("/v1/summaries").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        result = client.summaries.create_from_url("https://example.com/post")

    assert isinstance(result, SummaryAccepted)
    assert result.is_complete is False
    assert result.job_id == "j1b2c3d4"
    assert result.tracking_url == "/v1/jobs/j1b2c3d4"


@respx.mock(base_url=BASE_URL)
def test_callers_can_branch_on_is_complete_without_knowing_the_type(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("/v1/summaries").mock(
        side_effect=[
            httpx.Response(200, json=ALREADY_COMPLETE),
            httpx.Response(202, json=ACCEPTED),
        ]
    )
    with Shorty(TEST_API_KEY) as client:
        assert client.summaries.create_from_text("hello world").is_complete is True
        assert client.summaries.create_from_text("hello world").is_complete is False


@respx.mock(base_url=BASE_URL)
def test_an_accepted_but_untrackable_job_keeps_the_article_id(respx_mock: respx.MockRouter) -> None:
    """job_id / tracking_url are nullable; article_id is the fallback handle."""
    respx_mock.post("/v1/summaries").mock(
        return_value=httpx.Response(
            202,
            json={
                "job_id": None,
                "status": "queued",
                "tracking_url": None,
                "article_id": "a9",
            },
        )
    )
    with Shorty(TEST_API_KEY) as client:
        result = client.summaries.create_from_text("some text")

    assert isinstance(result, SummaryAccepted)
    assert result.job_id is None
    assert result.tracking_url is None
    assert result.article_id == "a9"


@respx.mock(base_url=BASE_URL)
def test_the_youtube_constructor_emits_the_youtube_source_body(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/summaries").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        client.summaries.create_from_youtube("https://youtu.be/x", language="french")

    assert json.loads(route.calls.last.request.content) == {
        "source": "youtube",
        "url": "https://youtu.be/x",
        "language": "french",
    }


@respx.mock(base_url=BASE_URL)
def test_the_url_constructor_emits_the_url_source_body(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/summaries").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        client.summaries.create_from_url("https://example.com/blog/post")

    body = json.loads(route.calls.last.request.content)
    assert body == {"source": "url", "url": "https://example.com/blog/post"}
    assert "language" not in body, "an omitted language must not be sent as null"


@respx.mock(base_url=BASE_URL)
def test_the_text_constructor_emits_the_text_source_body_with_the_title_hint(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.post("/v1/summaries").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        client.summaries.create_from_text("Long text.", title="My note", language="en")

    assert json.loads(route.calls.last.request.content) == {
        "source": "text",
        "content": "Long text.",
        "title": "My note",
        "language": "en",
    }


@respx.mock(base_url=BASE_URL)
def test_the_generic_create_accepts_a_hand_built_body(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/summaries").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        client.summaries.create({"source": "youtube", "url": "https://youtu.be/y"})

    assert json.loads(route.calls.last.request.content)["source"] == "youtube"


@respx.mock(base_url=BASE_URL)
def test_a_replayed_summary_is_flagged(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("/v1/summaries").mock(
        return_value=httpx.Response(
            202, json=ACCEPTED, headers={"Idempotency-Replayed": "true"}
        )
    )
    with Shorty(TEST_API_KEY) as client:
        result = client.summaries.create_from_url("https://example.com")
    assert result.idempotency_replayed is True


@respx.mock(base_url=BASE_URL)
def test_a_202_body_that_still_says_already_complete_is_treated_as_complete(
    respx_mock: respx.MockRouter,
) -> None:
    """Belt and braces: discriminate by status first, then by the body's marker."""
    respx_mock.post("/v1/summaries").mock(return_value=httpx.Response(202, json=ALREADY_COMPLETE))
    with Shorty(TEST_API_KEY) as client:
        assert client.summaries.create_from_text("x").is_complete is True


@respx.mock(base_url=BASE_URL)
async def test_the_async_client_returns_the_same_discriminated_result(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("/v1/summaries").mock(
        side_effect=[
            httpx.Response(200, json=ALREADY_COMPLETE),
            httpx.Response(202, json=ACCEPTED),
        ]
    )
    async with AsyncShorty(TEST_API_KEY) as client:
        complete = await client.summaries.create_from_youtube("https://youtu.be/x")
        accepted = await client.summaries.create_from_text("text", title="t", language="en")

    assert isinstance(complete, SummaryAlreadyComplete)
    assert isinstance(accepted, SummaryAccepted)


@respx.mock(base_url=BASE_URL)
async def test_the_async_url_constructor_emits_the_url_source_body(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.post("/v1/summaries").mock(return_value=httpx.Response(202, json=ACCEPTED))
    async with AsyncShorty(TEST_API_KEY) as client:
        await client.summaries.create_from_url("https://example.com", language="es")
        await client.summaries.create({"source": "text", "content": "raw"})

    assert json.loads(route.calls[0].request.content)["source"] == "url"
    assert json.loads(route.calls[1].request.content)["content"] == "raw"
