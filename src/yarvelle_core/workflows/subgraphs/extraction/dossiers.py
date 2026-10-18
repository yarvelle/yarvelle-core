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

"""Structured document extraction dossiers for Yarvelle Core.

Implements typed Pydantic models for structured document extraction
from ingested attachments, supporting strict validation,
convenience serialization methods, and grounding verification.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class BaseDossier(BaseModel):
    """Base class for all extraction dossiers providing shared serialization."""

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
    )

    @property
    def dossier_type(self) -> str:
        """Normalized identifier for the dossier model."""
        return "base"

    def to_dict(self, include_type: bool = False, **kwargs: Any) -> Dict[str, Any]:
        """Serialize dossier model to a Python dictionary.

        Args:
            include_type: If True, includes 'dossier_type' key in the output.
            **kwargs: Additional keyword arguments passed to model_dump.

        Returns:
            Dict[str, Any] representation of the model.
        """
        data = self.model_dump(**kwargs)
        if include_type:
            data["dossier_type"] = self.dossier_type
        return data

    def to_json(self, indent: Optional[int] = None, **kwargs: Any) -> str:
        """Serialize dossier model to a JSON string.

        Args:
            indent: Indentation spaces for formatted JSON output.
            **kwargs: Additional keyword arguments passed to model_dump_json.

        Returns:
            JSON-formatted string representation.
        """
        return self.model_dump_json(indent=indent, **kwargs)

    def extract_numerical_strings(self) -> List[str]:
        """Extract all string values containing numeric digits for grounding checks.

        Returns:
            List of string values containing one or more digits.
        """
        numerical_values: List[str] = []
        payload = self.model_dump()

        def _traverse(val: Any) -> None:
            if isinstance(val, str):
                if re.search(r"\d", val):
                    numerical_values.append(val)
            elif isinstance(val, list):
                for item in val:
                    _traverse(item)
            elif isinstance(val, dict):
                for v in val.values():
                    _traverse(v)

        _traverse(payload)
        return numerical_values


class GenericDocumentDossier(BaseDossier):
    """Fallback extraction dossier for unclassified documents and text."""

    summary: str = Field(
        default="",
        description="Executive summary or high-level document synthesis.",
    )
    key_numerical_values: Dict[str, str] = Field(
        default_factory=dict,
        description="Key extracted metrics, dates, and labeled numerical values.",
    )
    sections: List[str] = Field(
        default_factory=list,
        description="List of section headings and major content divisions.",
    )

    @property
    def dossier_type(self) -> str:
        return "generic_document"


# Union type of all structured extraction dossiers in core
DocumentDossier = Union[GenericDocumentDossier, BaseDossier]

# Extensible registry mapping shorthand type strings to dossier classes
DOSSIER_REGISTRY: Dict[str, type[BaseDossier]] = {
    "generic": GenericDocumentDossier,
    "generic_document": GenericDocumentDossier,
}


def register_dossier_type(dossier_type: str, dossier_cls: type[BaseDossier]) -> None:
    """Register a dynamic dossier model from a domain pack.

    Args:
        dossier_type: Shorthand or canonical type identifier.
        dossier_cls: Subclass of BaseDossier to handle extraction.
    """
    normalized = dossier_type.lower().strip().replace("-", "_")
    DOSSIER_REGISTRY[normalized] = dossier_cls


def get_dossier_cls(dossier_type: str) -> type[BaseDossier]:
    """Resolve a dossier class from a string identifier.

    Args:
        dossier_type: Type identifier (e.g. 'generic', or pack-registered identifier).

    Returns:
        The matching BaseDossier subclass, defaulting to GenericDocumentDossier.
    """
    normalized = dossier_type.lower().strip().replace("-", "_")
    return DOSSIER_REGISTRY.get(normalized, GenericDocumentDossier)


__all__ = [
    "BaseDossier",
    "DOSSIER_REGISTRY",
    "DocumentDossier",
    "GenericDocumentDossier",
    "get_dossier_cls",
    "register_dossier_type",
]
