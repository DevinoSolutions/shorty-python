# shorty-py

[![CI](https://github.com/DevinoSolutions/shorty-python/actions/workflows/ci.yml/badge.svg)](https://github.com/DevinoSolutions/shorty-python/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/shorty-py.svg)](https://pypi.org/project/shorty-py/)
[![Python](https://img.shields.io/pypi/pyversions/shorty-py.svg)](https://pypi.org/project/shorty-py/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Official Python SDK for the **[Shorty](https://aishorty.com) API** — AI summarization,
transcription, and subtitling.

- All **11** `/v1` operations, **sync and async**
- One dependency (`httpx`), fully typed, ships `py.typed`
- Typed RFC 9457 errors, cursor pagination, automatic idempotency keys,
  jittered retries, Standard-Webhooks verification
- TypeScript sibling: [`@aishorty/sdk`](https://github.com/DevinoSolutions/shorty-sdk)

## Install

```bash
pip install shorty-py
```

Requires Python 3.10+.

## 60-second quickstart

```python
from shorty_py import Shorty

# Reads SHORTY_API_KEY from the environment.
with Shorty() as client:
    # What plan am I on, and what's left?
    usage = client.usage.get()
    print(usage.plan.tier, usage.usage.cloudConversionsRemaining)

    # Summarize a YouTube video.
    result = client.summaries.create_from_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    if result.is_complete:
        article = client.articles.get(result.article_id)  # cached: nothing to wait for
    else:
        client.jobs.wait_for(result.job_id)  # queued: poll to completion
        article = client.articles.get(client.jobs.get(result.job_id).output["articleId"])

    print(article.title)
```

## Authentication

Every `/v1` operation is authenticated. Pass a `shk_live_…` key explicitly, or set
`SHORTY_API_KEY` and let the client pick it up:

```python
client = Shorty("shk_live_...")  # explicit wins over the environment
client = Shorty()  # reads SHORTY_API_KEY, raises ValueError if unset
```

Keys carry **scopes** — `articles:read`, `articles:write`, `transcriptions:read`,
`transcriptions:write`, `jobs:read`, `usage:read`. A key without the scope an
operation needs gets a `403 insufficient_scope` **before** any quota is consumed.
OAuth 2.1 access tokens issued to connected apps use the same header, so they can be
passed to `Shorty(...)` unchanged.

The key never appears in `repr()`, is not an attribute of the client, and the client
refuses to be pickled or deep-copied:

```python
>>> repr(Shorty("shk_live_secret"))
"Shorty(base_url='https://aishorty.com')"
```

## Async

Every method has an async twin. `AsyncShorty` takes the same arguments.

```python
import asyncio
from shorty_py import AsyncShorty


async def main() -> None:
    async with AsyncShorty() as client:
        page = await client.articles.list(limit=50)
        async for article in page:  # walks every page
            print(article.id, article.title)


asyncio.run(main())
```

## Resources

### Usage — `client.usage`

```python
usage = client.usage.get()
usage.plan.tier  # "free" | "subscriber" | "pro"
usage.subscription.isOnTrial
usage.limits.transcription.maxUploadSizeLabel
usage.usage.cloudConversionsRemaining  # None = unlimited
```

### Articles — `client.articles`

```python
page = client.articles.list(limit=50)  # cursor-paginated
for article in page.auto_paging_iter():  # walks every page
    print(article.id, article.article_type)

hits = client.articles.search("transformers", limit=10)  # NOT paginated
print(hits.count, [a.title for a in hits.data])

detail = client.articles.get("a1b2c3d4")
for part in detail.summary.parts if detail.summary else []:
    print(part.title, part.content)
```

### Summaries — `client.summaries`

`POST /v1/summaries` returns **200 or 202**. 200 means this exact source was already
summarized and no job was started; 202 means a job was queued. Branch on
`.is_complete` rather than on the type:

```python
result = client.summaries.create_from_url("https://example.com/blog/post")
result = client.summaries.create_from_youtube("https://youtu.be/xyz", language="french")
result = client.summaries.create_from_text("Long text…", title="My note")

if result.is_complete:
    print("cached:", result.article_id)
else:
    print("queued:", result.job_id, result.tracking_url)
```

### Transcriptions — `client.transcriptions`

```python
accepted = client.transcriptions.create(url="https://example.com/podcast.mp3", language="english")
final = client.jobs.wait_for(accepted.job_id)
print(client.transcriptions.get("t1").output_text)

for row in client.transcriptions.list(limit=100).auto_paging_iter():
    print(row.id, row.status, row.progress)
```

### Subtitles — `client.subtitles`

Captioning is a create → poll → download loop. The download **409s with
`resource_not_ready` until the job finishes** — that is the normal pre-completion
state, not a failure, so poll the job rather than retrying the download:

```python
job = client.subtitles.create(
    url="https://example.com/clip.mp4",
    style="TIKTOK",  # CLEAN is free; TIKTOK/PODCAST/MINIMAL need Premium
    duration_seconds=542,  # optional: get a 413 up front instead of a failed job
)
client.jobs.wait_for(job.job_id)
artifact = client.subtitles.download(job.job_id, kind="srt")  # srt | vtt | ass | burned
print(artifact.url, artifact.expires_at)
```

### Jobs — `client.jobs`

```python
status = client.jobs.get("j1")  # nested camelCase: .jobId, .progress, .step
final = client.jobs.wait_for("j1", poll_interval=2.0, timeout=600.0)

from shorty_py import normalize_job_status

normalize_job_status(status.status)  # QUEUED | PROCESSING | SUCCESS | ERROR | CANCELLED
```

`wait_for` is a **client-side** loop. It returns the final status on success, raises
`JobFailedError` (carrying the job's own error) on `ERROR` / `CANCELLED`, and
`APITimeoutError` when the deadline elapses.

## Errors

Every non-2xx response becomes a typed exception carrying `.status`, `.code`,
`.problem_type`, `.title`, `.detail`, `.instance`, `.field_errors`, `.request_id`,
`.response_headers`, `.retry_after`, and `.rate_limit`.

```python
from shorty_py import NotFoundError, RateLimitError, ShortyError

try:
    client.articles.get("nope")
except NotFoundError as exc:
    print(exc.code, exc.request_id)  # "resource_not_found", "req_…"
except RateLimitError as exc:
    print(exc.retry_after)
except ShortyError as exc:  # base class for everything this SDK raises
    print(exc)
```

| `code` | Status | Exception |
|---|---|---|
| `unauthorized`, `invalid_api_key` | 401 | `AuthenticationError` |
| `insufficient_scope`, `feature_not_enabled` | 403 | `PermissionDeniedError` |
| `resource_not_found` | 404 | `NotFoundError` |
| `idempotency_conflict`, `idempotency_in_progress`, `resource_not_ready` | 409 | `ConflictError` |
| `validation_failed` | 400 | `ValidationError` |
| `request_too_large` | 413 | `ValidationError` |
| `idempotency_key_reused` | 422 | `ValidationError` |
| `rate_limited` | 429 | `RateLimitError` |
| `quota_exhausted` | 429 | `QuotaExhaustedError` |
| `service_unavailable` | 503 | `APIServerError` |
| `internal_error` | 500 | `APIServerError` |

Transport failures raise `APIConnectionError` / `APITimeoutError`. An unknown future
`code` never crashes the mapper: it degrades to the status-derived class with `.code`
preserved verbatim.

## Pagination

`articles.list` and `transcriptions.list` are cursor-paginated. `articles.search` is
relevance-ranked and returns a plain response, not a page.

```python
page = client.articles.list(limit=50)

for article in page:  # this page only
    ...
for article in page.auto_paging_iter():  # every page
    ...

while page:  # explicit walk
    for article in page.data:
        ...
    page = page.next_page()  # None on the last page
```

Paging reuses the original filters and only advances the opaque cursor — the server
binds cursors to the query they came from.

## Idempotency

All three writes are replay-safe. The SDK generates an `Idempotency-Key` (a UUID v4)
per logical call and reuses it across every retry, so a retried POST is deduplicated
server-side instead of starting a second billable job.

```python
client.transcriptions.create(url=...)  # auto key
client.transcriptions.create(url=..., idempotency_key="invoice-2026-08")  # your key
client.transcriptions.create(url=..., idempotency_key=None)  # opt out; never retried

accepted = client.summaries.create_from_url("https://example.com")
accepted.idempotency_replayed  # True when the server replayed a stored response
```

Reusing a key with a different body is a `422 idempotency_key_reused`; a concurrent
request with the same key is a `409 idempotency_in_progress`.

## Retries and rate limits

Defaults: `timeout=60.0` (**per attempt**), `max_retries=2`.

Retried: connection errors, per-attempt timeouts, `408`, `429 rate_limited`, and
`500` / `502` / `503` / `504`. **Never** retried: `429 quota_exhausted` (retrying a
blown quota is abuse), any other 4xx, and any POST without an idempotency key.

Delay is `Retry-After` when the server sends one (delta-seconds or HTTP-date, clamped
to 60 s), otherwise full-jitter backoff `random(0, min(0.5 · 2ⁿ, 8))` seconds.

```python
client = Shorty(timeout=30.0, max_retries=5)

client.usage.get()
client.last_rate_limit  # RateLimit(name=…, limit=…, remaining=…, reset_seconds=…)
```

Every authenticated `/v1` response carries the headers, so `last_rate_limit` is
populated after any successful call. It is `None` before the first request and when the
server refused before the limiter ran (e.g. a 401).

## Webhooks

Verify incoming Shorty webhooks (Standard Webhooks v1, `whsec_…` secrets, 5-minute
replay tolerance). **Pass the raw request body** — re-serializing the JSON changes the
bytes and verification will correctly fail.

```python
from shorty_py import verify_webhook_signature

result = verify_webhook_signature(
    payload=request.body,  # raw bytes/str, exactly as received
    headers=request.headers,  # webhook-id / webhook-timestamp / webhook-signature
    secret=os.environ["SHORTY_WEBHOOK_SECRET"],
)
if not result:
    return 400, result.reason  # missing_headers | malformed_timestamp |
    # timestamp_out_of_tolerance | no_matching_signature
```

Comparison is constant-time, and a header carrying several `v1,` tokens (a secret
rotation) passes if **any** of them matches.

## Escape hatch

```python
response = client.request("GET", "/v1/some-new-endpoint", query={"limit": 10})
response.status_code, response.data, response.headers, response.request_id
```

Same retry rules apply; a POST without `idempotency_key=` is never retried.

## Debugging

```python
client = Shorty(debug=True)  # method/path/status/attempt/request-id to stderr
client = Shorty(debug=logger.info)  # or your own sink
```

Headers and bodies are never logged, and every line is passed through the same
redaction that scrubs `shk_live_…`, `whsec_…`, and `Bearer …` from error messages.

## Contributing

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
ruff check . && ruff format --check . && ty check
pytest tests --ignore=tests/smoke
```

`tests/smoke` runs read-only calls against production and skips loudly without
`SHORTY_API_KEY`. `tests/test_parity.py` is the endpoint-coverage gate: it fails if
the vendored OpenAPI spec has an operation the SDK does not implement, or vice versa.

## License

MIT © Devino Solutions Inc.
