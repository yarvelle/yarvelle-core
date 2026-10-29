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

"""Yarvelle Core: Domain-Neutral AI Agent Runtime & Execution Engine."""

from __future__ import annotations

import importlib as _importlib
import importlib.abc as _importlib_abc
import importlib.machinery as _machinery
import sys as _sys

__version__ = "0.1.2"


class _AliasLoader(_importlib_abc.Loader):
    def __init__(self, target_mod) -> None:
        self.target_mod = target_mod
        self.orig_spec = getattr(target_mod, "__spec__", None)

    def create_module(self, spec):
        return self.target_mod

    def exec_module(self, module):
        if self.orig_spec is not None:
            try:
                module.__spec__ = self.orig_spec
            except AttributeError:
                pass


class _ConnectorsRedirectFinder(_importlib_abc.MetaPathFinder):
    """Redirects top-level `connectors.*` imports to `yarvelle_core.connectors.*`."""

    def find_spec(self, fullname: str, path=None, target=None):
        if fullname == "connectors" or fullname.startswith("connectors."):
            target_name = "yarvelle_core." + fullname
            try:
                mod = _importlib.import_module(target_name)
            except ImportError:
                return None
            is_pkg = hasattr(mod, "__path__")
            spec = _machinery.ModuleSpec(fullname, _AliasLoader(mod), is_package=is_pkg)
            if is_pkg:
                spec.submodule_search_locations = list(mod.__path__)
            return spec
        return None



if not any(type(f).__name__ == "_ConnectorsRedirectFinder" for f in _sys.meta_path):
    _sys.meta_path.insert(0, _ConnectorsRedirectFinder())
