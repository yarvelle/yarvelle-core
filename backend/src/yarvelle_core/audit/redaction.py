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

"""Zero-Body Privacy Redaction Engine.

Enforces zero-body retention: strips prompt and completion bodies unless
store_bodies is strictly configured to True.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Dict, Tuple, Union

from yarvelle_core.schemas.audit import AuditEvent


def redact_audit_event(
    event: Union[AuditEvent, Dict[str, Any]],
    store_bodies: bool = False,
) -> Dict[str, Any]:
    """Redacts prompt and completion bodies from audit event unless store_bodies is True."""
    if isinstance(event, AuditEvent):
        data = event.model_dump(exclude_none=True)
    else:
        data = dict(event)

    if not store_bodies:
        data.pop("prompt", None)
        data.pop("completion", None)

    return data


# ---------------------------------------------------------------------------
# Tool-argument redaction (approvals, approval events and audit records)
# ---------------------------------------------------------------------------

REDACTED_PLACEHOLDER = "[REDACTED]"

_SENSITIVE_KEY_PARTS: Tuple[str, ...] = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "apikey",
    "authorization",
    "cookie",
    "session",
    "credential",
    "privatekey",
    "socialsecurity",
    "cardnumber",
    "creditcard",
    "accountnumber",
    "routingnumber",
)
# Short markers are matched exactly to avoid false hits (e.g. "otp" in "footprint").
_SENSITIVE_EXACT_KEYS = frozenset(
    {"pin", "auth", "dek", "kek", "ssn", "cvv", "cvc", "iban", "otp", "otpcode", "mfa", "mfacode", "totp"}
)
# Usage counters, not secrets.
_NON_SENSITIVE_KEYS = frozenset({"maxtokens", "tokens", "tokencount", "maxoutputtokens"})

_SENSITIVE_VALUE_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"\beyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|pk|rk)-[a-zA-Z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def _normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def is_sensitive_arg_key(key: Any) -> bool:
    """True when an argument name denotes a credential or regulated identifier."""
    norm = _normalize_key(key)
    if not norm:
        return False
    if norm in _NON_SENSITIVE_KEYS:
        return False
    if norm in _SENSITIVE_EXACT_KEYS:
        return True
    return any(part in norm for part in _SENSITIVE_KEY_PARTS)


def _redact_string(value: str) -> str:
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        value = pattern.sub(REDACTED_PLACEHOLDER, value)
    return value


def redact_tool_args(value: Any) -> Any:
    """Returns a deep copy of tool arguments with sensitive values masked.

    Values under credential-like keys (password, token, api_key, ...) are
    replaced wholesale; free-text values have embedded secrets (bearer
    tokens, JWTs, private keys, well-known API key formats) masked. The
    original arguments are never mutated; the payload hash binding an
    approval is always computed over the real arguments.
    """
    if isinstance(value, Mapping):
        return {
            k: (REDACTED_PLACEHOLDER if is_sensitive_arg_key(k) and v not in (None, "") else redact_tool_args(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_tool_args(v) for v in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def contains_redaction_placeholder(value: Any) -> bool:
    """True when any (nested) value carries the redaction placeholder."""
    if isinstance(value, Mapping):
        return any(contains_redaction_placeholder(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_redaction_placeholder(v) for v in value)
    return isinstance(value, str) and REDACTED_PLACEHOLDER in value
