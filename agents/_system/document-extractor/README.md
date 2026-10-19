# Document Extractor Agent

The **Document Extractor** is an administrative and clinical document analysis agent in Carefold.
It extracts structured data into typed Pydantic dossiers while enforcing deterministic PII masking and numerical grounding verification.

## Capabilities
- Sandboxed file reading via `attach-read`
- Deterministic regex-based PII sanitization via `sanitize_pii`
- Schema-targeted extraction (Insurance, Clinical, Generic) via `extract_structured_data`
- Deterministic numerical grounding verification via `validate_grounding`

## Safety Bounds
- Never renders or stores unmasked SSN, MRN, phone numbers, or street addresses.
- Strictly forbidden from diagnosing medical conditions or recommending treatment.
