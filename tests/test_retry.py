"""The retry policy — every row of the PRD's retry table, plus the delay math."""

from __future__ import annotations

import email.utils

import httpx
import pytest
import respx

from shorty_py import (
    APIServerError,
    APITimeoutError,
    AuthenticationError,
    QuotaExhaustedError,
    RateLimitError,
    Shorty,
    ValidationError,
)
from shorty_py._retry import (
    BACKOFF_CAP_SECONDS,
    RETRY_AFTER_CAP_SECONDS,
    capped_retry_after,
    full_jitter_backoff,
    parse_retry_after,
)
from tests.conftest import BASE_URL, TEST_API_KEY, problem_response


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries must be provably taken without the suite actually waiting."""
    monkeypatch.setattr("shorty_py._transport.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("shorty_py._transport.asyncio.sleep", _instant_async_sleep)


async def _instant_async_sleep(_seconds: float) -> None:
    return None


# ---------------------------------------------------------------------------
# Delay math
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attempt", range(12))
def test_full_jitter_backoff_is_always_within_the_eight_second_cap(attempt: int) -> None:
    assert 0.0 <= full_jitter_backoff(attempt, rand=lambda: 1.0) <= BACKOFF_CAP_SECONDS


def test_full_jitter_backoff_grows_geometrically_until_it_saturates() -> None:
    ceilings = [full_jitter_backoff(a, rand=lambda: 1.0) for a in range(6)]
    assert ceilings[:5] == [0.5, 1.0, 2.0, 4.0, 8.0]
    assert ceilings[5] == BACKOFF_CAP_SECONDS  # saturated, not 16


def test_full_jitter_backoff_can_return_zero() -> None:
    assert full_jitter_backoff(5, rand=lambda: 0.0) == 0.0


def test_retry_after_is_capped_at_sixty_seconds() -> None:
    assert capped_retry_after(3600) == RETRY_AFTER_CAP_SECONDS
    assert capped_retry_after(5) == 5


def test_retry_after_parses_delta_seconds_and_http_dates_and_shrugs_at_garbage() -> None:
    assert parse_retry_after("30") == 30
    assert parse_retry_after("  7  ") == 7
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("not-a-date") is None
    # An HTTP-date 60s in the future, measured against an injected "now".
    http_date = "Wed, 21 Oct 2026 07:29:00 GMT"
    when = email.utils.parsedate_to_datetime(http_date).timestamp()
    assert parse_retry_after(http_date, now=when - 60) == 60.0
    # A date in the past clamps to zero rather than going negative.
    assert parse_retry_after("Wed, 21 Oct 2020 07:28:00 GMT") == 0.0


# ---------------------------------------------------------------------------
# Which failures are retried
# ---------------------------------------------------------------------------


@respx.mock(base_url=BASE_URL)
def test_a_429_rate_limit_is_retried_and_then_succeeds(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/usage").mock(
        side_effect=[
            problem_response("rate_limited", 429),
            httpx.Response(200, json={"plan": {"tier": "pro"}}),
        ]
    )
    with Shorty(TEST_API_KEY, max_retries=2) as client:
        assert client.usage.get().plan.tier == "pro"
    assert route.call_count == 2


@respx.mock(base_url=BASE_URL)
def test_a_429_quota_exhausted_is_never_retried(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/usage").mock(return_value=problem_response("quota_exhausted", 429))
    with Shorty(TEST_API_KEY, max_retries=5) as client, pytest.raises(QuotaExhaustedError):
        client.usage.get()
    assert route.call_count == 1, "a blown quota must not be retried"


@pytest.mark.parametrize("status", [500, 502, 503, 504, 408])
@respx.mock(base_url=BASE_URL)
def test_retryable_statuses_are_retried(status: int, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/usage").mock(
        side_effect=[httpx.Response(status), httpx.Response(200, json={})]
    )
    with Shorty(TEST_API_KEY, max_retries=2) as client:
        client.usage.get()
    assert route.call_count == 2


@pytest.mark.parametrize(
    ("code", "status", "expected"),
    [("validation_failed", 400, ValidationError), ("unauthorized", 401, AuthenticationError)],
)
@respx.mock(base_url=BASE_URL)
def test_client_errors_are_not_retried(
    code: str, status: int, expected: type[Exception], respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/v1/usage").mock(return_value=problem_response(code, status))
    with Shorty(TEST_API_KEY, max_retries=3) as client, pytest.raises(expected):
        client.usage.get()
    assert route.call_count == 1


@respx.mock(base_url=BASE_URL)
def test_a_503_service_unavailable_is_retried_then_surfaces_as_a_server_error(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get("/v1/usage").mock(
        return_value=problem_response("service_unavailable", 503)
    )
    with Shorty(TEST_API_KEY, max_retries=2) as client, pytest.raises(APIServerError):
        client.usage.get()
    assert route.call_count == 3  # first attempt + 2 retries


@respx.mock(base_url=BASE_URL)
def test_connection_errors_are_retried(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/usage").mock(
        side_effect=[httpx.ConnectError("reset"), httpx.Response(200, json={})]
    )
    with Shorty(TEST_API_KEY, max_retries=1) as client:
        client.usage.get()
    assert route.call_count == 2


@respx.mock(base_url=BASE_URL)
def test_timeouts_are_retried_up_to_the_limit(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/usage").mock(side_effect=httpx.ReadTimeout("slow"))
    with Shorty(TEST_API_KEY, max_retries=2) as client, pytest.raises(APITimeoutError):
        client.usage.get()
    assert route.call_count == 3


@respx.mock(base_url=BASE_URL)
def test_max_retries_zero_disables_retrying_entirely(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/usage").mock(return_value=httpx.Response(503))
    with Shorty(TEST_API_KEY, max_retries=0) as client, pytest.raises(APIServerError):
        client.usage.get()
    assert route.call_count == 1


# ---------------------------------------------------------------------------
# Method safety: POST is only retried when the server can deduplicate it
# ---------------------------------------------------------------------------


@respx.mock(base_url=BASE_URL)
def test_a_post_without_an_idempotency_key_is_never_retried(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/transcriptions").mock(return_value=httpx.Response(503))
    with Shorty(TEST_API_KEY, max_retries=3) as client, pytest.raises(APIServerError):
        client.transcriptions.create(url="https://example.com/a.mp3", idempotency_key=None)

    assert route.call_count == 1, "an un-deduplicable write must never be replayed"
    assert "idempotency-key" not in route.calls.last.request.headers


@respx.mock(base_url=BASE_URL)
def test_a_post_with_an_idempotency_key_is_retried_with_the_same_key(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.post("/v1/transcriptions").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(202, json={"job_id": "j1", "status": "queued", "tracking_url": "/x"}),
        ]
    )
    with Shorty(TEST_API_KEY, max_retries=2) as client:
        accepted = client.transcriptions.create(url="https://example.com/a.mp3")

    assert accepted.job_id == "j1"
    assert route.call_count == 3
    keys = {call.request.headers["idempotency-key"] for call in route.calls}
    assert len(keys) == 1, "every retry of one logical write must reuse the same key"


@respx.mock(base_url=BASE_URL)
def test_a_413_on_a_write_is_a_validation_error_and_is_not_retried(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.post("/v1/subtitles").mock(
        return_value=problem_response("request_too_large", 413)
    )
    with Shorty(TEST_API_KEY, max_retries=3) as client, pytest.raises(ValidationError):
        client.subtitles.create(url="https://example.com/clip.mp4", duration_seconds=99999)
    assert route.call_count == 1


# ---------------------------------------------------------------------------
# Delay selection
# ---------------------------------------------------------------------------


@respx.mock(base_url=BASE_URL)
def test_retry_after_overrides_backoff_and_is_clamped_to_sixty_seconds(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("shorty_py._transport.time.sleep", slept.append)
    respx_mock.get("/v1/usage").mock(
        side_effect=[
            httpx.Response(
                429,
                json={"code": "rate_limited", "title": "Slow down", "status": 429},
                headers={"retry-after": "3600"},
            ),
            httpx.Response(200, json={}),
        ]
    )
    with Shorty(TEST_API_KEY, max_retries=1) as client:
        client.usage.get()

    assert slept == [RETRY_AFTER_CAP_SECONDS]


@respx.mock(base_url=BASE_URL)
def test_without_retry_after_the_delay_is_jittered_and_bounded(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("shorty_py._transport.time.sleep", slept.append)
    respx_mock.get("/v1/usage").mock(return_value=httpx.Response(503))
    with Shorty(TEST_API_KEY, max_retries=4) as client, pytest.raises(APIServerError):
        client.usage.get()

    assert len(slept) == 4
    assert all(0.0 <= delay <= BACKOFF_CAP_SECONDS for delay in slept)


@respx.mock(base_url=BASE_URL)
async def test_the_async_client_applies_the_same_retry_policy(respx_mock: respx.MockRouter) -> None:
    from shorty_py import AsyncShorty

    route = respx_mock.get("/v1/usage").mock(
        side_effect=[problem_response("rate_limited", 429), httpx.Response(200, json={})]
    )
    async with AsyncShorty(TEST_API_KEY, max_retries=1) as client:
        await client.usage.get()
    assert route.call_count == 2


@respx.mock(base_url=BASE_URL)
async def test_the_async_client_refuses_to_retry_a_keyless_post(
    respx_mock: respx.MockRouter,
) -> None:
    from shorty_py import AsyncShorty

    route = respx_mock.post("/v1/summaries").mock(return_value=httpx.Response(503))
    async with AsyncShorty(TEST_API_KEY, max_retries=3) as client:
        with pytest.raises(APIServerError):
            await client.summaries.create_from_url("https://example.com", idempotency_key=None)
    assert route.call_count == 1


@respx.mock(base_url=BASE_URL)
def test_a_429_without_a_parseable_code_is_still_retried(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/usage").mock(
        side_effect=[httpx.Response(429, text="too many"), httpx.Response(200, json={})]
    )
    with Shorty(TEST_API_KEY, max_retries=1) as client:
        client.usage.get()
    assert route.call_count == 2
    assert isinstance(RateLimitError(status=429), RateLimitError)
