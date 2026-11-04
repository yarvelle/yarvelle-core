# Orchestrator Agent

The **Orchestrator** is the built-in routing and workflow planning agent.
It routes user requests to the specialist agents registered by installed packs, based on user intent and conversational context.

## Capabilities
- Dynamic specialist discovery via `list_agents`
- Intent classification and structured routing via `delegate_to_agent`
- Multi-step workflow sequencing

## Routing Defaults
- Core has no default specialist. A pack sets one with `orchestration.default_agent`; without it, a request that cannot be routed fails with an error.

## Safety Bounds
- Bound by the core safety policy and the forbidden intents declared in its manifest.
- Directs acute emergencies to local emergency services.
