"""Auto-generated idempotency keys, caller-supplied keys, and replay surfacing."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from shorty_py import ConflictError, Shorty, ValidationError
from shorty_py._idempotency import (
    MAX_IDEMPOTENCY_KEY_LENGTH,
    new_idempotency_key,
    validate_idempotency_key,
)
from tests.conftest import BASE_URL, TEST_API_KEY, problem_response

ACCEPTED = {"job_id": "j1", "status": "queued", "tracking_url": "/v1/jobs/j1"}


def test_generated_keys_are_uuid_v4_and_unique() -> None:
    first, second = new_idempotency_key(), new_idempotency_key()
    assert first != second
    assert uuid.UUID(first).version == 4


def test_a_caller_key_is_validated_against_the_servers_constraints() -> None:
    assert validate_idempotency_key("order-42") == "order-42"
    with pytest.raises(ValueError, match="non-empty"):
        validate_idempotency_key("")
    with pytest.raises(ValueError, match="at most 255"):
        validate_idempotency_key("k" * (MAX_IDEMPOTENCY_KEY_LENGTH + 1))
    with pytest.raises(ValueError, match="visible ASCII"):
        validate_idempotency_key("has a space")
    with pytest.raises(ValueError, match="visible ASCII"):
        validate_idempotency_key("emoji-\U0001f600")


@pytest.mark.parametrize(
    ("resource", "path", "call"),
    [
        (
            "transcriptions",
            "/v1/transcriptions",
            lambda c, **kw: c.transcriptions.create(url="https://example.com/a.mp3", **kw),
        ),
        (
            "subtitles",
            "/v1/subtitles",
            lambda c, **kw: c.subtitles.create(url="https://example.com/clip.mp4", **kw),
        ),
        (
            "summaries",
            "/v1/summaries",
            lambda c, **kw: c.summaries.create_from_url("https://example.com/post", **kw),
        ),
    ],
)
@respx.mock(base_url=BASE_URL)
def test_every_write_auto_generates_an_idempotency_key(
    resource: str, path: str, call, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.post(path).mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        call(client)

    key = route.calls.last.request.headers["idempotency-key"]
    assert uuid.UUID(key).version == 4, f"{resource} did not auto-generate a v4 key"


@respx.mock(base_url=BASE_URL)
def test_a_caller_supplied_key_is_sent_verbatim(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/transcriptions").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        client.transcriptions.create(
            url="https://example.com/a.mp3", idempotency_key="invoice-2026-08-05"
        )
    assert route.calls.last.request.headers["idempotency-key"] == "invoice-2026-08-05"


@respx.mock(base_url=BASE_URL)
def test_an_invalid_caller_key_fails_locally_before_any_request_is_made(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.post("/v1/transcriptions").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client, pytest.raises(ValueError):
        client.transcriptions.create(url="https://example.com/a.mp3", idempotency_key="bad key")
    assert route.call_count == 0


@respx.mock(base_url=BASE_URL)
def test_passing_none_opts_out_of_the_header_entirely(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/transcriptions").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        client.transcriptions.create(url="https://example.com/a.mp3", idempotency_key=None)
    assert "idempotency-key" not in route.calls.last.request.headers


@respx.mock(base_url=BASE_URL)
def test_a_replayed_response_is_surfaced_on_the_result(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("/v1/transcriptions").mock(
        return_value=httpx.Response(202, json=ACCEPTED, headers={"Idempotency-Replayed": "true"})
    )
    with Shorty(TEST_API_KEY) as client:
        accepted = client.transcriptions.create(url="https://example.com/a.mp3")

    assert accepted.idempotency_replayed is True
    assert accepted.job_id == "j1"


@respx.mock(base_url=BASE_URL)
def test_a_fresh_response_is_not_marked_as_replayed(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("/v1/transcriptions").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        assert client.transcriptions.create(url="https://example.com/a.mp3").idempotency_replayed is False


@respx.mock(base_url=BASE_URL)
def test_reusing_a_key_with_a_different_body_surfaces_an_actionable_validation_error(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("/v1/transcriptions").mock(
        return_value=problem_response(
            "idempotency_key_reused",
            422,
            title="Idempotency key reused",
            detail='Key "order-42" was already used with a different request body.',
        )
    )
    with Shorty(TEST_API_KEY, max_retries=0) as client, pytest.raises(ValidationError) as caught:
        client.transcriptions.create(url="https://example.com/b.mp3", idempotency_key="order-42")

    assert caught.value.code == "idempotency_key_reused"
    assert "order-42" in str(caught.value)


@respx.mock(base_url=BASE_URL)
def test_a_concurrent_replay_surfaces_as_a_conflict_naming_the_key(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("/v1/summaries").mock(
        return_value=problem_response(
            "idempotency_in_progress",
            409,
            title="Request in progress",
            detail='Key "order-42" is still being processed.',
        )
    )
    with Shorty(TEST_API_KEY, max_retries=0) as client, pytest.raises(ConflictError) as caught:
        client.summaries.create_from_text("hello", idempotency_key="order-42")

    assert caught.value.code == "idempotency_in_progress"
    assert "order-42" in str(caught.value)


@respx.mock(base_url=BASE_URL)
async def test_the_async_client_auto_generates_keys_too(respx_mock: respx.MockRouter) -> None:
    from shorty_py import AsyncShorty

    route = respx_mock.post("/v1/subtitles").mock(return_value=httpx.Response(202, json=ACCEPTED))
    async with AsyncShorty(TEST_API_KEY) as client:
        await client.subtitles.create(url="https://example.com/clip.mp4")
    assert uuid.UUID(route.calls.last.request.headers["idempotency-key"]).version == 4
