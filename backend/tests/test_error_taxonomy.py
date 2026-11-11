# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Contract and integration tests for the immutable YRV-XXX-YYY error taxonomy (#51).

Verifies:
1. Schema, uniqueness, block-to-category alignment, and immutability of resources/errors.yaml.
2. YarvelleError lazy {} formatting, __cause__ chaining, context redaction, RFC 7807
   Problem Details, and MCP JSON-RPC 2.0 error mapping.
3. Unification of vault, connector, agent, and pack subsystem exceptions onto YarvelleError.
4. ToolResult structured error_code, retryable classification, and execute_tool_call mapping.
5. FastAPI ProblemDetailsRoute + create_app / register_error_handlers emitting
   application/problem+json, zero HTTPException usage in yarvelle_core, and zero 500 string leaks.
6. Disjoint pack error-prefix registration (<PREFIX>-XXX-YYY) via register_pack_error_catalog
   and PackSpec / ResourceLoader.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
import pytest
import yaml

from yarvelle_core.agents.errors import (
    AgentNotFoundError,
    DuplicateAgentError,
    SubagentHookError,
)
from yarvelle_core.api import (
    PROBLEM_JSON_MEDIA_TYPE,
    ProblemDetailsRoute,
    api_router,
    create_app,
    register_error_handlers,
)
from yarvelle_core.connectors.errors import (
    AuthExpiredError,
    ConnectorError,
    EgressBlockedError,
    ManifestValidationError,
)
from yarvelle_core.connectors.mcp_remote import McpSchemaDriftError
from yarvelle_core.engine.tool_exec import ToolContext, execute_tool_call
from yarvelle_core.engine.tool_registry import DataFlows, ToolSpec
from yarvelle_core.errors import (
    API_VERSION_ERRORS_V1,
    BLOCK_TO_CATEGORY,
    ERROR_CODE_PATTERN,
    REDACTED_VALUE,
    RESERVED_CORE_ERROR_PREFIX,
    ErrorCatalog,
    ErrorCatalogRegistrationError,
    ErrorCodeSpec,
    YarvelleError,
    ensure_yarvelle_error,
    get_error_catalog,
    register_pack_error_catalog,
    unregister_pack_error_catalog,
)
from yarvelle_core.pack.loader import PackLoadError, PackNotFoundError
from yarvelle_core.pack.spec import PackProvidesSpec, PackSpec
from yarvelle_core.resources.loader import ResourceLoader, get_resource_loader
from yarvelle_core.schemas.tool import ToolResult
from yarvelle_core.vault.checkpoints import CheckpointDecryptionError, CheckpointKeyError
from yarvelle_core.vault.errors import (
    DecryptionError,
    KeyDerivationError,
    VaultError,
    VaultLockedError,
)
from yarvelle_core.vault.field_crypto import FieldDecryptionError

CORE_SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "yarvelle_core"
ERRORS_YAML_PATH = CORE_SRC_ROOT / "resources" / "errors.yaml"

