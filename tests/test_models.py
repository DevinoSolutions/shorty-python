"""Wire DTOs: exact field mirroring, forward compatibility, and rate-limit parsing."""

from __future__ import annotations

import httpx
import respx

from shorty_py import AsyncShorty, Shorty, parse_rate_limit
from shorty_py.types import Article, ArticleDetail, ProblemBody, UsageResponse
from tests.conftest import BASE_URL, TEST_API_KEY

USAGE_BODY = {
    "plan": {"tier": "pro", "planName": "Pro Annual"},
    "subscription": {
        "isSubscribed": True,
        "isProSubscriber": True,
        "isOnTrial": False,
        "trialEndsAt": None,
        "expiresAt": "2027-01-01T00:00:00.000Z",
        "willRenew": True,
    },
    "limits": {
        "transcription": {
            "maxUploadSizeGb": 5,
            "maxUploadSizeLabel": "5 GB",
            "realtimeMaxDurationMinutes": 120,
            "realtimeMaxDurationLabel": "2 hours",
        },
        "conversion": {
            "maxFileSizeMb": 500,
            "maxFileSizeLabel": "500 MB",
            "maxBatchItems": 20,
            "canUseManagedQueue": True,
            "dailyCloudQuota": None,
        },
    },
    "usage": {"cloudConversionsUsedLast24h": 3, "cloudConversionsRemaining": None},
}


@respx.mock(base_url=BASE_URL)
def test_usage_is_decoded_into_its_nested_camel_case_wire_shape(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/usage").mock(return_value=httpx.Response(200, json=USAGE_BODY))
    with Shorty(TEST_API_KEY) as client:
        usage = client.usage.get()

    assert usage.plan.tier == "pro"
    assert usage.plan.planName == "Pro Annual"
    assert usage.subscription.isProSubscriber is True
    assert usage.subscription.trialEndsAt is None
    assert usage.limits.transcription.maxUploadSizeLabel == "5 GB"
    assert usage.limits.conversion.dailyCloudQuota is None
    assert usage.usage.cloudConversionsUsedLast24h == 3


def test_a_model_never_raises_on_a_server_field_it_has_never_seen() -> None:
    """The server may add response fields at any time; that is not a client bug."""
    article = Article.from_wire(
        {"id": "a1", "title": "T", "shiny_new_field": {"nested": 1}, "another": [1, 2]}
    )
    assert article.id == "a1"
    assert article.extra["shiny_new_field"] == {"nested": 1}
    assert article.extra["another"] == [1, 2]


def test_a_model_tolerates_a_partial_payload_by_falling_back_to_defaults() -> None:
    article = Article.from_wire({"id": "a1"})
    assert article.title is None
    assert article.article_type == ""
    assert Article.from_wire(None).id == ""


def test_unknown_nested_usage_fields_land_in_the_extra_bag() -> None:
    usage = UsageResponse.from_wire({**USAGE_BODY, "beta_feature": True})
    assert usage.extra["beta_feature"] is True
    assert usage.plan.tier == "pro"


def test_an_unknown_plan_tier_is_carried_through_as_a_plain_string() -> None:
    """Enum-ish fields are plain strings so a new server tier never breaks a client."""
    usage = UsageResponse.from_wire({"plan": {"tier": "enterprise", "planName": "Enterprise"}})
    assert usage.plan.tier == "enterprise"


@respx.mock(base_url=BASE_URL)
def test_an_article_detail_decodes_its_nested_summary_parts(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/articles/a1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "a1",
                "title": "How transformers work",
                "description": "A primer.",
                "article_type": "YOUTUBE_ARTICLE",
                "source_url": "https://youtu.be/x",
                "created_at": "2026-07-20T12:00:00.000Z",
                "summary": {
                    "parts": [
                        {"title": "Intro", "content": "..."},
                        {"title": None, "content": "More."},
                    ]
                },
                "body_text": "Full transcript.",
            },
        )
    )
    with Shorty(TEST_API_KEY) as client:
        detail = client.articles.get("a1")

    assert detail.summary is not None
    assert len(detail.summary.parts) == 2
    assert detail.summary.parts[0].title == "Intro"
    assert detail.summary.parts[1].title is None
    assert detail.body_text == "Full transcript."


def test_an_article_detail_with_a_null_summary_stays_none() -> None:
    detail = ArticleDetail.from_wire({"id": "a1", "summary": None})
    assert detail.summary is None


