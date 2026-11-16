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

"""Closed Phase 0 tool: workspace-note.

Saves structured markdown notes into the workspace notes directory.
Prevents directory traversal, protects against symlink overwriting, and formats with YAML frontmatter.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional

from yarvelle_core.constants.defaults import (
    DEFAULT_NOTE_AGENT_ID,
    DEFAULT_NOTE_SLUG,
    MAX_NOTE_SLUG_LENGTH,
)
from yarvelle_core.constants.paths import (
    NOTES_DIR,
    WORKSPACE_DIR,
    WORKSPACE_NOTES_DIR,
)
from yarvelle_core.schemas.tool import ToolResult
from yarvelle_core.scope.context import DEFAULT_SCOPE, current_scope
from yarvelle_core.tools.sandbox import SandboxSecurityError, resolve_sandboxed_path

logger = logging.getLogger(__name__)


async def execute_workspace_note(params: Dict[str, Any], context: Any) -> ToolResult:
    """Executes the workspace-note tool securely."""
    try:
        title = params.get("title")
        content = params.get("content")

        if not title or not isinstance(title, str):
            return ToolResult(
                success=False,
                output=None,
                error='Parameter "title" must be a non-empty string.',
            )
        if content is None or not isinstance(content, str):
            return ToolResult(
                success=False,
                output=None,
                error='Parameter "content" must be a string.',
            )

        from yarvelle_core.config import settings

        ws_root = getattr(context, "workspace_root", None)
        if ws_root and not (Path(ws_root) / "backend").is_dir():
            ws_root_path = Path(ws_root).resolve()
            sub_ws_notes = ws_root_path / WORKSPACE_NOTES_DIR
            root_notes = ws_root_path / NOTES_DIR

            if sub_ws_notes.is_dir() or (ws_root_path / WORKSPACE_DIR).is_dir():
                notes_dir = sub_ws_notes
            elif root_notes.is_dir():
                notes_dir = root_notes
            else:
                notes_dir = sub_ws_notes
        else:
            ws_root_path = settings.home_dir
            notes_dir = settings.get_notes_dir()

        # Sanitize title to safe filename slug
        safe_title = re.sub(r"[^a-zA-Z0-9_\-\s]", "", title.strip())
        safe_title = re.sub(r"\s+", "-", safe_title).lower()[:MAX_NOTE_SLUG_LENGTH] or DEFAULT_NOTE_SLUG
        filename = f"{safe_title}.md"
        notes_dir.mkdir(parents=True, exist_ok=True)
        target_path = resolve_sandboxed_path(notes_dir, filename, must_exist=False, for_write=True)

        # Defense-in-depth: check if candidate or target is an existing symlink
        candidate_file = notes_dir / filename
        if (
            candidate_file.is_symlink()
            or os.path.islink(candidate_file)
            or target_path.is_symlink()
            or os.path.islink(target_path)
        ):
            return ToolResult(
                success=False,
                output=None,
                error=f'Path traversal forbidden: Target note "{filename}" is an existing symlink.',
            )

        agent_id = DEFAULT_NOTE_AGENT_ID
        if hasattr(context, "agent") and context.agent and hasattr(context.agent, "id"):
            agent_id = context.agent.id

        now_iso = datetime.now(timezone.utc).isoformat()
        escaped_title = title.strip().replace("\\", "\\\\").replace('"', '\\"')
        frontmatter = (
            f"---\n"
            f'title: "{escaped_title}"\n'
            f'created_at: "{now_iso}"\n'
            f'agent_id: "{agent_id}"\n'
            f"---\n\n"
            f"{content.strip()}\n"
        )

        target_path.write_text(frontmatter, encoding="utf-8")

        # Also persist into relational database via McpDatabaseToolbox when not in an isolated test tmp_path
        db_note_id: Optional[str] = None
        is_isolated_test_workspace = bool(
            ws_root
            and not (Path(ws_root) / "backend").is_dir()
            and Path(ws_root).resolve() != settings.home_dir.resolve()
        )
        if not is_isolated_test_workspace:
            try:
                from yarvelle_core.tools.mcp_db_toolbox import get_db_toolbox

                ctx_user_id = getattr(context, "user_id", None) if context is not None else None
                ctx_profile_id = getattr(context, "profile_id", None) if context is not None else None
                active_profile_id = str(ctx_profile_id or "").strip() or "default_profile"
                active_scope = (
                    (getattr(context, "scope", None) if context is not None else None)
                    or current_scope()
                    or DEFAULT_SCOPE
                )
                display_title = title.strip()
                if display_title == safe_title:
                    display_title = (
                        safe_title.replace("-", " ").replace("_", " ").strip().title()
                        or title.strip()
                    )
                note_type = str(params.get("type") or agent_id or "general").strip() or "general"

                db_res = await get_db_toolbox().execute(
                    "upsert_workspace_note",
                    {
                        "slug": safe_title,
                        "title": display_title,
                        "content": content.strip(),
                        "type": note_type,
                    },
                    profile_id=active_profile_id,
                    user_id=str(ctx_user_id).strip() if ctx_user_id else None,
                    scope=str(active_scope),
                    ctx=context,
                )
                record = db_res.get("record") if isinstance(db_res, dict) else None
                if isinstance(record, dict) and record.get("id"):
                    db_note_id = str(record["id"])
            except Exception as db_err:
                logger.warning(
                    "workspace-note DB persistence failed for slug '%s': %s",
                    safe_title,
                    db_err,
                )

        try:
            rel_path = str(target_path.relative_to(ws_root_path))
        except ValueError:
            rel_path = str(target_path)

        abs_path = str(target_path.resolve())

        output_payload: Dict[str, Any] = {
            "title": safe_title,
            "slug": safe_title,
            "display_title": title.strip(),
            "filename": filename,
            "path": rel_path,
            "full_path": abs_path,
            "absolute_path": abs_path,
            "bytes_written": len(frontmatter.encode("utf-8")),
            "db_saved": bool(db_note_id),
        }
        if db_note_id:
            output_payload["note_id"] = db_note_id

        return ToolResult(success=True, output=output_payload)

    except SandboxSecurityError as sec_err:
        return ToolResult(success=False, output=None, error=str(sec_err))
    except Exception as err:
        return ToolResult(success=False, output=None, error=f"Failed to save note: {err}")


# Alias for compatibility with tests and tool runner
workspace_note_tool = execute_workspace_note

