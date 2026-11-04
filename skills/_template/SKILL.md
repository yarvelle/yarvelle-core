---
# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

name: _template
description: Canonical template skill providing boilerplate structure, safety disclosures,
  and golden evals for skill contributors.
license: Apache-2.0
compatibility: Requires local LLM or API key for model access
allowed-tools: ''
metadata:
  title: Skill Starter Template
  risk_class: wellness
  domain: general
  category: general.template
  version: 0.1.0
  author: Yarvelle Contributor
  tools: []
  forbidden:
  - diagnose
  - prescribe
  - dose
  - replace_emergency_care
  - instruct_stop_medication
  evals: evals/golden.jsonl
---

# Skill Name Template

Replace this heading and text with the prompt instructions for your skill. This Markdown content serves as the operational system prompt provided to the model when the skill is active.

## Intended Use & Safety Disclosures
Every skill MUST contain these three statements verbatim (the core skill loader checks for them):
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician

## Skill Overview & Guidelines
Describe what your skill accomplishes, when an agent should invoke it, and what domain it addresses (e.g., household planning, document organization, learning support).

### Developer Rules
1. **Instruction Length**: Keep this instruction file concise and focused (recommended under 500 lines). Extensive reference texts, tables, or guides should be placed in `references/` and loaded dynamically via the `skill-docs` tool.
2. **Closed Tool Policy**: In Phase 0, skills may only declare tools from the closed registry:
   - `attach-read`: Reads text or PDF documents located inside `attachments/`.
   - `workspace-note`: Writes notes to `workspace/notes/<title>.md`.
   - `skill-docs`: Loads reference documents from `skills/<skill_id>/references/<doc>`.
   Any other tool declared in `yarvelle_core.yaml` will fail runtime validation.
3. **Mandatory Forbidden Intents**: The core safety policy blocks clinical diagnosis, prescription dosing, emergency care triage diversion, and instructions to stop or alter prescribed medications.

## References (Optional)
If your skill uses documentation stored in `references/`, describe available files here and instruct the model to retrieve them using `skill-docs`.

## Structured Interaction Protocol
When interacting with users, follow this structured four-step methodology:
1. Clarify Context & Validate Concerns: Acknowledge the user's primary situation with empathy, validating any emotional or logistical stress they may be experiencing.
2. Structure Relevant Information: Break down user disclosures into organized categories such as timeline of events, primary questions, and open items.
3. Formulate Actionable Agendas: Create a concise, prioritized 3-to-5 item checklist or agenda that the user can act on or bring to the person who can help.
4. Encourage Expert Collaboration: Point the user to a qualified professional for decisions outside the skill's scope.
