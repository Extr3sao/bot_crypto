"""Independent verification of the RFC-046 cost forensics.

These tests do not re-run the forensics script's simulation.  They take the numbers the *recorded*
campaign already published in ``data/rfc046/RUN_REPORT.json`` — aggregate net expectancy and the
per-partition net sums in gate PG-5 — add back the audited round-trip cost, and check that the
forensics artefact says exactly that.  Builder and verifier therefore reach the decomposition from
different inputs: the builder re-simulates the raw bars, the verifier reads the published evidence.

They also pin the properties a later edit is most likely to break: the verdict vocabulary, the fact
that the aggregate positive gross of CAND-046-001 is *not* presented as a harvestable edge, and that
nothing in the artefact admits a candidate, refills a hypothesis or claims profitability.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from trading_bot.research import discovery as D

REPO = Path(__file__).resolve().parents[3]
FORENSICS = REPO / "data" / "rfc046" / "COST_FORENSICS.json"
FORENSICS_MD = REPO / "data" / "rfc046" / "COST_FORENSICS.md"
RUN_REPORT = REPO / "data" / "rfc046" / "RUN_REPORT.json"
COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"
SPECS = REPO / "docs" / "research" / "discovery_campaign" / "specs"

BPS = 10_000.0
VERDICTS = ("ZERO_SAMPLE", "NO_GROSS_EDGE", "COST_DISQUALIFIED", "COST_BOUND")
FORBIDDEN = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY", "READY_FOR_LIVE")
REQUIRED_FIELDS = (
    "artifact",
    "rfc",
    "purpose",
    "generated_at_utc",
    "head_at_run",
    "cost_model",
    "candidates",
    "campaign_status_unchanged",
    "false_success",
    "standing_state",
    "admission_effect",
)


@pytest.fixture(scope="module")
def forensics() -> dict:
    return json.loads(FORENSICS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def recorded() -> dict:
    return json.loads(RUN_REPORT.read_text(encoding="utf-8"))


def _gate(recorded: dict, hypothesis_id: str) -> dict:
    return next(r["gate"] for r in recorded["runs"] if r["hypothesis_id"] == hypothesis_id)


def _observed(gate: dict, gate_id: str) -> object:
    return next(r["observed"] for r in gate["requirements"] if r["id"] == gate_id)


def _classify(gross_bps: float | None, n_total: int, cheapest_documented_bps: float) -> str:
    """The verdict rules, re-implemented from the specification rather than imported."""
    if n_total == 0 or gross_bps is None:
        return "ZERO_SAMPLE"
    if gross_bps <= 0.0:
        return "NO_GROSS_EDGE"
    if gross_bps < cheapest_documented_bps:
        return "COST_DISQUALIFIED"
    return "COST_BOUND"


def test_both_artefacts_exist_and_are_not_empty() -> None:
    for path in (FORENSICS, FORENSICS_MD):
        assert path.is_file(), f"missing {path.name}"
        assert path.stat().st_size > 0, f"empty {path.name}"


def test_required_fields_are_present(forensics: dict) -> None:
    for field in REQUIRED_FIELDS:
        assert field in forensics, f"missing field {field}"
    assert set(forensics["candidates"]) == {"CAND-046-001", "CAND-046-002", "CAND-046-003"}


def test_cost_landscape_is_read_from_the_frozen_model(forensics: dict) -> None:
    doc = json.loads(COST_MODEL.read_text(encoding="utf-8"))
    rows = [
        (
            float(s["evaluation"]["round_trip_bps"]),
            s["evaluation"]["scenario_id"],
            s["spec"]["product"],
        )
        for s in doc["scenarios"]
    ]
    rows.sort()
    cost = forensics["cost_model"]
    assert cost["name"] == doc["model"]
    assert cost["admission_scenario"] == doc["admission_scenario_id"]
    assert cost["admission_round_trip_bps"] == pytest.approx(D.ROUND_TRIP_BPS)
    assert cost["cheapest_documented_bps"] == pytest.approx(rows[0][0])
    assert cost["cheapest_documented_scenario"] == rows[0][1]
    spot = [r for r in rows if r[2] == "Spot"]
    assert cost["cheapest_spot_bps"] == pytest.approx(spot[0][0])
    assert cost["cheapest_spot_scenario"] == spot[0][1]
    assert cost["stressed_round_trip_bps"] == pytest.approx(
        cost["admission_round_trip_bps"] * D.STRESS_MULTIPLE, abs=1e-4
    )


def test_gross_is_net_plus_the_audited_cost_for_every_candidate(forensics: dict) -> None:
    """The whole artefact rests on this one line of arithmetic."""
    cost = forensics["cost_model"]["admission_round_trip_bps"]
    for cid, c in forensics["candidates"].items():
        if c["zero_sample"]:
            assert c["gross_expectancy_bps"] is None
            assert c["net_expectancy_bps"] is None
            continue
        assert c["gross_expectancy_bps"] == pytest.approx(
            c["net_expectancy_bps"] + cost, abs=1e-5
        ), cid
        assert c["break_even_round_trip_bps"] == pytest.approx(
            c["gross_expectancy_bps"], abs=1e-9
        ), cid


def test_decomposition_reproduces_the_recorded_campaign(forensics: dict, recorded: dict) -> None:
    """Independent path: recorded net expectancy + published cost, never the raw bars."""
    cost = forensics["cost_model"]["admission_round_trip_bps"]
    for hyp in ("HYP-001", "HYP-002", "HYP-003"):
        cid = next(r["candidate_id"] for r in recorded["runs"] if r["hypothesis_id"] == hyp)
        c = forensics["candidates"][cid]
        recorded_net = _observed(_gate(recorded, hyp), "PG-1")
        if recorded_net is None:
            assert c["zero_sample"] is True
            assert c["recorded_net_expectancy_bps"] is None
            continue
        assert c["recorded_net_expectancy_bps"] == pytest.approx(
            float(recorded_net) * BPS, abs=1e-4
        ), cid
        assert c["net_expectancy_bps"] == pytest.approx(float(recorded_net) * BPS, abs=1e-5), cid
        assert c["gross_expectancy_bps"] == pytest.approx(
            float(recorded_net) * BPS + cost, abs=1e-5
        ), cid
        assert c["recorded_vs_measured"]["comparable"] is True
        assert c["recorded_vs_measured"]["match"] is True
        assert c["recorded_vs_measured"]["abs_diff_bps"] < 1e-4


def test_partition_decomposition_reproduces_the_recorded_sums(
    forensics: dict, recorded: dict
) -> None:
    """PG-5 publishes a net *sum* and a count per partition; dividing gives the mean the artefact claims."""
    cost = forensics["cost_model"]["admission_round_trip_bps"]
    for hyp in ("HYP-001", "HYP-002", "HYP-003"):
        cid = next(r["candidate_id"] for r in recorded["runs"] if r["hypothesis_id"] == hyp)
        c = forensics["candidates"][cid]
        observed = _observed(_gate(recorded, hyp), "PG-5")
        for name, (count, total) in observed.items():
            detail = c["partition_detail"][name]
            assert detail["n"] == count, f"{cid}/{name} sample size"
            if count == 0:
                assert detail["gross_bps"] is None and detail["net_bps"] is None
                continue
            mean_net = float(total) / count * BPS
            assert detail["net_bps"] == pytest.approx(mean_net, abs=1e-5), f"{cid}/{name} net"
            assert detail["gross_bps"] == pytest.approx(mean_net + cost, abs=1e-5), (
                f"{cid}/{name} gross"
            )


def test_verdicts_follow_the_rules_and_are_not_vacuously_assigned(
    forensics: dict, recorded: dict
) -> None:
    cheapest = forensics["cost_model"]["cheapest_documented_bps"]
    rederived = {}
    for hyp in ("HYP-001", "HYP-002", "HYP-003"):
        cid = next(r["candidate_id"] for r in recorded["runs"] if r["hypothesis_id"] == hyp)
        c = forensics["candidates"][cid]
        recorded_net = _observed(_gate(recorded, hyp), "PG-1")
        gross = (
            None
            if recorded_net is None
            else float(recorded_net) * BPS + forensics["cost_model"]["admission_round_trip_bps"]
        )
        n_total = _observed(_gate(recorded, hyp), "PG-4")["total"]
        expected = _classify(gross, n_total, cheapest)
        assert c["verdict"] == expected, (
            f"{cid}: artefact says {c['verdict']}, rules say {expected}"
        )
        assert c["verdict"] in VERDICTS
        assert c["verdict_reason"].strip()
        rederived[cid] = expected

    assert rederived == {
        "CAND-046-001": "COST_DISQUALIFIED",
        "CAND-046-002": "NO_GROSS_EDGE",
        "CAND-046-003": "ZERO_SAMPLE",
    }


def test_001_positive_gross_is_not_presented_as_a_harvestable_edge(forensics: dict) -> None:
    """The aggregate is positive only because of development; saying less would oversell it."""
    c = forensics["candidates"]["CAND-046-001"]
    assert c["gross_expectancy_bps"] > 0.0, "the premise of the qualifier"
    assert c["gross_positive_in_every_partition"] is False
    assert c["partitions_without_gross_edge"] == ["final_oos", "validation"]
    assert c["oos_gross_expectancy_bps"] < 0.0
    assert c["partition_detail"]["development"]["gross_bps"] > 0.0
    assert "not a stable edge" in c["verdict_reason"]
    assert "No cost-side change documented in this repository rescues it." in c["verdict_reason"]


def test_001_break_even_is_below_every_documented_scenario(forensics: dict) -> None:
    c = forensics["candidates"]["CAND-046-001"]
    documented = [r["round_trip_bps"] for r in forensics["cost_model"]["scenarios"]]
    assert c["break_even_round_trip_bps"] < min(documented)
    assert c["cost_reduction_factor_required"] > 2.0, (
        "the multiple by which execution would have to improve"
    )


def test_zero_sample_is_recorded_as_unmeasured_not_as_a_measured_non_edge(forensics: dict) -> None:
    c = forensics["candidates"]["CAND-046-003"]
    assert c["zero_sample"] is True
    assert c["trades_total"] == 0
    assert c["gross_positive_in_every_partition"] is None, "absence of data is not an edge verdict"
    assert c["partitions_without_gross_edge"] == []
    assert "never fired" in c["verdict_reason"]


def test_spec_hashes_match_the_frozen_files(forensics: dict) -> None:
    frozen = {p.stem: D.spec_hash_from_file(p) for p in sorted(SPECS.glob("HYP-*.json"))}
    assert len(frozen) == 3, "the campaign must not have grown a fourth frozen spec"
    by_hypothesis = {c["hypothesis_id"]: c["spec_hash"] for c in forensics["candidates"].values()}
    assert by_hypothesis == frozen


def test_nothing_was_admitted_refilled_or_promoted(forensics: dict, recorded: dict) -> None:
    assert forensics["campaign_status_unchanged"] == recorded["campaign"]["campaign_status"]
    assert forensics["campaign_status_unchanged"] == "DISCOVERY_CAMPAIGN_FAILED"
    assert "NONE" in forensics["admission_effect"]
    assert "no new hypothesis" in forensics["admission_effect"]

    text = json.dumps(forensics) + FORENSICS_MD.read_text(encoding="utf-8")
    for token in FORBIDDEN:
        assert token not in text, f"the artefact must not claim {token}"

    state = forensics["standing_state"]
    assert state["live_trading"] == "DISABLED"
    assert state["trades_authorized"] == 0
    assert state["G_BUSINESS_REENTRY"] == "NOT_PASS"
    assert state["profitability_verified"] is False
    assert state["discovery_offline_authorized"] is True
    assert forensics["false_success"] == 0


def test_every_execution_timestamp_is_real_and_computed(forensics: dict) -> None:
    """TD-4: a run records when it actually ran, and it is later than the run it explains."""
    stamp = forensics["generated_at_utc"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp), stamp
    recorded = json.loads(RUN_REPORT.read_text(encoding="utf-8"))["generated_at_utc"]
    assert stamp >= recorded, "the forensics cannot predate the run it decomposes"
    head = forensics["head_at_run"]
    assert re.fullmatch(r"[0-9a-f]{40}", head), head
    assert head != recorded, (
        "the forensics ran after the campaign, so its head must be a later commit than the "
        "recorded run's"
    )
