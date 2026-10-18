#!/usr/bin/env python3
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

"""Comprehensive script to extract domain-neutral modules from Carefold to Yarvelle Core."""

from pathlib import Path
import re
import shutil
import sys

CAREFOLD_BASE = Path("/Users/bharatjoshi/git/carefold/backend/src/carefold")
YARVELLE_BASE = Path("/Users/bharatjoshi/git/yarvelle-core/src/yarvelle_core")

OFFICIAL_HEADER = """# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)"""

CAREFOLD_HEADER_PATTERN = re.compile(
    r"^# Carefold — Healthcare AI Agent Marketplace & Runtime.*?"
    r"# Required Notice: Copyright 2026 Spectrayan \(https://spectrayan\.com\)\n",
    re.DOTALL | re.MULTILINE,
)

FILES_TO_COPY = [
    # Root
    ("__init__.py", "__init__.py"),
    ("config.py", "config.py"),
    ("logging.py", "logging.py"),
    # audit
    ("audit/__init__.py", "audit/__init__.py"),
    ("audit/hash_chain.py", "audit/hash_chain.py"),
    ("audit/logger.py", "audit/logger.py"),
    ("audit/redaction.py", "audit/redaction.py"),
    # auth
    ("auth/__init__.py", "auth/__init__.py"),
    ("auth/adapters/__init__.py", "auth/adapters/__init__.py"),
    ("auth/adapters/disabled_adapter.py", "auth/adapters/disabled_adapter.py"),
    ("auth/adapters/oidc_adapter.py", "auth/adapters/oidc_adapter.py"),
    ("auth/adapters/sql_adapter.py", "auth/adapters/sql_adapter.py"),
    ("auth/factory.py", "auth/factory.py"),
    ("auth/ports.py", "auth/ports.py"),
    # platform
    ("platform/__init__.py", "platform/__init__.py"),
    ("platform/email_drafts.py", "platform/email_drafts.py"),
    ("platform/reminders.py", "platform/reminders.py"),
    ("platform/routines.py", "platform/routines.py"),
    # companion
    ("companion/__init__.py", "companion/__init__.py"),
    ("companion/pairing.py", "companion/pairing.py"),
    # connectors
    ("connectors/__init__.py", "connectors/__init__.py"),
    ("connectors/lifecycle.py", "connectors/lifecycle.py"),
    ("connectors/mcp_remote.py", "connectors/mcp_remote.py"),
    ("connectors/oauth.py", "connectors/oauth.py"),
    ("connectors/relay.py", "connectors/relay.py"),
    ("connectors/sync.py", "connectors/sync.py"),
    # constants
    ("constants/__init__.py", "constants/__init__.py"),
    ("constants/models.py", "constants/models.py"),
    ("constants/paths.py", "constants/paths.py"),
    ("constants/defaults.py", "constants/defaults.py"),
    ("constants/api.py", "constants/api.py"),
    # db
    ("db/__init__.py", "db/__init__.py"),
    ("db/base.py", "db/base.py"),
    ("db/seeding.py", "db/seeding.py"),
    ("db/session.py", "db/session.py"),
    ("db/scoped_session.py", "db/scoped_session.py"),
    ("db/models.py", "db/models.py"),
    ("db/migrations/env.py", "db/migrations/env.py"),
    ("db/migrations/script.py.mako", "db/migrations/script.py.mako"),
    ("db/migrations/versions/0001_baseline_schema.py", "db/migrations/versions/0001_baseline_schema.py"),
    ("db/migrations/versions/0002_autonomy_foundations.py", "db/migrations/versions/0002_autonomy_foundations.py"),
    ("db/migrations/versions/0003_household_profiles_and_audit.py", "db/migrations/versions/0003_household_profiles_and_audit.py"),
    ("db/migrations/versions/0004_policy_gate_and_vault.py", "db/migrations/versions/0004_policy_gate_and_vault.py"),
    ("db/migrations/versions/0007_connectors_and_consent.py", "db/migrations/versions/0007_connectors_and_consent.py"),
    ("db/migrations/versions/0008_routines_mcp_and_drafts.py", "db/migrations/versions/0008_routines_mcp_and_drafts.py"),
    ("db/migrations/versions/0010_i18n_and_locale_storage.py", "db/migrations/versions/0010_i18n_and_locale_storage.py"),
    ("db/migrations/versions/0011_scopes.py", "db/migrations/versions/0011_scopes.py"),
    # engine
    ("engine/__init__.py", "engine/__init__.py"),
    ("engine/agent_factory.py", "engine/agent_factory.py"),
    ("engine/builder.py", "engine/builder.py"),
    ("engine/graph.py", "engine/graph.py"),
    ("engine/job_runner.py", "engine/job_runner.py"),
    ("engine/prompt_builder.py", "engine/prompt_builder.py"),
    ("engine/runner.py", "engine/runner.py"),
    ("engine/service.py", "engine/service.py"),
    ("engine/tool_exec.py", "engine/tool_exec.py"),
    ("engine/tool_registry.py", "engine/tool_registry.py"),
    ("engine/safety_policy.py", "engine/safety_policy.py"),
    # i18n
    ("i18n/__init__.py", "i18n/__init__.py"),
    ("i18n/locale.py", "i18n/locale.py"),
    # loaders
    ("loaders/__init__.py", "loaders/__init__.py"),
    ("loaders/agent_loader.py", "loaders/agent_loader.py"),
    ("loaders/context_loader.py", "loaders/context_loader.py"),
    ("loaders/skill_loader.py", "loaders/skill_loader.py"),
    ("loaders/union.py", "loaders/union.py"),
    # memory
    ("memory/__init__.py", "memory/__init__.py"),
    ("memory/namespace.py", "memory/namespace.py"),
    ("memory/factory.py", "memory/factory.py"),
    ("memory/adapters/__init__.py", "memory/adapters/__init__.py"),
    ("memory/adapters/spector/__init__.py", "memory/adapters/spector/__init__.py"),
    ("memory/adapters/spector/memory_adapter.py", "memory/adapters/spector/memory_adapter.py"),
    ("memory/adapters/spector/store.py", "memory/adapters/spector/store.py"),
    ("memory/adapters/sqlite/__init__.py", "memory/adapters/sqlite/__init__.py"),
    ("memory/adapters/sqlite/catalog_adapter.py", "memory/adapters/sqlite/catalog_adapter.py"),
    ("memory/adapters/sqlite/memory_adapter.py", "memory/adapters/sqlite/memory_adapter.py"),
    ("memory/ports/__init__.py", "memory/ports/__init__.py"),
    ("memory/ports/catalog_port.py", "memory/ports/catalog_port.py"),
    ("memory/ports/memory_port.py", "memory/ports/memory_port.py"),
    # middleware
    ("middleware/__init__.py", "middleware/__init__.py"),
    ("middleware/skills.py", "middleware/skills.py"),
    # migration
    ("migration/__init__.py", "migration/__init__.py"),
    ("migration/runtime_migrator.py", "migration/runtime_migrator.py"),
    # model
    ("model/__init__.py", "model/__init__.py"),
    ("model/client.py", "model/client.py"),
    ("model/egress.py", "model/egress.py"),
    ("model/factory.py", "model/factory.py"),
    ("model/types.py", "model/types.py"),
    ("model/providers/__init__.py", "model/providers/__init__.py"),
    ("model/providers/base.py", "model/providers/base.py"),
    ("model/providers/anthropic_provider.py", "model/providers/anthropic_provider.py"),
    ("model/providers/google_provider.py", "model/providers/google_provider.py"),
    ("model/providers/ollama_provider.py", "model/providers/ollama_provider.py"),
    ("model/providers/openai_provider.py", "model/providers/openai_provider.py"),
    ("model/providers/custom_provider.py", "model/providers/custom_provider.py"),
    # packaging
    ("packaging/__init__.py", "packaging/__init__.py"),
    ("packaging/service.py", "packaging/service.py"),
    # schemas
    ("schemas/__init__.py", "schemas/__init__.py"),
    ("schemas/activity.py", "schemas/activity.py"),
    ("schemas/audit.py", "schemas/audit.py"),
    ("schemas/chat.py", "schemas/chat.py"),
    ("schemas/health.py", "schemas/health.py"),
    ("schemas/memory.py", "schemas/memory.py"),
    ("schemas/plan.py", "schemas/plan.py"),
    ("schemas/profiles.py", "schemas/profiles.py"),
    ("schemas/tool.py", "schemas/tool.py"),
    ("schemas/manifest.py", "schemas/manifest.py"),
    ("schemas/routing.py", "schemas/routing.py"),
    # scope
    ("scope/__init__.py", "scope/__init__.py"),
    ("scope/context.py", "scope/context.py"),
    ("scope/mixin.py", "scope/mixin.py"),
    ("scope/adapter.py", "scope/adapter.py"),
    # search
    ("search/__init__.py", "search/__init__.py"),
    ("search/base.py", "search/base.py"),
    ("search/chunker.py", "search/chunker.py"),
    ("search/factory.py", "search/factory.py"),
    ("search/adapters/__init__.py", "search/adapters/__init__.py"),
    ("search/adapters/spector.py", "search/adapters/spector.py"),
    ("search/adapters/sqlite.py", "search/adapters/sqlite.py"),
    # settings
    ("settings/__init__.py", "settings/__init__.py"),
    ("settings/ports.py", "settings/ports.py"),
    ("settings/factory.py", "settings/factory.py"),
    ("settings/adapters/__init__.py", "settings/adapters/__init__.py"),
    ("settings/adapters/sql_adapter.py", "settings/adapters/sql_adapter.py"),
    # storage
    ("storage/__init__.py", "storage/__init__.py"),
    ("storage/cas.py", "storage/cas.py"),
    ("storage/extract.py", "storage/extract.py"),
    ("storage/factory.py", "storage/factory.py"),
    ("storage/adapters/__init__.py", "storage/adapters/__init__.py"),
    ("storage/adapters/local_adapter.py", "storage/adapters/local_adapter.py"),
    ("storage/ports/__init__.py", "storage/ports/__init__.py"),
    ("storage/ports/storage_port.py", "storage/ports/storage_port.py"),
    # templates
    ("templates/__init__.py", "templates/__init__.py"),
    ("templates/engine.py", "templates/engine.py"),
    ("templates/helpers.py", "templates/helpers.py"),
    # tools
    ("tools/__init__.py", "tools/__init__.py"),
    ("tools/attach_read.py", "tools/attach_read.py"),
    ("tools/attachments.py", "tools/attachments.py"),
    ("tools/delegation_tools.py", "tools/delegation_tools.py"),
    ("tools/mcp_db_toolbox.py", "tools/mcp_db_toolbox.py"),
    ("tools/registry.py", "tools/registry.py"),
    ("tools/reminders.py", "tools/reminders.py"),
    ("tools/sandbox.py", "tools/sandbox.py"),
    ("tools/web_search.py", "tools/web_search.py"),
    ("tools/workspace_note.py", "tools/workspace_note.py"),
    # vault
    ("vault/__init__.py", "vault/__init__.py"),
    ("vault/crypto.py", "vault/crypto.py"),
    ("vault/dek.py", "vault/dek.py"),
    ("vault/errors.py", "vault/errors.py"),
    ("vault/kek.py", "vault/kek.py"),
    # workflows
    ("workflows/__init__.py", "workflows/__init__.py"),
    ("workflows/dispatcher.py", "workflows/dispatcher.py"),
    ("workflows/state.py", "workflows/state.py"),
    ("workflows/nodes/__init__.py", "workflows/nodes/__init__.py"),
    ("workflows/nodes/base.py", "workflows/nodes/base.py"),
    ("workflows/nodes/agent.py", "workflows/nodes/agent.py"),
    ("workflows/nodes/agent_execution_node.py", "workflows/nodes/agent_execution_node.py"),
    ("workflows/nodes/agent_node.py", "workflows/nodes/agent_node.py"),
    ("workflows/nodes/audit.py", "workflows/nodes/audit.py"),
    ("workflows/nodes/audit_node.py", "workflows/nodes/audit_node.py"),
    ("workflows/nodes/error.py", "workflows/nodes/error.py"),
    ("workflows/nodes/error_node.py", "workflows/nodes/error_node.py"),
    ("workflows/nodes/input_guardrail.py", "workflows/nodes/input_guardrail.py"),
    ("workflows/nodes/output_guardrail.py", "workflows/nodes/output_guardrail.py"),
    ("workflows/nodes/reflection.py", "workflows/nodes/reflection.py"),
    ("workflows/nodes/refusal.py", "workflows/nodes/refusal.py"),
    ("workflows/nodes/response_synthesizer_node.py", "workflows/nodes/response_synthesizer_node.py"),
    ("workflows/nodes/suggestion.py", "workflows/nodes/suggestion.py"),
    ("workflows/nodes/suggestion_node.py", "workflows/nodes/suggestion_node.py"),
    ("workflows/nodes/supervisor.py", "workflows/nodes/supervisor.py"),
    ("workflows/nodes/supervisor_node.py", "workflows/nodes/supervisor_node.py"),
    ("workflows/nodes/tool.py", "workflows/nodes/tool.py"),
    ("workflows/nodes/tool_execution.py", "workflows/nodes/tool_execution.py"),
    ("workflows/nodes/tool_node.py", "workflows/nodes/tool_node.py"),
    ("workflows/nodes/tool_validator.py", "workflows/nodes/tool_validator.py"),
    ("workflows/nodes/tool_validator_node.py", "workflows/nodes/tool_validator_node.py"),
    ("workflows/subgraphs/__init__.py", "workflows/subgraphs/__init__.py"),
    ("workflows/subgraphs/supervisor.py", "workflows/subgraphs/supervisor.py"),
    ("workflows/subgraphs/extraction/__init__.py", "workflows/subgraphs/extraction/__init__.py"),
    ("workflows/subgraphs/extraction/graph.py", "workflows/subgraphs/extraction/graph.py"),
    ("workflows/subgraphs/extraction/grounding.py", "workflows/subgraphs/extraction/grounding.py"),
    ("workflows/subgraphs/extraction/sanitizer.py", "workflows/subgraphs/extraction/sanitizer.py"),
    ("workflows/subgraphs/extraction/subgraph.py", "workflows/subgraphs/extraction/subgraph.py"),
    # agents
    ("agents/__init__.py", "agents/__init__.py"),
    ("agents/registry.py", "agents/registry.py"),
    # api
    ("api/__init__.py", "api/__init__.py"),
    ("api/admin.py", "api/admin.py"),
    ("api/approvals.py", "api/approvals.py"),
    ("api/attachments.py", "api/attachments.py"),
    ("api/audit.py", "api/audit.py"),
    ("api/auth.py", "api/auth.py"),
    ("api/chat.py", "api/chat.py"),
    ("api/connections.py", "api/connections.py"),
    ("api/deps.py", "api/deps.py"),
    ("api/email_drafts.py", "api/email_drafts.py"),
    ("api/health.py", "api/health.py"),
    ("api/i18n.py", "api/i18n.py"),
    ("api/memory.py", "api/memory.py"),
    ("api/models.py", "api/models.py"),
    ("api/reminders.py", "api/reminders.py"),
    ("api/routines.py", "api/routines.py"),
    ("api/search.py", "api/search.py"),
    ("api/skills.py", "api/skills.py"),
    ("api/router.py", "api/router.py"),
    # resources
    ("resources/__init__.py", "resources/__init__.py"),
    ("resources/loader.py", "resources/loader.py"),
    ("resources/errors.yaml", "resources/errors.yaml"),
    ("resources/prompts.yaml", "resources/prompts.yaml"),
    ("resources/prompts/extraction/generic_document.md", "resources/prompts/extraction/generic_document.md"),
    ("resources/prompts/extraction/grounding_validation.md", "resources/prompts/extraction/grounding_validation.md"),
    ("resources/prompts/suggestions/generation.md", "resources/prompts/suggestions/generation.md"),
    ("resources/prompts/system/capabilities_section_header.md", "resources/prompts/system/capabilities_section_header.md"),
    ("resources/prompts/system/persona_section_header.md", "resources/prompts/system/persona_section_header.md"),
    ("resources/prompts/system/scaffold.yaml", "resources/prompts/system/scaffold.yaml"),
    ("resources/prompts/system/skill_section_format.md", "resources/prompts/system/skill_section_format.md"),
    ("resources/prompts/system/skills_section_header.md", "resources/prompts/system/skills_section_header.md"),
    ("resources/prompts/system/tools_summary_none.md", "resources/prompts/system/tools_summary_none.md"),
    ("resources/prompts/system/tools_summary_sandboxed.md", "resources/prompts/system/tools_summary_sandboxed.md"),
    ("resources/prompts/templates/agent_execution_prompt.hbs", "resources/prompts/templates/agent_execution_prompt.hbs"),
    ("resources/prompts/templates/orchestrator_routing_prompt.hbs", "resources/prompts/templates/orchestrator_routing_prompt.hbs"),
    ("resources/prompts/templates/system_prompt.hbs", "resources/prompts/templates/system_prompt.hbs"),
]


