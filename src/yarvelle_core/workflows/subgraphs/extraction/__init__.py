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

"""Yarvelle Core Document Extraction & Attachment Processing Subgraph package (Requirement R2).

Exports structured dossiers, PII sanitizer, grounding validator,
and dual-invocation extraction tool and subgraph.
"""

from __future__ import annotations

from yarvelle_core.workflows.subgraphs.extraction.dossiers import (
    BaseDossier,
    ClinicalVisitDossier,
    DOSSIER_REGISTRY,
    DocumentDossier,
    GenericDocumentDossier,
    InsuranceBenefitsDossier,
    get_dossier_cls,
)
from yarvelle_core.workflows.subgraphs.extraction.grounding import (
    GroundingValidationResult,
    GroundingValidator,
    extract_numeric_tokens,
)
from yarvelle_core.workflows.subgraphs.extraction.sanitizer import (
    DEFAULT_ADDRESS_TAG,
    DEFAULT_EMAIL_TAG,
    DEFAULT_MRN_TAG,
    DEFAULT_PHONE_TAG,
    DEFAULT_REDACTED_TAG,
    DEFAULT_SSN_TAG,
    PIISanitizer,
    SanitizationResult,
    mask_pii,
    sanitize_pii,
    sanitize_pii_with_metadata,
)
from yarvelle_core.workflows.subgraphs.extraction.subgraph import (
    build_extraction_subgraph,
    create_extraction_node,
    create_extraction_subgraph,
    create_ingestion_node,
)
from yarvelle_core.workflows.subgraphs.extraction.tool import (
    ExtractDocumentDossierInput,
    ExtractDocumentDossierTool,
    extract_document_dossier,
)

__all__ = [
    "BaseDossier",
    "ClinicalVisitDossier",
    "DEFAULT_ADDRESS_TAG",
    "DEFAULT_EMAIL_TAG",
    "DEFAULT_MRN_TAG",
    "DEFAULT_PHONE_TAG",
    "DEFAULT_REDACTED_TAG",
    "DEFAULT_SSN_TAG",
    "DOSSIER_REGISTRY",
    "DocumentDossier",
    "ExtractDocumentDossierInput",
    "ExtractDocumentDossierTool",
    "GenericDocumentDossier",
    "GroundingValidationResult",
    "GroundingValidator",
    "InsuranceBenefitsDossier",
    "PIISanitizer",
    "SanitizationResult",
    "build_extraction_subgraph",
    "create_extraction_node",
    "create_extraction_subgraph",
    "create_ingestion_node",
    "extract_document_dossier",
    "extract_numeric_tokens",
    "get_dossier_cls",
    "mask_pii",
    "sanitize_pii",
    "sanitize_pii_with_metadata",
]
