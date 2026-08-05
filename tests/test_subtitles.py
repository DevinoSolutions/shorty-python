"""Subtitles: the create/poll/download loop and its two sharp edges (409, 413)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from shorty_py import AsyncShorty, ConflictError, Shorty, ValidationError
from tests.conftest import BASE_URL, TEST_API_KEY, problem_response

ACCEPTED = {"job_id": "j1", "status": "queued", "tracking_url": "/v1/jobs/j1"}
DOWNLOAD = {
    "url": "https://cdn.example.com/signed/subtitles-a1.srt",
    "expires_at": "2026-07-20T12:05:00.000Z",
    "kind": "srt",
    "filename": "subtitles-a1.srt",
}


@respx.mock(base_url=BASE_URL)
def test_create_sends_only_the_fields_the_caller_supplied(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/subtitles").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        client.subtitles.create(url="https://example.com/clip.mp4")

    assert json.loads(route.calls.last.request.content) == {"url": "https://example.com/clip.mp4"}


@respx.mock(base_url=BASE_URL)
def test_create_forwards_style_language_and_measured_duration(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/subtitles").mock(return_value=httpx.Response(202, json=ACCEPTED))
    with Shorty(TEST_API_KEY) as client:
        accepted = client.subtitles.create(
            url="https://example.com/clip.mp4",
            language="english",
            style="TIKTOK",
            duration_seconds=542,
        )

    assert accepted.job_id == "j1"
    assert json.loads(route.calls.last.request.content) == {
        "url": "https://example.com/clip.mp4",
        "language": "english",
        "style": "TIKTOK",
        "duration_seconds": 542,
    }


@respx.mock(base_url=BASE_URL)
def test_a_413_is_a_validation_error_and_is_never_retried(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/subtitles").mock(
        return_value=problem_response(
            "request_too_large", 413, title="Media too long", detail="Over your plan's cap."
        )
    )
    with Shorty(TEST_API_KEY, max_retries=3) as client, pytest.raises(ValidationError) as caught:
        client.subtitles.create(url="https://example.com/movie.mp4", duration_seconds=99_999)

    assert caught.value.status == 413
    assert caught.value.code == "request_too_large"
    assert route.call_count == 1, "an over-cap request must not be replayed"


@respx.mock(base_url=BASE_URL)
def test_download_returns_a_presigned_artifact(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/subtitles/j1/download").mock(
        return_value=httpx.Response(200, json=DOWNLOAD)
    )
    with Shorty(TEST_API_KEY) as client:
        artifact = client.subtitles.download("j1", kind="srt")

    assert artifact.kind == "srt"
    assert artifact.filename == "subtitles-a1.srt"
    assert artifact.url.startswith("https://cdn.example.com/")
    assert route.calls.last.request.url.params["kind"] == "srt"


@respx.mock(base_url=BASE_URL)
def test_download_omits_kind_when_not_specified_so_the_server_default_applies(
    respx_mock: respx.MockRouter,
) -> None:
    route = respx_mock.get("/v1/subtitles/j1/download").mock(
        return_value=httpx.Response(200, json=DOWNLOAD)
    )
    with Shorty(TEST_API_KEY) as client:
        client.subtitles.download("j1")
    assert "kind" not in route.calls.last.request.url.params


@respx.mock(base_url=BASE_URL)
def test_downloading_before_the_job_finishes_is_a_conflict_not_a_retry_storm(
    respx_mock: respx.MockRouter,
) -> None:
    """409 resource_not_ready is the normal pre-completion state. It must surface
    once as a ConflictError — retrying it blindly would hammer the API."""
    route = respx_mock.get("/v1/subtitles/j1/download").mock(
        return_value=problem_response(
            "resource_not_ready", 409, title="Not ready", detail="The job is still running."
        )
    )
    with Shorty(TEST_API_KEY, max_retries=5) as client, pytest.raises(ConflictError) as caught:
        client.subtitles.download("j1")

    assert caught.value.code == "resource_not_ready"
    assert route.call_count == 1


@respx.mock(base_url=BASE_URL)
def test_the_documented_poll_then_download_loop_works_end_to_end(
    respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shorty_py.resources.jobs.time.sleep", lambda _s: None)
    respx_mock.post("/v1/subtitles").mock(return_value=httpx.Response(202, json=ACCEPTED))
    respx_mock.get("/v1/jobs/j1").mock(
        side_effect=[
            httpx.Response(200, json={"jobId": "j1", "status": "processing"}),
            httpx.Response(200, json={"jobId": "j1", "status": "success"}),
        ]
    )
    respx_mock.get("/v1/subtitles/j1/download").mock(return_value=httpx.Response(200, json=DOWNLOAD))

    with Shorty(TEST_API_KEY) as client:
        accepted = client.subtitles.create(url="https://example.com/clip.mp4")
        client.jobs.wait_for(accepted.job_id, poll_interval=0.01)
        artifact = client.subtitles.download(accepted.job_id, kind="srt")

    assert artifact.url.endswith(".srt")


@respx.mock(base_url=BASE_URL)
def test_a_job_id_is_url_encoded_in_the_download_path(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(path__startswith="/v1/subtitles/").mock(
        return_value=httpx.Response(200, json=DOWNLOAD)
    )
    with Shorty(TEST_API_KEY) as client:
        client.subtitles.download("a/b")
    assert "/v1/subtitles/a%2Fb/download" in str(route.calls.last.request.url)


@respx.mock(base_url=BASE_URL)
async def test_the_async_subtitles_resource_mirrors_the_sync_one(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.post("/v1/subtitles").mock(return_value=httpx.Response(202, json=ACCEPTED))
    respx_mock.get("/v1/subtitles/j1/download").mock(return_value=httpx.Response(200, json=DOWNLOAD))

    async with AsyncShorty(TEST_API_KEY) as client:
        accepted = await client.subtitles.create(
            url="https://example.com/clip.mp4", style="CLEAN", language="en", duration_seconds=10
        )
        artifact = await client.subtitles.download(accepted.job_id, kind="vtt")

    assert accepted.job_id == "j1"
    assert artifact.filename == "subtitles-a1.srt"


@respx.mock(base_url=BASE_URL)
async def test_the_async_download_raises_conflict_before_completion(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/subtitles/j1/download").mock(
        return_value=problem_response("resource_not_ready", 409)
    )
    async with AsyncShorty(TEST_API_KEY, max_retries=2) as client:
        with pytest.raises(ConflictError):
            await client.subtitles.download("j1")
