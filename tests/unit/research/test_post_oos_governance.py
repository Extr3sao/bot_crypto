"""ARP-008 §25 — tests for the experiment-governance primitives.

Covers the six mandated failure modes:

1. contract mismatch            -> ``EXPERIMENT_INVALID``
2. split mutation               -> ``SplitMutationError`` (NEW_EXPERIMENT_ID)
3. OOS reuse                    -> ``HoldoutReuseError``
4. holdout crash state          -> a crash still leaves the holdout CONSUMED
5. terminal experiment mutation -> ``TerminalExperimentMutationError``
6. SPEC vs implementation       -> the divergence the verifier found is caught
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.governance import (  # noqa: E402
    EXPERIMENT_INVALID,
    ExperimentContract,
    ExperimentContractValidator,
    ExperimentInvalidError,
    Holdout,
    HoldoutRegistry,
    HoldoutReuseError,
    HoldoutStatus,
    ImmutableSplitRegistry,
    SplitDefinition,
    SplitMutationError,
    TerminalExperimentMutationError,
    TerminalExperimentRecord,
    TerminalExperimentRegistry,
    TerminalState,
)

SPLIT = SplitDefinition(
    dev_start="2019-01-01",
    dev_end="2024-01-01",
    validation_start="2024-01-01",
    validation_end="2025-07-01",
    oos_start="2025-07-01",
    oos_end="2026-03-01",
)

BASE_VIEWS = {
    "experiment_id": "EXP-ARP-900",
    "strategy_id": "H-TEST-001",
    "timeframe": "1d",
    "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "lookback_days": 30,
    "max_hold_days": 20,
    "entry_rule": "long if close_t > close_{t-lookback}",
    "exit_rule": "signal flip at next open; max_hold forced at next open",
    "dataset_fingerprint": "abc123",
    "cost_round_trip_bps": 23.559016994374947,
    **SPLIT.to_dict(),
    "split_contract": SPLIT.to_dict(),
}


def _contract(overrides: dict[str, dict] | None = None) -> ExperimentContract:
    overrides = overrides or {}

    def view(name: str) -> dict:
        merged = dict(BASE_VIEWS)
        merged.update(overrides.get(name, {}))
        return merged

    return ExperimentContract(
        experiment_id="EXP-ARP-900",
        spec=view("SPEC"),
        manifest=view("MANIFEST"),
        implementation_config=view("IMPLEMENTATION"),
        split_definition=SPLIT.to_dict(),
        cost_model={"cost_round_trip_bps": BASE_VIEWS["cost_round_trip_bps"]},
    )


# 1. contract mismatch -------------------------------------------------------
def test_contract_validator_passes_on_identical_views() -> None:
    result = ExperimentContractValidator().validate(_contract(None))
    assert result.valid is True
    assert result.status == "PASS"
    assert result.mismatches == ()


def test_contract_validator_flags_cost_mismatch_as_experiment_invalid() -> None:
    contract = _contract({"IMPLEMENTATION": {"cost_round_trip_bps": 10.0}})
    result = ExperimentContractValidator().validate(contract)
    assert result.status == EXPERIMENT_INVALID
    assert result.valid is False
    assert any(m.field == "cost_round_trip_bps" for m in result.mismatches)


def test_contract_validator_refuses_dev_execution_on_mismatch() -> None:
    contract = _contract({"MANIFEST": {"max_hold_days": 10}})
    with pytest.raises(ExperimentInvalidError) as exc:
        ExperimentContractValidator().assert_dev_allowed(contract)
    assert exc.value.result.status == EXPERIMENT_INVALID


# 6. SPEC vs implementation (the ARP-008 defect) -----------------------------
def test_spec_vs_implementation_exit_semantics_mismatch_is_caught() -> None:
    """SPEC says next-open exit; the implementation exits at bar close."""
    contract = _contract(
        {
            "SPEC": {"exit_rule": "signal flip OR next-open exit at max_hold"},
            "IMPLEMENTATION": {"exit_rule": "signal flip next open; max_hold forced at bar close"},
        }
    )
    result = ExperimentContractValidator().validate(contract)
    assert result.status == EXPERIMENT_INVALID
    fields = {m.field for m in result.mismatches}
    assert "exit_rule" in fields


def test_split_rebased_away_from_preregistration_is_caught() -> None:
    """The W1-W7 window contract vs the epoch splits actually executed."""
    contract = _contract(
        {
            "SPEC": {"split_contract": {"DEV": ["W1", "W2", "W3", "W4"]}},
            "MANIFEST": {"split_contract": {"DEV": ["W1", "W2", "W3", "W4"]}},
        }
    )
    result = ExperimentContractValidator().validate(contract)
    assert result.status == EXPERIMENT_INVALID
    assert any(m.field == "split_contract" for m in result.mismatches)


# 2. split mutation ----------------------------------------------------------
def test_split_mutation_requires_new_experiment_id() -> None:
    registry = ImmutableSplitRegistry()
    registry.register("EXP-ARP-900", SPLIT)
    mutated = SplitDefinition(
        dev_start="2018-01-01",  # widened after pre-registration
        dev_end="2024-01-01",
        validation_start="2024-01-01",
        validation_end="2025-07-01",
        oos_start="2025-07-01",
        oos_end="2026-03-01",
    )
    with pytest.raises(SplitMutationError):
        registry.register("EXP-ARP-900", mutated)


def test_split_re_registration_is_idempotent() -> None:
    registry = ImmutableSplitRegistry()
    h1 = registry.register("EXP-ARP-900", SPLIT)
    h2 = registry.register("EXP-ARP-900", SPLIT)
    assert h1 == h2 == SPLIT.split_hash()


def test_split_hash_is_deterministic() -> None:
    assert SPLIT.split_hash() == SPLIT.split_hash()
    assert len(SPLIT.split_hash()) == 64


# 3. OOS reuse ---------------------------------------------------------------
def _holdout() -> Holdout:
    return Holdout(
        holdout_id="HOLDOUT-900",
        start="2025-07-01",
        end="2026-03-01",
        assets=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        dataset_hash="deadbeef",
    )


def test_holdout_firewall_refuses_consumed_reuse() -> None:
    registry = HoldoutRegistry()
    registry.register(_holdout())
    registry.assert_untouched("HOLDOUT-900")
    registry.mark_opened("HOLDOUT-900", "EXP-ARP-008")
    registry.mark_consumed("HOLDOUT-900", "EXP-ARP-008")
    assert registry.status("HOLDOUT-900") is HoldoutStatus.CONSUMED
    with pytest.raises(HoldoutReuseError):
        registry.assert_untouched("HOLDOUT-900")


def test_consumed_holdout_never_returns_to_untouched() -> None:
    registry = HoldoutRegistry()
    registry.register(_holdout())
    registry.mark_consumed("HOLDOUT-900", "EXP-ARP-008")
    with pytest.raises(HoldoutReuseError):
        registry.mark_opened("HOLDOUT-900", "EXP-ARP-009")
    assert registry.status("HOLDOUT-900") is HoldoutStatus.CONSUMED


# 4. holdout crash state -----------------------------------------------------
def test_holdout_crash_still_burns_the_holdout() -> None:
    registry = HoldoutRegistry()
    registry.register(_holdout())
    registry.assert_untouched("HOLDOUT-900")
    try:
        registry.mark_opened("HOLDOUT-900", "EXP-ARP-008")
        raise RuntimeError("simulated OOS script crash")
    except RuntimeError:
        pass
    finally:
        registry.mark_consumed("HOLDOUT-900", "EXP-ARP-008")
    assert registry.status("HOLDOUT-900") is HoldoutStatus.CONSUMED
    with pytest.raises(HoldoutReuseError):
        registry.assert_untouched("HOLDOUT-900")


def test_holdout_registry_round_trips_through_dict() -> None:
    registry = HoldoutRegistry()
    registry.register(_holdout())
    registry.mark_opened("HOLDOUT-900", "EXP-ARP-008")
    restored = HoldoutRegistry.from_dict(registry.to_dict())
    assert restored.status("HOLDOUT-900") is HoldoutStatus.OPENED


# 5. terminal experiment mutation -------------------------------------------
def _terminal() -> TerminalExperimentRecord:
    return TerminalExperimentRecord(
        experiment_id="EXP-ARP-008",
        strategy_id="H-DAILY-TSMOM-001",
        terminal_state=TerminalState.OOS_FAIL,
        reason="OOS net expectancy negative (-210.049 bps)",
        execution_sha="5161360",
        manifest_hash="2b5edac8",
        spec_hash="c922391f",
        dataset_hash="abc847bd",
        metrics={"oos_net_bps": -210.049},
        oos_window=("2025-07-01", "2026-03-01"),
    )


def test_terminal_record_marks_terminal() -> None:
    record = _terminal()
    assert record.terminal is True
    assert record.to_dict()["status"] == "OOS_FAIL"
    assert record.to_dict()["terminal"] is True


def test_terminal_experiment_cannot_be_edited() -> None:
    registry = TerminalExperimentRegistry()
    registry.record(_terminal())
    assert registry.is_terminal("EXP-ARP-008") is True
    with pytest.raises(TerminalExperimentMutationError):
        registry.record(replace(_terminal(), reason="retuned and re-run"))


def test_terminal_experiment_cannot_be_resumed() -> None:
    registry = TerminalExperimentRegistry()
    registry.record(_terminal())
    with pytest.raises(TerminalExperimentMutationError):
        registry.assert_not_terminal("EXP-ARP-008")


def test_terminal_experiment_round_trips_and_is_stable() -> None:
    registry = TerminalExperimentRegistry()
    h1 = registry.record(_terminal())
    h2 = registry.record(_terminal())
    assert h1 == h2
    restored = TerminalExperimentRegistry.from_dict(registry.to_dict())
    assert restored.is_terminal("EXP-ARP-008") is True
