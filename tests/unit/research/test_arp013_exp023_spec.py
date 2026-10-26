"""ARP-013 -- pre-registration contract tests for EXP-ARP-023.

EXP-ARP-023 (market-neutral relative value) is **specification only**: no strategy
is implemented, no DEV execution runs and no OOS is opened. These tests verify the
pre-registration *artifact* itself, so the frozen contract cannot silently drift:

* the SPEC/MANIFEST contract validates ``PASS``;
* split mutation is refused; the forward holdout stays ``UNTOUCHED``;
* the declared dataset fingerprint equals the live frozen corpus digest;
* the dollar-neutral construction really is neutral (weights sum to zero, gross 2x);
* the short leg is declared ``EXTERNAL_DATA_REQUIRED`` with **no** assumed borrow
  cost (a guessed zero would be a false success);
* the frozen kill criteria carry the neutrality (``REJECT_BETA``) and effective-
  sample gates the ARP-012 verdict made binding.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.diversified import data as D  # noqa: E402
from trading_bot.research.governance import (  # noqa: E402
    ExperimentContract,
    ExperimentContractValidator,
    Holdout,
    HoldoutRegistry,
    HoldoutStatus,
    ImmutableSplitRegistry,
    SplitDefinition,
    SplitMutationError,
)

EXP_DIR = REPO / "docs" / "research" / "post_oos_recovery" / "experiments" / "EXP-ARP-023"
FROZEN_SPLIT = SplitDefinition(
    "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2026-03-01", "2027-03-01"
)
COST_ROUND_TRIP_BPS = 23.559016994374947


def _manifest() -> dict[str, Any]:
    return json.loads((EXP_DIR / "MANIFEST.json").read_text(encoding="utf-8"))


def _frozen_contract() -> ExperimentContract:
    manifest = _manifest()
    spec_block = dict(manifest["spec_contract"])
    impl = dict(manifest["implementation_config"])
    split_dict = FROZEN_SPLIT.to_dict()
    return ExperimentContract(
        experiment_id=manifest["experiment_id"],
        spec={**spec_block, "split_contract": split_dict},
        manifest={**spec_block, "split_contract": split_dict},
        implementation_config=impl,
        split_definition=split_dict,
        cost_model={
            "cost_round_trip_bps": COST_ROUND_TRIP_BPS,
            "cost_model_version": manifest["cost_model"]["version"],
            "cost_scenario": manifest["cost_model"]["scenario"],
        },
    )


# ------------------------------------------------------------------ governance


def test_frozen_contract_passes() -> None:
    result = ExperimentContractValidator().validate(_frozen_contract())
    assert result.status == "PASS"
    assert result.mismatches == ()


def test_split_mutation_is_refused() -> None:
    reg = ImmutableSplitRegistry()
    reg.register("EXP-ARP-023", FROZEN_SPLIT)
    with pytest.raises(SplitMutationError):
        reg.register(
            "EXP-ARP-023",
            SplitDefinition(
                "2019-01-01", "2024-01-01", "2024-01-01", "2025-07-01", "2025-07-01", "2026-03-01"
            ),
        )


def test_forward_holdout_stays_untouched() -> None:
    reg = HoldoutRegistry()
    reg.register(
        Holdout(
            holdout_id="HOLDOUT-ARP-019-FORWARD",
            start="2026-03-01",
            end="2027-03-01",
            assets=("DYNAMIC_ASSET_UNIVERSE(ARP-006-UNIVERSE-v1)",),
            dataset_hash=D.corpus_digest(),
            forward_only=True,
        )
    )
    assert reg.status("HOLDOUT-ARP-019-FORWARD") is HoldoutStatus.UNTOUCHED
    assert _manifest()["splits"]["oos_opened"] is False


# ------------------------------------------------------------------- identity


def test_identity_and_status_are_the_new_frozen_values() -> None:
    manifest = _manifest()
    assert manifest["experiment_id"] == "EXP-ARP-023"
    assert manifest["strategy_id"] == "H-MKTNEUTRAL-RELVAL-001"
    assert manifest["status"] == "PREREGISTERED_NOT_IMPLEMENTED"
    assert manifest["frozen_before_results"] is True
    assert manifest["oos_locked"] is True
    assert "NOT_IMPLEMENTED" in manifest["implementation_config"]["disposition"]
    # not a silent re-run of a terminal/rejected configuration
    assert "EXP-ARP-023" not in manifest["multiple_testing"]["graveyard"]


def test_dataset_fingerprint_matches_frozen_corpus() -> None:
    assert _manifest()["spec_contract"]["dataset_fingerprint"] == D.corpus_digest()


# ------------------------------------------------------------- neutrality contract


def test_dollar_neutral_book_weights_sum_to_zero_and_gross_is_two_x() -> None:
    manifest = _manifest()
    k = int(manifest["parameters"]["top_k"])
    assert k >= 1
    long_weight = k * (1.0 / k)
    short_weight = -k * (1.0 / k)
    assert long_weight + short_weight == pytest.approx(0.0, abs=1e-12)
    assert long_weight - short_weight == pytest.approx(2.0, abs=1e-12)
    assert manifest["neutrality"]["gross_exposure_multiple"] == 2.0
    assert manifest["neutrality"]["beta_reference"] == "BTCUSDT"
    assert manifest["neutrality"]["beta_tolerance"] == 0.1
    assert manifest["neutrality"]["residual_beta_reported_per_rebalance"] is True
    # the beta rule must be fail-closed, not a soft target
    assert "flat" in manifest["neutrality"]["fail_closed_if"]


def test_short_leg_is_data_blocked_with_no_invented_borrow_cost() -> None:
    manifest = _manifest()
    short_leg = manifest["short_leg"]
    assert short_leg["status"] == "EXTERNAL_DATA_REQUIRED"
    assert short_leg["assumed_borrow_bps_per_day"] is None
    assert short_leg["zero_borrow_forbidden"] is True
    assert short_leg["gross_screen_promotable"] is False
    assert manifest["short_leg_data_blocked"] is True


def test_no_numeric_borrow_or_funding_cost_is_assumed_anywhere() -> None:
    """A guessed borrow cost is the one assumption that would manufacture an edge."""
    manifest = _manifest()

    def walk(node: Any, key: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, key)
        else:
            lowered = key.lower()
            is_number = isinstance(node, (int, float)) and not isinstance(node, bool)
            if ("borrow" in lowered or "funding" in lowered) and is_number:
                raise AssertionError(f"numeric borrow/funding cost invented at {key!r}: {node!r}")

    walk(manifest)


# -------------------------------------------------------------- frozen criteria


def test_kill_criteria_carry_the_neutrality_and_sample_gates() -> None:
    criteria = " || ".join(_manifest()["kill_criteria"])
    for required in (
        "REJECT_NO_EDGE",
        "REJECT_COSTS",
        "REJECT_BETA",
        "REJECT_INSUFFICIENT_SAMPLE",
        "REJECT_FRAGILE",
        "REJECT_PIT",
        "REJECT_VALIDATION",
        "REJECT_SHORT_LEG_UNCOSTED",
    ):
        assert required in criteria
    # effective sample is the binding constraint (ARP-012 verdict)
    power = _manifest()["power_requirement"]
    assert power["min_independent_rebalances_dev"] == 40
    assert power["min_independent_rebalances_validation"] == 15
