"""RFC 9457 problem documents map onto the typed exception hierarchy."""

from __future__ import annotations

import httpx
import pytest
import respx

from shorty_py import (
    APIError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExhaustedError,
    RateLimitError,
    Shorty,
    ValidationError,
)
from shorty_py.errors import APIServerError, create_api_error
from tests.conftest import BASE_URL, TEST_API_KEY, problem, problem_response

#: Every code in the server's registry (problemCodes.ts), with its status and
#: the exception class the SDK contracts to raise.
PROBLEM_CODE_REGISTRY = [
    ("unauthorized", 401, AuthenticationError),
    ("invalid_api_key", 401, AuthenticationError),
    ("insufficient_scope", 403, PermissionDeniedError),
    ("feature_not_enabled", 403, PermissionDeniedError),
    ("rate_limited", 429, RateLimitError),
    ("quota_exhausted", 429, QuotaExhaustedError),
    ("idempotency_conflict", 409, ConflictError),
    ("idempotency_in_progress", 409, ConflictError),
    ("idempotency_key_reused", 422, ValidationError),
    ("resource_not_found", 404, NotFoundError),
    ("resource_not_ready", 409, ConflictError),
    ("validation_failed", 400, ValidationError),
    ("request_too_large", 413, ValidationError),
    ("service_unavailable", 503, APIServerError),
    ("internal_error", 500, APIServerError),
]


def test_the_registry_under_test_covers_all_fifteen_documented_codes() -> None:
    assert len(PROBLEM_CODE_REGISTRY) == 15
    assert len({code for code, _, _ in PROBLEM_CODE_REGISTRY}) == 15


@pytest.mark.parametrize(("code", "status", "expected"), PROBLEM_CODE_REGISTRY)
def test_each_problem_code_maps_to_its_documented_exception_class(
    code: str, status: int, expected: type[APIError]
) -> None:
    error = create_api_error(status=status, body=problem(code, status))
    assert type(error) is expected
    assert error.code == code
    assert error.status == status
    assert error.problem_type == f"https://aishorty.com/docs/api/errors/{code}"


def test_quota_exhausted_is_a_rate_limit_error_so_broad_handlers_still_catch_it() -> None:
    error = create_api_error(status=429, body=problem("quota_exhausted", 429))
    assert isinstance(error, RateLimitError)
    assert type(error) is QuotaExhaustedError


def test_an_unknown_future_code_degrades_to_the_status_class_and_keeps_the_code() -> None:
    error = create_api_error(status=404, body=problem("some_future_code", 404))
    assert type(error) is NotFoundError
    assert error.code == "some_future_code"


def test_an_unknown_code_on_an_unmapped_status_falls_back_to_the_base_api_error() -> None:
    error = create_api_error(status=418, body=problem("teapot", 418))
    assert type(error) is APIError
    assert error.status == 418


def test_any_5xx_without_a_recognized_code_becomes_a_server_error() -> None:
    assert type(create_api_error(status=599, body=None, raw_text="")) is APIServerError


def test_a_non_json_body_does_not_crash_the_mapper_and_is_folded_into_detail() -> None:
    html = "<html><body>502 Bad Gateway from the edge</body></html>"
    error = create_api_error(status=502, body=None, raw_text=html)
    assert type(error) is APIServerError
    assert error.detail is not None
    assert "502 Bad Gateway" in error.detail
    assert error.title == "HTTP 502"


def test_an_oversized_non_json_body_is_truncated_before_it_reaches_the_message() -> None:
    error = create_api_error(status=500, body=None, raw_text="x" * 5000)
    assert error.detail is not None
    assert len(error.detail) == 500


def test_a_secret_in_a_server_error_body_is_redacted_from_the_message() -> None:
    error = create_api_error(status=500, body=None, raw_text="key shk_live_abc123 rejected")
    assert "shk_live_abc123" not in str(error)
    assert "shk_live_***" in str(error)


def test_field_errors_and_request_id_are_populated_from_the_problem_document() -> None:
    body = problem(
        "validation_failed",
        400,
        errors=[{"pointer": "#/body/url", "code": "invalid_url", "message": "Not a URL."}],
    )
    error = create_api_error(status=400, body=body)
    assert isinstance(error, ValidationError)
    assert error.request_id == "req_test_123"
    assert len(error.field_errors) == 1
    assert error.field_errors[0].pointer == "#/body/url"
    assert error.field_errors[0].code == "invalid_url"


def test_the_request_id_falls_back_to_the_response_header() -> None:
    error = create_api_error(
        status=500, body=None, headers={"Request-Id": "req_from_header"}, raw_text="boom"
    )
    assert error.request_id == "req_from_header"


def test_the_message_reads_title_detail_and_request_id() -> None:
    error = create_api_error(
        status=404, body=problem("resource_not_found", 404, title="Not found", detail="No article.")
    )
    assert str(error) == "Not found: No article. (req_test_123)"


def test_retry_after_is_parsed_onto_the_error() -> None:
    error = create_api_error(
        status=429, body=problem("rate_limited", 429), headers={"Retry-After": "12"}
    )
    assert error.retry_after == 12


def test_from_problem_is_available_as_a_classmethod_on_api_error() -> None:
    error = APIError.from_problem(403, problem("insufficient_scope", 403), {})
    assert type(error) is PermissionDeniedError


@respx.mock(base_url=BASE_URL)
def test_a_real_request_raises_the_mapped_exception_with_headers_attached(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/v1/articles/missing").mock(
        return_value=problem_response("resource_not_found", 404, title="Article not found")
    )
    with Shorty(TEST_API_KEY, max_retries=0) as client, pytest.raises(NotFoundError) as caught:
        client.articles.get("missing")

    error = caught.value
    assert error.code == "resource_not_found"
    assert error.status == 404
    assert error.response_headers["request-id"] == "req_test_123"
    assert error.instance == "/v1/usage"


@respx.mock(base_url=BASE_URL)
def test_a_transport_failure_becomes_an_api_connection_error(respx_mock: respx.MockRouter) -> None:
    from shorty_py import APIConnectionError

    respx_mock.get("/v1/usage").mock(side_effect=httpx.ConnectError("dns went away"))
    with Shorty(TEST_API_KEY, max_retries=0) as client, pytest.raises(APIConnectionError) as caught:
        client.usage.get()
    assert isinstance(caught.value.cause, httpx.ConnectError)


@respx.mock(base_url=BASE_URL)
def test_a_timeout_becomes_an_api_timeout_error(respx_mock: respx.MockRouter) -> None:
    from shorty_py import APITimeoutError

    respx_mock.get("/v1/usage").mock(side_effect=httpx.ReadTimeout("too slow"))
    with Shorty(TEST_API_KEY, max_retries=0) as client, pytest.raises(APITimeoutError):
        client.usage.get()
