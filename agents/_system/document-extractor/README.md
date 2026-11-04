# Document Extractor Agent

The **Document Extractor** is a built-in document analysis agent.
It extracts structured data into typed Pydantic dossiers while enforcing deterministic PII masking and numerical grounding verification.

## Capabilities
- Sandboxed file reading via `attach-read`
- Deterministic regex-based PII sanitization via `sanitize_pii`
- Schema-targeted extraction (generic, or a typed dossier schema) via `extract_structured_data`
- Deterministic numerical grounding verification via `validate_grounding`

## Safety Bounds
- Never renders or stores unmasked identifiers such as SSNs, record numbers, phone numbers, or street addresses.
- Bound by the forbidden intents declared in its manifest.