# Append-only immutability snapshot: released YRV-XXX-YYY codes MUST NEVER be
# deleted or reassigned to a different canonical slug.
IMMUTABLE_CORE_CODE_PINS: Dict[str, str] = {
    "YRV-100-001": "prompt_empty",
    "YRV-100-002": "invalid_input",
    "YRV-100-003": "validation_error",
    "YRV-100-004": "missing_required_parameter",
    "YRV-100-005": "invalid_state_transition",
    "YRV-100-006": "payload_too_large",
    "YRV-100-009": "invalid_locale_tag",
    "YRV-100-010": "redacted_placeholder_rejected",
    "YRV-200-001": "malformed_yaml",
    "YRV-200-002": "manifest_validation_error",
    "YRV-200-003": "missing_api_key",
    "YRV-200-005": "unsupported_provider",
    "YRV-200-006": "pack_not_found",
    "YRV-200-007": "pack_load_failed",
    "YRV-300-001": "authentication_required",
    "YRV-300-002": "invalid_credentials",
    "YRV-300-003": "session_expired",
    "YRV-300-004": "forbidden",
    "YRV-300-006": "admin_required",
    "YRV-300-007": "profile_access_denied",
    "YRV-300-008": "scope_access_denied",
    "YRV-300-009": "csrf_forbidden",
    "YRV-300-010": "consent_required",
    "YRV-300-012": "sandbox_access_denied",
    "YRV-300-013": "policy_blocked",
    "YRV-400-001": "vault_error",
    "YRV-400-002": "vault_locked",
    "YRV-400-003": "vault_decryption_failed",
    "YRV-400-004": "vault_key_derivation_failed",
    "YRV-400-005": "audit_decryption_failed",
    "YRV-500-001": "not_found",
    "YRV-500-002": "profile_not_found",
    "YRV-500-003": "user_not_found",
    "YRV-500-004": "attachment_not_found",
    "YRV-500-006": "memory_not_found",
    "YRV-500-007": "reminder_not_found",
    "YRV-500-008": "routine_not_found",
    "YRV-500-009": "connection_not_found",
    "YRV-500-010": "email_draft_not_found",
    "YRV-500-012": "resource_conflict",
    "YRV-500-013": "storage_operation_failed",
    "YRV-500-014": "memory_operation_failed",
    "YRV-600-001": "connector_error",
    "YRV-600-002": "egress_blocked",
    "YRV-600-003": "connector_auth_expired",
    "YRV-600-004": "model_timeout",
    "YRV-600-005": "model_server_error",
    "YRV-600-006": "connector_timeout",
    "YRV-600-007": "connector_unavailable",
    "YRV-600-008": "oauth_state_mismatch",
    "YRV-700-001": "tool_validation_error",
    "YRV-700-002": "tool_forbidden",
    "YRV-700-003": "tool_executor_missing",
    "YRV-700-004": "approval_not_found",
    "YRV-700-005": "approval_required",
    "YRV-700-006": "approval_invalid",
    "YRV-700-007": "mcp_schema_drift",
    "YRV-700-008": "mcp_transport_error",
    "YRV-700-009": "tool_execution_failed",
    "YRV-800-001": "agent_not_found",
    "YRV-800-002": "duplicate_agent",
    "YRV-800-003": "subagent_hook_invalid",
    "YRV-800-005": "skill_not_found",
    "YRV-800-008": "thread_not_found",
    "YRV-800-012": "safety_refusal",
    "YRV-800-014": "max_reflections_exceeded",
    "YRV-900-001": "internal_error",
}


# ============================================================================
# 1. Declarative Catalog Schema, Uniqueness & Immutability Contract
# ============================================================================


def test_errors_yaml_schema_uniqueness_and_immutability() -> None:
    raw = yaml.safe_load(ERRORS_YAML_PATH.read_text(encoding="utf-8"))
    assert raw["apiVersion"] == API_VERSION_ERRORS_V1
    assert raw["kind"] == "ErrorCatalog"
    assert raw["prefix"] == RESERVED_CORE_ERROR_PREFIX
    assert raw["categories"] == BLOCK_TO_CATEGORY

    entries = raw["errors"]
    assert isinstance(entries, dict)
    assert len(entries) >= len(IMMUTABLE_CORE_CODE_PINS)

    seen_codes: set[str] = set()
    blocks_covered: set[int] = set()

    for slug, entry in entries.items():
        code = entry["code"]
        assert ERROR_CODE_PATTERN.match(code), f"Malformed error code {code} on slug {slug}"
        assert code.startswith("YRV-"), f"Core error {code} must use YRV- prefix"
        assert code not in seen_codes, f"Duplicate error code {code}"
        seen_codes.add(code)

        block = int(code.split("-")[1])
        blocks_covered.add(block)
        assert entry["category"] == BLOCK_TO_CATEGORY[block]
        assert isinstance(entry["http_status"], int) and 100 <= entry["http_status"] <= 599
        assert entry["status_code"] == entry["http_status"]
        assert isinstance(entry["jsonrpc_code"], int) and entry["jsonrpc_code"] <= -32000
        assert isinstance(entry["retryable"], bool)
        assert isinstance(entry["title"], str) and entry["title"].strip()
        assert isinstance(entry["template"], str) and entry["template"].strip()
        assert isinstance(entry["description"], str) and entry["description"].strip()

    # All 9 numeric blocks (100..900) are populated
    assert blocks_covered == set(BLOCK_TO_CATEGORY.keys())

    # Immutability pin verification
    catalog = ErrorCatalog(ERRORS_YAML_PATH)
    for pinned_code, pinned_slug in IMMUTABLE_CORE_CODE_PINS.items():
        spec = catalog.resolve(pinned_code)
        assert spec.slug == pinned_slug, (
            f"Immutability violation: {pinned_code} reassigned from '{pinned_slug}' to '{spec.slug}'"
        )
        assert catalog.resolve(pinned_slug) == spec


