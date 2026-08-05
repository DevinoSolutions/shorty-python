"""Client construction, credential handling, and the secret-leak guarantees."""

from __future__ import annotations

import copy
import json
import pickle
import re

import httpx
import pytest
import respx

from shorty_py import AsyncShorty, Shorty, __version__
from tests.conftest import BASE_URL, TEST_API_KEY


def test_api_key_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHORTY_API_KEY", TEST_API_KEY)
    with Shorty() as client:
        assert client.base_url == BASE_URL


def test_an_explicit_api_key_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHORTY_API_KEY", "shk_live_fromenv")
    with respx.mock(base_url=BASE_URL) as mock:
        route = respx_mock.get("/v1/usage").mock(return_value=httpx.Response(200, json={}))
        with Shorty("shk_live_explicit") as client:
            client.usage.get()
    assert route.calls.last.request.headers["authorization"] == "Bearer shk_live_explicit"


def test_a_missing_api_key_raises_a_clear_value_error() -> None:
    with pytest.raises(ValueError, match="SHORTY_API_KEY"):
        Shorty()
    with pytest.raises(ValueError, match="SHORTY_API_KEY"):
        AsyncShorty()


def test_repr_and_str_never_contain_the_api_key() -> None:
    with Shorty(TEST_API_KEY) as client:
        for rendering in (repr(client), str(client), repr(vars(client)), repr(client.usage)):
            assert "shk_live_" not in rendering
        assert repr(client) == f"Shorty(base_url='{BASE_URL}')"


def test_the_key_is_not_reachable_through_the_instance_dict() -> None:
    """The key lives in a transport closure, not in any attribute value."""
    with Shorty(TEST_API_KEY) as client:
        dumped = json.dumps(
            {k: str(v) for k, v in vars(client).items()}
            | {k: str(v) for k, v in vars(client._transport).items()}
        )
        assert TEST_API_KEY not in dumped


def test_pickling_the_client_is_refused() -> None:
    with Shorty(TEST_API_KEY) as client, pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(client)


def test_deep_copying_the_client_is_refused() -> None:
    with Shorty(TEST_API_KEY) as client, pytest.raises(TypeError, match="cannot be pickled"):
        copy.deepcopy(client)


@respx.mock(base_url=BASE_URL)
def test_auth_and_user_agent_headers_have_the_documented_shape(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/usage").mock(return_value=httpx.Response(200, json={}))
    with Shorty(TEST_API_KEY) as client:
        client.usage.get()

    headers = route.calls.last.request.headers
    assert headers["authorization"] == f"Bearer {TEST_API_KEY}"
    assert headers["accept"] == "application/json"
    assert re.fullmatch(rf"shorty-py/{re.escape(__version__)} python/\d+\.\d+\.\d+", headers["user-agent"])
    # The twin header for environments that forbid overriding User-Agent.
    assert headers["x-shorty-sdk"] == headers["user-agent"]


@respx.mock(base_url=BASE_URL)
def test_a_get_body_carries_no_content_type(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/usage").mock(return_value=httpx.Response(200, json={}))
    with Shorty(TEST_API_KEY) as client:
        client.usage.get()
    assert "content-type" not in route.calls.last.request.headers


@respx.mock(base_url=BASE_URL)
def test_the_raw_request_escape_hatch_returns_status_headers_and_body(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/anything").mock(
        return_value=httpx.Response(200, json={"ok": True}, headers={"request-id": "req_abc"})
    )
    with Shorty(TEST_API_KEY) as client:
        response = client.request("GET", "/v1/anything", query={"a": 1, "skip": None})

    assert response.status_code == 200
    assert response.data == {"ok": True}
    assert response.request_id == "req_abc"
    assert respx_mock.calls.last.request.url.params["a"] == "1"
    assert "skip" not in respx_mock.calls.last.request.url.params


@respx.mock(base_url=BASE_URL)
def test_the_context_manager_closes_the_connection_pool(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/usage").mock(return_value=httpx.Response(200, json={}))
    with Shorty(TEST_API_KEY) as client:
        client.usage.get()
        transport = client._transport
    assert transport._client.is_closed


@respx.mock(base_url=BASE_URL)
async def test_the_async_context_manager_closes_the_connection_pool(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/usage").mock(return_value=httpx.Response(200, json={}))
    async with AsyncShorty(TEST_API_KEY) as client:
        await client.usage.get()
        transport = client._transport
    assert transport._client.is_closed


def test_an_injected_http_client_is_not_closed_by_the_sdk() -> None:
    injected = httpx.Client()
    with Shorty(TEST_API_KEY, http_client=injected):
        pass
    assert not injected.is_closed
    injected.close()


@respx.mock(base_url="https://staging.example.com")
def test_a_custom_base_url_is_honored_and_trailing_slashes_are_trimmed(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/usage").mock(return_value=httpx.Response(200, json={}))
    with Shorty(TEST_API_KEY, base_url="https://staging.example.com/") as client:
        assert client.base_url == "https://staging.example.com"
        client.usage.get()
    assert respx_mock.calls.last.request.url.host == "staging.example.com"


@respx.mock(base_url=BASE_URL)
def test_debug_logging_is_redacted_and_never_prints_the_key(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/usage").mock(
        return_value=httpx.Response(200, json={}, headers={"request-id": "req_dbg"})
    )
    lines: list[str] = []
    with Shorty(TEST_API_KEY, debug=lines.append) as client:
        client.usage.get()

    assert lines, "debug sink received nothing"
    assert any("GET /v1/usage -> 200" in line and "req=req_dbg" in line for line in lines)
    assert not any("shk_live_TESTKEY" in line for line in lines)


def test_the_version_is_the_single_source_of_truth_for_the_user_agent() -> None:
    from shorty_py._transport import default_user_agent

    assert default_user_agent(__version__).startswith(f"shorty-py/{__version__} python/")