def test_a_problem_body_decodes_its_field_errors() -> None:
    problem = ProblemBody.from_wire(
        {
            "type": "https://aishorty.com/docs/api/errors/validation_failed",
            "title": "Invalid request",
            "status": 400,
            "instance": "/v1/summaries",
            "code": "validation_failed",
            "request_id": "req_1",
            "errors": [{"pointer": "#/body/url", "code": "invalid_url", "message": "Bad URL."}],
            "unexpected": "ignored",
        }
    )
    assert problem.code == "validation_failed"
    assert problem.errors[0].message == "Bad URL."
    assert problem.extra["unexpected"] == "ignored"


def test_models_are_frozen_and_hashable_free_of_surprises() -> None:
    import dataclasses

    import pytest as _pytest

    article = Article.from_wire({"id": "a1"})
    with _pytest.raises(dataclasses.FrozenInstanceError):
        article.id = "a2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Rate-limit header parsing
# ---------------------------------------------------------------------------


def test_draft_11_structured_fields_are_parsed() -> None:
    rate_limit = parse_rate_limit(
        {
            "RateLimit-Policy": '"default";q=1000;w=60',
            "RateLimit": '"default";r=997;t=42',
        }
    )
    assert rate_limit is not None
    assert rate_limit.name == "default"
    assert rate_limit.limit == 1000
    assert rate_limit.window_seconds == 60
    assert rate_limit.remaining == 997
    assert rate_limit.reset_seconds == 42


def test_legacy_x_ratelimit_headers_are_parsed_when_draft_11_is_absent() -> None:
    rate_limit = parse_rate_limit(
        {
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "99",
            "X-RateLimit-Reset": "1793000000",
        }
    )
    assert rate_limit is not None
    assert rate_limit.limit == 100
    assert rate_limit.remaining == 99
    assert rate_limit.reset_at == 1793000000


def test_no_rate_limit_headers_means_none_not_an_empty_object() -> None:
    """Server-side limiting is not fully wired yet, so absence must be legible."""
    assert parse_rate_limit({"content-type": "application/json"}) is None


def test_malformed_rate_limit_values_degrade_to_none_fields() -> None:
    rate_limit = parse_rate_limit({"RateLimit": '"default";r=abc;t='})
    assert rate_limit is not None
    assert rate_limit.remaining is None
    assert rate_limit.reset_seconds is None


@respx.mock(base_url=BASE_URL)
def test_the_client_exposes_the_rate_limit_from_the_last_response(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/usage").mock(
        return_value=httpx.Response(
            200,
            json=USAGE_BODY,
            headers={
                "RateLimit-Policy": '"default";q=1000;w=60',
                "RateLimit": '"default";r=42;t=9',
            },
        )
    )
    with Shorty(TEST_API_KEY) as client:
        assert client.last_rate_limit is None
        client.usage.get()
        assert client.last_rate_limit is not None
        assert client.last_rate_limit.remaining == 42


@respx.mock(base_url=BASE_URL)
def test_a_rate_limit_error_carries_the_parsed_rate_limit(respx_mock: respx.MockRouter) -> None:
    import pytest as _pytest

    from shorty_py import RateLimitError

    respx_mock.get("/v1/usage").mock(
        return_value=httpx.Response(
            429,
            json={"code": "rate_limited", "title": "Slow down", "status": 429},
            headers={"RateLimit": '"default";r=0;t=30', "Retry-After": "30"},
        )
    )
    with Shorty(TEST_API_KEY, max_retries=0) as client, _pytest.raises(RateLimitError) as caught:
        client.usage.get()

    assert caught.value.rate_limit is not None
    assert caught.value.rate_limit.remaining == 0
    assert caught.value.retry_after == 30


@respx.mock(base_url=BASE_URL)
async def test_the_async_client_also_exposes_the_last_rate_limit(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/usage").mock(
        return_value=httpx.Response(200, json=USAGE_BODY, headers={"X-RateLimit-Remaining": "7"})
    )
    async with AsyncShorty(TEST_API_KEY) as client:
        await client.usage.get()
        assert client.last_rate_limit is not None
        assert client.last_rate_limit.remaining == 7


@respx.mock(base_url=BASE_URL)
def test_an_empty_body_decodes_to_none_rather_than_raising(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/usage").mock(return_value=httpx.Response(204))
    with Shorty(TEST_API_KEY) as client:
        assert client.usage.get().plan.tier == ""


@respx.mock(base_url=BASE_URL)
def test_a_non_json_success_body_decodes_to_none_rather_than_raising(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/usage").mock(return_value=httpx.Response(200, text="not json"))
    with Shorty(TEST_API_KEY) as client:
        assert client.usage.get().plan.planName == ""


@respx.mock(base_url=BASE_URL)
def test_a_transcription_detail_carries_its_output_text(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/transcriptions/t1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "t1",
                "status": "SUCCESS",
                "progress": 100,
                "model_type": "whisper-large",
                "language": "english",
                "input_file": "podcast.mp3",
                "error": None,
                "created_at": "2026-07-20T12:00:00.000Z",
                "output_text": "Hello and welcome.",
            },
        )
    )
    with Shorty(TEST_API_KEY) as client:
        detail = client.transcriptions.get("t1")

    assert detail.output_text == "Hello and welcome."
    assert detail.model_type == "whisper-large"


