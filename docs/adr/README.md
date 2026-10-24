# Architecture Decision Records

This folder holds Architecture Decision Records (ADRs) for `yarvelle-core`: short documents that capture one significant design decision, its context and its consequences.

## Index

| ADR | Title | Status | Date |
| :--- | :--- | :--- | :--- |
| [0001](0001-multi-agent-deliberation.md) | Multi-Agent Deliberation (`ExecutionMode.DELIBERATE`) | Proposed | 2026-10-24 |

## Statuses

- **Proposed**: under discussion; not yet binding.
- **Accepted**: agreed; implementation may proceed.
- **Rejected**: considered and declined (kept for the record).
- **Deprecated**: no longer applies, without a direct replacement.
- **Superseded by ADR-NNNN**: replaced by a later ADR.

## Adding an ADR

1. Copy the template below to `NNNN-short-title.md`, using the next free number.
2. Open a PR with status **Proposed** and add a row to the index.
3. Once agreed, change the status to **Accepted** in the same or a follow-up PR. Do not rewrite an accepted ADR's decision; supersede it with a new one.
4. Link code with repo-relative paths (for example `../../backend/src/yarvelle_core/...`) and state the commit that line numbers were checked against.
5. Keep ADRs domain-neutral where possible: core knows no domain, and dependencies point app -> packs -> core.

## Template

```markdown
# ADR NNNN: Title

- **Status:** Proposed
- **Date:** YYYY-MM-DD
- **Authors:** Yarvelle maintainers
- **Verified against:** `main` @ `<commit>`

## 1. Context
What problem are we solving, and what does the code do today?

## 2. Decision
What we will do, stated as binding rules.

## 3. Consequences
Positive and negative effects, costs and risks.

## 4. Alternatives considered
Options weighed and why they were not chosen.

## 5. Open questions
What is still undecided.

## 6. Implementation phases
How the change lands incrementally.

## 7. References
Code and external sources.
```
