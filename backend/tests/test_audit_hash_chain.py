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

"""Unit tests for SHA-256 tamper-evident hash chaining and scope.cross_read audit logging."""

from __future__ import annotations

import json
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.audit.hash_chain import (
    GENESIS_HASH,
    append_chained_audit_event,
    compute_audit_entry_hash,
    record_scope_cross_read_audit,
    verify_profile_audit_chain,
)
from yarvelle_core.audit.logger import AuditLogger, compute_payload_hash


@pytest.mark.asyncio
async def test_genesis_event_hash_chaining(async_db_session: AsyncSession) -> None:
    """Verify the genesis event correctly anchors to GENESIS_HASH and validates."""
    profile_id = "profile_test_genesis"
    payload = {"operation": "init", "parameters": {"mode": "default"}}
    payload_hash = compute_payload_hash(payload)

    record = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        actor_user_id="user_admin",
        principal="user",
        event="run",
        tool=None,
        risk="read",
        decision="allow",
        payload_hash=payload_hash,
        detail_redacted=json.dumps(payload, sort_keys=True),
        scope="domain_alpha.tasks",
        pack_id="domain_alpha",
        risk_tier="read",
    )
    await async_db_session.commit()

    assert record.prev_hash == GENESIS_HASH
    assert len(record.entry_hash) == 64
    assert record.scope == "domain_alpha.tasks"

    expected_hash = compute_audit_entry_hash(
        prev_hash=GENESIS_HASH,
        event_id=record.id,
        profile_id=profile_id,
        event="run",
        tool=None,
        risk="read",
        decision="allow",
        payload_hash=payload_hash,
        scope="domain_alpha.tasks",
        pack_id="domain_alpha",
        risk_tier="read",
    )
    assert record.entry_hash == expected_hash

    verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verification["valid"] is True
    assert verification["checked_count"] == 1
    assert verification["head_hash"] == record.entry_hash
    assert verification["broken_at_event_id"] is None


@pytest.mark.asyncio
async def test_sequential_hash_chaining_and_monotonic_timestamps(async_db_session: AsyncSession) -> None:
    """Verify multiple sequential events chain cryptographically with increasing timestamps."""
    profile_id = "profile_test_seq"
    records = []

    for idx in range(5):
        payload = {"step": idx, "data": f"content_{idx}"}
        rec = await append_chained_audit_event(
            async_db_session,
            profile_id=profile_id,
            actor_user_id="user_agent",
            principal="agent",
            event="tool",
            tool=f"tool_{idx}",
            risk="read",
            decision="allow",
            payload_hash=compute_payload_hash(payload),
            detail_redacted=json.dumps(payload, sort_keys=True),
            scope="domain_alpha.tasks",
            pack_id="domain_alpha",
            risk_tier="read",
        )
        records.append(rec)

    await async_db_session.commit()

    assert records[0].prev_hash == GENESIS_HASH
    for i in range(1, 5):
        assert records[i].prev_hash == records[i - 1].entry_hash
        assert records[i].ts >= records[i - 1].ts

    verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verification["valid"] is True
    assert verification["checked_count"] == 5
    assert verification["head_hash"] == records[-1].entry_hash