def test_backward_compatible_resource_loader_helpers() -> None:
    loader = get_resource_loader()
    msg_by_slug = loader.format_error("agent_not_found", agent_id="planner")
    msg_by_code = loader.format_error("YRV-800-001", agent_id="planner")
    assert msg_by_slug == "Agent 'planner' not found."
    assert msg_by_code == msg_by_slug
    assert loader.get_error_status_code("agent_not_found") == 404
    assert loader.get_error_status_code("YRV-800-001") == 404


# ============================================================================
# 2. YarvelleError Lazy Formatting, Chaining, Sanitization & Protocol Mappers
# ============================================================================


class _LazyArgCounter:
    def __init__(self, text: str) -> None:
        self.text = text
        self.evaluations = 0

    def __str__(self) -> str:
        self.evaluations += 1
        return self.text


def test_yarvelle_error_lazy_formatting_chaining_and_redaction() -> None:
    lazy_val = _LazyArgCounter("bad_filter")
    root_cause = ValueError("underlying parse failure")

    err = YarvelleError(
        "YRV-100-002",
        lazy_val,
        context={
            "field": "filter",
            "api_key": "sk-live-secret",
            "nested": {"access_token": "tok-123", "safe": 42},
        },
        cause=root_cause,
        instance="/api/v1/search",
    )

    # Template formatting MUST NOT run at instantiation time
    assert lazy_val.evaluations == 0
    assert err.__cause__ is root_cause
    assert err.code == "YRV-100-002"
    assert err.slug == "invalid_input"
    assert err.http_status == 400
    assert err.status_code == 400
    assert err.jsonrpc_code == -32602
    assert err.retryable is False

    # Accessing detail evaluates template once and caches result
    assert err.detail == "Invalid request parameter: bad_filter"
    assert lazy_val.evaluations == 1
    _ = str(err)
    assert lazy_val.evaluations == 1

    # Context redacts secrets recursively
    ctx = err.context
    assert ctx["field"] == "filter"
    assert ctx["api_key"] == REDACTED_VALUE
    assert ctx["nested"]["access_token"] == REDACTED_VALUE
    assert ctx["nested"]["safe"] == 42

    # RFC 7807 Problem Details mapping
    problem = err.to_problem_details()
    assert problem == {
        "type": "https://errors.yarvelle.dev/yrv-100-002",
        "title": "Invalid Input",
        "status": 400,
        "detail": "Invalid request parameter: bad_filter",
        "instance": "/api/v1/search",
        "code": "YRV-100-002",
        "slug": "invalid_input",
        "retryable": False,
        "context": {
            "field": "filter",
            "api_key": REDACTED_VALUE,
            "nested": {"access_token": REDACTED_VALUE, "safe": 42},
        },
    }

    # MCP JSON-RPC 2.0 error mapping
    rpc_err = err.to_jsonrpc_error()
    assert rpc_err == {
        "code": -32602,
        "message": "Invalid request parameter: bad_filter",
        "data": {
            "yarvelle_code": "YRV-100-002",
            "slug": "invalid_input",
            "category": "validation",
            "http_status": 400,
            "retryable": False,
            "context": {
                "field": "filter",
                "api_key": REDACTED_VALUE,
                "nested": {"access_token": REDACTED_VALUE, "safe": 42},
            },
        },
    }


def test_ensure_yarvelle_error_lossless_and_sanitized() -> None:
    original = YarvelleError("YRV-600-004", context={"timeout": 15})
    assert ensure_yarvelle_error(original) is original

    timeout_mapped = ensure_yarvelle_error(asyncio.TimeoutError("socket stalled"))
    assert timeout_mapped.code == "YRV-600-006"
    assert timeout_mapped.retryable is True

    conn_mapped = ensure_yarvelle_error(ConnectionError("connection reset"))
    assert conn_mapped.code == "YRV-600-007"
    assert conn_mapped.retryable is True

    raw_internal = RuntimeError("postgres://admin:supersecret@10.0.0.5/db")
    internal_mapped = ensure_yarvelle_error(raw_internal)
    assert internal_mapped.code == "YRV-900-001"
    assert internal_mapped.http_status == 500
    assert internal_mapped.retryable is False
    assert "supersecret" not in internal_mapped.detail
    assert internal_mapped.__cause__ is raw_internal


