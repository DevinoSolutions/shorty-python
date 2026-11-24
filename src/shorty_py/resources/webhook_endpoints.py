"""``client.webhook_endpoints`` — register, list, and delete webhook endpoints.

To verify the deliveries themselves, see :func:`shorty_py.verify_webhook_signature`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from shorty_py._transport import RequestSpec
from shorty_py.types import (
    WebhookEndpointCreated,
    WebhookEndpointDeleted,
    WebhookEndpointListResponse,
    WebhookEventType,
)

from ._base import AsyncResource, SyncResource, as_mapping

_PATH = "/v1/webhook-endpoints"


def _list_spec(*, timeout: float | None, headers: Mapping[str, str] | None) -> RequestSpec:
    return RequestSpec(method="GET", path=_PATH, timeout=timeout, headers=headers)


def _create_spec(
    *,
    url: str,
    event_types: Sequence[WebhookEventType],
    description: str | None,
    timeout: float | None,
    headers: Mapping[str, str] | None,
) -> RequestSpec:
    body: dict[str, Any] = {"url": url, "event_types": list(event_types)}
    if description is not None:
        body["description"] = description
    # The operation takes no Idempotency-Key, so this POST is never retried:
    # a replay could register the same URL twice.
    return RequestSpec(method="POST", path=_PATH, body=body, timeout=timeout, headers=headers)


def _delete_spec(
    *, endpoint_id: str, timeout: float | None, headers: Mapping[str, str] | None
) -> RequestSpec:
    return RequestSpec(
        method="DELETE",
        path=f"{_PATH}/{quote(endpoint_id, safe='')}",
        timeout=timeout,
        headers=headers,
    )


class WebhookEndpointsResource(SyncResource):
    """The authenticated account's webhook endpoints."""

    def list(
        self,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> WebhookEndpointListResponse:
        """``GET /v1/webhook-endpoints`` — operation ``listWebhookEndpoints``.

        Newest first and **not** paginated. Signing secrets are never listed.
        """
        response = self._transport.request(_list_spec(timeout=timeout, headers=headers))
        return WebhookEndpointListResponse.from_wire(as_mapping(response.data))

    def create(
        self,
        *,
        url: str,
        event_types: Sequence[WebhookEventType],
        description: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> WebhookEndpointCreated:
        """``POST /v1/webhook-endpoints`` — operation ``createWebhookEndpoint``.

        Returns the endpoint and its ``whsec_`` signing secret, which is shown
        **only in this response**. Shorty immediately sends a signed ``ping`` to
        ``url``; a 2xx answer sets ``verified_at``, and only verified endpoints
        receive events. A URL that is not public HTTPS on port 443 raises
        :class:`~shorty_py.ValidationError`; an account at its endpoint limit
        raises :class:`~shorty_py.QuotaExhaustedError`.
        """
        response = self._transport.request(
            _create_spec(
                url=url,
                event_types=event_types,
                description=description,
                timeout=timeout,
                headers=headers,
            )
        )
        return WebhookEndpointCreated.from_wire(as_mapping(response.data))

    def delete(
        self,
        endpoint_id: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> WebhookEndpointDeleted:
        """``DELETE /v1/webhook-endpoints/{endpointId}`` — operation ``deleteWebhookEndpoint``.

        Also drops any deliveries still queued for the endpoint. An unknown or
        foreign id raises :class:`~shorty_py.NotFoundError`.
        """
        response = self._transport.request(
            _delete_spec(endpoint_id=endpoint_id, timeout=timeout, headers=headers)
        )
        return WebhookEndpointDeleted.from_wire(as_mapping(response.data))


class AsyncWebhookEndpointsResource(AsyncResource):
    """The authenticated account's webhook endpoints."""

    async def list(
        self,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> WebhookEndpointListResponse:
        """``GET /v1/webhook-endpoints`` — operation ``listWebhookEndpoints``."""
        response = await self._transport.request(_list_spec(timeout=timeout, headers=headers))
        return WebhookEndpointListResponse.from_wire(as_mapping(response.data))

    async def create(
        self,
        *,
        url: str,
        event_types: Sequence[WebhookEventType],
        description: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> WebhookEndpointCreated:
        """``POST /v1/webhook-endpoints`` — operation ``createWebhookEndpoint``."""
        response = await self._transport.request(
            _create_spec(
                url=url,
                event_types=event_types,
                description=description,
                timeout=timeout,
                headers=headers,
            )
        )
        return WebhookEndpointCreated.from_wire(as_mapping(response.data))

    async def delete(
        self,
        endpoint_id: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> WebhookEndpointDeleted:
        """``DELETE /v1/webhook-endpoints/{endpointId}`` — operation ``deleteWebhookEndpoint``."""
        response = await self._transport.request(
            _delete_spec(endpoint_id=endpoint_id, timeout=timeout, headers=headers)
        )
        return WebhookEndpointDeleted.from_wire(as_mapping(response.data))