@pytest.mark.asyncio
async def test_tamper_detection_payload_modification(async_db_session: AsyncSession) -> None:
    """Verify post-hoc tampering of payload_hash or metadata fails verification with hash_mismatch."""
    profile_id = "profile_test_tamper_payload"

    r1 = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        event="run",
        scope="domain_alpha",
    )
    r2 = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        event="tool",
        tool="query_tool",
        payload_hash="original_valid_hash_000000000000000000000000000000000000000000000",
        scope="domain_alpha",
    )
    await async_db_session.commit()

    # Tamper with r2's payload_hash in the database row using raw SQL
    from sqlalchemy import text

    await async_db_session.execute(
        text("UPDATE audit_events SET payload_hash = :new_hash WHERE id = :event_id"),
        {"new_hash": "tampered_corrupted_hash_999999999999999999999999999999999999999999", "event_id": r2.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verification["valid"] is False
    assert verification["reason"] == "hash_mismatch"
    assert verification["broken_at_event_id"] == r2.id


@pytest.mark.asyncio
async def test_tamper_detection_prev_hash_modification(async_db_session: AsyncSession) -> None:
    """Verify tampering with prev_hash or inserting an unlinked row fails with prev_hash_mismatch."""
    profile_id = "profile_test_tamper_chain"

    r1 = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        event="run",
        scope="domain_alpha",
    )
    r2 = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        event="tool",
        scope="domain_alpha",
    )
    await async_db_session.commit()

    # Tamper with r2's prev_hash using raw SQL
    from sqlalchemy import text

    await async_db_session.execute(
        text("UPDATE audit_events SET prev_hash = :new_prev WHERE id = :event_id"),
        {"new_prev": "0000000000000000000000000000000000000000000000000000000000000000", "event_id": r2.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verification["valid"] is False
    assert verification["reason"] == "prev_hash_mismatch"
    assert verification["broken_at_event_id"] == r2.id


@pytest.mark.asyncio
async def test_record_scope_cross_read_audit_success(async_db_session: AsyncSession) -> None:
    """Verify record_scope_cross_read_audit logs valid scope.cross_read events chained cryptographically."""
    profile_id = "profile_test_cross_read"

    # 1. Anchor with a base event
    base_event = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        event="run",
        scope="domain_alpha.tasks",
    )
    await async_db_session.commit()

    # 2. Record cross-read audit event
    claim_keys = ["resource_limit", "alpha_quota", "beta_threshold"]
    cross_read_rec = await record_scope_cross_read_audit(
        async_db_session,
        reader_agent_id="specialist_alpha",
        reader_scope="domain_alpha.tasks",
        target_agent_id="specialist_beta",
        target_scope="domain_beta.metrics",
        claim_keys=claim_keys,
        round_num=2,
        profile_id=profile_id,
        actor_user_id="user_test",
        run_id="run_123",
        panel_id="panel_multi_1",
    )
    await async_db_session.commit()

    assert cross_read_rec.event == "scope.cross_read"
    assert cross_read_rec.prev_hash == base_event.entry_hash
    assert cross_read_rec.scope == "domain_alpha.tasks"
    assert cross_read_rec.risk == "read"
    assert cross_read_rec.decision == "allow"
    assert cross_read_rec.risk_tier == "read"

    # Detail must contain sorted claim keys and canonical metadata
    payload_data = json.loads(cross_read_rec.detail_redacted)
    assert payload_data["claim_keys"] == sorted(claim_keys)
    assert payload_data["reader_agent_id"] == "specialist_alpha"
    assert payload_data["reader_scope"] == "domain_alpha.tasks"
    assert payload_data["target_agent_id"] == "specialist_beta"
    assert payload_data["source_scope"] == "domain_beta.metrics"
    assert payload_data["round_num"] == 2
    assert payload_data["panel_id"] == "panel_multi_1"

    # Cryptographic integrity must pass
    verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verification["valid"] is True
    assert verification["checked_count"] == 2
    assert verification["head_hash"] == cross_read_rec.entry_hash


@pytest.mark.asyncio
async def test_interleaved_audit_events_integrity(async_db_session: AsyncSession) -> None:
    """Verify chain validity when standard events and scope.cross_read events are interleaved."""
    profile_id = "profile_test_interleaved"

    # Event 1: run
    e1 = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        event="run",
        scope="domain_alpha.tasks",
    )

    # Event 2: scope.cross_read
    e2 = await record_scope_cross_read_audit(
        async_db_session,
        reader_agent_id="specialist_alpha",
        reader_scope="domain_alpha.tasks",
        target_agent_id="specialist_beta",
        target_scope="domain_beta.metrics",
        claim_keys=["quota_limit"],
        round_num=1,
        profile_id=profile_id,
    )

    # Event 3: tool execution
    e3 = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        event="tool",
        tool="compute_metrics",
        scope="domain_alpha.tasks",
    )

    # Event 4: second scope.cross_read in round 2
    e4 = await record_scope_cross_read_audit(
        async_db_session,
        reader_agent_id="specialist_alpha",
        reader_scope="domain_alpha.tasks",
        target_agent_id="specialist_beta",
        target_scope="domain_beta.metrics",
        claim_keys=["quota_limit", "cost_window"],
        round_num=2,
        profile_id=profile_id,
    )

    await async_db_session.commit()

    assert e2.prev_hash == e1.entry_hash
    assert e3.prev_hash == e2.entry_hash
    assert e4.prev_hash == e3.entry_hash

    verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verification["valid"] is True
    assert verification["checked_count"] == 4
    assert verification["head_hash"] == e4.entry_hash


