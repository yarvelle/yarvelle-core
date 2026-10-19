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

"""Conformance suite isolation layer tests."""

from yarvelle_core.conformance.layers.base import BaseIsolationLayerTest
from yarvelle_core.conformance.layers.layer_01_orm import Layer01OrmTest
from yarvelle_core.conformance.layers.layer_02_cas import Layer02CasTest
from yarvelle_core.conformance.layers.layer_03_fts5 import Layer03Fts5Test
from yarvelle_core.conformance.layers.layer_04_memory import Layer04MemoryTest
from yarvelle_core.conformance.layers.layer_05_vault import Layer05VaultTest
from yarvelle_core.conformance.layers.layer_06_tool_gate import Layer06ToolGateTest
from yarvelle_core.conformance.layers.layer_07_prompt import Layer07PromptTest
from yarvelle_core.conformance.layers.layer_08_api import Layer08ApiTest
from yarvelle_core.conformance.layers.layer_09_export import Layer09ExportTest
from yarvelle_core.conformance.layers.layer_10_audit import Layer10AuditTest
from yarvelle_core.conformance.layers.layer_11_redaction import Layer11RedactionTest

ALL_ISOLATION_LAYERS = [
    Layer01OrmTest(),
    Layer02CasTest(),
    Layer03Fts5Test(),
    Layer04MemoryTest(),
    Layer05VaultTest(),
    Layer06ToolGateTest(),
    Layer07PromptTest(),
    Layer08ApiTest(),
    Layer09ExportTest(),
    Layer10AuditTest(),
    Layer11RedactionTest(),
]

__all__ = [
    "BaseIsolationLayerTest",
    "Layer01OrmTest",
    "Layer02CasTest",
    "Layer03Fts5Test",
    "Layer04MemoryTest",
    "Layer05VaultTest",
    "Layer06ToolGateTest",
    "Layer07PromptTest",
    "Layer08ApiTest",
    "Layer09ExportTest",
    "Layer10AuditTest",
    "Layer11RedactionTest",
    "ALL_ISOLATION_LAYERS",
]
