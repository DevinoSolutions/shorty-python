"""Job status normalization and the client-side ``wait_for`` poller."""

from __future__ import annotations

import httpx
import pytest
import respx

from shorty_py import APITimeoutError, AsyncShorty, JobFailedError, Shorty, normalize_job_status
from tests.conftest import BASE_URL, TEST_API_KEY


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shorty_py.resources.jobs.time.sleep", lambda _s: None)
    monkeypatch.setattr("shorty_py.resources.jobs.asyncio.sleep", _instant)


async def _instant(_seconds: float) -> None:
    return None


def job(status: str, **extra: object) -> dict[str, object]:
    return {"jobId": "j1", "status": status, **extra}


# ---------------------------------------------------------------------------
# normalize_job_status — the mapping must match the TS table exactly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("success", "SUCCESS"),
        ("completed", "SUCCESS"),
        ("done", "SUCCESS"),
        ("SUCCESS", "SUCCESS"),
        ("cancelled", "CANCELLED"),
        ("CANCELLED", "CANCELLED"),
        ("error", "ERROR"),
        ("failed", "ERROR"),
        ("missing", "ERROR"),
        ("processing", "PROCESSING"),
        ("running", "PROCESSING"),
        ("queued", "QUEUED"),
        ("pending", "QUEUED"),
        ("", "QUEUED"),
        (None, "QUEUED"),
        ("a-status-invented-next-year", "QUEUED"),
    ],
)
def test_normalize_job_status_matches_the_typescript_mapping(raw: object, expected: str) -> None:
    assert normalize_job_status(raw) == expected


# ---------------------------------------------------------------------------
# jobs.get
# ---------------------------------------------------------------------------


@respx.mock(base_url=BASE_URL)
def test_jobs_get_preserves_the_nested_camel_case_wire_shape(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/jobs/j1").mock(
        return_value=httpx.Response(
            200,
            json=job(
                "processing",
                progress=42,
                step="transcribing",
                error=None,
                output={"jobType": "SUBTITLES", "articleId": "a1"},
            ),
        )
    )
    with Shorty(TEST_API_KEY) as client:
        status = client.jobs.get("j1")

    assert status.jobId == "j1"
    assert status.progress == 42
    assert status.step == "transcribing"
    assert status.output["articleId"] == "a1"


@respx.mock(base_url=BASE_URL)
def test_a_job_id_is_url_encoded_in_the_path(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(path__startswith="/v1/jobs/").mock(
        return_value=httpx.Response(200, json=job("success"))
    )
    with Shorty(TEST_API_KEY) as client:
        client.jobs.get("weird/id?x=1")
    assert "weird%2Fid%3Fx%3D1" in str(route.calls.last.request.url)


# ---------------------------------------------------------------------------
# jobs.wait_for
# ---------------------------------------------------------------------------


@respx.mock(base_url=BASE_URL)
def test_wait_for_polls_until_the_job_succeeds(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/jobs/j1").mock(
        side_effect=[
            httpx.Response(200, json=job("queued")),
            httpx.Response(200, json=job("processing", progress=50)),
            httpx.Response(200, json=job("success", progress=100)),
        ]
    )
    with Shorty(TEST_API_KEY) as client:
        final = client.jobs.wait_for("j1", poll_interval=0.01)

    assert normalize_job_status(final.status) == "SUCCESS"
    assert final.progress == 100
    assert route.call_count == 3


@respx.mock(base_url=BASE_URL)
def test_wait_for_raises_job_failed_carrying_the_jobs_own_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/jobs/j1").mock(
        return_value=httpx.Response(200, json=job("error", error="GPU worker died"))
    )
    with Shorty(TEST_API_KEY) as client, pytest.raises(JobFailedError) as caught:
        client.jobs.wait_for("j1", poll_interval=0.01)

    assert caught.value.job_id == "j1"
    assert caught.value.status == "error"
    assert caught.value.job_error == "GPU worker died"
    assert "GPU worker died" in str(caught.value)


@respx.mock(base_url=BASE_URL)
def test_a_cancelled_job_also_raises_job_failed(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/jobs/j1").mock(return_value=httpx.Response(200, json=job("cancelled")))
    with Shorty(TEST_API_KEY) as client, pytest.raises(JobFailedError) as caught:
        client.jobs.wait_for("j1", poll_interval=0.01)
    assert caught.value.status == "cancelled"
    assert caught.value.job_error is None


@respx.mock(base_url=BASE_URL)
def test_wait_for_raises_api_timeout_when_the_deadline_elapses(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/jobs/j1").mock(return_value=httpx.Response(200, json=job("processing")))
    with Shorty(TEST_API_KEY) as client, pytest.raises(APITimeoutError) as caught:
        client.jobs.wait_for("j1", poll_interval=5.0, timeout=0.0)

    assert "j1" in str(caught.value)
    assert route.call_count == 1, "the deadline check must run before another poll"


def test_wait_for_defaults_match_the_typescript_sdk() -> None:
    from shorty_py.resources.jobs import DEFAULT_POLL_INTERVAL, DEFAULT_WAIT_TIMEOUT

    assert DEFAULT_POLL_INTERVAL == 2.0
    assert DEFAULT_WAIT_TIMEOUT == 600.0


@respx.mock(base_url=BASE_URL)
async def test_the_async_wait_for_behaves_identically(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/jobs/j1").mock(
        side_effect=[
            httpx.Response(200, json=job("running")),
            httpx.Response(200, json=job("done")),
        ]
    )
    async with AsyncShorty(TEST_API_KEY) as client:
        final = await client.jobs.wait_for("j1", poll_interval=0.01)
    assert normalize_job_status(final.status) == "SUCCESS"


@respx.mock(base_url=BASE_URL)
async def test_the_async_wait_for_raises_job_failed_too(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/jobs/j1").mock(
        return_value=httpx.Response(200, json=job("failed", error="bad input"))
    )
    async with AsyncShorty(TEST_API_KEY) as client:
        with pytest.raises(JobFailedError) as caught:
            await client.jobs.wait_for("j1", poll_interval=0.01)
    assert caught.value.job_error == "bad input"


@respx.mock(base_url=BASE_URL)
async def test_the_async_wait_for_times_out(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/jobs/j1").mock(return_value=httpx.Response(200, json=job("queued")))
    async with AsyncShorty(TEST_API_KEY) as client:
        with pytest.raises(APITimeoutError):
            await client.jobs.wait_for("j1", poll_interval=5.0, timeout=0.0)
