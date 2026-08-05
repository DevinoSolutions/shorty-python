"""``client.usage`` — the account's plan, subscription, limits, and counters."""

from __future__ import annotations

from collections.abc import Mapping

from shorty_py._transport import RequestSpec
from shorty_py.types import UsageResponse

from ._base import AsyncResource, SyncResource, as_mapping


def _spec(*, timeout: float | None, headers: Mapping[str, str] | None) -> RequestSpec:
    return RequestSpec(method="GET", path="/v1/usage", timeout=timeout, headers=headers)


class UsageResource(SyncResource):
    """Requires the ``usage:read`` scope."""

    def get(
        self,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> UsageResponse:
        """``GET /v1/usage`` — operation ``getUsage``."""
        response = self._transport.request(_spec(timeout=timeout, headers=headers))
        return UsageResponse.from_wire(as_mapping(response.data))


class AsyncUsageResource(AsyncResource):
    """Requires the ``usage:read`` scope."""

    async def get(
        self,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> UsageResponse:
        """``GET /v1/usage`` — operation ``getUsage``."""
        response = await self._transport.request(_spec(timeout=timeout, headers=headers))
        return UsageResponse.from_wire(as_mapping(response.data))
