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

"""Canonical FastAPI application factory for Yarvelle Core."""

from __future__ import annotations

from typing import Any, Optional, Sequence
from fastapi import APIRouter, FastAPI

from yarvelle_core import __version__
from yarvelle_core.api.errors import ProblemDetailsRoute, register_error_handlers
from yarvelle_core.api.router import api_router, mount_router_contributions
from yarvelle_core.pack.spec import RouterContribution


def create_app(
    *,
    title: str = "Yarvelle Core API",
    version: str = __version__,
    api_prefix: str = "/api/v1",
    include_api_router: bool = True,
    contributions: Optional[Sequence[RouterContribution]] = None,
    **fastapi_kwargs: Any,
) -> FastAPI:
    """Constructs a FastAPI application with RFC 7807 ``YarvelleError`` handling registered."""
    app = FastAPI(title=title, version=version, **fastapi_kwargs)
    register_error_handlers(app)
    if include_api_router:
        if contributions is not None:
            mounted = APIRouter(route_class=ProblemDetailsRoute)
            mount_router_contributions(mounted, contributions)
            app.include_router(mounted, prefix=api_prefix)
        else:
            app.include_router(api_router, prefix=api_prefix)
    return app


__all__ = ["create_app", "register_error_handlers"]
