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

"""Unified YRV-XXX-YYY error taxonomy, YarvelleError base class, and protocol mappers."""

from yarvelle_core.errors.base import (
    PROBLEM_JSON_MEDIA_TYPE,
    REDACTED_VALUE,
    YarvelleError,
    ensure_yarvelle_error,
    sanitize_error_context,
)
from yarvelle_core.errors.catalog import (
    API_VERSION_ERRORS_V1,
    BLOCK_TO_CATEGORY,
    DEFAULT_PROBLEM_TYPE_BASE_URI,
    ERROR_CODE_PATTERN,
    ERROR_PREFIX_PATTERN,
    RESERVED_CORE_ERROR_PREFIX,
    ErrorCatalog,
    ErrorCatalogRegistrationError,
    ErrorCategory,
    ErrorCodeSpec,
    get_error_catalog,
    register_pack_error_catalog,
    unregister_pack_error_catalog,
)

__all__ = [
    "API_VERSION_ERRORS_V1",
    "BLOCK_TO_CATEGORY",
    "DEFAULT_PROBLEM_TYPE_BASE_URI",
    "ERROR_CODE_PATTERN",
    "ERROR_PREFIX_PATTERN",
    "PROBLEM_JSON_MEDIA_TYPE",
    "REDACTED_VALUE",
    "RESERVED_CORE_ERROR_PREFIX",
    "ErrorCatalog",
    "ErrorCatalogRegistrationError",
    "ErrorCategory",
    "ErrorCodeSpec",
    "YarvelleError",
    "ensure_yarvelle_error",
    "get_error_catalog",
    "register_pack_error_catalog",
    "sanitize_error_context",
    "unregister_pack_error_catalog",
]
