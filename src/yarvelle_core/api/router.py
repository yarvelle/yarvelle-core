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

"""Master API Router mounting all Yarvelle Core endpoints and pack contributions."""

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Union
from fastapi import APIRouter

from yarvelle_core.api.admin import router as admin_router
from yarvelle_core.api.approvals import router as approvals_router
from yarvelle_core.api.attachments import router as attachments_router
from yarvelle_core.api.audit import router as audit_router
from yarvelle_core.api.auth import router as auth_router
from yarvelle_core.api.chat import router as chat_router
from yarvelle_core.api.connections import router as connections_router
from yarvelle_core.api.email_drafts import router as email_drafts_router
from yarvelle_core.api.health import router as health_router
from yarvelle_core.api.i18n import router as i18n_router
from yarvelle_core.api.memory import router as memory_router
from yarvelle_core.api.models import router as models_router
from yarvelle_core.api.profiles import router as profiles_router
from yarvelle_core.api.reminders import router as reminders_router
from yarvelle_core.api.routines import router as routines_router
from yarvelle_core.api.search import router as search_router
from yarvelle_core.api.skills import router as skills_router


from yarvelle_core.pack.spec import RouterContribution


def get_default_router_contributions() -> List[RouterContribution]:
    """Returns the ordered list of core router contributions."""
    return [
        RouterContribution(health_router, pack_id="core"),
        RouterContribution(i18n_router, pack_id="core"),
        RouterContribution(reminders_router, pack_id="core"),
        RouterContribution(connections_router, pack_id="core"),
        RouterContribution(routines_router, pack_id="core"),
        RouterContribution(email_drafts_router, pack_id="core"),
        RouterContribution(skills_router, pack_id="core"),
        RouterContribution(audit_router, pack_id="core"),
        RouterContribution(approvals_router, prefix="/approvals", tags=["approvals"], pack_id="core"),
        RouterContribution(chat_router, pack_id="core"),
        RouterContribution(models_router, pack_id="core"),
        RouterContribution(attachments_router, pack_id="core"),
        RouterContribution(profiles_router, prefix="/profiles", tags=["profiles"], pack_id="core"),
        RouterContribution(search_router, pack_id="core"),
        RouterContribution(memory_router, prefix="/memory", tags=["memory"], pack_id="core"),
        RouterContribution(
            memory_router, prefix="/memories", tags=["memory"], include_in_schema=False, pack_id="core"
        ),
        RouterContribution(auth_router, prefix="/auth", tags=["auth"], pack_id="core"),
        RouterContribution(admin_router, prefix="/admin", tags=["admin"], pack_id="core"),
    ]


def mount_router_contributions(
    app_router: APIRouter,
    contributions: Optional[Sequence[RouterContribution]] = None,
) -> APIRouter:
    """Mounts a deterministic list of RouterContribution instances onto target router."""
    contribs = contributions if contributions is not None else get_default_router_contributions()
    for contrib in contribs:
        app_router.include_router(
            contrib.router,
            prefix=contrib.prefix,
            tags=contrib.tags or [],
            dependencies=contrib.dependencies,
            include_in_schema=contrib.include_in_schema,
        )
    return app_router


router = APIRouter()
mount_router_contributions(router)
api_router = router

