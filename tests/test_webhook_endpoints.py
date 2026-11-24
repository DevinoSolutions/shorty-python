"""``/v1/webhook-endpoints`` — list, create (secret shown once), and delete."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from shorty_py import (
    APIServerError,
    AsyncShorty,
    NotFoundError,
    Shorty,
    ValidationError,
    WebhookEndpoint,
    WebhookEndpointCreated,
)
from tests.conftest import BASE_URL, TEST_API_KEY, problem

ENDPOINT = {
    "id": "6f1c2a3b-0000-4000-8000-000000000000",
    "url": "https://hooks.example.com/shorty",
    "description": "Zapier",
    "event_types": ["job.succeeded"],
    "enabled": True,
    "verified_at": "2026-10-21T12:00:00.000Z",
    "disabled_at": None,
    "disabled_reason": None,
    "created_at": "2026-10-21T12:00:00.000Z",
}
SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"


@respx.mock(base_url=BASE_URL)
def test_list_returns_every_endpoint(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("/v1/webhook-endpoints").mock(
        return_value=httpx.Response(200, json={"data": [ENDPOINT]})
    )
    with Shorty(TEST_API_KEY) as client:
        listed = client.webhook_endpoints.list()

    assert route.called
    assert len(listed.data) == 1
    endpoint = listed.data[0]
    assert isinstance(endpoint, WebhookEndpoint)
    assert endpoint.id == ENDPOINT["id"]
    assert endpoint.event_types == ("job.succeeded",)
    assert endpoint.enabled is True
    assert endpoint.verified_at == "2026-10-21T12:00:00.000Z"
    assert endpoint.disabled_reason is None


@respx.mock(base_url=BASE_URL)
def test_unknown_endpoint_fields_land_in_extra(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/webhook-endpoints").mock(
        return_value=httpx.Response(200, json={"data": [{**ENDPOINT, "new_field": 1}]})
    )
    with Shorty(TEST_API_KEY) as client:
        endpoint = client.webhook_endpoints.list().data[0]

    assert endpoint.extra == {"new_field": 1}


@respx.mock(base_url=BASE_URL)
def test_create_sends_the_body_and_returns_the_secret(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/webhook-endpoints").mock(
        return_value=httpx.Response(201, json={"endpoint": ENDPOINT, "secret": SECRET})
    )
    with Shorty(TEST_API_KEY) as client:
        created = client.webhook_endpoints.create(
            url="https://hooks.example.com/shorty",
            event_types=["job.succeeded", "job.failed"],
            description="Zapier",
        )

    assert isinstance(created, WebhookEndpointCreated)
    assert created.secret == SECRET
    assert created.endpoint.id == ENDPOINT["id"]
    request = route.calls.last.request
    assert json.loads(request.content) == {
        "url": "https://hooks.example.com/shorty",
        "event_types": ["job.succeeded", "job.failed"],
        "description": "Zapier",
    }
    # The operation has no Idempotency-Key parameter.
    assert "idempotency-key" not in request.headers


@respx.mock(base_url=BASE_URL)
def test_create_omits_an_unset_description(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/webhook-endpoints").mock(
        return_value=httpx.Response(201, json={"endpoint": ENDPOINT, "secret": SECRET})
    )
    with Shorty(TEST_API_KEY) as client:
        client.webhook_endpoints.create(url="https://h.example.com", event_types=("job.failed",))

    assert json.loads(route.calls.last.request.content) == {
        "url": "https://h.example.com",
        "event_types": ["job.failed"],
    }


def test_the_secret_is_kept_out_of_the_repr() -> None:
    created = WebhookEndpointCreated.from_wire({"endpoint": ENDPOINT, "secret": SECRET})
    assert SECRET not in repr(created)


@respx.mock(base_url=BASE_URL)
def test_create_is_not_retried_on_a_server_error(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post("/v1/webhook-endpoints").mock(
        return_value=httpx.Response(503, json=problem("internal_error", 503))
    )
    with Shorty(TEST_API_KEY, max_retries=3) as client, pytest.raises(APIServerError):
        client.webhook_endpoints.create(url="https://h.example.com", event_types=["job.failed"])

    assert route.call_count == 1


@respx.mock(base_url=BASE_URL)
def test_a_refused_url_raises_validation_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("/v1/webhook-endpoints").mock(
        return_value=httpx.Response(400, json=problem("validation_failed", 400))
    )
    with Shorty(TEST_API_KEY) as client, pytest.raises(ValidationError):
        client.webhook_endpoints.create(url="http://localhost", event_types=["job.failed"])


@respx.mock(base_url=BASE_URL)
def test_delete_escapes_the_id_and_confirms(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.delete("/v1/webhook-endpoints/a%2Fb").mock(
        return_value=httpx.Response(200, json={"id": "a/b", "deleted": True})
    )
    with Shorty(TEST_API_KEY) as client:
        deleted = client.webhook_endpoints.delete("a/b")

    assert route.called
    assert deleted.id == "a/b"
    assert deleted.deleted is True


@respx.mock(base_url=BASE_URL)
def test_deleting_an_unknown_endpoint_raises_not_found(respx_mock: respx.MockRouter) -> None:
    respx_mock.delete("/v1/webhook-endpoints/missing").mock(
        return_value=httpx.Response(404, json=problem("not_found", 404))
    )
    with Shorty(TEST_API_KEY) as client, pytest.raises(NotFoundError):
        client.webhook_endpoints.delete("missing")


@respx.mock(base_url=BASE_URL)
async def test_the_async_client_supports_all_three(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/v1/webhook-endpoints").mock(
        return_value=httpx.Response(200, json={"data": [ENDPOINT]})
    )
    respx_mock.post("/v1/webhook-endpoints").mock(
        return_value=httpx.Response(201, json={"endpoint": ENDPOINT, "secret": SECRET})
    )
    respx_mock.delete(f"/v1/webhook-endpoints/{ENDPOINT['id']}").mock(
        return_value=httpx.Response(200, json={"id": ENDPOINT["id"], "deleted": True})
    )
    async with AsyncShorty(TEST_API_KEY) as client:
        listed = await client.webhook_endpoints.list()
        created = await client.webhook_endpoints.create(
            url=ENDPOINT["url"], event_types=["job.succeeded"]
        )
        deleted = await client.webhook_endpoints.delete(ENDPOINT["id"])

    assert listed.data[0].url == ENDPOINT["url"]
    assert created.secret == SECRET
    assert deleted.deleted is True
