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

"""Unit tests for Scoped Content-Addressed Storage (CAS)."""

from __future__ import annotations

import hashlib
from pathlib import Path
import pytest

from yarvelle_core.storage.cas import (
    cas_file_exists,
    get_cas_path,
    read_cas_file,
    sanitize_partition_segment,
    store_cas_file,
)


def test_sanitize_partition_segment_security():
    """Verify traversal sequences are blocked."""
    assert sanitize_partition_segment("valid_user") == "valid_user"
    assert sanitize_partition_segment("user-123.abc") == "user-123.abc"

    with pytest.raises(ValueError):
        sanitize_partition_segment("../escaped")
    with pytest.raises(ValueError):
        sanitize_partition_segment("user/child")
    with pytest.raises(ValueError):
        sanitize_partition_segment("user\0null")


def test_cas_partitioned_storage_and_read(tmp_path: Path):
    """Verify CAS stores content under <home>/data/files/<user>/<profile>/<scope>/<sha>."""
    home = tmp_path / "home"
    payload = b"Top secret household financial statement"
    expected_sha = hashlib.sha256(payload).hexdigest()

    path, sha, is_dedup = store_cas_file(
        content=payload,
        yarvelle_home=home,
        user_id="usr_1",
        profile_id="prf_1",
        scope="finance.accounts",
    )

    assert sha == expected_sha
    assert is_dedup is False
    assert path == get_cas_path(home, "usr_1", "prf_1", sha, scope="finance.accounts")
    assert cas_file_exists(home, "usr_1", "prf_1", sha, scope="finance.accounts")

    # Read back with correct scope
    read_content = read_cas_file(home, "usr_1", "prf_1", sha, scope="finance.accounts")
    assert read_content == payload

    # Read back with wrong scope raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        read_cas_file(home, "usr_1", "prf_1", sha, scope="health.records")
