"""The typed RFC 9457 error hierarchy.

Mapping is **code-driven first** (the 15-code registry from the server's
``problemCodes.ts``), with a status-class fallback so an UNKNOWN future ``code``
never crashes the mapper — it maps by status instead and preserves ``.code``
verbatim. Every ``str(exc)`` is ``title: detail (request_id)`` and is redacted,
so an API key can never reach a traceback.

::

    ShortyError
    ├─ APIConnectionError
    │  └─ APITimeoutError
    ├─ APIError
    │  ├─ AuthenticationError      401
    │  ├─ PermissionDeniedError    403
    │  ├─ NotFoundError            404
    │  ├─ ConflictError            409
    │  ├─ ValidationError          400 / 413 / 422
    │  ├─ RateLimitError           429
    │  │  └─ QuotaExhaustedError   429 quota_exhausted (NOT retryable)
    │  └─ APIServerError           5xx
    └─ JobFailedError              client-side, from jobs.wait_for
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ._redaction import redact
from ._retry import parse_retry_after
from .types import FieldError, ProblemBody, RateLimit

__all__ = [
    "APIConnectionError",
    "APIError",
    "APIServerError",
    "APITimeoutError",
    "AuthenticationError",
    "ConflictError",
    "JobFailedError",
    "NotFoundError",
    "PermissionDeniedError",
    "QuotaExhaustedError",
    "RateLimitError",
    "ShortyError",
    "ValidationError",
    "create_api_error",
]


class ShortyError(Exception):
    """Base class for every error this SDK raises."""


class APIConnectionError(ShortyError):
    """A transport-level failure: DNS, connection refused, TLS, reset."""

    def __init__(self, message: str = "Connection error.", *, cause: BaseException | None = None):
        super().__init__(redact(message))
        #: The underlying ``httpx`` exception, kept for debugging.
        self.cause = cause


class APITimeoutError(APIConnectionError):
    """A per-attempt timeout elapsed, or a ``wait_for`` deadline was reached."""

    def __init__(self, message: str = "Request timed out."):
        super().__init__(message)


class JobFailedError(ShortyError):
    """A polled job ended in ``ERROR`` / ``CANCELLED``.

    Raised only by ``jobs.wait_for`` — it is a client-side outcome, not an HTTP
    failure, so it does not descend from :class:`APIError`.
    """

    def __init__(self, *, job_id: str, status: str, error: str | None = None):
        suffix = f": {error}" if error else ""
        super().__init__(redact(f'Job {job_id} ended in status "{status}"{suffix}'))
        self.job_id = job_id
        #: The un-normalized terminal status string (e.g. ``"error"``).
        self.status = status
        #: The job's own error message, if any.
        self.job_error = error


class APIError(ShortyError):
    """Any non-2xx response. The subclass is chosen by ``code``, then status."""

    def __init__(
        self,
        *,
        status: int,
        code: str | None = None,
        problem_type: str | None = None,
        title: str = "",
        detail: str | None = None,
        instance: str | None = None,
        request_id: str | None = None,
        field_errors: Sequence[FieldError] = (),
        response_headers: Mapping[str, str] | None = None,
        retry_after: float | None = None,
        rate_limit: RateLimit | None = None,
    ):
        base = f"{title}: {detail}" if detail else title
        message = f"{base} ({request_id})" if request_id else base
        super().__init__(redact(message or f"HTTP {status}"))
        #: HTTP status code.
        self.status = status
        #: The RFC 9457 ``code`` — the stable machine identifier to switch on.
        self.code = code
        #: The RFC 9457 ``type`` URI, dereferenceable to the error's doc page.
        self.problem_type = problem_type
        self.title = title
        self.detail = detail
        #: The RFC 9457 ``instance`` — this specific occurrence.
        self.instance = instance
        #: Quote this in a support ticket.
        self.request_id = request_id
        #: Per-field validation errors (``validation_failed`` only).
        self.field_errors = tuple(field_errors)
        #: All response headers, lowercased.
        self.response_headers: Mapping[str, str] = dict(response_headers or {})
        #: Parsed ``Retry-After``, in seconds.
        self.retry_after = retry_after
        #: Parsed rate-limit headers, when the server sent any.
        self.rate_limit = rate_limit

    @classmethod
    def from_problem(
        cls,
        status: int,
        body: Any,
        headers: Mapping[str, str] | None = None,
        *,
        raw_text: str | None = None,
        rate_limit: RateLimit | None = None,
    ) -> APIError:
        """Build the right :class:`APIError` subclass from a problem document.

        Delegates to :func:`create_api_error`; exposed as a classmethod because
        that is the discoverable spelling from the exception itself.
        """
        return create_api_error(
            status=status,
            body=body,
            headers=headers,
            raw_text=raw_text,
            rate_limit=rate_limit,
        )


class AuthenticationError(APIError):
    """401 — the key is missing, malformed, revoked, or unknown."""


class PermissionDeniedError(APIError):
    """403 — the key is valid but lacks the scope or the plan feature."""


class NotFoundError(APIError):
    """404 — no such resource, or it belongs to another account."""


class ConflictError(APIError):
    """409 — includes ``resource_not_ready``, the normal pre-completion state.

    A subtitle download 409s until the job finishes: poll ``jobs.get`` (or
    ``jobs.wait_for``) and download once the job reports success, rather than
    retrying the download blindly.
    """


class ValidationError(APIError):
    """400 / 413 / 422 — the request was rejected. Never retried."""


class APIServerError(APIError):
    """5xx. ``service_unavailable`` (503) is retryable; ``internal_error`` is not.

    503 means a known upstream (the GPU transcription service, the summary
    queue) refused to start the job — distinct from an unexpected throw.
    """


class RateLimitError(APIError):
    """429 ``rate_limited`` — slow down. Retried automatically."""


class QuotaExhaustedError(RateLimitError):
    """429 ``quota_exhausted`` — a period allowance is spent.

    A hard stop: retrying a blown quota is abuse, so the transport never
    retries this even though it shares the 429 status with a rate limit.
    """


#: ``code`` -> exception class. The primary mapping (the 15-code registry).
_CODE_TO_CLASS: Mapping[str, type[APIError]] = {
    "unauthorized": AuthenticationError,
    "invalid_api_key": AuthenticationError,
    "insufficient_scope": PermissionDeniedError,
    "feature_not_enabled": PermissionDeniedError,
    "rate_limited": RateLimitError,
    "quota_exhausted": QuotaExhaustedError,
    "idempotency_conflict": ConflictError,
    "idempotency_in_progress": ConflictError,
    "idempotency_key_reused": ValidationError,
    "resource_not_found": NotFoundError,
    "resource_not_ready": ConflictError,
    "validation_failed": ValidationError,
    "request_too_large": ValidationError,
    "service_unavailable": APIServerError,
    "internal_error": APIServerError,
}

#: Status -> exception class. The fallback when ``code`` is absent or unknown.
_STATUS_TO_CLASS: Mapping[int, type[APIError]] = {
    400: ValidationError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    413: ValidationError,
    422: ValidationError,
    # An unknown/absent code at 429 is treated as a plain rate limit, i.e.
    # retryable. QuotaExhaustedError only ever comes from the code map.
    429: RateLimitError,
}


def _class_by_status(status: int) -> type[APIError]:
    mapped = _STATUS_TO_CLASS.get(status)
    if mapped is not None:
        return mapped
    if status >= 500:
        return APIServerError
    return APIError


def create_api_error(
    *,
    status: int,
    body: Any = None,
    headers: Mapping[str, str] | None = None,
    raw_text: str | None = None,
    rate_limit: RateLimit | None = None,
) -> APIError:
    """Map an HTTP failure onto the right exception. **Never raises.**

    ``body`` is the decoded JSON body when the response was JSON, otherwise
    ``None``; ``raw_text`` is the undecoded text, used to fold a bounded,
    redacted snippet into ``detail`` when a proxy returns HTML instead of a
    problem document.
    """
    hdrs = {k.lower(): v for k, v in (headers or {}).items()}

    problem: ProblemBody | None = None
    if isinstance(body, Mapping) and isinstance(body.get("code"), str):
        problem = ProblemBody.from_wire(body)

    code = problem.code if problem is not None else None
    cls = _CODE_TO_CLASS.get(code or "") or _class_by_status(status)

    request_id = (problem.request_id if problem is not None else None) or hdrs.get("request-id")

    # Non-problem body (a proxy's 502 HTML, a Cloudflare page): keep a bounded,
    # redacted snippet so the failure is still legible.
    snippet: str | None = None
    if problem is None and raw_text is not None and raw_text.strip() != "":
        snippet = redact(raw_text[:500])

    return cls(
        status=status,
        code=code,
        problem_type=problem.type if problem is not None else None,
        title=(problem.title if problem is not None else "") or f"HTTP {status}",
        detail=(problem.detail if problem is not None else None) or snippet,
        instance=problem.instance if problem is not None else None,
        request_id=request_id or None,
        field_errors=problem.errors if problem is not None else (),
        response_headers=hdrs,
        retry_after=parse_retry_after(hdrs.get("retry-after")),
        rate_limit=rate_limit,
    )
