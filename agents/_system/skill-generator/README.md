# Skill Generator Agent

The **Skill Generator** is a specialized meta-agent (`hidden: true`) within Carefold.

## Purpose
When the **Orchestrator** analyzes a user inquiry and determines that:
1. The answering agent's declared skill is missing from the system, or
2. The user's query demands specialized domain guidelines or reference materials not currently installed,

the Orchestrator calls the **Skill Generator**. The generated skill (specifications, instructions, safety constraints, and reference docs) is dynamically created, optionally installed into the workspace `skills/` directory, and injected into the execution state so that the subsequent answering agent can leverage it to provide an accurate, grounded, and safety-compliant response.
