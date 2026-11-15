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

"""Closed Phase 0 tool: skill-docs.

Reads reference documentation strictly from an installed and declared skill's references/ folder.
Enforces authenticated agent authorization and sandbox path boundary isolation.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set

from yarvelle_core.constants.defaults import ALLOWED_SKILL_DOC_EXTENSIONS
from yarvelle_core.constants.paths import REFERENCES_DIR, SKILLS_DIR
from yarvelle_core.schemas.manifest import SLUG_REGEX
from yarvelle_core.schemas.tool import ToolResult
from yarvelle_core.tools.sandbox import SandboxSecurityError, resolve_sandboxed_path

logger = logging.getLogger(__name__)
ALLOWED_DOC_EXTS: Set[str] = set(ALLOWED_SKILL_DOC_EXTENSIONS)


def _list_available_skill_docs(
    skill_dir: Optional[Path],
    ref_dir: Path,
    generated_refs: Optional[List[str]] = None,
) -> List[str]:
    """Lists readable reference document filenames available for an authorized skill."""
    available: List[str] = []
    seen: Set[str] = set()

    if ref_dir.is_dir():
        resolved_ref_dir = ref_dir.resolve()
        for entry in sorted(ref_dir.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith(".") or entry.is_symlink() or not entry.is_file():
                continue
            if entry.suffix.lower() not in ALLOWED_DOC_EXTS:
                continue
            try:
                if not entry.resolve().is_relative_to(resolved_ref_dir):
                    continue
            except OSError:
                continue
            available.append(entry.name)
            seen.add(entry.name)

    for g_name in generated_refs or []:
        if g_name and g_name not in seen:
            available.append(g_name)
            seen.add(g_name)

    if skill_dir is not None and skill_dir.is_dir():
        skill_md = skill_dir / "SKILL.md"
        if skill_md.is_file() and not skill_md.is_symlink() and "SKILL.md" not in seen:
            available.append("SKILL.md")
            seen.add("SKILL.md")

    return available




async def execute_skill_docs(params: Dict[str, Any], context: Any) -> ToolResult:
    """Executes the skill-docs tool securely."""
    try:
        skill_id = params.get("skill_id")
        doc = params.get("doc") or params.get("doc_name")

        if not skill_id or not isinstance(skill_id, str):
            return ToolResult(
                success=False,
                output=None,
                error='Parameter "skill_id" is required and must be a string.',
            )
        if not doc or not isinstance(doc, str):
            return ToolResult(
                success=False,
                output=None,
                error='Parameter "doc" is required and must be a string.',
            )

        # 1. Strict slug validation for skill_id
        if not SLUG_REGEX.match(skill_id):
            return ToolResult(
                success=False,
                output=None,
                error=f'Path traversal forbidden: Invalid skill_id "{skill_id}". Skill IDs must contain only alphanumeric characters, dashes, and underscores.',
            )

        # 2. Fail-closed authorization check: agent context and declared skills are mandatory
        agent = getattr(context, "agent", None)
        if not agent or not hasattr(agent, "skills") or not isinstance(agent.skills, list):
            return ToolResult(
                success=False,
                output=None,
                error="Access denied: An authenticated agent context with declared skills is required to access skill docs.",
            )

        # Check if the skill is a dynamically generated skill passed via context / state
        gen_skills: List[Dict[str, Any]] = []
        ctx_state = getattr(context, "state", None)
        if isinstance(ctx_state, dict):
            gen_skills = list(ctx_state.get("generated_skills") or [])
            if ctx_state.get("generated_skill"):
                gen_skills.append(ctx_state["generated_skill"])
        elif hasattr(context, "generated_skills"):
            gen_skills = list(getattr(context, "generated_skills") or [])

        is_gen = any(isinstance(gs, dict) and (gs.get("id") == skill_id or gs.get("name") == skill_id) for gs in gen_skills)

        # Resolve skill_id against declared agent skills and generated skills
        resolved_skill_id = skill_id
        matched_declared: Optional[str] = None
        if not is_gen:
            if skill_id in agent.skills:
                matched_declared = skill_id
            else:
                # Fuzzy / alias / prefix / stem matching against declared skills
                clean_req = skill_id.lower().strip()
                for s in agent.skills:
                    s_lower = s.lower().strip()
                    if s_lower.replace("-", "_") == clean_req.replace("-", "_"):
                        matched_declared = s
                        break
                    if s_lower.startswith(f"{clean_req}-") or s_lower.startswith(clean_req):
                        matched_declared = s
                        break
                    if s_lower.split("-")[0] == clean_req.split("-")[0] or s_lower.split("_")[0] == clean_req.split("_")[0]:
                        matched_declared = s
                        break
                    if clean_req.startswith(f"{s_lower}-") or clean_req.startswith(s_lower):
                        matched_declared = s
                        break

                # Check against agent ID (e.g. agent "travel-guide" with skill "travel-prep" called with "travel")
                if not matched_declared and agent.skills:
                    agent_id_str = getattr(agent, "id", "").lower().strip()
                    agent_stem = agent_id_str.split("-")[0] if agent_id_str else ""
                    if agent_stem and (clean_req.startswith(agent_stem) or agent_stem.startswith(clean_req)):
                        for s in agent.skills:
                            if agent_stem in s.lower():
                                matched_declared = s
                                break
                        if not matched_declared:
                            matched_declared = agent.skills[0]

            if matched_declared:
                resolved_skill_id = matched_declared
            else:
                agent_id = getattr(agent, "id", "unknown")
                return ToolResult(
                    success=False,
                    output=None,
                    error=f'Access denied: Skill "{skill_id}" is not declared on agent "{agent_id}". Undeclared skills cannot be accessed.',
                )

        # If it's a dynamic skill with in-memory references, resolve directly
        gen_ref_names: List[str] = []
        if is_gen:
            doc_stem_norm = Path(doc).stem.lower().replace("-", "_")
            for gs in gen_skills:
                if isinstance(gs, dict) and (gs.get("id") == skill_id or gs.get("name") == skill_id or gs.get("id") == resolved_skill_id):
                    refs = gs.get("references", {})
                    for r_name, r_content in refs.items():
                        gen_ref_names.append(r_name)
                        if (
                            r_name == doc
                            or r_name == f"{doc}.md"
                            or Path(r_name).stem == doc
                            or Path(r_name).stem.lower().replace("-", "_") == doc_stem_norm
                        ):
                            return ToolResult(
                                success=True,
                                output={
                                    "skill_id": resolved_skill_id,
                                    "doc": r_name,
                                    "content": r_content,
                                },
                            )

        ws_root = getattr(context, "workspace_root", None) or Path.cwd()
        skills_dir = getattr(context, "skills_dir", None) or (Path(ws_root) / SKILLS_DIR)
        skills_dir_path = Path(skills_dir).resolve()

        # 3. Sandboxed resolution of skill folder and reference document
        skill_dir = resolve_sandboxed_path(skills_dir_path, resolved_skill_id, must_exist=False)
        ref_dir = skill_dir / REFERENCES_DIR

        # Check for path traversal in doc parameter
        if ".." in Path(doc).parts or ".." in doc:
            return ToolResult(
                success=False,
                output=None,
                error=f'Path traversal forbidden: Document path "{doc}" escapes allowed directory.',
            )

        # If doc without extension is passed, check candidate extensions or normalize
        resolved_doc = doc
        if not Path(resolved_doc).suffix:
            if ref_dir.is_dir() and (ref_dir / f"{resolved_doc}.md").exists():
                resolved_doc = f"{resolved_doc}.md"
            elif ref_dir.is_dir() and (ref_dir / resolved_doc).exists():
                resolved_doc = doc
            else:
                resolved_doc = f"{resolved_doc}.md"

        # 4. Extension check
        ext = Path(resolved_doc).suffix.lower()
        if ext not in ALLOWED_DOC_EXTS:
            return ToolResult(
                success=False,
                output=None,
                error=f'Document "{doc}" has unsupported extension "{ext}". Only text/markdown documents are permitted.',
            )

        content = None
        if ref_dir.is_dir():
            target_path = resolve_sandboxed_path(ref_dir, resolved_doc, must_exist=False)
            if target_path.is_file():
                content = target_path.read_text(encoding="utf-8", errors="replace")
            else:
                # Match case-insensitively with hyphen/underscore stem normalization across real reference files
                req_stem = Path(resolved_doc).stem.lower().replace("-", "_")
                req_ext = Path(resolved_doc).suffix.lower()
                resolved_ref_dir = ref_dir.resolve()
                for cand in sorted(ref_dir.iterdir(), key=lambda p: p.name.lower()):
                    if cand.name.startswith(".") or cand.is_symlink() or not cand.is_file():
                        continue
                    try:
                        if not cand.resolve().is_relative_to(resolved_ref_dir):
                            continue
                    except OSError:
                        continue
                    if cand.suffix.lower() == req_ext and cand.stem.lower().replace("-", "_") == req_stem:
                        resolved_doc = cand.name
                        content = cand.read_text(encoding="utf-8", errors="replace")
                        break

        # Allow reading the skill's own SKILL.md manifest if explicitly requested
        if (
            content is None
            and Path(resolved_doc).parts == (Path(resolved_doc).name,)
            and Path(resolved_doc).name.lower() == "skill.md"
            and skill_dir.is_dir()
        ):
            skill_md_path = resolve_sandboxed_path(skill_dir, "SKILL.md", must_exist=False)
            if skill_md_path.is_file():
                resolved_doc = "SKILL.md"
                content = skill_md_path.read_text(encoding="utf-8", errors="replace")

        # If not found on filesystem, check database knowledge_base table
        if content is None:
            try:
                from yarvelle_core.db.session import get_session_factory
                from yarvelle_core.db.models import KnowledgeBase
                from sqlalchemy import select

                session_factory = get_session_factory()
                async with session_factory() as session:
                    doc_candidates = [resolved_doc]
                    if not resolved_doc.endswith(".md"):
                        doc_candidates.append(f"{resolved_doc}.md")
                    else:
                        doc_candidates.append(resolved_doc[:-3])

                    stmt = select(KnowledgeBase).where(
                        KnowledgeBase.target_type.in_(["skill", "agent"]),
                        KnowledgeBase.target_id.in_([resolved_skill_id, skill_id]),
                        KnowledgeBase.name.in_(doc_candidates),
                    )
                    res = await session.execute(stmt)
                    db_doc = res.scalars().first()
                    if db_doc and db_doc.content:
                        content = db_doc.content
            except Exception:
                pass

        if content is None:
            available = _list_available_skill_docs(
                skill_dir if skill_dir.is_dir() else None,
                ref_dir,
                gen_ref_names,
            )
            avail_msg = (
                f" Available documents: {', '.join(available)}."
                if available
                else " No reference documents are installed for this skill."
            )
            return ToolResult(
                success=False,
                output=None,
                error=f'Reference document "{doc}" not found in skill "{resolved_skill_id}".{avail_msg}',
            )

        return ToolResult(
            success=True,
            output={
                "skill_id": resolved_skill_id,
                "doc": resolved_doc,
                "content": content,
            },
        )

    except SandboxSecurityError as sec_err:
        return ToolResult(success=False, output=None, error=str(sec_err))
    except Exception as err:
        return ToolResult(success=False, output=None, error=f"Failed to load skill doc: {err}")


# Alias for compatibility with tests and tool runner
skill_docs_tool = execute_skill_docs