@respx.mock(base_url=BASE_URL)
def test_creating_a_transcription_returns_the_accepted_job(respx_mock: respx.MockRouter) -> None:
    import json

    route = respx_mock.post("/v1/transcriptions").mock(
        return_value=httpx.Response(
            202, json={"job_id": "j7", "status": "queued", "tracking_url": "/v1/jobs/j7"}
        )
    )
    with Shorty(TEST_API_KEY) as client:
        accepted = client.transcriptions.create(
            url="https://example.com/podcast.mp3", language="english"
        )

    assert accepted.job_id == "j7"
    assert accepted.tracking_url == "/v1/jobs/j7"
    assert json.loads(route.calls.last.request.content) == {
        "url": "https://example.com/podcast.mp3",
        "language": "english",
    }


@respx.mock(base_url=BASE_URL)
async def test_the_async_read_resources_decode_the_same_models(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/usage").mock(return_value=httpx.Response(200, json=USAGE_BODY))
    respx_mock.get("/v1/articles/a1").mock(
        return_value=httpx.Response(200, json={"id": "a1", "title": "T"})
    )
    respx_mock.get("/v1/articles/search").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "a1"}], "count": 1})
    )
    respx_mock.get("/v1/transcriptions/t1").mock(
        return_value=httpx.Response(200, json={"id": "t1", "output_text": "x"})
    )
    respx_mock.get("/v1/transcriptions").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "t1"}], "has_more": False, "next_cursor": None}
        )
    )
    async with AsyncShorty(TEST_API_KEY) as client:
        assert (await client.usage.get()).plan.tier == "pro"
        assert (await client.articles.get("a1")).title == "T"
        assert (await client.articles.search("q")).count == 1
        assert (await client.transcriptions.get("t1")).output_text == "x"
        page = await client.transcriptions.list(limit=1)
        assert [t.id async for t in page] == ["t1"]


@respx.mock(base_url=BASE_URL)
async def test_the_async_raw_request_escape_hatch_works(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("/v1/anything").mock(return_value=httpx.Response(200, json={"ok": 1}))
    async with AsyncShorty(TEST_API_KEY) as client:
        response = await client.request(
            "POST", "/v1/anything", body={"a": 1}, idempotency_key="k1", timeout=5.0
        )
    assert response.data == {"ok": 1}
    assert respx_mock.calls.last.request.headers["idempotency-key"] == "k1"


def test_an_injected_async_http_client_is_not_closed_by_the_sdk() -> None:
    import asyncio

    async def run() -> bool:
        injected = httpx.AsyncClient()
        async with AsyncShorty(TEST_API_KEY, http_client=injected):
            pass
        closed = injected.is_closed
        await injected.aclose()
        return closed

    assert asyncio.run(run()) is False


def test_the_async_client_repr_and_pickle_guards_match_the_sync_client() -> None:
    import pickle

    import pytest as _pytest

    client = AsyncShorty(TEST_API_KEY)
    assert repr(client) == f"AsyncShorty(base_url='{BASE_URL}')"
    with _pytest.raises(TypeError):
        pickle.dumps(client)


def test_debug_true_writes_a_redacted_line_to_stderr(capsys) -> None:
    from shorty_py._client import _resolve_debug

    sink = _resolve_debug(True)
    assert sink is not None
    sink("GET /v1/usage -> 200")
    assert "[shorty] GET /v1/usage -> 200" in capsys.readouterr().err
    assert _resolve_debug(False) is None
    assert _resolve_debug(None) is None


def test_redaction_masks_every_known_secret_shape() -> None:
    from shorty_py._redaction import redact

    assert redact("key=shk_live_abc123XYZ") == "key=shk_live_***"
    assert redact("key=shk_test_abc123") == "key=shk_test_***"
    assert redact("secret=whsec_AbC+/=123") == "secret=whsec_***"
    assert redact("Authorization: Bearer shk_live_abc") == "Authorization: Bearer ***"
    assert redact("nothing to hide") == "nothing to hide"
    # Idempotent: redacting twice does not corrupt the placeholder.
    assert redact(redact("shk_live_abc")) == "shk_live_***"
