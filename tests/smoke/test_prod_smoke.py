"""Read-only smoke tests against the real Shorty production API.

These run against **https://aishorty.com** with a real ``shk_live_`` key and are
excluded from the unit run (``pytest tests --ignore=tests/smoke``).

They are gated on ``SHORTY_API_KEY``. When it is absent every test **SKIPS
LOUDLY** rather than passing silently — a skipped smoke test is not a green
smoke test, and the reason string says so.

**Scope: reads only.** No POST is exercised here. Writes would burn GPU quota
and create junk records on every push, so write-path coverage lives in the unit
suite against ``respx``. Revisit only if a dedicated non-billing test tenant
exists. The key this job uses should be scoped to ``usage:read``,
``articles:read``, ``jobs:read`` and nothing else.
"""

from __future__ import annotations

import os

import httpx
import pytest

from shorty_py import AuthenticationError, NotFoundError, Shorty

API_KEY = os.environ.get("SHORTY_API_KEY")
BASE_URL = os.environ.get("SHORTY_BASE_URL", "https://aishorty.com")

pytestmark = pytest.mark.skipif(
    not API_KEY,
    reason=(
        "LOUD SKIP: SHORTY_API_KEY is not set, so the real prod smoke tests cannot "
        "run. Set SHORTY_API_KEY to a read-only shk_live_ key (scopes: usage:read, "
        "articles:read, jobs:read) to exercise GET /v1/usage, GET /v1/articles, the "
        "RFC 9457 error contract, and the OpenAPI drift gate against "
        "https://aishorty.com."
    ),
)


@pytest.fixture(scope="module")
def client() -> Shorty:
    with Shorty(API_KEY, base_url=BASE_URL, timeout=30.0) as c:
        yield c


def test_usage_returns_the_accounts_plan_limits_and_counters(client: Shorty) -> None:
    usage = client.usage.get()

    assert isinstance(usage.plan.tier, str)
    assert usage.plan.tier != ""
    assert isinstance(usage.plan.planName, str)
    assert isinstance(usage.subscription.isSubscribed, bool)
    assert isinstance(usage.limits.transcription.maxUploadSizeGb, (int, float))
    assert isinstance(usage.limits.conversion.maxBatchItems, int)
    assert isinstance(usage.usage.cloudConversionsUsedLast24h, int)


def test_rate_limit_headers_parse_when_the_server_sends_them(client: Shorty) -> None:
    """Conditional on purpose.

    ``rateLimitHeaders.ts`` states the serializer is not wired to a live limiter
    yet, so requiring the headers here would fail for a *server* reason. Assert
    the parse is correct **if** they are present, and tighten this to a hard
    requirement once the limiter ships.
    """
    client.usage.get()
    rate_limit = client.last_rate_limit
    if rate_limit is None:
        pytest.skip(
            "LOUD SKIP: the server sent no RateLimit / X-RateLimit-* headers on "
            "GET /v1/usage. Expected until the server-side limiter is wired up; "
            "make this assertion unconditional once it is."
        )
    for value in (rate_limit.limit, rate_limit.remaining):
        assert value is None or isinstance(value, int)
    if rate_limit.limit is not None and rate_limit.remaining is not None:
        assert rate_limit.remaining <= rate_limit.limit


def test_listing_articles_returns_the_documented_cursor_envelope(client: Shorty) -> None:
    page = client.articles.list(limit=1)

    assert isinstance(page.has_more, bool)
    assert page.next_cursor is None or isinstance(page.next_cursor, str)
    assert len(page.data) <= 1
    for article in page.data:
        assert isinstance(article.id, str) and article.id
        assert isinstance(article.article_type, str)
        assert isinstance(article.created_at, str)


def test_an_unknown_article_id_produces_the_rfc_9457_not_found_contract(
    client: Shorty,
) -> None:
    """Proves the problem-document mapping against the real server, not a fixture."""
    with pytest.raises(NotFoundError) as caught:
        client.articles.get("shorty-py-smoke-does-not-exist-00000000")

    error = caught.value
    assert error.status == 404
    assert error.code == "resource_not_found"
    assert error.problem_type is not None
    assert error.problem_type.startswith("https://aishorty.com/docs/api/errors/")
    assert error.request_id, "every error must carry a request id for support"


def test_a_bad_key_is_rejected_as_an_authentication_error() -> None:
    with Shorty("shk_live_definitely-not-a-real-key", base_url=BASE_URL) as bad_client:
        with pytest.raises(AuthenticationError) as caught:
            bad_client.usage.get()

    assert caught.value.status == 401
    assert caught.value.code in {"unauthorized", "invalid_api_key"}


def test_the_live_spec_still_matches_the_vendored_fixture(client: Shorty) -> None:
    """The drift gate: a new server operation must not silently desync the SDK."""
    from tests.test_parity import OPERATION_MAP, SPEC_OPERATIONS

    response = httpx.get(f"{BASE_URL}/api/openapi", timeout=30.0)
    assert response.status_code == 200
    live = response.json()
    assert live["openapi"] == "3.1.0"

    live_operations = {
        operation["operationId"]
        for path, methods in live["paths"].items()
        for method, operation in methods.items()
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }

    assert live_operations == set(SPEC_OPERATIONS), (
        "the live spec's operation set differs from tests/fixtures/openapi-v1.json — "
        "re-vendor the fixture and extend the SDK"
    )
    assert live_operations == set(OPERATION_MAP)
