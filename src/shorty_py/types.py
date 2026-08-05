"""Wire DTOs for the Shorty ``/v1`` surface.

Hand-written to match ``shortyapi/src/openapi/v1.json`` component schemas
exactly. Two rules govern every model here:

**1. Field names are the WIRE names.** No renaming. The article/transcription
families are ``snake_case`` (``has_more``, ``next_cursor``, ``source_url``); the
usage and job-status families are ``camelCase`` (``planName``, ``jobId``). That
asymmetry is the server's, and mirroring it means a debugger session matches the
API reference line for line.

**2. Forward compatibility is mandatory.** Every model keeps an ``extra`` bag of
unknown keys and NEVER raises on them, and every field carries a default so a
partial payload degrades instead of exploding. The server's spec sets
``additionalProperties: false`` on *requests*; responses may grow at any time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, TypedDict, TypeVar, cast

__all__ = [
    "Article",
    "ArticleDetail",
    "ArticleListResponse",
    "ArticleSearchResponse",
    "ArticleSummary",
    "ArticleSummaryPart",
    "CreateSubtitlesBody",
    "CreateSummaryBody",
    "CreateSummaryTextBody",
    "CreateSummaryUrlBody",
    "CreateSummaryYoutubeBody",
    "CreateTranscriptionBody",
    "FieldError",
    "JobAccepted",
    "JobStatus",
    "ProblemBody",
    "RateLimit",
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
]

_T = TypeVar("_T", bound="_Wire")

_EMPTY: Mapping[str, Any] = MappingProxyType({})


class _Wire:
    """Mixin giving every DTO a forgiving ``from_wire`` constructor."""

    __slots__ = ()

    @classmethod
    def _field_names(cls) -> frozenset[str]:
        # Read the dataclass registry off the concrete subclass; the mixin
        # itself is not a dataclass, so this is a lookup, not `fields(cls)`.
        declared: Mapping[str, Any] = getattr(cls, "__dataclass_fields__", {})
        return frozenset(name for name in declared if name != "extra")

    @classmethod
    def from_wire(cls: type[_T], data: Mapping[str, Any] | None) -> _T:
        """Build the model from a decoded JSON object.

        Unknown keys land in ``extra``; missing keys fall back to the field
        default. Never raises on a shape the SDK does not recognize.
        """
        payload: Mapping[str, Any] = data or {}
        known = cls._field_names()
        kwargs = {k: v for k, v in payload.items() if k in known}
        extra = {k: v for k, v in payload.items() if k not in known}
        construct = cast("Callable[..., _T]", cls)
        return construct(**kwargs, extra=MappingProxyType(extra))


def _extra() -> Any:
    return field(default=_EMPTY)


# ---------------------------------------------------------------------------
# Errors (RFC 9457 problem document — mirrors the server's ProblemSchema)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldError(_Wire):
    """One field-level validation error from a ``validation_failed`` problem."""

    #: JSON-pointer-ish path to the offending input field, e.g. ``"#/body/url"``.
    pointer: str = ""
    #: Machine-readable validation code from the validator.
    code: str = ""
    #: Human-readable explanation of this field error.
    message: str = ""
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class ProblemBody(_Wire):
    """The RFC 9457 problem document every ``/v1`` route returns on error."""

    #: Dereferenceable URI, ``https://aishorty.com/docs/api/errors/<code>``.
    type: str = ""
    title: str = ""
    status: int = 0
    detail: str | None = None
    instance: str = ""
    #: The stable machine identifier clients switch on.
    code: str = ""
    request_id: str = ""
    errors: Sequence[FieldError] = ()
    extra: Mapping[str, Any] = _extra()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any] | None) -> ProblemBody:
        payload: Mapping[str, Any] = data or {}
        known = cls._field_names()
        kwargs = {k: v for k, v in payload.items() if k in known}
        raw_errors = kwargs.pop("errors", None)
        errors: tuple[FieldError, ...] = ()
        if isinstance(raw_errors, list):
            errors = tuple(FieldError.from_wire(e) for e in raw_errors if isinstance(e, Mapping))
        extra = {k: v for k, v in payload.items() if k not in known}
        return cls(**kwargs, errors=errors, extra=MappingProxyType(extra))


# ---------------------------------------------------------------------------
# Rate limiting (IETF draft-11 + legacy X-RateLimit-*)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RateLimit:
    """Parsed rate-limit signal from a response's headers.

    Populated from the IETF draft-11 ``RateLimit`` / ``RateLimit-Policy``
    structured fields when present, and from the legacy ``X-RateLimit-*`` trio
    otherwise. Any field may be ``None`` — the server does not always emit every
    one, and a live limiter is still being wired up server-side.
    """

    #: Policy name, e.g. ``"default"`` (the sf-string key in both headers).
    name: str | None = None
    #: ``q=`` from ``RateLimit-Policy``, else ``X-RateLimit-Limit``.
    limit: int | None = None
    #: ``r=`` from ``RateLimit``, else ``X-RateLimit-Remaining``.
    remaining: int | None = None
    #: ``t=`` from ``RateLimit`` — seconds until the window resets.
    reset_seconds: int | None = None
    #: ``X-RateLimit-Reset`` — absolute UNIX epoch seconds.
    reset_at: int | None = None
    #: ``w=`` from ``RateLimit-Policy`` — the window length in seconds.
    window_seconds: int | None = None


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UsagePlan(_Wire):
    """The account's plan tier (``free`` / ``subscriber`` / ``pro``)."""

    tier: str = ""
    planName: str = ""
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class UsageSubscription(_Wire):
    """Subscription state, including trial and renewal information."""

    isSubscribed: bool = False
    isProSubscriber: bool = False
    isOnTrial: bool = False
    trialEndsAt: str | None = None
    expiresAt: str | None = None
    willRenew: bool | None = None
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class UsageTranscriptionLimits(_Wire):
    """Upload-size and realtime-duration caps for transcription."""

    maxUploadSizeGb: float = 0.0
    maxUploadSizeLabel: str = ""
    realtimeMaxDurationMinutes: float = 0.0
    realtimeMaxDurationLabel: str = ""
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class UsageConversionLimits(_Wire):
    """File-size, batch, and cloud-queue caps for conversions."""

    maxFileSizeMb: float = 0.0
    maxFileSizeLabel: str = ""
    maxBatchItems: int = 0
    canUseManagedQueue: bool = False
    dailyCloudQuota: int | None = None
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class UsageLimits(_Wire):
    """The plan's limits, split by feature family."""

    transcription: UsageTranscriptionLimits = field(default_factory=UsageTranscriptionLimits)
    conversion: UsageConversionLimits = field(default_factory=UsageConversionLimits)
    extra: Mapping[str, Any] = _extra()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any] | None) -> UsageLimits:
        payload: Mapping[str, Any] = data or {}
        extra = {k: v for k, v in payload.items() if k not in cls._field_names()}
        return cls(
            transcription=UsageTranscriptionLimits.from_wire(payload.get("transcription")),
            conversion=UsageConversionLimits.from_wire(payload.get("conversion")),
            extra=MappingProxyType(extra),
        )