# ============================================================================
# 3. Subsystem Exception Hierarchy Unification
# ============================================================================


def test_subsystem_exceptions_inherit_from_yarvelle_error() -> None:
    vault_locked = VaultLockedError()
    assert isinstance(vault_locked, (VaultError, YarvelleError))
    assert vault_locked.code == "YRV-400-002"
    assert vault_locked.http_status == 503
    assert vault_locked.retryable is False

    checkpoint_key = CheckpointKeyError("checkpoint KEK missing")
    assert isinstance(checkpoint_key, (VaultError, YarvelleError))
    assert checkpoint_key.code == "YRV-400-001"

    checkpoint_dec = CheckpointDecryptionError("checkpoint GCM tag mismatch")
    assert isinstance(checkpoint_dec, (DecryptionError, YarvelleError))
    assert checkpoint_dec.code == "YRV-400-003"

    dec_err = DecryptionError("GCM tag mismatch")
    assert isinstance(dec_err, YarvelleError)
    assert dec_err.code == "YRV-400-003"

    field_dec = FieldDecryptionError("sealed audit field mismatch")
    assert isinstance(field_dec, (DecryptionError, YarvelleError))
    assert field_dec.code == "YRV-400-003"

    kdf_err = KeyDerivationError("HKDF failure")
    assert isinstance(kdf_err, YarvelleError)
    assert kdf_err.code == "YRV-400-004"

    conn_err = ConnectorError("upstream 502")
    assert isinstance(conn_err, YarvelleError)
    assert conn_err.code == "YRV-600-001"
    assert conn_err.retryable is True

    egress_err = EgressBlockedError("blocked private IP")
    assert isinstance(egress_err, (ConnectorError, YarvelleError))
    assert egress_err.code == "YRV-600-002"
    assert egress_err.http_status == 403
    assert egress_err.retryable is False

    auth_exp = AuthExpiredError("refresh token revoked")
    assert isinstance(auth_exp, (ConnectorError, YarvelleError))
    assert auth_exp.code == "YRV-600-003"
    assert auth_exp.http_status == 401
    assert auth_exp.retryable is False

    manifest_err = ManifestValidationError("missing scopes")
    assert isinstance(manifest_err, YarvelleError)
    assert manifest_err.code == "YRV-200-002"

    drift_err = McpSchemaDriftError("Remote MCP tool 'search_docs' drifted from pinned SHA-256")
    assert isinstance(drift_err, (ConnectorError, YarvelleError))
    assert drift_err.code == "YRV-700-007"
    assert drift_err.retryable is False

    agent_nf = AgentNotFoundError("missing", ["planner", "critic"])
    assert isinstance(agent_nf, (YarvelleError, KeyError))
    assert agent_nf.code == "YRV-800-001"

    dup_agent = DuplicateAgentError("dup", ["pack_a", "pack_b"])
    assert isinstance(dup_agent, (YarvelleError, ValueError))
    assert dup_agent.code == "YRV-800-002"

    hook_err = SubagentHookError("Missing audit hook")
    assert isinstance(hook_err, (YarvelleError, RuntimeError))
    assert hook_err.code == "YRV-800-003"

    pack_nf = PackNotFoundError("sample-pack")
    assert isinstance(pack_nf, YarvelleError)
    assert pack_nf.code == "YRV-200-006"

    pack_load = PackLoadError("Broken entry point", pack_id="sample-pack")
    assert isinstance(pack_load, YarvelleError)
    assert pack_load.code == "YRV-200-007"


# ============================================================================
# 4. MCP / Tool Execution Structured Error Metadata & Retryability
# ============================================================================


