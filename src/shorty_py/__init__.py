"""Official Python SDK for the Shorty API (https://aishorty.com).

Shorty is an AI media-summarization, transcription, and subtitling product. This
package is a hand-written, dependency-light (``httpx`` only) client for its
public ``/v1`` REST surface — all 11 operations, sync and async.

::

    from shorty_py import Shorty

    with Shorty() as client:                     # reads SHORTY_API_KEY
        job = client.subtitles.create(url="https://example.com/clip.mp4")
        client.jobs.wait_for(job.job_id)
        artifact = client.subtitles.download(job.job_id, kind="srt")
        print(artifact.url)
"""

from __future__ import annotations

from ._client import API_KEY_ENV_VAR, AsyncShorty, Shorty
from ._pagination import AsyncPage, Page
from ._transport import APIResponse, RequestSpec, parse_rate_limit
from ._version import __version__
from .errors import (
    APIConnectionError,
    APIError,
    APIServerError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    JobFailedError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExhaustedError,
    RateLimitError,
    ShortyError,
    ValidationError,
)
from .resources.jobs import NormalizedJobStatus, normalize_job_status
from .types import (
    Article,
    ArticleDetail,
    ArticleListResponse,
    ArticleSearchResponse,
    ArticleSummary,
    ArticleSummaryPart,
    CreateSubtitlesBody,
    CreateSummaryBody,
    CreateSummaryTextBody,
    CreateSummaryUrlBody,
    CreateSummaryYoutubeBody,
    CreateTranscriptionBody,
    FieldError,
    JobAccepted,
    JobStatus,
    ProblemBody,
    RateLimit,
    SubtitleDownload,
    SummaryAccepted,
    SummaryAlreadyComplete,
    SummaryResult,
    Transcription,
    TranscriptionDetail,
    TranscriptionListResponse,
    UsageConversionLimits,
    UsageCounters,
    UsageLimits,
    UsagePlan,
    UsageResponse,
    UsageSubscription,
    UsageTranscriptionLimits,
)
from .webhooks import (
    DEFAULT_TOLERANCE_SECONDS,
    WebhookVerifyFailure,
    WebhookVerifyResult,
    verify_webhook_signature,
)

__all__ = [
    "API_KEY_ENV_VAR",
    "DEFAULT_TOLERANCE_SECONDS",
    "APIConnectionError",
    "APIError",
    "APIResponse",
    "APIServerError",
    "APITimeoutError",
    "Article",
    "ArticleDetail",
    "ArticleListResponse",
    "ArticleSearchResponse",
    "ArticleSummary",
    "ArticleSummaryPart",
    "AsyncPage",
    "AsyncShorty",
    "AuthenticationError",
    "ConflictError",
    "CreateSubtitlesBody",
    "CreateSummaryBody",
    "CreateSummaryTextBody",
    "CreateSummaryUrlBody",
    "CreateSummaryYoutubeBody",
    "CreateTranscriptionBody",
    "FieldError",
    "JobAccepted",
    "JobFailedError",
    "JobStatus",
    "NormalizedJobStatus",
    "NotFoundError",
    "Page",
    "PermissionDeniedError",
    "ProblemBody",
    "QuotaExhaustedError",
    "RateLimit",
    "RateLimitError",
    "RequestSpec",
    "Shorty",
    "ShortyError",
    "SubtitleDownload",
    "SummaryAccepted",
    "SummaryAlreadyComplete",
    "SummaryResult",
    "Transcription",
    "TranscriptionDetail",
    "TranscriptionListResponse",
    "UsageConversionLimits",
    "UsageCounters",
    "UsageLimits",
    "UsagePlan",
    "UsageResponse",
    "UsageSubscription",
    "UsageTranscriptionLimits",
    "ValidationError",
    "WebhookVerifyFailure",
    "WebhookVerifyResult",
    "__version__",
    "normalize_job_status",
    "parse_rate_limit",
    "verify_webhook_signature",
]