def clean_db_models(content: str) -> str:
    """Removes the 7 health models and health relationships from Profile."""
    # 1. Remove classes: HealthResource, Appointment, PreventiveRecord, ImportBatch, SchoolForm, SchoolIcsFeed, CompanionDevice
    # We can use regex to match class definition to next class or EOF
    health_classes = [
        "HealthResource",
        "Appointment",
        "PreventiveRecord",
        "ImportBatch",
        "SchoolForm",
        "SchoolIcsFeed",
        "CompanionDevice",
    ]

    for cname in health_classes:
        # Match class Cname(Base...): until next class or # Register dual-write
        pattern = re.compile(
            rf"^class {cname}\(.*?\n(?=(?:class [A-Z]|# Register dual-write|\Z))",
            re.MULTILINE | re.DOTALL,
        )
        content = pattern.sub("", content)

    # 2. Remove relationship declarations from Profile
    # Remove health_resources, appointments, preventive_records, import_batches, school_forms, school_ics_feeds, companion_devices
    rel_names = [
        "health_resources",
        "appointments",
        "preventive_records",
        "import_batches",
        "school_forms",
        "school_ics_feeds",
        "companion_devices",
    ]
    for rname in rel_names:
        rel_pattern = re.compile(
            rf"^\s+{rname}:.*?\)\n",
            re.MULTILINE | re.DOTALL,
        )
        content = rel_pattern.sub("", content)

    return content


