"""``client.subtitles`` — start captioning jobs and fetch finished artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from shorty_py._transport import RequestSpec
from shorty_py.types import JobAccepted, SubtitleDownload

from ._base import UNSET, AsyncResource, SyncResource, as_mapping, resolve_idempotency_key


def _create_spec(
    *,
    url: str,
    language: str | None,
    style: str | None,
    duration_seconds: float | None,
    idempotency_key: Any,
    timeout: float | None,
    headers: Mapping[str, str] | None,
) -> RequestSpec:
    body: dict[str, Any] = {"url": url}
    if language is not None:
        body["language"] = language
    if style is not None:
        body["style"] = style
    if duration_seconds is not None:
        body["duration_seconds"] = duration_seconds
    return RequestSpec(
        method="POST",
        path="/v1/subtitles",
        body=body,
        idempotency_key=resolve_idempotency_key(idempotency_key),
        timeout=timeout,
        headers=headers,
    )


def _download_spec(
    *,
    job_id: str,
    kind: str | None,
    timeout: float | None,
    headers: Mapping[str, str] | None,
) -> RequestSpec:
    return RequestSpec(
        method="GET",
        path=f"/v1/subtitles/{quote(job_id, safe='')}/download",
        query={"kind": kind},
        timeout=timeout,
        headers=headers,
    )


class SubtitlesResource(SyncResource):
    """``create`` needs ``transcriptions:write``; ``download`` needs ``transcriptions:read``."""

    def create(
        self,
        *,
        url: str,
        language: str | None = None,
        style: str | None = None,
        duration_seconds: float | None = None,
        idempotency_key: str | None = UNSET,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JobAccepted:
        """``POST /v1/subtitles`` — operation ``createSubtitles``.

        ``style`` is ``CLEAN`` (free) or ``TIKTOK`` / ``PODCAST`` / ``MINIMAL``
        (Premium). Supplying ``duration_seconds`` lets the API reject over-cap
        media up front with a **413** ``request_too_large`` — surfaced as
        :class:`~shorty_py.ValidationError` and never retried — instead of
        failing the job minutes later.
        """
        response = self._transport.request(
            _create_spec(
                url=url,
                language=language,
                style=style,
                duration_seconds=duration_seconds,
                idempotency_key=idempotency_key,
                timeout=timeout,
                headers=headers,
            )
        )
        payload = dict(as_mapping(response.data))
        payload["idempotency_replayed"] = response.idempotency_replayed
        return JobAccepted.from_wire(payload)

    def download(
        self,
        job_id: str,
        *,
        kind: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> SubtitleDownload:
        """``GET /v1/subtitles/{jobId}/download`` — operation ``downloadSubtitles``.

        Returns a short-lived presigned URL for the ``srt`` / ``vtt`` / ``ass``
        file or the ``burned`` mp4.

        **Until the job completes this returns 409 ``resource_not_ready``**, which
        the SDK raises as :class:`~shorty_py.ConflictError`. That is the normal
        pre-completion state, not a failure — poll the job first::

            job = client.subtitles.create(url="https://example.com/clip.mp4")
            client.jobs.wait_for(job.job_id)
            artifact = client.subtitles.download(job.job_id, kind="srt")
        """
        response = self._transport.request(
            _download_spec(job_id=job_id, kind=kind, timeout=timeout, headers=headers)
        )
        return SubtitleDownload.from_wire(as_mapping(response.data))


class AsyncSubtitlesResource(AsyncResource):
    """``create`` needs ``transcriptions:write``; ``download`` needs ``transcriptions:read``."""

    async def create(
        self,
        *,
        url: str,
        language: str | None = None,
        style: str | None = None,
        duration_seconds: float | None = None,
        idempotency_key: str | None = UNSET,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JobAccepted:
        """``POST /v1/subtitles`` — operation ``createSubtitles``."""
        response = await self._transport.request(
            _create_spec(
                url=url,
                language=language,
                style=style,
                duration_seconds=duration_seconds,
                idempotency_key=idempotency_key,
                timeout=timeout,
                headers=headers,
            )
        )
        payload = dict(as_mapping(response.data))
        payload["idempotency_replayed"] = response.idempotency_replayed
        return JobAccepted.from_wire(payload)

    async def download(
        self,
        job_id: str,
        *,
        kind: str | None = None,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> SubtitleDownload:
        """``GET /v1/subtitles/{jobId}/download`` — operation ``downloadSubtitles``."""
        response = await self._transport.request(
            _download_spec(job_id=job_id, kind=kind, timeout=timeout, headers=headers)
        )
        return SubtitleDownload.from_wire(as_mapping(response.data))
