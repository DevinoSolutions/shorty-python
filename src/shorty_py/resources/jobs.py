"""``client.jobs`` — poll async job status; ``wait_for`` blocks until terminal."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Literal
from urllib.parse import quote

from shorty_py._transport import RequestSpec
from shorty_py.errors import APITimeoutError, JobFailedError
from shorty_py.types import JobStatus

from ._base import AsyncResource, SyncResource, as_mapping

#: The coarse job state ``normalize_job_status`` collapses the wire value into.
NormalizedJobStatus = Literal["QUEUED", "PROCESSING", "SUCCESS", "ERROR", "CANCELLED"]

DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_WAIT_TIMEOUT = 600.0

_SUCCESS = frozenset({"success", "completed", "done"})
_ERROR = frozenset({"error", "failed", "missing"})
_PROCESSING = frozenset({"processing", "running"})


def normalize_job_status(raw: object) -> NormalizedJobStatus:
    """Collapse the wire's un-normalized status string into a coarse state.

    Mirrors ``shorty-sdk/src/resources/jobs.ts`` exactly, including its
    fallback: anything unrecognized (or missing) reads as ``"QUEUED"`` rather
    than raising, so a new server status string never breaks a poll loop.
    """
    value = str("queued" if raw is None else raw).lower()
    if value in _SUCCESS:
        return "SUCCESS"
    if value == "cancelled":
        return "CANCELLED"
    if value in _ERROR:
        return "ERROR"
    if value in _PROCESSING:
        return "PROCESSING"
    return "QUEUED"


def _get_spec(
    *, job_id: str, timeout: float | None, headers: Mapping[str, str] | None
) -> RequestSpec:
    return RequestSpec(
        method="GET",
        path=f"/v1/jobs/{quote(job_id, safe='')}",
        timeout=timeout,
        headers=headers,
    )


def _terminal_or_none(status: JobStatus, job_id: str) -> JobStatus | None:
    """Return the status when the job is done, raise when it failed, else ``None``."""
    normalized = normalize_job_status(status.status)
    if normalized == "SUCCESS":
        return status
    if normalized in ("ERROR", "CANCELLED"):
        raise JobFailedError(
            job_id=status.jobId or job_id,
            status=status.status,
            error=status.error,
        )
    return None


class JobsResource(SyncResource):
    """Requires the ``jobs:read`` scope."""

    def get(
        self,
        job_id: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JobStatus:
        """``GET /v1/jobs/{jobId}`` — operation ``getJob``."""
        response = self._transport.request(
            _get_spec(job_id=job_id, timeout=timeout, headers=headers)
        )
        return JobStatus.from_wire(as_mapping(response.data))

    def wait_for(
        self,
        job_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        headers: Mapping[str, str] | None = None,
    ) -> JobStatus:
        """Poll until the job is terminal. **Client-side**, not a server feature.

        Returns the final :class:`~shorty_py.types.JobStatus` on success; raises
        :class:`~shorty_py.JobFailedError` on ``ERROR`` / ``CANCELLED`` (carrying
        the job's own error message) and :class:`~shorty_py.APITimeoutError` when
        the deadline elapses.
        """
        deadline = time.monotonic() + timeout
        while True:
            status = self.get(job_id, headers=headers)
            terminal = _terminal_or_none(status, job_id)
            if terminal is not None:
                return terminal
            if time.monotonic() + poll_interval > deadline:
                raise APITimeoutError(f"Timed out waiting for job {job_id} after {timeout}s.")
            time.sleep(poll_interval)


class AsyncJobsResource(AsyncResource):
    """Requires the ``jobs:read`` scope."""

    async def get(
        self,
        job_id: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JobStatus:
        """``GET /v1/jobs/{jobId}`` — operation ``getJob``."""
        response = await self._transport.request(
            _get_spec(job_id=job_id, timeout=timeout, headers=headers)
        )
        return JobStatus.from_wire(as_mapping(response.data))

    async def wait_for(
        self,
        job_id: str,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        headers: Mapping[str, str] | None = None,
    ) -> JobStatus:
        """Async mirror of :meth:`JobsResource.wait_for` — same defaults, same raises."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            status = await self.get(job_id, headers=headers)
            terminal = _terminal_or_none(status, job_id)
            if terminal is not None:
                return terminal
            if loop.time() + poll_interval > deadline:
                raise APITimeoutError(f"Timed out waiting for job {job_id} after {timeout}s.")
            await asyncio.sleep(poll_interval)
