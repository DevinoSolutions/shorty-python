"""Resource namespaces hung off :class:`~shorty_py.Shorty` / :class:`~shorty_py.AsyncShorty`."""

from __future__ import annotations

from .articles import ArticlesResource, AsyncArticlesResource
from .jobs import AsyncJobsResource, JobsResource, NormalizedJobStatus, normalize_job_status
from .subtitles import AsyncSubtitlesResource, SubtitlesResource
from .summaries import AsyncSummariesResource, SummariesResource
from .transcriptions import AsyncTranscriptionsResource, TranscriptionsResource
from .usage import AsyncUsageResource, UsageResource

__all__ = [
    "ArticlesResource",
    "AsyncArticlesResource",
    "AsyncJobsResource",
    "AsyncSubtitlesResource",
    "AsyncSummariesResource",
    "AsyncTranscriptionsResource",
    "AsyncUsageResource",
    "JobsResource",
    "NormalizedJobStatus",
    "SubtitlesResource",
    "SummariesResource",
    "TranscriptionsResource",
    "UsageResource",
    "normalize_job_status",
]