@dataclass(frozen=True, slots=True)
class UsageCounters(_Wire):
    """Rolling usage counters for the current period."""

    cloudConversionsUsedLast24h: int = 0
    cloudConversionsRemaining: int | None = None
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class UsageResponse(_Wire):
    """``GET /v1/usage`` — plan, subscription, limits, and counters."""

    plan: UsagePlan = field(default_factory=UsagePlan)
    subscription: UsageSubscription = field(default_factory=UsageSubscription)
    limits: UsageLimits = field(default_factory=UsageLimits)
    usage: UsageCounters = field(default_factory=UsageCounters)
    extra: Mapping[str, Any] = _extra()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any] | None) -> UsageResponse:
        payload: Mapping[str, Any] = data or {}
        extra = {k: v for k, v in payload.items() if k not in cls._field_names()}
        return cls(
            plan=UsagePlan.from_wire(payload.get("plan")),
            subscription=UsageSubscription.from_wire(payload.get("subscription")),
            limits=UsageLimits.from_wire(payload.get("limits")),
            usage=UsageCounters.from_wire(payload.get("usage")),
            extra=MappingProxyType(extra),
        )


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Article(_Wire):
    """An article summary row (list + search results)."""

    id: str = ""
    title: str | None = None
    description: str | None = None
    #: ``YOUTUBE_ARTICLE`` / ``WEBPAGE_ARTICLE`` / ``PDF_ARTICLE`` /
    #: ``WORD_ARTICLE`` / ``TEXT_ARTICLE`` / ``AUDIO_ARTICLE``. Kept as a plain
    #: ``str`` so a new server enum member never breaks a typed client.
    article_type: str = ""
    source_url: str | None = None
    created_at: str = ""
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class ArticleSummaryPart(_Wire):
    """One ordered section of a generated summary."""

    title: str | None = None
    content: str | None = None
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class ArticleSummary(_Wire):
    """The generated summary: an ordered list of parts."""

    parts: Sequence[ArticleSummaryPart] = ()
    extra: Mapping[str, Any] = _extra()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any] | None) -> ArticleSummary:
        payload: Mapping[str, Any] = data or {}
        extra = {k: v for k, v in payload.items() if k not in cls._field_names()}
        raw = payload.get("parts")
        parts = (
            tuple(ArticleSummaryPart.from_wire(p) for p in raw if isinstance(p, Mapping))
            if isinstance(raw, list)
            else ()
        )
        return cls(parts=parts, extra=MappingProxyType(extra))


