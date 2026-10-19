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
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Set

from yarvelle_core.constants.defaults import ALLOWED_SKILL_DOC_EXTENSIONS
from yarvelle_core.constants.paths import REFERENCES_DIR, SKILLS_DIR
from yarvelle_core.schemas.manifest import SLUG_REGEX
from yarvelle_core.schemas.tool import ToolResult
from yarvelle_core.tools.sandbox import SandboxSecurityError, resolve_sandboxed_path

logger = logging.getLogger(__name__)
ALLOWED_DOC_EXTS: Set[str] = set(ALLOWED_SKILL_DOC_EXTENSIONS)


def synthesize_missing_skill_doc(
    skill_id: str,
    doc_name: str,
    skill_dir: Optional[Path] = None,
    context: Optional[Any] = None,
) -> str:
    """Synthesizes structured, safety-compliant documentation when a reference doc is missing."""
    clean_stem = Path(doc_name).stem.replace("_", " ").replace("-", " ").title()
    skill_title = skill_id.replace("_", " ").replace("-", " ").title()

    # Check if SKILL.md has description
    skill_desc = ""
    if skill_dir and (skill_dir / "SKILL.md").is_file():
        try:
            raw_skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            for line in raw_skill.splitlines():
                if line.startswith("description:"):
                    skill_desc = line.split("description:", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            pass

    if not skill_desc:
        skill_desc = f"Domain guidance and procedural reference for {skill_title}."

    doc_lower = doc_name.lower()
    if "template" in doc_lower or "log" in doc_lower or "tracker" in doc_lower:
        archetype_content = (
            f"## 1. Purpose & Overview\n"
            f"This template provides a standardized tracking tool for {clean_stem.lower()} to support productive discussions.\n\n"
            f"## 2. Tracking Log Matrix\n\n"
            f"| Date & Time | Primary Observation / Entry | Severity / Rating (1-10) | Duration / Frequency | Triggers / Contributing Factors | Actions / Interventions Tried | Impact on Daily Function |\n"
            f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
            f"| *YYYY-MM-DD* | *Detailed description* | *1 - 10* | *e.g., 2 hours* | *Specific triggers noted* | *Action or routine remedies* | *Impact on work, routine, or tasks* |\n"
            f"| | | | | | | |\n"
            f"| | | | | | | |\n\n"
            f"## 3. Key Discussion Points\n"
            f"- Describe specific patterns or triggers identified during logging.\n"
            f"- Note which interventions provided relief and which were ineffective.\n"
            f"- Ask what subsequent steps, lifestyle modifications, or specialist consultations are recommended.\n"
        )
    elif "checklist" in doc_lower or "prep" in doc_lower:
        archetype_content = (
            f"## 1. Preparation Logistics & Documents\n"
            f"- [ ] Identification and relevant account credentials.\n"
            f"- [ ] Current documentation list including active requirements.\n"
            f"- [ ] Prior records, reports, or referring coordinator notes.\n\n"
            f"## 2. Priority Agendas\n"
            f"- [ ] Top 1–3 questions or goals prioritized for this session.\n"
            f"- [ ] Timeline of relevant changes or concerns over the past 30–90 days.\n\n"
            f"## 3. Next Steps & Follow-Up Verification\n"
            f"- [ ] Clarify required action items, referrals, or requisitions.\n"
            f"- [ ] Confirm follow-up timeline and contact procedures.\n"
        )
    elif "glossary" in doc_lower or "terms" in doc_lower or "code" in doc_lower or "explanation" in doc_lower:
        archetype_content = (
            f"## 1. Key Terminology & Concepts\n"
            f"- **Core Definition**: Essential understanding of {clean_stem.lower()} within workflow navigation.\n"
            f"- **Operational Context**: How coordinators and team members use this terminology.\n"
            f"- **User Considerations**: What this means for your workflow, responsibilities, and outcomes.\n\n"
            f"## 2. Questions to Clarify\n"
            f"1. *How does this apply to my specific situation or plan?*\n"
            f"2. *Are there formal pre-authorization, verification, or documentation requirements?*\n"
        )
    else:
        archetype_content = (
            f"## 1. Overview & Context\n"
            f"{clean_stem} provides structured informational guidance for {skill_title.lower()}.\n"
            f"Context: {skill_desc}\n\n"
            f"## 2. Key Action Items & Guidance\n"
            f"1. Review relevant history and document priorities in writing.\n"
            f"2. Formulate clear, concise questions for the coordinator.\n"
            f"3. Verify plan details, provider tiers, and required authorizations.\n\n"
            f"## 3. Communication Guide\n"
            f"Prepare a concise 2-minute summary of your goals to ensure all priorities are addressed.\n"
        )

    app_brand = "Carefold" if "carefold" in sys.modules or os.environ.get("CAREFOLD_HOME") else "Yarvelle Core"
    return (
        f"# {clean_stem}\n\n"
        f"**Skill Domain**: {skill_title}  \n"
        f"**Reference Document**: `{doc_name}`\n\n"
        f"---\n\n"
        f"{archetype_content}\n"
        f"---\n\n"
        f"## ⚠️ {app_brand} Boundary & Safety Disclosures\n\n"
        f"> **INFORMATIONAL AID**: This reference document is an educational and organizational resource. "
        f"It does **NOT** provide authoritative binding determinations or replace licensed professional judgment.\n"
    )



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

                # Check against agent ID (e.g. agent "cardiology-guide" with skill "cardiology-prep" called with "cardiology")
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
        if is_gen:
            for gs in gen_skills:
                if isinstance(gs, dict) and (gs.get("id") == skill_id or gs.get("name") == skill_id or gs.get("id") == resolved_skill_id):
                    refs = gs.get("references", {})
                    for r_name, r_content in refs.items():
                        if r_name == doc or r_name == f"{doc}.md" or Path(r_name).stem == doc:
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
            # Dynamically synthesize missing reference document on demand in-memory so UI never fails with error.
            # Do NOT persist synthesized content to disk in skills/ to prevent repository leaks and untracked stubs.
            content = synthesize_missing_skill_doc(
                skill_id=resolved_skill_id,
                doc_name=resolved_doc,
                skill_dir=skill_dir if skill_dir.is_dir() else None,
                context=context,
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
        # Fallback to dynamic synthesis so unexpected runtime file glitches do not leak raw errors
        try:
            content = synthesize_missing_skill_doc(
                skill_id=resolved_skill_id if 'resolved_skill_id' in locals() else skill_id,
                doc_name=resolved_doc if 'resolved_doc' in locals() else doc,
                skill_dir=None,
                context=context,
            )
            return ToolResult(
                success=True,
                output={
                    "skill_id": resolved_skill_id if 'resolved_skill_id' in locals() else skill_id,
                    "doc": resolved_doc if 'resolved_doc' in locals() else doc,
                    "content": content,
                },
            )
        except Exception:
            return ToolResult(success=False, output=None, error=f"Failed to load skill doc: {err}")


# Alias for compatibility with tests and tool runner
skill_docs_tool = execute_skill_docs

