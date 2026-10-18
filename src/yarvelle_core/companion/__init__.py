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

"""Companion Device Pairing and Pinned TLS Verification package."""

from yarvelle_core.companion.pairing import (
    DEFAULT_COMPANION_CATEGORIES,
    LOOPBACK_HOSTS,
    VALID_COMPANION_CATEGORIES,
    VALID_COMPANION_PLATFORMS,
    CompanionPairingError,
    authenticate_companion_device,
    check_companion_mode_guard,
    complete_companion_pairing,
    initiate_companion_pairing,
    revoke_companion_device,
)

__all__ = [
    "DEFAULT_COMPANION_CATEGORIES",
    "LOOPBACK_HOSTS",
    "VALID_COMPANION_CATEGORIES",
    "VALID_COMPANION_PLATFORMS",
    "CompanionPairingError",
    "authenticate_companion_device",
    "check_companion_mode_guard",
    "complete_companion_pairing",
    "initiate_companion_pairing",
    "revoke_companion_device",
]
