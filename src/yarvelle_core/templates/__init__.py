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

"""Template compilation and rendering package for Yarvelle Core."""

from yarvelle_core.templates.engine import (
    TemplateEngine,
    get_template_engine,
    render_template,
)
from yarvelle_core.templates.helpers import BUILTIN_HELPERS

__all__ = [
    "TemplateEngine",
    "get_template_engine",
    "render_template",
    "BUILTIN_HELPERS",
]
