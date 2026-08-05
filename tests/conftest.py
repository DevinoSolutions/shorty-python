"""Shared fixtures and helpers for the unit suite.

Every test in this directory runs against ``respx`` — no network, no secrets.
The prod smoke tests live in ``tests/smoke`` and are excluded from the unit run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from shorty_py import AsyncShorty, Shorty

#: A syntactically real-looking key. Never a live credential.
TEST_API_KEY = "shk_live_TESTKEY0123456789abcdef"
BASE_URL = "https://aishorty.com"

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_ambient_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure a developer's real ``SHORTY_API_KEY`` cannot leak into a test."""
    monkeypatch.delenv("SHORTY_API_KEY", raising=False)


@pytest.fixture
def client() -> Iterator[Shorty]:
    with Shorty(TEST_API_KEY, max_retries=0) as c:
        yield c


@pytest.fixture
async def aclient() -> Any:
    async with AsyncShorty(TEST_API_KEY, max_retries=0) as c:
        yield c


def problem(
    code: str,
    status: int,
    *,
    title: str = "Something went wrong",
    detail: str | None = "Details here.",
    request_id: str = "req_test_123",
    errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build an RFC 9457 problem document exactly as the server emits one."""
    body: dict[str, Any] = {
        "type": f"https://aishorty.com/docs/api/errors/{code}",
        "title": title,
        "status": status,
        "instance": "/v1/usage",
        "code": code,
        "request_id": request_id,
    }
    if detail is not None:
        body["detail"] = detail
    if errors is not None:
        body["errors"] = errors
    return body


def problem_response(code: str, status: int, **kwargs: Any) -> httpx.Response:
    return httpx.Response(
        status,
        json=problem(code, status, **kwargs),
        headers={"content-type": "application/problem+json", "request-id": "req_test_123"},
    )


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