def transform_content(rel_dst: str, content: str) -> str:
    # 1. License header replacement for python files
    if rel_dst.endswith(".py"):
        shebang = ""
        body = content
        if content.startswith("#!"):
            idx = content.find("\n")
            shebang = content[: idx + 1]
            body = content[idx + 1 :]

        if CAREFOLD_HEADER_PATTERN.match(body):
            body = CAREFOLD_HEADER_PATTERN.sub(OFFICIAL_HEADER + "\n", body, count=1)
        elif not body.startswith(OFFICIAL_HEADER):
            body = OFFICIAL_HEADER + "\n\n" + body

        content = shebang + body

    # 2. General import path rewrites
    content = content.replace("from carefold.", "from yarvelle_core.")
    content = content.replace("import carefold.", "import yarvelle_core.")
    content = content.replace("from carefold import", "from yarvelle_core import")
    content = content.replace('"carefold.', '"yarvelle_core.')
    content = content.replace("'carefold.", "'yarvelle_core.")
    content = content.replace("carefold_", "yarvelle_")

    # 3. File specific neutralizations
    if rel_dst == "config.py":
        content = content.replace('product_name: str = "Carefold"', 'product_name: str = "Yarvelle Core"')
        content = content.replace('env_prefix: str = "CAREFOLD_"', 'env_prefix: str = "YARVELLE_CORE_"')
        content = content.replace('home_dir_name: str = ".carefold"', 'home_dir_name: str = ".yarvelle"')
        content = content.replace('db_filename: str = "carefold.db"', 'db_filename: str = "yarvelle.db"')
        content = content.replace('oauth_scheme: str = "carefold"', 'oauth_scheme: str = "yarvelle"')
        content = content.replace('cookie_prefix: str = "carefold_"', 'cookie_prefix: str = "yarvelle_"')
        content = content.replace('default_agent: str = "visit-steward"', 'default_agent: str = "assistant"')
        content = content.replace('env_prefix="CAREFOLD_"', 'env_prefix="YARVELLE_CORE_"')
        content = content.replace(
            'env_home = os.getenv("CAREFOLD_HOME") or os.getenv("CAREFOLD_HOME_DIR")',
            'env_home = os.getenv("YARVELLE_HOME") or os.getenv("CAREFOLD_HOME") or os.getenv("YARVELLE_HOME_DIR")',
        )
        content = content.replace(
            'env_cf = os.getenv("CAREFOLD_DATABASE_URL")',
            'env_cf = os.getenv("YARVELLE_DATABASE_URL") or os.getenv("CAREFOLD_DATABASE_URL")',
        )

    elif rel_dst == "constants/paths.py":
        content = content.replace('DEFAULT_HOME_DIR: str = ".carefold"', 'DEFAULT_HOME_DIR: str = ".yarvelle"')
        content = content.replace('SQL_DB_FILENAME: str = "carefold.db"', 'SQL_DB_FILENAME: str = "yarvelle.db"')
        content = content.replace('DEFAULT_SQL_DB_PATH: str = "carefold.db"', 'DEFAULT_SQL_DB_PATH: str = "yarvelle.db"')

    elif rel_dst == "constants/defaults.py":
        content = content.replace('DEFAULT_HOST: str = "0.0.0.0"', 'DEFAULT_HOST: str = "127.0.0.1"')

    elif rel_dst == "db/models.py":
        content = clean_db_models(content)

    elif rel_dst == "db/__init__.py":
        # Remove health models from db/__init__.py
        health_names = [
            "HealthResource",
            "Appointment",
            "PreventiveRecord",
            "ImportBatch",
            "SchoolForm",
            "SchoolIcsFeed",
            "CompanionDevice",
        ]
        for h in health_names:
            content = re.sub(rf"\b{h},?\s*", "", content)

    elif rel_dst == "api/deps.py":
        # Add get_user_profile_access helper so api/connections.py can import it
        access_helper = """
from yarvelle_core.db.models import Profile, ProfileAccess
from yarvelle_core.auth.adapters.disabled_adapter import DEFAULT_STEWARD_USER

async def get_user_profile_access(profile: Profile, user: UserProfile, db: AsyncSession) -> Optional[str]:
    owner_id = resolve_owner_user_id(user)
    if owner_id is None:
        if getattr(user, "id", None) == DEFAULT_STEWARD_USER.id or profile.user_id is None or profile.user_id == getattr(user, "id", None):
            return "manage"
    if profile.user_id is not None and profile.user_id == owner_id:
        return "manage"
    stmt = select(ProfileAccess).where(ProfileAccess.profile_id == profile.id, ProfileAccess.user_id == (owner_id or user.id))
    res = await db.execute(stmt)
    grant = res.scalar_one_or_none()
    return grant.access_level if grant is not None else None
"""
        content += "\n" + access_helper

    elif rel_dst == "api/connections.py":
        # Update import of get_user_profile_access to api.deps
        content = content.replace("from yarvelle_core.api.profiles import get_user_profile_access", "from yarvelle_core.api.deps import get_user_profile_access")
        content = content.replace("detail=\"Access denied: clinical view permissions required to inspect connections.\"", "detail=\"Access denied: profile view permissions required to inspect connections.\"")

    elif rel_dst == "api/email_drafts.py":
        # Remove school_ics endpoints
        # Strip import of school_ics
        content = re.sub(r"from yarvelle_core\.clinical\.school_ics import.*?\)\n", "", content, flags=re.DOTALL)
        content = re.sub(r"from yarvelle_core\.connectors\.gmail_mcp import.*?\)\n", "", content, flags=re.DOTALL)
        content = content.replace("ImportBatch, ", "")
        content = content.replace("SchoolIcsFeed, ", "")
        # Remove school-ics endpoints from line @router.post("/profiles/{profile_id}/school-ics" to end
        school_ics_idx = content.find('@router.post(\n    "/profiles/{profile_id}/school-ics"')
        if school_ics_idx != -1:
            content = content[:school_ics_idx] + '__all__ = ["router"]\n'

    elif rel_dst == "connectors/lifecycle.py":
        # Remove HealthResource deletion in revoke_connection
        content = content.replace("HealthResource,\n", "")
        content = content.replace("HealthResource,", "")
        content = re.sub(r"\s+# 4\. Optionally delete imported HealthResource rows.*?(?=\s+# \d|\s+await session\.commit)", "", content, flags=re.DOTALL)

    elif rel_dst == "connectors/sync.py":
        # Remove HealthResource from db.models import
        content = content.replace("HealthResource,\n", "")
        content = content.replace("HealthResource,", "")

    elif rel_dst == "tools/mcp_db_toolbox.py":
        content = re.sub(r"from yarvelle_core\.safety\.vitals import.*?\n", "", content)
        content = content.replace("check_vitals_red_flags(parsed_records)", "None")

    elif rel_dst == "api/router.py":
        # Neutralize router.py so it only imports and registers core routers
        # Core routers: health, i18n, reminders, connections, routines, email_drafts, skills, audit, approvals, chat, models, attachments, search, memory, auth, admin
        core_router_content = """# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

\"\"\"Master API Router mounting all Yarvelle Core endpoints and pack contributions.\"\"\"

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
from yarvelle_core.api.reminders import router as reminders_router
from yarvelle_core.api.routines import router as routines_router
from yarvelle_core.api.search import router as search_router
from yarvelle_core.api.skills import router as skills_router


@dataclass
class RouterContribution:
    \"\"\"Metadata describing an API router contribution from core or a domain pack.\"\"\"

    router: APIRouter
    prefix: str = ""
    tags: Optional[List[Union[str, Any]]] = None
    dependencies: Optional[Sequence[Any]] = None
    include_in_schema: bool = True
    pack_id: Optional[str] = None
    scope: Optional[str] = None
    level: Optional[str] = None


def get_default_router_contributions() -> List[RouterContribution]:
    \"\"\"Returns the ordered list of core router contributions.\"\"\"
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
        RouterContribution(search_router, pack_id="core"),
        RouterContribution(memory_router, pack_id="core"),
        RouterContribution(auth_router, prefix="/auth", tags=["auth"], pack_id="core"),
        RouterContribution(admin_router, prefix="/admin", tags=["admin"], pack_id="core"),
    ]


def mount_router_contributions(
    app_router: APIRouter,
    contributions: Optional[Sequence[RouterContribution]] = None,
) -> APIRouter:
    \"\"\"Mounts a deterministic list of RouterContribution instances onto target router.\"\"\"
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
"""
        content = core_router_content

    # 4. Neutralize docstrings and domain terms across core files
    content = content.replace("clinical permissions required", "permissions required")
    content = content.replace("clinical view permissions required", "view permissions required")
    content = content.replace("clinical safety boundaries", "safety boundaries")
    content = content.replace("clinical safety refusal", "safety refusal")
    content = content.replace("clinical determinism", "determinism")
    content = content.replace("patient profile", "profile")
    content = content.replace("Patient profile", "Profile")
    content = content.replace("patient medical records", "user records")
    content = content.replace("clinical appointments", "appointments")
    content = content.replace("clinical reminders", "reminders")
    content = content.replace("Clinical Reminders", "Reminders")
    content = content.replace("clinical notes", "notes")
    content = content.replace("Clinical notes", "Notes")

    return content


def main():
    print(f"Extracting {len(FILES_TO_COPY)} files to {YARVELLE_BASE}...")
    YARVELLE_BASE.mkdir(parents=True, exist_ok=True)

    for src_rel, dst_rel in FILES_TO_COPY:
        src_path = CAREFOLD_BASE / src_rel
        dst_path = YARVELLE_BASE / dst_rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if not src_path.exists():
            print(f"ERROR: missing source file {src_path}")
            sys.exit(1)

        raw_content = src_path.read_text(encoding="utf-8")
        transformed = transform_content(dst_rel, raw_content)
        dst_path.write_text(transformed, encoding="utf-8")

    print(f"Extracted {len(FILES_TO_COPY)} files successfully.")


if __name__ == "__main__":
    main()
