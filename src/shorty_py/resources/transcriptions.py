"""``client.transcriptions`` — list, fetch, and start transcription jobs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from shorty_py._pagination import AsyncPage, Page
from shorty_py._transport import RequestSpec
from shorty_py.types import (
    JobAccepted,
    Transcription,
    TranscriptionDetail,
    TranscriptionListResponse,
)

from ._base import UNSET, AsyncResource, SyncResource, as_mapping, resolve_idempotency_key


def _list_spec(
    *,
    limit: int | None,
    cursor: str | None,
    timeout: float | None,
    headers: Mapping[str, str] | None,
) -> RequestSpec:
    return RequestSpec(
        method="GET",
        path="/v1/transcriptions",
        query={"limit": limit, "cursor": cursor},
        timeout=timeout,
        headers=headers,
    )


def _get_spec(
    *, transcription_id: str, timeout: float | None, headers: Mapping[str, str] | None
) -> RequestSpec:
    return RequestSpec(
        method="GET",
        path=f"/v1/transcriptions/{quote(transcription_id, safe='')}",
        timeout=timeout,
        headers=headers,
    )


def _create_spec(
    *,
    url: str,
    language: str | None,
    idempotency_key: Any,
    timeout: float | None,
    headers: Mapping[str, str] | None,
) -> RequestSpec:
    body: dict[str, Any] = {"url": url}
    if language is not None:
        body["language"] = language
    return RequestSpec(
        method="POST",
        path="/v1/transcriptions",
        body=body,
        idempotency_key=resolve_idempotency_key(idempotency_key),
        timeout=timeout,
        headers=headers,
    )


class TranscriptionsResource(SyncResource):
    """Reads need ``transcriptions:read``; ``create`` needs ``transcriptions:write``."""

    def list(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Page[Transcription]:
        """``GET /v1/transcriptions`` — operation ``listTranscriptions``."""

        def fetch(next_cursor: str | None) -> Page[Transcription]:
            response = self._transport.request(
                _list_spec(limit=limit, cursor=next_cursor, timeout=timeout, headers=headers)
            )
            envelope = TranscriptionListResponse.from_wire(as_mapping(response.data))
            return Page(
                data=envelope.data,
                has_more=envelope.has_more,
                next_cursor=envelope.next_cursor,
                fetch_next=fetch,
            )

        return fetch(cursor)

    def get(
        self,
        transcription_id: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> TranscriptionDetail:
        """``GET /v1/transcriptions/{transcriptionId}`` — ``getTranscription``."""
        response = self._transport.request(
            _get_spec(transcription_id=transcription_id, timeout=timeout, headers=headers)
        )
        return TranscriptionDetail.from_wire(as_mapping(response.data))

    def create(
        self,
        *,
        url: str,
        language: str | None = None,
        idempotency_key: str | None = UNSET,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JobAccepted:
        """``POST /v1/transcriptions`` — operation ``createTranscription``.

        Starts an async job and returns ``202 JobAccepted``; poll it with
        ``client.jobs.wait_for(accepted.job_id)``.

        An ``Idempotency-Key`` is generated automatically and reused across
        every retry attempt, so the write is retry-safe by default. Pass
        ``idempotency_key=None`` to opt out — the transport will then refuse to
        retry this POST at all.
        """
        response = self._transport.request(
            _create_spec(
                url=url,
                language=language,
                idempotency_key=idempotency_key,
                timeout=timeout,
                headers=headers,
            )
        )
        payload = dict(as_mapping(response.data))
        payload["idempotency_replayed"] = response.idempotency_replayed
        return JobAccepted.from_wire(payload)


class AsyncTranscriptionsResource(AsyncResource):
    """Reads need ``transcriptions:read``; ``create`` needs ``transcriptions:write``."""

    async def list(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncPage[Transcription]:
        """``GET /v1/transcriptions`` — operation ``listTranscriptions``."""

        async def fetch(next_cursor: str | None) -> AsyncPage[Transcription]:
            response = await self._transport.request(
                _list_spec(limit=limit, cursor=next_cursor, timeout=timeout, headers=headers)
            )
            envelope = TranscriptionListResponse.from_wire(as_mapping(response.data))
            return AsyncPage(
                data=envelope.data,
                has_more=envelope.has_more,
                next_cursor=envelope.next_cursor,
                fetch_next=fetch,
            )

        return await fetch(cursor)

    async def get(
        self,
        transcription_id: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> TranscriptionDetail:
        """``GET /v1/transcriptions/{transcriptionId}`` — ``getTranscription``."""
        response = await self._transport.request(
            _get_spec(transcription_id=transcription_id, timeout=timeout, headers=headers)
        )
        return TranscriptionDetail.from_wire(as_mapping(response.data))

    async def create(
        self,
        *,
        url: str,
        language: str | None = None,
        idempotency_key: str | None = UNSET,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JobAccepted:
        """``POST /v1/transcriptions`` — operation ``createTranscription``."""
        response = await self._transport.request(
            _create_spec(
                url=url,
                language=language,
                idempotency_key=idempotency_key,
                timeout=timeout,
                headers=headers,
            )
        )
        payload = dict(as_mapping(response.data))
        payload["idempotency_replayed"] = response.idempotency_replayed
        return JobAccepted.from_wire(payload)