@dataclass(frozen=True, slots=True)
class ArticleDetail(_Wire):
    """``GET /v1/articles/{id}`` — an article with its summary and source text."""

    id: str = ""
    title: str | None = None
    description: str | None = None
    article_type: str = ""
    source_url: str | None = None
    created_at: str = ""
    summary: ArticleSummary | None = None
    body_text: str | None = None
    extra: Mapping[str, Any] = _extra()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any] | None) -> ArticleDetail:
        payload: Mapping[str, Any] = data or {}
        known = cls._field_names()
        kwargs = {k: v for k, v in payload.items() if k in known}
        raw_summary = kwargs.pop("summary", None)
        summary = (
            ArticleSummary.from_wire(raw_summary) if isinstance(raw_summary, Mapping) else None
        )
        extra = {k: v for k, v in payload.items() if k not in known}
        return cls(**kwargs, summary=summary, extra=MappingProxyType(extra))


@dataclass(frozen=True, slots=True)
class ArticleListResponse(_Wire):
    """The cursor-paginated ``GET /v1/articles`` envelope."""

    data: Sequence[Article] = ()
    has_more: bool = False
    next_cursor: str | None = None
    extra: Mapping[str, Any] = _extra()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any] | None) -> ArticleListResponse:
        payload: Mapping[str, Any] = data or {}
        extra = {k: v for k, v in payload.items() if k not in cls._field_names()}
        rows = payload.get("data")
        return cls(
            data=tuple(Article.from_wire(r) for r in rows if isinstance(r, Mapping))
            if isinstance(rows, list)
            else (),
            has_more=bool(payload.get("has_more", False)),
            next_cursor=payload.get("next_cursor"),
            extra=MappingProxyType(extra),
        )


