"""Persistence / restart / replay / corruption tests — GATE STRAT-PERSIST-003.

Closes DEF-VERIFY-010 coverage: state persists, restart is deterministic, a
corrupt store fails closed and replay reconstructs the same state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_bot.strategy_lifecycle.contracts import (
    ContextKey,
    LifecycleState,
    PromotionRecord,
)
from trading_bot.strategy_lifecycle.ecosystem import DynamicStrategyEcosystem
from trading_bot.strategy_lifecycle.lifecycle import LifecycleDecision
from trading_bot.strategy_lifecycle.persistence import (
    LifecycleCorruptionError,
    LifecyclePersistenceError,
    LifecycleSchemaVersionError,
    ecosystem_state_hash,
    load_ecosystem,
    replay_lifecycle,
    restore_ecosystem,
    save_ecosystem,
    snapshot_ecosystem,
)

from ._helpers import descriptor, observation

# state -> the chain of states to walk from SHADOW
_CHAINS: dict[LifecycleState, list[LifecycleState]] = {
    LifecycleState.SHADOW: [],
    LifecycleState.ELIGIBLE: [LifecycleState.ELIGIBLE],
    LifecycleState.ACTIVE: [LifecycleState.ELIGIBLE, LifecycleState.ACTIVE],
    LifecycleState.DEGRADED: [
        LifecycleState.ELIGIBLE,
        LifecycleState.ACTIVE,
        LifecycleState.DEGRADED,
    ],
    LifecycleState.THROTTLED: [
        LifecycleState.ELIGIBLE,
        LifecycleState.ACTIVE,
        LifecycleState.DEGRADED,
        LifecycleState.THROTTLED,
    ],
    LifecycleState.PAUSED: [LifecycleState.PAUSED],
    LifecycleState.RETIRED: [LifecycleState.RETIRED],
}

_EVIDENCE_EDGES = {
    (LifecycleState.SHADOW, LifecycleState.ELIGIBLE),
    (LifecycleState.ELIGIBLE, LifecycleState.ACTIVE),
}


def _advance(eco: DynamicStrategyEcosystem, sid: str, target: LifecycleState, *, ts: int) -> None:
    reg = eco.registry
    src = reg.state_of(sid)
    assert src is not None
    promo = None
    if (src, target) in _EVIDENCE_EDGES:
        promo = PromotionRecord(
            promotion_id=f"{sid}:{src.value}->{target.value}:{ts}",
            strategy_id=sid,
            from_state=src,
            to_state=target,
            evidence=("persistence-test",),
            policy_version="v1",
        )
    reg.apply(
        LifecycleDecision(
            strategy_id=sid,
            context=ContextKey(sid, "BTC", "5m", "TREND_UP"),
            from_state=src,
            to_state=target,
            reason_codes=("TEST",),
            metrics_snapshot={},
            evidence=("persistence-test",),
            policy_version="v1",
            promotion=promo,
            timestamp_ms=ts,
        )
    )


def _ecosystem() -> DynamicStrategyEcosystem:
    eco = DynamicStrategyEcosystem()
    ts = 1_000
    for state, chain in _CHAINS.items():
        sid = f"s-{state.value.lower()}"
        eco.register(descriptor(sid, state=LifecycleState.SHADOW))
        reg = eco.registry
        for step in chain:
            _advance(eco, sid, step, ts=ts)
            ts += 1
        reg._degraded_streak[sid] = 2
    # A few observations so the performance store is non-trivial.
    for i in range(5):
        eco.performance.record(observation("s-active", net_bps=10.0, timestamp_ms=i * 1000))
    return eco


# --------------------------------------------------------------------------- #
# Snapshot / restore round-trip (§5)
# --------------------------------------------------------------------------- #


def test_snapshot_restore_preserves_every_state() -> None:
    eco = _ecosystem()
    payload = snapshot_ecosystem(eco, run_id="run-1", commit_sha="deadbeef", persisted_at_ms=5)

    restored = DynamicStrategyEcosystem()
    restore_ecosystem(restored, payload)

    for state in _CHAINS:
        sid = f"s-{state.value.lower()}"
        assert restored.registry.state_of(sid) is state, sid
    assert ecosystem_state_hash(eco) == ecosystem_state_hash(restored)
    assert restored.performance.observations(ContextKey("s-active", "BTC", "5m", "TREND_UP")) == (
        eco.performance.observations(ContextKey("s-active", "BTC", "5m", "TREND_UP"))
    )


def test_snapshot_has_mandated_event_log_fields() -> None:
    payload = snapshot_ecosystem(_ecosystem(), run_id="run-1", commit_sha="deadbeef")
    assert payload["event_log"], "an ecosystem with transitions must have an event log"
    row = payload["event_log"][0]
    for field in (
        "event_id",
        "run_id",
        "strategy_id",
        "strategy_version",
        "from_state",
        "to_state",
        "reason",
        "evidence_ids",
        "timestamp",
        "schema_version",
        "commit_sha",
    ):
        assert field in row, field


def test_restart_does_not_promote() -> None:
    eco = _ecosystem()
    payload = snapshot_ecosystem(eco, run_id="r", commit_sha="c")
    restored = DynamicStrategyEcosystem()
    restore_ecosystem(restored, payload)
    # No strategy gained a state: the SHADOW one is still SHADOW.
    assert restored.registry.state_of("s-shadow") is LifecycleState.SHADOW
    assert restored.registry.active_ids() == ["s-active"]


# --------------------------------------------------------------------------- #
# Atomicity (§3)
# --------------------------------------------------------------------------- #


def test_save_is_atomic_and_leaves_no_temp(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle_state.json"
    save_ecosystem(path, _ecosystem(), run_id="r", commit_sha="c")
    assert path.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_stray_temp_file_does_not_corrupt_load(tmp_path: Path) -> None:
    path = tmp_path / "lifecycle_state.json"
    eco = _ecosystem()
    save_ecosystem(path, eco, run_id="r", commit_sha="c")
    (tmp_path / "lifecycle_state.json.tmp").write_text("{ partial", encoding="utf-8")
    restored = DynamicStrategyEcosystem()
    load_ecosystem(path, restored)
    assert ecosystem_state_hash(eco) == ecosystem_state_hash(restored)


def test_load_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(LifecyclePersistenceError):
        load_ecosystem(tmp_path / "nope.json", DynamicStrategyEcosystem())


# --------------------------------------------------------------------------- #
# Schema versioning + corruption (§4/§6) — all fail closed
# --------------------------------------------------------------------------- #


def _valid_payload() -> dict:
    return snapshot_ecosystem(_ecosystem(), run_id="r", commit_sha="c")


def test_unknown_newer_schema_is_refused() -> None:
    payload = _valid_payload()
    payload["schema_version"] = "strategy-lifecycle-persistence-v99"
    with pytest.raises(LifecycleSchemaVersionError):
        restore_ecosystem(DynamicStrategyEcosystem(), payload)


def test_missing_schema_is_refused() -> None:
    payload = _valid_payload()
    del payload["schema_version"]
    with pytest.raises(LifecycleCorruptionError):
        restore_ecosystem(DynamicStrategyEcosystem(), payload)


def test_checksum_mismatch_is_refused() -> None:
    payload = _valid_payload()
    # A real content change without recomputing the checksum.
    payload["registry"]["descriptors"][0]["lifecycle_state"] = "PAUSED"
    with pytest.raises(LifecycleCorruptionError):
        restore_ecosystem(DynamicStrategyEcosystem(), payload)


def test_truncated_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text('{"schema_version":"strategy-lifecycle-persistence-v1",', encoding="utf-8")
    with pytest.raises(LifecycleCorruptionError):
        load_ecosystem(path, DynamicStrategyEcosystem())


def test_broken_history_chain_is_refused() -> None:
    payload = _valid_payload()
    # Tamper with a history row and recompute the checksum so only the chain is wrong.
    import hashlib

    def canon(obj: object) -> str:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    key = "s-active"
    # Break continuity between row 0 (-> ELIGIBLE) and row 1.
    payload["registry"]["history"][key][1]["from_state"] = "DEGRADED"
    body = {k: v for k, v in payload.items() if k != "checksum"}
    payload["checksum"] = hashlib.sha256(canon(body).encode()).hexdigest()
    with pytest.raises(LifecycleCorruptionError):
        restore_ecosystem(DynamicStrategyEcosystem(), payload)


def test_invalid_enum_is_refused() -> None:
    payload = _valid_payload()
    import hashlib

    def canon(obj: object) -> str:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    payload["registry"]["descriptors"][0]["lifecycle_state"] = "TOTALLY_MADE_UP"
    body = {k: v for k, v in payload.items() if k != "checksum"}
    payload["checksum"] = hashlib.sha256(canon(body).encode()).hexdigest()
    with pytest.raises(LifecycleCorruptionError):
        restore_ecosystem(DynamicStrategyEcosystem(), payload)


def test_corrupt_state_leaves_target_empty_and_not_eligible() -> None:
    """A refused restore must never best-effort into ACTIVE/ELIGIBLE."""
    target = DynamicStrategyEcosystem()
    payload = _valid_payload()
    payload["checksum"] = "0" * 64
    with pytest.raises(LifecycleCorruptionError):
        restore_ecosystem(target, payload)
    assert target.registry.strategy_ids() == []
    assert target.registry.active_ids() == []


# --------------------------------------------------------------------------- #
# Replay (§7)
# --------------------------------------------------------------------------- #


def test_replay_reconstructs_the_same_state() -> None:
    eco = _ecosystem()
    for state in _CHAINS:
        sid = f"s-{state.value.lower()}"
        history = eco.registry.history(sid)
        start = LifecycleState.SHADOW
        replayed = replay_lifecycle(start, history)
        assert replayed is eco.registry.state_of(sid), sid


def test_replay_is_deterministic_and_orders_matter() -> None:
    eco = _ecosystem()
    history = eco.registry.history("s-active")
    assert replay_lifecycle(LifecycleState.SHADOW, history) == replay_lifecycle(
        LifecycleState.SHADOW, history
    )
    with pytest.raises(LifecycleCorruptionError):
        replay_lifecycle(LifecycleState.SHADOW, list(reversed(history)))


def test_original_hash_equals_restored_hash() -> None:
    eco = _ecosystem()
    original = ecosystem_state_hash(eco)
    payload = snapshot_ecosystem(eco, run_id="r", commit_sha="c")
    restored = DynamicStrategyEcosystem()
    restore_ecosystem(restored, payload)
    assert ecosystem_state_hash(restored) == original
