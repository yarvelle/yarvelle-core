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

"""Yarvelle Core resources package.

Provides external YAML schemas and ResourceLoader for:
- disclaimers.yaml
- refusal_patterns.yaml
- prompts.yaml
- errors.yaml
"""

from yarvelle_core.resources.loader import (
    RefusalPattern,
    ResourceLoader,
    get_resource_loader,
)

__all__ = [
    "RefusalPattern",
    "ResourceLoader",
    "get_resource_loader",
]