@dataclass(frozen=True, slots=True)
class ArticleSearchResponse(_Wire):
    """``GET /v1/articles/search`` — relevance-ranked, NOT cursor-paginated."""

    data: Sequence[Article] = ()
    #: Number of hits returned.
    count: int = 0
    extra: Mapping[str, Any] = _extra()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any] | None) -> ArticleSearchResponse:
        payload: Mapping[str, Any] = data or {}
        extra = {k: v for k, v in payload.items() if k not in cls._field_names()}
        rows = payload.get("data")
        return cls(
            data=tuple(Article.from_wire(r) for r in rows if isinstance(r, Mapping))
            if isinstance(rows, list)
            else (),
            count=int(payload.get("count", 0) or 0),
            extra=MappingProxyType(extra),
        )


# ---------------------------------------------------------------------------
# Transcriptions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Transcription(_Wire):
    """A transcription row (``PENDING`` / ``PROCESSING`` / ``SUCCESS`` / ``ERROR``)."""

    id: str = ""
    status: str = ""
    progress: float = 0.0
    model_type: str = ""
    language: str | None = None
    input_file: str = ""
    error: str | None = None
    created_at: str = ""
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class TranscriptionDetail(_Wire):
    """``GET /v1/transcriptions/{id}`` — a transcription plus its output text."""

    id: str = ""
    status: str = ""
    progress: float = 0.0
    model_type: str = ""
    language: str | None = None
    input_file: str = ""
    error: str | None = None
    created_at: str = ""
    output_text: str | None = None
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class TranscriptionListResponse(_Wire):
    """The cursor-paginated ``GET /v1/transcriptions`` envelope."""

    data: Sequence[Transcription] = ()
    has_more: bool = False
    next_cursor: str | None = None
    extra: Mapping[str, Any] = _extra()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any] | None) -> TranscriptionListResponse:
        payload: Mapping[str, Any] = data or {}
        extra = {k: v for k, v in payload.items() if k not in cls._field_names()}
        rows = payload.get("data")
        return cls(
            data=tuple(Transcription.from_wire(r) for r in rows if isinstance(r, Mapping))
            if isinstance(rows, list)
            else (),
            has_more=bool(payload.get("has_more", False)),
            next_cursor=payload.get("next_cursor"),
            extra=MappingProxyType(extra),
        )


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JobAccepted(_Wire):
    """The ``202 Accepted`` body every async write returns."""

    job_id: str = ""
    status: str = ""
    #: Relative path to poll this job, e.g. ``/v1/jobs/{id}``.
    tracking_url: str = ""
    #: ``True`` when the server replayed a previous response for the same
    #: ``Idempotency-Key`` (from the ``Idempotency-Replayed`` header). Not a
    #: wire field of the body.
    idempotency_replayed: bool = False
    extra: Mapping[str, Any] = _extra()


@dataclass(frozen=True, slots=True)
class JobStatus(_Wire):
    """``GET /v1/jobs/{id}`` — the nested **camelCase** job payload.

    Pinned deliberately: the flat-vs-nested drift incidents are exactly why this
    must match the server's ``JobStatus`` schema byte for byte.
    """

    jobId: str = ""
    status: str = ""
    #: Completion fraction 0–100, when known.
    progress: float | None = None
    #: Human-readable current step, or ``None``.
    step: str | None = None
    #: Error message if the job failed, or ``None``.
    error: str | None = None
    #: Job-type-specific extras (``jobType``, ``title``, ``articleId``, …).
    output: Mapping[str, Any] = _extra()
    extra: Mapping[str, Any] = _extra()


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubtitleDownload(_Wire):
    """``GET /v1/subtitles/{jobId}/download`` — a short-lived presigned URL."""

    url: str = ""
    #: ISO-8601 UTC timestamp the presigned URL expires.
    expires_at: str = ""
    #: ``srt`` / ``vtt`` / ``ass`` subtitle file, or ``burned`` (an mp4).
    kind: str = ""
    filename: str = ""
    extra: Mapping[str, Any] = _extra()


