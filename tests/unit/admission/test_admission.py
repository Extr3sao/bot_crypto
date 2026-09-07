"""ADMISSION-FOUNDATION-01 tests: registry, state machine, engine/verifier,
confirmation protocol V2, router contract (checkpoint §19, ADM-01..10/16/17)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest

from trading_bot.admission import (
    AdmissionState,
    ConfirmationAuthorityError,
    ConfirmationManifest,
    EvidenceRef,
    IllegalTransitionError,
    PromotionProposal,
    RegistryIntegrityError,
    StrategyAdmissionEngine,
    StrategyAdmissionVerifier,
    StrategyRegistry,
    StrategyVersionRecord,
    VerificationError,
    router_authorizes,
    validate_transition,
)

NOW = "2026-09-07T17:00:00+00:00"


def make_record(
    strategy_id: str = "s1",
    state: AdmissionState = AdmissionState.ROBUSTNESS_PASS,
    **overrides: object,
) -> StrategyVersionRecord:
    base = dict(
        strategy_id=strategy_id,
        version="v1",
        family="momentum",
        source="TEST",
        origin="test",
        assets=("SOL/USDT:USDT",),
        timeframes=("5m",),
        directions=("LONG",),
        config_sha256="cfg",
        code_sha256="code",
        created_at=NOW,
        admission_state=state,
    )
    base.update(overrides)
    return StrategyVersionRecord(**base)


def evidence(*claims: str) -> tuple[EvidenceRef, ...]:
    return tuple(
        EvidenceRef(claim=c, source="test", evidence="artifact", decision="ok") for c in claims
    )


# --- registry (ADM-01) -------------------------------------------------------


def test_registry_identity_is_immutable_under_mutation() -> None:
    r1 = make_record()
    r2 = make_record(config_sha256="CHANGED")
    assert r1.identity_hash() != r2.identity_hash()  # identity fields -> new identity


def test_registry_save_load_roundtrip_and_tamper_detection(tmp_path: Path) -> None:
    reg = StrategyRegistry()
    reg.register(make_record())
    p = tmp_path / "reg.json"
    reg.save(p)
    assert len(StrategyRegistry.load(p).all_records()) == 1
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["records"][0]["config_sha256"] = "TAMPERED"
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RegistryIntegrityError):
        StrategyRegistry.load(p)


def test_registry_evidence_hash_tamper_detected(tmp_path: Path) -> None:
    reg = StrategyRegistry()
    rec = make_record(evidence_refs=evidence("discovery manifest"))
    reg.register(rec)
    p = tmp_path / "reg.json"
    reg.save(p)
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["records"][0]["evidence_refs"][0]["evidence"] = "FORGED"
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RegistryIntegrityError):
        StrategyRegistry.load(p)


# --- state machine (ADM-02/ADM-05) -------------------------------------------


def test_full_legal_chain() -> None:
    chain = [
        AdmissionState.IDEA, AdmissionState.CANDIDATE, AdmissionState.SPECIFIED,
        AdmissionState.IMPLEMENTED, AdmissionState.TESTED, AdmissionState.BACKTEST_PASS,
        AdmissionState.ROBUSTNESS_PASS, AdmissionState.DISCOVERY_PASS,
        AdmissionState.CONFIRMATION_PASS, AdmissionState.HOLDOUT_PASS,
        AdmissionState.SHADOW_PASS, AdmissionState.PAPER_ELIGIBLE,
    ]
    for a, b in pairwise(chain):
        validate_transition(a, b)  # must not raise


@pytest.mark.parametrize(
    "frm,to",
    [
        (AdmissionState.DISCOVERY_PASS, AdmissionState.PAPER_ELIGIBLE),  # §2 example
        (AdmissionState.DISCOVERY_PASS, AdmissionState.HOLDOUT_PASS),
        (AdmissionState.CANDIDATE, AdmissionState.PAPER_ELIGIBLE),
        (AdmissionState.SHADOW_PASS, AdmissionState.BACKTEST_PASS),
        (AdmissionState.REJECTED, AdmissionState.CANDIDATE),  # terminal
        (AdmissionState.RETIRED, AdmissionState.SHADOW_PASS),
        (AdmissionState.ROBUSTNESS_PASS, AdmissionState.CONFIRMATION_PASS),  # skip discovery
    ],
)
def test_illegal_transitions_fail_closed(frm: AdmissionState, to: AdmissionState) -> None:
    with pytest.raises(IllegalTransitionError):
        validate_transition(frm, to)


# --- builder != verifier (ADM-03/ADM-04) --------------------------------------


def test_missing_evidence_blocks_promotion() -> None:
    reg = StrategyRegistry()
    rec = reg.register(make_record()) or None
    rec = reg.get(rec)
    engine = StrategyAdmissionEngine(reg)
    verifier = StrategyAdmissionVerifier(reg)
    prop = engine.propose(
        rec.identity_hash(), AdmissionState.DISCOVERY_PASS, evidence("only one claim"),
        proposed_at=NOW,
    )
    result = verifier.verify(prop)
    assert not result.accepted
    assert "missing required evidence" in result.reason
    with pytest.raises(VerificationError):
        verifier.apply(prop, decision="x", decided_at=NOW)


def test_builder_proposal_without_verifier_does_not_change_state() -> None:
    reg = StrategyRegistry()
    ident = reg.register(make_record())
    engine = StrategyAdmissionEngine(reg)
    prop = engine.propose(
        ident, AdmissionState.DISCOVERY_PASS,
        evidence(
            "discovery_manifest", "data_fingerprint", "pit_proof", "results", "stability"
        ),
        proposed_at=NOW,
    )
    # engine alone has NO apply path; record unchanged
    assert reg.get(ident).admission_state == AdmissionState.ROBUSTNESS_PASS
    assert prop.proposal_sha256  # proposal exists but is not authoritative


def test_verified_promotion_applies_and_records_history() -> None:
    reg = StrategyRegistry()
    ident = reg.register(make_record())
    engine = StrategyAdmissionEngine(reg)
    verifier = StrategyAdmissionVerifier(reg)
    prop = engine.propose(
        ident, AdmissionState.DISCOVERY_PASS,
        evidence(
            "discovery_manifest", "data fingerprint", "pit proof", "results", "stability thirds"
        ),
        proposed_at=NOW,
    )
    assert verifier.verify(prop).accepted
    updated = verifier.apply(prop, decision="verified", decided_at=NOW)
    assert updated.admission_state == AdmissionState.DISCOVERY_PASS
    assert updated.promotion_history[-1]["to"] == "DISCOVERY_PASS"


def test_tampered_proposal_rejected() -> None:
    reg = StrategyRegistry()
    ident = reg.register(make_record())
    engine = StrategyAdmissionEngine(reg)
    verifier = StrategyAdmissionVerifier(reg)
    prop = engine.propose(
        ident, AdmissionState.DISCOVERY_PASS,
        evidence(
            "discovery_manifest", "data fingerprint", "pit proof", "results", "stability"
        ),
        proposed_at=NOW,
    )
    tampered = PromotionProposal(
        strategy_identity=prop.strategy_identity,
        from_state=prop.from_state,
        to_state=prop.to_state,
        evidence=prop.evidence,
        proposed_at=prop.proposed_at,
        proposal_sha256="0" * 64,  # forged
    )
    assert not verifier.verify(tampered).accepted


def test_stale_proposal_after_state_change_rejected() -> None:
    reg = StrategyRegistry()
    ident = reg.register(make_record())
    engine = StrategyAdmissionEngine(reg)
    verifier = StrategyAdmissionVerifier(reg)
    prop = engine.propose(
        ident, AdmissionState.DISCOVERY_PASS,
        evidence(
            "discovery_manifest", "data fingerprint", "pit proof", "results", "stability"
        ),
        proposed_at=NOW,
    )
    verifier.apply(prop, decision="ok", decided_at=NOW)
    assert not verifier.verify(prop).accepted  # now stale: from_state mismatch


def test_trace_reconstruction_from_promotion_history() -> None:
    reg = StrategyRegistry()
    ident = reg.register(make_record(state=AdmissionState.DISCOVERY_PASS))
    engine = StrategyAdmissionEngine(reg)
    verifier = StrategyAdmissionVerifier(reg)
    prop = engine.propose(
        ident, AdmissionState.CONFIRMATION_PASS,
        evidence(
            "discovery_manifest", "execution manifest", "data fingerprint", "cost model",
            "pit proof", "results", "stability", "confirmation manifest",
        ),
        proposed_at=NOW,
    )
    verifier.apply(prop, decision="CONF-EDGE-002-001", decided_at=NOW)
    payload = reg.get(ident)
    assert [
        (h["from"], h["to"]) for h in payload.promotion_history
    ] == [("DISCOVERY_PASS", "CONFIRMATION_PASS")]
    assert payload.promotion_history[0]["decision"] == "CONF-EDGE-002-001"


# --- Confirmation Protocol V2 (ADM-08/09/10) -----------------------------------


def make_manifest(window_start: str, window_end: str, created_at: str) -> ConfirmationManifest:
    return ConfirmationManifest(
        confirmation_id="CONF-T-001",
        strategy_ids=("s1",),
        created_at=created_at,
        commit="deadbeef",
        protocol_version="CONFIRMATION-PROTOCOL-V2",
        window_start=window_start,
        window_end=window_end,
        expected_bars=288,
        assets=("SOL/USDT:USDT",),
        timeframes=("5m",),
        data_source="public",
        acceptance_criteria={"min_trades": 30},
        cost_model_sha256="costs",
        candidate_config_sha256=("cfg",),
    )


def test_manifest_future_ordering_pass() -> None:
    m = make_manifest(
        "2026-09-08T00:00:00+00:00", "2026-09-22T00:00:00+00:00", NOW
    )
    m.verify_future_ordering(
        manifest_commit_time=NOW, execution_time="2026-09-08T06:00:00+00:00"
    )


def test_manifest_created_after_window_start_rejected() -> None:
    m = make_manifest(
        "2026-09-08T00:00:00+00:00", "2026-09-22T00:00:00+00:00", NOW
    )
    with pytest.raises(ConfirmationAuthorityError):
        # manifest "committed" AFTER the window start (the DEF-MA4-style defect)
        m.verify_future_ordering(
            manifest_commit_time="2026-09-09T00:00:00+00:00",
            execution_time="2026-09-10T00:00:00+00:00",
        )


def test_manifest_execution_not_after_window_start_rejected() -> None:
    m = make_manifest(
        "2026-09-08T00:00:00+00:00", "2026-09-22T00:00:00+00:00", NOW
    )
    with pytest.raises(ConfirmationAuthorityError):
        m.verify_future_ordering(
            manifest_commit_time=NOW, execution_time="2026-09-07T23:00:00+00:00"
        )


def test_manifest_single_use_consumption_guard() -> None:
    from trading_bot.admission.confirmation import ConfirmationRegistry

    m = make_manifest(
        "2026-09-08T00:00:00+00:00", "2026-09-22T00:00:00+00:00", NOW
    )
    registry = ConfirmationRegistry()
    registry.consume(m, data_sha256="fp1", executed_at="2026-09-08T06:00:00+00:00")
    assert registry.is_consumed(m.confirmation_id)
    with pytest.raises(ConfirmationAuthorityError, match="CONSUMED"):
        registry.consume(m, data_sha256="fp2", executed_at="2026-09-09T06:00:00+00:00")


def test_manifest_config_hash_mismatch_rejected() -> None:
    m = make_manifest(
        "2026-09-08T00:00:00+00:00", "2026-09-22T00:00:00+00:00", NOW
    )
    with pytest.raises(ConfirmationAuthorityError, match="config hash mismatch"):
        m.verify_configs(("different",))


def test_manifest_immutability_roundtrip(tmp_path: Path) -> None:
    m = make_manifest(
        "2026-09-08T00:00:00+00:00", "2026-09-22T00:00:00+00:00", NOW
    )
    p = tmp_path / "m.json"
    p.write_text(json.dumps(m.to_dict()), encoding="utf-8")
    from trading_bot.admission.confirmation import load_manifest

    assert load_manifest(str(p)).manifest_sha256 == m.manifest_sha256
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["window_start"] = "2026-09-01T00:00:00+00:00"  # forge an earlier window
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfirmationAuthorityError, match="hash mismatch"):
        load_manifest(str(p))


# --- router contract (ADM-18) ---------------------------------------------------


def test_router_authority_mapping() -> None:
    assert router_authorizes(AdmissionState.PAPER_ELIGIBLE, "PAPER")
    assert router_authorizes(AdmissionState.PAPER_ACTIVE, "PAPER")
    assert not router_authorizes(AdmissionState.DISCOVERY_PASS, "PAPER")
    assert router_authorizes(AdmissionState.DISCOVERY_PASS, "SHADOW")
    assert not router_authorizes(AdmissionState.ROBUSTNESS_PASS, "SHADOW")
    assert router_authorizes(AdmissionState.CANDIDATE, "RESEARCH")
    assert not router_authorizes(AdmissionState.PAPER_ELIGIBLE, "LIVE")  # LIVE never


# --- bootstrap artifacts (ADM-06/07) ---------------------------------------------


def test_bootstrap_artifacts_if_present() -> None:
    """The committed bootstrap output must load and satisfy the checkpoint."""
    reg_path = Path("reports/admission-foundation-01/STRATEGY_REGISTRY.json")
    man_path = Path("reports/admission-foundation-01/CONFIRMATION_MANIFEST.json")
    if not reg_path.exists() or not man_path.exists():
        pytest.skip("bootstrap artifacts not generated in this checkout")
    reg = StrategyRegistry.load(reg_path)
    records = reg.all_records()
    assert len(records) == 8
    legacy = [r for r in records if r.admission_state == AdmissionState.LEGACY_PAPER_BASELINE]
    assert len(legacy) == 5
    assert all("Grandfathered" in r.notes for r in legacy)  # honest, not fabricated
    passers = [r for r in records if r.admission_state == AdmissionState.DISCOVERY_PASS]
    assert len(passers) == 3
    assert all(r.confirmation_status == "BLOCKED_CONFIRMATION_AUTHORITY" for r in passers)
    assert all(r.assets == ("SOL/USDT:USDT",) and r.directions == ("LONG",) for r in passers)
    payload = json.loads(man_path.read_text(encoding="utf-8"))
    ws = datetime.fromisoformat(payload["window_start"])
    assert ws > datetime.now(UTC) - timedelta(days=0.5)  # window is future-leaning