@pytest.mark.asyncio
async def test_audit_logger_record_cross_read_integration(async_db_session: AsyncSession) -> None:
    """Verify AuditLogger.record_cross_read classmethod dispatches and persists correctly."""
    profile_id = "profile_test_logger_alias"

    rec = await AuditLogger.record_cross_read(
        session=async_db_session,
        reader_agent_id="agent_r",
        reader_scope="domain_x.ops",
        target_agent_id="agent_t",
        target_scope="domain_y.data",
        claim_keys=["rate_ceiling"],
        round_num=1,
        profile_id=profile_id,
    )
    await async_db_session.commit()

    assert rec.event == "scope.cross_read"
    assert rec.entry_hash is not None
    assert rec.prev_hash == GENESIS_HASH

    verification = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verification["valid"] is True


@pytest.mark.asyncio
async def test_adversarial_tamper_detection_record_deletion(async_db_session: AsyncSession) -> None:
    """Adversarial: Delete an intermediate record via raw SQL and verify detection on successor."""
    from sqlalchemy import text

    profile_id = "profile_adv_deletion"

    records = []
    for i in range(4):
        rec = await append_chained_audit_event(
            async_db_session,
            profile_id=profile_id,
            event="tool" if i % 2 == 0 else "run",
            tool=f"tool_{i}" if i % 2 == 0 else None,
            scope="domain_alpha.ops",
        )
        records.append(rec)
    await async_db_session.commit()

    init_verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert init_verif["valid"] is True
    assert init_verif["checked_count"] == 4

    # Attack: Delete intermediate record records[1] via raw SQL
    deleted_id = records[1].id
    successor_id = records[2].id
    await async_db_session.execute(
        text("DELETE FROM audit_events WHERE id = :event_id"),
        {"event_id": deleted_id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    # Successor record[2] must fail with prev_hash_mismatch
    verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verif["valid"] is False
    assert verif["reason"] == "prev_hash_mismatch"
    assert verif["broken_at_event_id"] == successor_id
    assert verif["checked_count"] == 2


@pytest.mark.asyncio
async def test_adversarial_tamper_detection_genesis_deletion(async_db_session: AsyncSession) -> None:
    """Adversarial: Delete the genesis record via raw SQL and verify prev_hash_mismatch on successor."""
    from sqlalchemy import text

    profile_id = "profile_adv_genesis_del"

    r1 = await append_chained_audit_event(async_db_session, profile_id=profile_id, event="run", scope="domain_alpha.ops")
    r2 = await append_chained_audit_event(async_db_session, profile_id=profile_id, event="tool", scope="domain_alpha.ops")
    await async_db_session.commit()

    # Delete genesis record r1
    await async_db_session.execute(
        text("DELETE FROM audit_events WHERE id = :event_id"),
        {"event_id": r1.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    # r2 now looks like genesis but its prev_hash points to r1.entry_hash instead of GENESIS
    verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verif["valid"] is False
    assert verif["reason"] == "prev_hash_mismatch"
    assert verif["broken_at_event_id"] == r2.id
    assert verif["checked_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field_to_tamper,tampered_value",
    [
        ("event", "unauthorized_event"),
        ("tool", "malicious_tool"),
        ("scope", "domain_unauthorized"),
        ("tier", "irreversible"),
        ("decision", "deny"),
        ("risk", "write_external"),
    ],
)
async def test_adversarial_tamper_detection_metadata_fields(
    async_db_session: AsyncSession,
    field_to_tamper: str,
    tampered_value: str,
) -> None:
    """Adversarial: Modify individual metadata fields via raw SQL and verify hash_mismatch detection."""
    from sqlalchemy import text

    profile_id = f"profile_adv_tamper_{field_to_tamper}"

    r1 = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        event="run",
        scope="domain_alpha.ops",
    )
    r2 = await append_chained_audit_event(
        async_db_session,
        profile_id=profile_id,
        event="tool",
        tool="authorized_tool",
        risk="read",
        decision="allow",
        scope="domain_alpha.ops",
        pack_id="domain_alpha",
        risk_tier="read",
    )
    await async_db_session.commit()

    # Tamper with the chosen metadata field in r2 via raw SQL
    await async_db_session.execute(
        text(f"UPDATE audit_events SET {field_to_tamper} = :val WHERE id = :event_id"),
        {"val": tampered_value, "event_id": r2.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verif["valid"] is False
    assert verif["reason"] == "hash_mismatch"
    assert verif["broken_at_event_id"] == r2.id


@pytest.mark.asyncio
async def test_adversarial_tamper_detection_entry_hash_splicing(async_db_session: AsyncSession) -> None:
    """Adversarial: Tamper with record r2 AND recompute r2's entry_hash; verify r3 catches the prev_hash break."""
    from sqlalchemy import text

    profile_id = "profile_adv_splicing"

    r1 = await append_chained_audit_event(async_db_session, profile_id=profile_id, event="run", scope="domain_alpha")
    r2 = await append_chained_audit_event(async_db_session, profile_id=profile_id, event="tool", tool="tool_a", scope="domain_alpha")
    r3 = await append_chained_audit_event(async_db_session, profile_id=profile_id, event="tool", tool="tool_b", scope="domain_alpha")
    await async_db_session.commit()

    # Attacker recomputes r2's entry_hash with forged tool name to pass r2's internal hash check
    forged_hash = compute_audit_entry_hash(
        prev_hash=r2.prev_hash,
        event_id=r2.id,
        profile_id=profile_id,
        event="tool",
        tool="forged_tool",
        risk=r2.risk,
        decision=r2.decision,
        payload_hash=r2.payload_hash,
        scope=r2.scope,
        pack_id=r2.pack_id,
        risk_tier=r2.risk_tier,
    )

    await async_db_session.execute(
        text("UPDATE audit_events SET tool = 'forged_tool', entry_hash = :new_hash WHERE id = :event_id"),
        {"new_hash": forged_hash, "event_id": r2.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    # Verification of r2 passes internally, but successor r3 must fail with prev_hash_mismatch
    verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verif["valid"] is False
    assert verif["reason"] == "prev_hash_mismatch"
    assert verif["broken_at_event_id"] == r3.id
    assert verif["checked_count"] == 3


@pytest.mark.asyncio
async def test_adversarial_canonical_payload_determinism_unsorted_claim_keys(async_db_session: AsyncSession) -> None:
    """Adversarial: Verify claim_keys order permutation produces identical payload_hash and canonical structure."""
    profile_id = "profile_adv_determinism"

    keys_order_1 = ["zeta_constraint", "alpha_quota", "mid_threshold", "beta_budget"]
    keys_order_2 = ["alpha_quota", "beta_budget", "mid_threshold", "zeta_constraint"]
    keys_order_3 = ("mid_threshold", "zeta_constraint", "beta_budget", "alpha_quota")

    rec1 = await record_scope_cross_read_audit(
        async_db_session,
        reader_agent_id="agent_alpha",
        reader_scope="domain_alpha",
        target_agent_id="agent_beta",
        target_scope="domain_beta",
        claim_keys=keys_order_1,
        round_num=1,
        profile_id=profile_id,
        panel_id="panel_test",
    )
    rec2 = await record_scope_cross_read_audit(
        async_db_session,
        reader_agent_id="agent_alpha",
        reader_scope="domain_alpha",
        target_agent_id="agent_beta",
        target_scope="domain_beta",
        claim_keys=keys_order_2,
        round_num=1,
        profile_id=profile_id,
        panel_id="panel_test",
    )
    rec3 = await record_scope_cross_read_audit(
        async_db_session,
        reader_agent_id="agent_alpha",
        reader_scope="domain_alpha",
        target_agent_id="agent_beta",
        target_scope="domain_beta",
        claim_keys=keys_order_3,
        round_num=1,
        profile_id=profile_id,
        panel_id="panel_test",
    )
    await async_db_session.commit()

    # All three must share identical payload_hash
    assert rec1.payload_hash is not None
    assert rec1.payload_hash == rec2.payload_hash
    assert rec2.payload_hash == rec3.payload_hash

    # Detail redacted JSON must be byte-for-byte identical
    assert rec1.detail_redacted == rec2.detail_redacted
    assert rec2.detail_redacted == rec3.detail_redacted

    # Verify exact schema structure
    payload = json.loads(rec1.detail_redacted)
    expected_sorted = ["alpha_quota", "beta_budget", "mid_threshold", "zeta_constraint"]
    assert payload["claim_keys"] == expected_sorted
    assert payload["reader_agent_id"] == "agent_alpha"
    assert payload["reader_scope"] == "domain_alpha"
    assert payload["target_agent_id"] == "agent_beta"
    assert payload["target_scope"] == "domain_beta"
    assert payload["source_scope"] == "domain_beta"
    assert payload["round_num"] == 1
    assert payload["panel_id"] == "panel_test"

    verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verif["valid"] is True
    assert verif["checked_count"] == 3


@pytest.mark.asyncio
async def test_adversarial_stress_interleaved_event_stream(async_db_session: AsyncSession) -> None:
    """Adversarial: Heavy interleaving of scope.cross_read with tool, run, refuse, synthesis, boundary_warning."""
    profile_id = "profile_adv_stress_interleaving"

    event_sequence = [
        ("run", None, None),
        ("scope.cross_read", ["alpha_quota"], 1),
        ("tool", "tool_query", None),
        ("scope.cross_read", ["beta_limit", "alpha_quota"], 1),
        ("refuse", None, None),
        ("tool", "tool_check", None),
        ("boundary_warning", None, None),
        ("scope.cross_read", ["gamma_window"], 2),
        ("synthesis", None, None),
        ("error", None, None),
        ("scope.cross_read", ["delta_flag", "alpha_quota"], 2),
        ("tool", "tool_finalize", None),
    ]

    records = []
    for item in event_sequence:
        event_type, claim_keys, round_num = item
        if event_type == "scope.cross_read":
            rec = await record_scope_cross_read_audit(
                async_db_session,
                reader_agent_id="specialist_alpha",
                reader_scope="domain_alpha.ops",
                target_agent_id="specialist_beta",
                target_scope="domain_beta.ops",
                claim_keys=claim_keys,
                round_num=round_num,
                profile_id=profile_id,
            )
        else:
            rec = await append_chained_audit_event(
                async_db_session,
                profile_id=profile_id,
                event=event_type,
                tool=claim_keys if isinstance(claim_keys, str) else None,
                scope="domain_alpha.ops",
            )
        records.append(rec)

    await async_db_session.commit()

    assert records[0].prev_hash == GENESIS_HASH
    for i in range(1, len(records)):
        assert records[i].prev_hash == records[i - 1].entry_hash
        assert records[i].ts >= records[i - 1].ts

    verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verif["valid"] is True
    assert verif["checked_count"] == len(records)
    assert verif["head_hash"] == records[-1].entry_hash


@pytest.mark.asyncio
async def test_adversarial_profile_isolation(async_db_session: AsyncSession) -> None:
    """Adversarial: Ensure multiple profiles maintain strictly isolated hash chains without cross-pollution."""
    p_alpha = "profile_adv_alpha"
    p_beta = "profile_adv_beta"

    a1 = await append_chained_audit_event(async_db_session, profile_id=p_alpha, event="run", scope="domain_alpha")
    b1 = await append_chained_audit_event(async_db_session, profile_id=p_beta, event="run", scope="domain_beta")
    a2 = await record_scope_cross_read_audit(
        async_db_session,
        reader_agent_id="agent_a",
        reader_scope="domain_alpha",
        target_agent_id="agent_b",
        target_scope="domain_beta",
        claim_keys=["quota_limit"],
        round_num=1,
        profile_id=p_alpha,
    )
    b2 = await append_chained_audit_event(async_db_session, profile_id=p_beta, event="tool", scope="domain_beta")

    await async_db_session.commit()

    assert a1.prev_hash == GENESIS_HASH
    assert a2.prev_hash == a1.entry_hash

    assert b1.prev_hash == GENESIS_HASH
    assert b2.prev_hash == b1.entry_hash

    verif_a = await verify_profile_audit_chain(async_db_session, p_alpha)
    assert verif_a["valid"] is True
    assert verif_a["checked_count"] == 2
    assert verif_a["head_hash"] == a2.entry_hash

    verif_b = await verify_profile_audit_chain(async_db_session, p_beta)
    assert verif_b["valid"] is True
    assert verif_b["checked_count"] == 2
    assert verif_b["head_hash"] == b2.entry_hash


@pytest.mark.asyncio
async def test_adversarial_empty_claim_keys_and_slug_keys(async_db_session: AsyncSession) -> None:
    """Adversarial: Verify empty claim_keys and slug formatted claim_keys chain cleanly."""
    profile_id = "profile_adv_empty_and_slug_keys"

    rec1 = await record_scope_cross_read_audit(
        async_db_session,
        reader_agent_id="agent_alpha",
        reader_scope="domain_alpha",
        target_agent_id="agent_beta",
        target_scope="domain_beta",
        claim_keys=[],
        round_num=1,
        profile_id=profile_id,
    )
    rec2 = await record_scope_cross_read_audit(
        async_db_session,
        reader_agent_id="agent_alpha",
        reader_scope="domain_alpha",
        target_agent_id="agent_beta",
        target_scope="domain_beta",
        claim_keys=["valid-slug-key_1", "another_valid-key-2"],
        round_num=2,
        profile_id=profile_id,
    )
    await async_db_session.commit()

    payload1 = json.loads(rec1.detail_redacted)
    assert payload1["claim_keys"] == []
    payload2 = json.loads(rec2.detail_redacted)
    assert payload2["claim_keys"] == ["another_valid-key-2", "valid-slug-key_1"]

    verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verif["valid"] is True
    assert verif["checked_count"] == 2


@pytest.mark.asyncio
async def test_adversarial_empty_profile_chain_verification(async_db_session: AsyncSession) -> None:
    """Adversarial: Verify empty profile audit chain returns valid=True, checked_count=0, head_hash=GENESIS."""
    profile_id = "profile_adv_empty_nonexistent"
    verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verif["valid"] is True
    assert verif["checked_count"] == 0
    assert verif["head_hash"] == GENESIS_HASH
    assert verif["broken_at_event_id"] is None
    assert verif["reason"] is None


@pytest.mark.asyncio
async def test_adversarial_timestamp_order_swap_attack(async_db_session: AsyncSession) -> None:
    """Adversarial: Raw SQL swap of timestamps between R2 and R3; verify ordering break causes prev_hash_mismatch."""
    from sqlalchemy import text

    profile_id = "profile_adv_swap_attack"

    r1 = await append_chained_audit_event(async_db_session, profile_id=profile_id, event="run", scope="domain_alpha")
    r2 = await append_chained_audit_event(async_db_session, profile_id=profile_id, event="tool", tool="tool_alpha", scope="domain_alpha")
    r3 = await append_chained_audit_event(async_db_session, profile_id=profile_id, event="tool", tool="tool_beta", scope="domain_alpha")
    await async_db_session.commit()

    # Swap timestamps of r2 and r3 so that r3 sorts before r2
    t2, t3 = r2.ts, r3.ts
    await async_db_session.execute(
        text("UPDATE audit_events SET ts = :t3 WHERE id = :r2_id"),
        {"t3": t3, "r2_id": r2.id},
    )
    await async_db_session.execute(
        text("UPDATE audit_events SET ts = :t2 WHERE id = :r3_id"),
        {"t2": t2, "r3_id": r3.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    # When ordered by ts.asc(), query loads [r1, r3, r2]
    # At r3, expected_prev is r1.entry_hash, but r3.prev_hash is r2.entry_hash -> prev_hash_mismatch!
    verif = await verify_profile_audit_chain(async_db_session, profile_id)
    assert verif["valid"] is False
    assert verif["reason"] == "prev_hash_mismatch"
    assert verif["broken_at_event_id"] == r3.id


@pytest.mark.asyncio
async def test_adversarial_cross_profile_migration_attack(async_db_session: AsyncSession) -> None:
    """Adversarial: Move a record from profile A to profile B via raw SQL; verify both profile chains fail."""
    from sqlalchemy import text

    p_src = "profile_adv_src"
    p_dst = "profile_adv_dst"

    s1 = await append_chained_audit_event(async_db_session, profile_id=p_src, event="run", scope="domain_alpha")
    s2 = await append_chained_audit_event(async_db_session, profile_id=p_src, event="tool", tool="t1", scope="domain_alpha")
    s3 = await append_chained_audit_event(async_db_session, profile_id=p_src, event="tool", tool="t2", scope="domain_alpha")

    d1 = await append_chained_audit_event(async_db_session, profile_id=p_dst, event="run", scope="domain_beta")
    await async_db_session.commit()

    # Move s2 from p_src to p_dst via raw SQL
    await async_db_session.execute(
        text("UPDATE audit_events SET profile_id = :p_dst WHERE id = :s2_id"),
        {"p_dst": p_dst, "s2_id": s2.id},
    )
    await async_db_session.commit()
    async_db_session.expire_all()

    # p_src chain: s1 -> s3 (s2 missing). s3 expects s2.entry_hash, expected_prev is s1.entry_hash -> fail!
    verif_src = await verify_profile_audit_chain(async_db_session, p_src)
    assert verif_src["valid"] is False
    assert verif_src["reason"] == "prev_hash_mismatch"
    assert verif_src["broken_at_event_id"] == s3.id

    # p_dst chain: d1 -> s2. s2 has prev_hash = s1.entry_hash, but expected_prev in dst is d1.entry_hash -> fail!
    verif_dst = await verify_profile_audit_chain(async_db_session, p_dst)
    assert verif_dst["valid"] is False
    assert verif_dst["reason"] in ("prev_hash_mismatch", "hash_mismatch")
    assert verif_dst["broken_at_event_id"] == s2.id