# ---------------------------------------------------------------------------
# Summaries — the dual 200/202 result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SummaryAlreadyComplete(_Wire):
    """``POST /v1/summaries`` → **200**: a cache hit, no job was started."""

    #: Always ``"already_complete"``.
    status: str = "already_complete"
    #: Fetch the finished article at ``GET /v1/articles/{article_id}``.
    article_id: str = ""
    idempotency_replayed: bool = False
    extra: Mapping[str, Any] = _extra()

    @property
    def is_complete(self) -> bool:
        """``True`` — the summary already existed; nothing to poll."""
        return True


@dataclass(frozen=True, slots=True)
class SummaryAccepted(_Wire):
    """``POST /v1/summaries`` → **202**: a summarization job was queued."""

    #: ``None`` when the job was accepted but is not trackable.
    job_id: str | None = None
    status: str = ""
    #: ``None`` when tracking is unavailable.
    tracking_url: str | None = None
    #: Present only on the accepted-but-untrackable case, so the caller can
    #: still locate the result at ``GET /v1/articles/{id}``.
    article_id: str | None = None
    idempotency_replayed: bool = False
    extra: Mapping[str, Any] = _extra()

    @property
    def is_complete(self) -> bool:
        """``False`` — poll ``jobs.get`` / ``jobs.wait_for`` for the result."""
        return False


#: What :meth:`shorty_py.resources.summaries.SummariesResource.create` returns.
#: Branch on ``.is_complete`` rather than on the concrete type.
SummaryResult = SummaryAccepted | SummaryAlreadyComplete


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
#
# TypedDicts, not dataclasses: these go OUT on the wire as plain JSON objects,
# and the server sets ``additionalProperties: false`` on every request schema —
# so an extra key is a 400, and a TypedDict is exactly the shape that catches it
# at type-check time. Optional keys live on a ``total=False`` base so this stays
# Python 3.10-compatible (``NotRequired`` is 3.11+).


class _LanguageOptional(TypedDict, total=False):
    #: Language name (``"english"``) or ISO-639-1 code (``"en"``). Server
    #: default: ``english``.
    language: str


class CreateTranscriptionBody(_LanguageOptional):
    """``POST /v1/transcriptions`` body."""

    #: A URL to audio/video media to transcribe.
    url: str


class CreateSummaryYoutubeBody(_LanguageOptional):
    """``POST /v1/summaries`` body with ``source="youtube"``."""

    source: Literal["youtube"]
    #: A YouTube video URL.
    url: str


class CreateSummaryUrlBody(_LanguageOptional):
    """``POST /v1/summaries`` body with ``source="url"``."""

    source: Literal["url"]
    #: A web page / article URL to summarize.
    url: str


class _CreateSummaryTextOptional(_LanguageOptional, total=False):
    #: Optional title hint (reserved — currently derived by the summarizer).
    title: str


class CreateSummaryTextBody(_CreateSummaryTextOptional):
    """``POST /v1/summaries`` body with ``source="text"``."""

    source: Literal["text"]
    #: The raw text to summarize.
    content: str


#: Discriminated on ``source``: ``youtube`` | ``url`` | ``text``. The spec models
#: this as a ``oneOf`` with **no** ``discriminator`` keyword, which is why the
#: SDK also ships three named constructors on ``client.summaries``.
CreateSummaryBody = CreateSummaryYoutubeBody | CreateSummaryUrlBody | CreateSummaryTextBody


class _CreateSubtitlesOptional(_LanguageOptional, total=False):
    #: ``CLEAN`` is free; ``TIKTOK`` / ``PODCAST`` / ``MINIMAL`` need Premium.
    style: str
    #: Measured media duration. Lets the API reject over-cap media up front
    #: with a 413 instead of failing the job later.
    duration_seconds: float


class CreateSubtitlesBody(_CreateSubtitlesOptional):
    """``POST /v1/subtitles`` body."""

    #: A URL to the media to caption.
    url: str
