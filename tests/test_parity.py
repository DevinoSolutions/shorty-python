"""The endpoint-coverage gate.

Reads the vendored OpenAPI 3.1 artifact and asserts that **every** ``operationId``
the server publishes is reachable through a declared SDK method — on both the
sync and the async client — and that the SDK claims no operation the spec no
longer has. This is what makes "endpoint parity with the TypeScript SDK" a
machine-checked property instead of a promise.

Regenerate the fixture from ``shortyapi/src/openapi/v1.json`` whenever the
server surface changes; ``spec-drift.yml`` fetches the live spec nightly and
files an issue when it moves ahead of this file.
"""

from __future__ import annotations

from typing import Any

import pytest

from shorty_py import AsyncShorty, Shorty
from tests.conftest import load_fixture

SPEC: dict[str, Any] = load_fixture("openapi-v1.json")

#: ``operationId`` -> (resource attribute, method name, HTTP method, path).
#: Hand-maintained on purpose: adding a row is a deliberate act that says
#: "this SDK method implements this server operation".
OPERATION_MAP: dict[str, tuple[str, str, str, str]] = {
    "getUsage": ("usage", "get", "get", "/v1/usage"),
    "listArticles": ("articles", "list", "get", "/v1/articles"),
    "searchArticles": ("articles", "search", "get", "/v1/articles/search"),
    "getArticle": ("articles", "get", "get", "/v1/articles/{articleId}"),
    "listTranscriptions": ("transcriptions", "list", "get", "/v1/transcriptions"),
    "createTranscription": ("transcriptions", "create", "post", "/v1/transcriptions"),
    "getTranscription": (
        "transcriptions",
        "get",
        "get",
        "/v1/transcriptions/{transcriptionId}",
    ),
    "getJob": ("jobs", "get", "get", "/v1/jobs/{jobId}"),
    "downloadSubtitles": ("subtitles", "download", "get", "/v1/subtitles/{jobId}/download"),
    "createSummary": ("summaries", "create", "post", "/v1/summaries"),
    "createSubtitles": ("subtitles", "create", "post", "/v1/subtitles"),
}


def spec_operations() -> dict[str, tuple[str, str]]:
    """``operationId`` -> (http method, path) for every operation in the spec."""
    found: dict[str, tuple[str, str]] = {}
    for path, operations in SPEC["paths"].items():
        for method, operation in operations.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = operation.get("operationId")
            assert operation_id, f"{method.upper()} {path} has no operationId"
            assert operation_id not in found, f"duplicate operationId {operation_id}"
            found[operation_id] = (method.lower(), path)
    return found


SPEC_OPERATIONS = spec_operations()


def test_the_vendored_spec_is_the_one_this_sdk_was_written_against() -> None:
    assert SPEC["openapi"] == "3.1.0"
    assert SPEC["servers"][0]["url"] == "https://aishorty.com"


def test_the_spec_publishes_exactly_eleven_operations() -> None:
    assert len(SPEC_OPERATIONS) == 11, sorted(SPEC_OPERATIONS)


def test_every_spec_operation_has_an_sdk_method_declared() -> None:
    """Direction 1: a new server operation must fail this until the SDK adds it."""
    missing = sorted(set(SPEC_OPERATIONS) - set(OPERATION_MAP))
    assert not missing, f"operations in the spec with no SDK method: {missing}"


def test_the_sdk_claims_no_operation_the_spec_no_longer_publishes() -> None:
    """Direction 2: a removed server operation must fail this until the SDK drops it."""
    stale = sorted(set(OPERATION_MAP) - set(SPEC_OPERATIONS))
    assert not stale, f"SDK methods claiming operations that no longer exist: {stale}"


def test_there_is_no_allowlist_of_unimplemented_operations() -> None:
    """The Phase 2 allowlist is deleted; 11/11 is the standing contract."""
    assert len(OPERATION_MAP) == 11


@pytest.mark.parametrize("operation_id", sorted(OPERATION_MAP))
def test_each_mapped_method_exists_and_is_callable_on_both_clients(operation_id: str) -> None:
    resource_name, method_name, http_method, path = OPERATION_MAP[operation_id]
    assert SPEC_OPERATIONS[operation_id] == (http_method, path), (
        f"{operation_id} moved: spec says {SPEC_OPERATIONS[operation_id]}, "
        f"the SDK map says {(http_method, path)}"
    )

    for client_cls in (Shorty, Shorty):  # constructed below; loop keeps the check symmetric
        assert hasattr(client_cls, "__init__")

    sync_client = Shorty("shk_live_paritycheck")
    async_client = AsyncShorty("shk_live_paritycheck")
    try:
        for client in (sync_client, async_client):
            resource = getattr(client, resource_name, None)
            assert resource is not None, f"{type(client).__name__} has no `{resource_name}`"
            method = getattr(resource, method_name, None)
            assert callable(method), (
                f"{type(client).__name__}.{resource_name}.{method_name} is not callable"
            )
    finally:
        sync_client.close()


@pytest.mark.parametrize("operation_id", sorted(OPERATION_MAP))
def test_each_operations_security_requirement_is_bearer_auth(operation_id: str) -> None:
    """Every /v1 operation is authenticated; the SDK has exactly one auth path."""
    http_method, path = SPEC_OPERATIONS[operation_id]
    operation = SPEC["paths"][path][http_method]
    security = operation.get("security", SPEC.get("security"))
    assert security, f"{operation_id} declares no security requirement"
    assert any("BearerApiKey" in requirement for requirement in security), security


def test_the_only_declared_security_scheme_is_bearer_http_auth() -> None:
    schemes = SPEC["components"]["securitySchemes"]
    assert set(schemes) == {"BearerApiKey"}
    assert schemes["BearerApiKey"]["type"] == "http"
    assert schemes["BearerApiKey"]["scheme"] == "bearer"


def test_only_the_three_writes_accept_an_idempotency_key_header() -> None:
    with_idempotency = {
        operation_id
        for operation_id, (method, path) in SPEC_OPERATIONS.items()
        if any(
            parameter.get("name") == "Idempotency-Key"
            for parameter in SPEC["paths"][path][method].get("parameters", [])
        )
    }
    assert with_idempotency == {"createTranscription", "createSummary", "createSubtitles"}


def test_create_summary_is_the_only_operation_with_a_dual_success_status() -> None:
    dual = {
        operation_id
        for operation_id, (method, path) in SPEC_OPERATIONS.items()
        if len(
            [
                status
                for status in SPEC["paths"][path][method]["responses"]
                if status.startswith("2")
            ]
        )
        > 1
    }
    assert dual == {"createSummary"}
