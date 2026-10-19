# Orchestrator Agent

The **Orchestrator** is a meta-routing and workflow planning agent in Carefold.
It dynamically routes user requests to specialized health navigation agents based on user intent and conversational context.

## Capabilities
- Dynamic specialist discovery via `list_agents`
- Intent classification and structured routing via `delegate_to_agent`
- Multi-step workflow sequencing

## Safety Bounds
- Strictly forbidden from prescribing, dosing, or diagnosing.
- Refuses acute emergency inquiries and directs immediately to 911 / emergency services.
