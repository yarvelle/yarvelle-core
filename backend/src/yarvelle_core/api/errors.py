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

"""FastAPI RFC 7807 Problem Details exception handlers and APIRoute integration."""

from __future__ import annotations

from typing import Awaitable, Callable
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.routing import APIRoute
from fastapi.utils import is_body_allowed_for_status_code
from starlette.responses import JSONResponse
from starlette.routing import request_response

from yarvelle_core.errors.base import PROBLEM_JSON_MEDIA_TYPE, YarvelleError


async def yarvelle_error_handler(request: Request, exc: YarvelleError) -> Response:
    """FastAPI exception handler serializing ``YarvelleError`` as RFC 7807 Problem Details."""
    if not is_body_allowed_for_status_code(exc.http_status):
        return Response(status_code=exc.http_status, headers=exc.headers)
    instance = exc.instance or str(request.url.path)
    payload = exc.to_problem_details(instance=instance)
    return JSONResponse(
        status_code=exc.http_status,
        content=payload,
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers=exc.headers,
    )


def wrap_route_handler_for_problem_details(
    handler: Callable[[Request], Awaitable[Response]],
) -> Callable[[Request], Awaitable[Response]]:
    """Wraps a FastAPI route handler so ``YarvelleError`` emits ``application/problem+json``."""
    if getattr(handler, "_yarvelle_problem_details_wrapped", False):
        return handler

    async def _wrapped(request: Request) -> Response:
        try:
            return await handler(request)
        except YarvelleError as exc:
            return await yarvelle_error_handler(request, exc)

    setattr(_wrapped, "_yarvelle_problem_details_wrapped", True)
    return _wrapped


class ProblemDetailsRoute(APIRoute):
    """``APIRoute`` ensuring RFC 7807 Problem Details serialization on any FastAPI host app."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        return wrap_route_handler_for_problem_details(super().get_route_handler())


def ensure_problem_details_routes(router: APIRouter) -> APIRouter:
    """Ensures all ``APIRoute`` entries on ``router`` (including nested routers) serialize ``YarvelleError`` as Problem Details."""
    for route in router.routes:
        nested_router = getattr(route, "original_router", None)
        if isinstance(nested_router, APIRouter):
            ensure_problem_details_routes(nested_router)
            continue
        if isinstance(route, APIRoute) and not isinstance(route, ProblemDetailsRoute):
            if type(route) is APIRoute:
                route.__class__ = ProblemDetailsRoute
                route.app = request_response(route.get_route_handler())
            elif not getattr(route, "_yarvelle_problem_details_installed", False):
                orig_get_handler = route.get_route_handler

                def _bound_get_handler(
                    _orig: Callable[[], Callable[[Request], Awaitable[Response]]] = orig_get_handler,
                ) -> Callable[[Request], Awaitable[Response]]:
                    return wrap_route_handler_for_problem_details(_orig())

                route.get_route_handler = _bound_get_handler  # type: ignore[method-assign]
                route.app = request_response(route.get_route_handler())
                setattr(route, "_yarvelle_problem_details_installed", True)
    return router


def register_error_handlers(app: FastAPI) -> FastAPI:
    """Registers the ``YarvelleError`` RFC 7807 exception handler on a FastAPI app."""
    app.add_exception_handler(YarvelleError, yarvelle_error_handler)  # type: ignore[arg-type]
    return app


__all__ = [
    "PROBLEM_JSON_MEDIA_TYPE",
    "ProblemDetailsRoute",
    "ensure_problem_details_routes",
    "register_error_handlers",
    "wrap_route_handler_for_problem_details",
    "yarvelle_error_handler",
]