@pytest.mark.asyncio
async def test_execute_tool_call_populates_structured_error_code_and_retryable() -> None:
    async def _timeout_tool(args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        raise asyncio.TimeoutError("remote MCP timed out")

    async def _noop_tool(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
        return {"ok": True}

    timeout_spec = ToolSpec(
        name="transient_mcp_tool",
        description="Simulates remote MCP timeout",
        risk_tier="read",
        executor=_timeout_tool,
    )
    write_spec = ToolSpec(
        name="external_mutating_tool",
        description="Mutates external state",
        risk_tier="write_external",
        data_flows=DataFlows(allowed_hosts=("api.allowed.test",)),
        executor=_noop_tool,
    )
    egress_spec = ToolSpec(
        name="restricted_http_tool",
        description="Fetches from allowlisted host",
        risk_tier="read",
        data_flows=DataFlows(allowed_hosts=("api.allowed.test",)),
        executor=_noop_tool,
    )

    # 1. Policy blocked under child_under_13 age_band -> permanent YRV-300-013 (retryable=False)
    ctx_a1 = ToolContext(user_id="user-1", profile_id="prof-1", autonomy="A1", agent_id="coord")
    denied = await execute_tool_call(ctx_a1, write_spec, {}, age_band="child_under_13")
    assert denied.success is False
    assert denied.error_code == "YRV-300-013"
    assert denied.retryable is False
    rpc_denied = denied.to_jsonrpc_error()
    assert rpc_denied is not None
    assert rpc_denied["code"] == -32002
    assert rpc_denied["data"]["yarvelle_code"] == "YRV-300-013"
    assert rpc_denied["data"]["retryable"] is False

    # 2. Approval required under A1 autonomy -> YRV-700-005 (retryable=False, needs_approval=True)
    pending = await execute_tool_call(ctx_a1, write_spec, {})
    assert pending.success is False
    assert pending.needs_approval is True
    assert pending.error_code == "YRV-700-005"
    assert pending.retryable is False

    # 3. Upstream timeout -> transient YRV-600-006 (retryable=True)
    timed_out = await execute_tool_call(ctx_a1, timeout_spec, {})
    assert timed_out.success is False
    assert timed_out.error_code == "YRV-600-006"
    assert timed_out.retryable is True
    rpc_timeout = timed_out.to_jsonrpc_error()
    assert rpc_timeout is not None
    assert rpc_timeout["code"] == -32006
    assert rpc_timeout["data"]["retryable"] is True

    # 4. Egress firewall block -> permanent YRV-600-002 (retryable=False)
    egress_res = await execute_tool_call(
        ctx_a1,
        egress_spec,
        {"url": "https://169.254.169.254/latest/meta-data"},
    )
    assert egress_res.success is False
    assert egress_res.error_code == "YRV-600-002"
    assert egress_res.retryable is False


# ============================================================================
# 5. FastAPI RFC 7807 Problem Details & Zero-HTTPException Contract
# ============================================================================


def test_zero_http_exception_usage_in_yarvelle_core() -> None:
    offenders: list[str] = []
    for py_file in sorted(CORE_SRC_ROOT.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "HTTPException":
                rel = py_file.relative_to(CORE_SRC_ROOT)
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], f"Found residual HTTPException references in yarvelle_core: {offenders}"


def test_fastapi_problem_details_on_create_app_and_bare_host_app() -> None:
    # 1. Canonical create_app() factory
    app = create_app(include_api_router=False)

    @app.get("/boom-auth")
    async def _boom_auth() -> Dict[str, Any]:
        raise YarvelleError("YRV-300-001", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/boom-500")
    async def _boom_500() -> Dict[str, Any]:
        try:
            raise RuntimeError("sqlite:///private/secret_key_material.db")
        except RuntimeError as raw:
            raise ensure_yarvelle_error(raw) from raw

    client = TestClient(app)

    res_401 = client.get("/boom-auth")
    assert res_401.status_code == 401
    assert res_401.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    assert res_401.headers.get("www-authenticate") == "Bearer"
    body_401 = res_401.json()
    assert body_401["type"] == "https://errors.yarvelle.dev/yrv-300-001"
    assert body_401["title"] == "Authentication Required"
    assert body_401["status"] == 401
    assert body_401["detail"] == "Authentication required"
    assert body_401["instance"] == "/boom-auth"
    assert body_401["code"] == "YRV-300-001"
    assert body_401["retryable"] is False

    res_500 = client.get("/boom-500")
    assert res_500.status_code == 500
    assert res_500.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    body_500 = res_500.json()
    assert body_500["code"] == "YRV-900-001"
    assert "secret_key_material" not in body_500["detail"]

    # 2. Bare host FastAPI() mounting api_router directly (downstream compatibility)
    bare_app = FastAPI()
    bare_app.include_router(api_router, prefix="/api/v1")
    bare_client = TestClient(bare_app)

    res_locale = bare_client.get("/api/v1/i18n/catalog/invalid_locale_$$$")
    assert res_locale.status_code == 422
    assert res_locale.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
    locale_problem = res_locale.json()
    assert locale_problem["code"] == "YRV-100-009"
    assert locale_problem["status"] == 422
    assert locale_problem["instance"] == "/api/v1/i18n/catalog/invalid_locale_$$$"
    assert locale_problem["retryable"] is False


# ============================================================================
# 6. Disjoint Pack Error-Prefix Registration API
# ============================================================================


def test_pack_error_prefix_registration_and_collision_guards(tmp_path: Path) -> None:
    pack_id = "synthetic-ops"
    unregister_pack_error_catalog(pack_id)
    unregister_pack_error_catalog("other-pack")

    try:
        # Reserved YRV prefix MUST be rejected for packs
        with pytest.raises(ErrorCatalogRegistrationError, match="reserved"):
            register_pack_error_catalog(
                pack_id,
                "YRV",
                [
                    {
                        "slug": "illegal_core_claim",
                        "code": "YRV-100-999",
                        "category": "validation",
                        "http_status": 400,
                        "jsonrpc_code": -32602,
                        "retryable": False,
                        "title": "Illegal",
                        "template": "Illegal",
                        "description": "Should fail.",
                    }
                ],
            )

        # Register via PackSpec + ResourceLoader YAML integration
        res_dir = tmp_path / "resources"
        res_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "pack.yaml").write_text("pack_api: 1\n", encoding="utf-8")
        pack_errors_yaml = res_dir / "errors.yaml"
        pack_errors_yaml.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "yarvelle.errors/v1",
                    "kind": "ErrorCatalog",
                    "prefix": "OPS",
                    "type_base_uri": "https://errors.example.org/ops",
                    "errors": {
                        "ops_quota_exceeded": {
                            "code": "OPS-300-001",
                            "category": "auth",
                            "http_status": 429,
                            "jsonrpc_code": -32029,
                            "retryable": True,
                            "title": "Operations Quota Exceeded",
                            "template": "Quota exceeded for workspace '{workspace}'.",
                            "description": "Pack-scoped quota limit reached.",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        spec = PackSpec(
            id=pack_id,
            name="Synthetic Ops Pack",
            version="0.1.0",
            domain="operations",
            requires_core=">=0.1.0",
            manifest_path=str(tmp_path / "pack.yaml"),
            error_prefix="OPS",
            provides=PackProvidesSpec(errors_file="resources/errors.yaml"),
        )
        loader = ResourceLoader()
        loader.register_pack(spec)

        # Another pack cannot claim 'OPS'
        with pytest.raises(ErrorCatalogRegistrationError, match="already registered"):
            register_pack_error_catalog(
                "other-pack",
                "OPS",
                [
                    {
                        "slug": "other_conflict",
                        "code": "OPS-100-001",
                        "category": "validation",
                        "http_status": 400,
                        "jsonrpc_code": -32602,
                        "retryable": False,
                        "title": "Conflict",
                        "template": "Conflict",
                        "description": "Should fail.",
                    }
                ],
            )

        # Resolve and map through both FastAPI RFC 7807 and MCP JSON-RPC
        app = FastAPI()
        register_error_handlers(app)
        pack_router = APIRouter(route_class=ProblemDetailsRoute)

        @pack_router.get("/ops/check")
        async def _ops_check() -> Dict[str, Any]:
            raise YarvelleError("OPS-300-001", context={"workspace": "ws-alpha"})

        app.include_router(pack_router)
        client = TestClient(app)

        resp = client.get("/ops/check")
        assert resp.status_code == 429
        assert resp.headers["content-type"].startswith(PROBLEM_JSON_MEDIA_TYPE)
        problem = resp.json()
        assert problem == {
            "type": "https://errors.example.org/ops/ops-300-001",
            "title": "Operations Quota Exceeded",
            "status": 429,
            "detail": "Quota exceeded for workspace 'ws-alpha'.",
            "instance": "/ops/check",
            "code": "OPS-300-001",
            "slug": "ops_quota_exceeded",
            "retryable": True,
            "context": {"workspace": "ws-alpha"},
        }

        rpc = YarvelleError("ops_quota_exceeded", context={"workspace": "ws-alpha"}).to_jsonrpc_error()
        assert rpc["code"] == -32029
        assert rpc["data"]["yarvelle_code"] == "OPS-300-001"
        assert rpc["data"]["retryable"] is True
    finally:
        unregister_pack_error_catalog(pack_id)
        unregister_pack_error_catalog("other-pack")
        assert get_error_catalog().get("OPS-300-001") is None
