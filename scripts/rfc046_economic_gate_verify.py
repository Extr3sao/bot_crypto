"""Independent verification of the RFC-046 economic feasibility report.

Different program from the builder, and it reaches every number by a different route:

* the toll is recomputed from the **frozen JSON constants** (fees, base slippage/impact, size
  reference, liquidity multiplier) without importing the cost model, then cross-checked against the
  model itself and against the value the frozen model recorded at its own reference size;
* the horizon medians are recomputed from the **1-hour series** (not the 5-minute series the
  builder used) with a shifted window start, and every family verdict is re-derived from the
  verifier's own medians and the stated rule;
* the break-even, turnover and size tables are recomputed arithmetically from the recomputed toll;
* the RFC-046 confirmations are re-derived from ``RUN_REPORT.json`` and ``COST_FORENSICS.json``
  directly, not from the feasibility report's summary of them;
* the standing limits are read from the governance documents themselves;
* the frozen specs are re-hashed and must match the campaign record, so the report cannot have
  been produced by editing a spec.

It refuses forbidden verdicts, requires ``FALSE_SUCCESS = 0`` and fails closed: any mismatch is a
FAIL with the offending field named.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY.json"
REPORT_MD = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY.md"
COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"
VENUE_MATRIX = REPO / "docs" / "VENUE_EXECUTION_MATRIX_V1.json"
RFC046 = REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"
OPERATING_MODEL = REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json"
EXCHANGE_CFG = REPO / "config" / "exchange.yaml"
RUN_JSON = REPO / "data" / "rfc046" / "RUN_REPORT.json"
FORENSICS = REPO / "data" / "rfc046" / "COST_FORENSICS.json"
SPECS = REPO / "docs" / "research" / "discovery_campaign" / "specs"
PRICE_DIR = REPO / "data" / "raw" / "alpha003" / "price"
OUT = REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY_VERIFICATION.json"

ADMISSION = "BINANCE_SPOT_STANDARD_TAKER"
MAKER = "BINANCE_SPOT_STANDARD_MAKER"
BPS = 10_000.0
CAPITAL = 200.0
DOCUMENTED_SIZE = 1000.0
TARGET_NET_ANNUAL = 0.20
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")

#: family -> (source file, bars per window, bars skipped at the start).  A different route from the
#: builder: the 1-hour series for every horizon at or above an hour, shifted windows everywhere.
VERIFIER_HORIZONS: dict[str, tuple[str, int, int]] = {
    "5m": ("5m", 1, 1),
    "15m": ("15m", 1, 1),
    "1h": ("1h", 1, 1),
    "4h": ("1h", 4, 1),
    "8h": ("1h", 8, 1),
    "24h": ("1h", 24, 1),
    "72h": ("1h", 72, 1),
    "168h": ("1h", 168, 1),
}
FAMILY_HORIZONS = {
    "scalping": "5m",
    "intraday": "1h",
    "mean_reversion": "4h",
    "momentum": "24h",
    "swing_trading": "72h",
    "trend_following": "168h",
}
MEDIAN_TOLERANCE = 0.25
SHARE_TOLERANCE = 0.03
#: Published figures are rounded to 9 decimals, so 1e-9 is the exact-arithmetic tolerance for
#: ratios and bps; money is compared at 1e-8 USDT, a ten-millionth of a cent.
EXACT = 1e-9
MONEY = 1e-8
SCOPE_VERDICTS = (
    "VIABLE_COST_PROFILE_IDENTIFIED",
    "NO_VIABLE_PROFILE_IDENTIFIED",
    "INSUFFICIENT_EVIDENCE",
)
COST_VERDICTS = ("NOT_COST_COMPATIBLE", "COST_BOUNDARY", "COST_COMPATIBLE")
FORBIDDEN_TOKENS = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY", "READY_FOR_LIVE")
REQUIRED_FIELDS = (
    "artifact",
    "purpose",
    "generated_at_utc",
    "head_at_run",
    "authorized_runtime",
    "cost_audit",
    "break_even",
    "horizon_measurement",
    "family_classification",
    "rfc046_review",
    "decision",
    "standing_state",
    "false_success",
    "admission_effect",
)


class Checks:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def check(self, name: str, ok: bool, detail: Any = None) -> None:
        if ok:
            self.passed += 1
        else:
            self.failed.append(f"{name}: {detail}")

    def close(self, name: str, value: float | None, expected: float | None, tol: float) -> None:
        ok = (
            value is not None
            and expected is not None
            and abs(float(value) - float(expected)) <= tol
        )
        self.check(name, ok, f"report={value} recomputed={expected} tol={tol}")

    @property
    def total(self) -> int:
        return self.passed + len(self.failed)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def yaml_scalar(text: str, key: str) -> str | None:
    match = re.search(rf"^\s*{key}:\s*\"?([^\"\n#]+?)\"?\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


# --------------------------------------------------------------------------- #
# Route 1 — the toll, recomputed from the frozen constants only
# --------------------------------------------------------------------------- #


def recomputed_costs() -> dict[str, Any]:
    """Fee + spread + slippage + impact, from COST_MODEL_V3.json and nothing else."""
    doc = read_json(COST_MODEL)
    scenario = next(
        s for s in doc["scenarios"] if s["evaluation"]["scenario_id"] == ADMISSION
    )
    spec = scenario["spec"]
    evaluation = scenario["evaluation"]
    constants = doc["model_constants"]
    reference_notional = float(constants["reference_notional_usd"])
    base_slippage = float(constants["base_slippage_bps"])
    base_impact = float(constants["base_impact_bps"])
    liquidity = float(constants["liquidity_multiplier"]["normal"])

    def size_factor(size: float) -> float:
        return 1.0 + math.sqrt(size / reference_notional)

    def taker_total(size: float) -> tuple[float, dict[str, float]]:
        parts = {
            "exchange_fee_entry": float(spec["taker_fee_bps"]),
            "exchange_fee_exit": float(spec["taker_fee_bps"]),
            "spread": float(spec["default_taker_spread_bps"]) * 1.0,
            "slippage": base_slippage * liquidity * size_factor(size) * 2.0,
            "market_impact": base_impact * liquidity * (size_factor(size) - 1.0) * 2.0,
        }
        return sum(parts.values()), parts

    recorded_1000 = float(evaluation["round_trip_bps"])
    total_1000, parts_1000 = taker_total(DOCUMENTED_SIZE)
    total_200, parts_200 = taker_total(CAPITAL)

    maker_scenario = next(s for s in doc["scenarios"] if s["evaluation"]["scenario_id"] == MAKER)
    maker_spec = maker_scenario["spec"]
    maker_p = float(constants["maker_fill_prob"])
    maker_total = (
        2.0 * float(maker_spec["maker_fee_bps"])
        + float(constants["maker_adverse_selection_bps"]) * 2.0
        + float(constants["maker_partial_fill_penalty_bps"]) * (1.0 - maker_p) * 2.0
        + (2.0 * float(maker_spec["maker_fee_bps"])) * (1.0 / maker_p - 1.0)
    )
    return {
        "recorded_1000": recorded_1000,
        "recomputed_1000": total_1000,
        "recomputed_200": total_200,
        "parts_200": parts_200,
        "parts_1000": parts_1000,
        "maker_recomputed": maker_total,
        "maker_recorded": float(maker_scenario["evaluation"]["round_trip_bps"]),
        "stress_multiple": float(read_json(RFC046)["cost_baseline"]["stress_multiple"]),
        "allowed_stress_multiples": [float(m) for m in doc["stress_multiples"]],
        "constants": constants,
    }


def verify_cost_audit(c: Checks, report: dict[str, Any], costs: dict[str, Any]) -> None:
    audit = report["cost_audit"]
    c.check(
        "the report reuses the frozen model by name and hash",
        audit["model"] == read_json(COST_MODEL)["model"]
        and audit["model_file_sha256"] == sha256(COST_MODEL),
        audit["model"],
    )
    c.check(
        "the campaign's stress multiple comes from the governance document and is a frozen option",
        costs["stress_multiple"] in costs["allowed_stress_multiples"],
        (costs["stress_multiple"], costs["allowed_stress_multiples"]),
    )
    c.close(
        "recomputed cost at the documented reference size agrees with the frozen record",
        costs["recomputed_1000"],
        costs["recorded_1000"],
        1e-4,
    )
    c.close(
        "report toll at 1,000 USD equals the independent recomputation",
        audit["at_documented_reference_size"]["round_trip_bps"],
        costs["recomputed_1000"],
        EXACT,
    )
    c.close(
        "report toll at 200 USDT equals the independent recomputation",
        audit["at_reference_capital"]["round_trip_bps"],
        costs["recomputed_200"],
        EXACT,
    )
    # The library must agree with the frozen-constant route: two independent evaluations.
    sys.path.insert(0, str(REPO / "src"))
    from trading_bot.research.microstructure.cost_model_v3 import default_model

    for size, report_value in (
        (DOCUMENTED_SIZE, audit["at_documented_reference_size"]["round_trip_bps"]),
        (CAPITAL, audit["at_reference_capital"]["round_trip_bps"]),
    ):
        library = default_model(ADMISSION).evaluate(
            size_usd=size, liquidity_regime="normal", entry_order_type="market", exit_order_type="market"
        ).round_trip_bps
        c.close(f"the cost model library agrees at {size:.0f} USD", library, report_value, EXACT)

    c.close(
        "report maker cost equals the independent recomputation",
        audit["maker_path"]["at_documented_reference_size"]["round_trip_bps"],
        costs["maker_recomputed"],
        EXACT,
    )
    c.close(
        "the frozen model's own maker record agrees",
        costs["maker_recomputed"],
        costs["maker_recorded"],
        1e-4,
    )
    matrix = read_json(VENUE_MATRIX)
    matrix_maker = next(
        r["maker_rt_cost_bps_theoretical"] for r in matrix["rows"] if r["scenario_id"] == MAKER
    )
    c.close("the venue matrix's maker column agrees with the model", matrix_maker, costs["maker_recomputed"], 1e-4)
    c.close(
        "the maker path is not presented as cheaper than taking",
        audit["maker_path"]["premium_over_taker_bps"],
        costs["maker_recomputed"] - costs["recorded_1000"],
        1e-4,
    )
    c.check(
        "an empty defect list is truthful",
        (audit["open_defects"] == [])
        == (abs(float(matrix_maker) - costs["maker_recomputed"]) <= 1e-9),
        audit["open_defects"],
    )

    dominance = audit["fee_dominance_at_200_usdt"]
    parts = costs["parts_200"]
    fee = parts["exchange_fee_entry"] + parts["exchange_fee_exit"]
    c.check(
        "the fee decomposition sums to the toll",
        abs(sum(parts.values()) - costs["recomputed_200"]) < 1e-9,
        parts,
    )
    c.close("reported fees match the schedule", dominance["exchange_fees_bps"], fee, EXACT)
    c.close(
        "reported fee share is the fee over the toll",
        dominance["fees_share_of_round_trip"],
        fee / costs["recomputed_200"],
        EXACT,
    )
    c.close("reported spread", dominance["spread_bps"], parts["spread"], EXACT)
    c.close("reported slippage", dominance["slippage_bps"], parts["slippage"], EXACT)
    c.close("reported impact", dominance["market_impact_bps"], parts["market_impact"], EXACT)
    c.check(
        "the toll is fee-dominated (fees are the majority of the round trip)",
        fee / costs["recomputed_200"] > 0.5,
        fee / costs["recomputed_200"],
    )
    c.check(
        "every published component carries a knowledge class and a source",
        all(
            component.get("knowledge") and component.get("source_id")
            for component in audit["at_reference_capital"]["components"]
        ),
        audit["at_reference_capital"]["components"],
    )
    c.check(
        "the model contains no fixed cost beyond the instrument minimum",
        "none" in audit["fixed_costs"]["fixed_cash_costs_in_model"].lower()
        and audit["fixed_costs"]["min_notional_usd"] == 5.0
        and abs(
            audit["fixed_costs"]["min_position_fraction_of_capital"] - 5.0 / CAPITAL
        )
        < 1e-9,
        audit["fixed_costs"],
    )
    row = next(r for r in audit["applicability"] if r["assumption"].startswith("min notional"))
    c.check(
        "the minimum notional is recorded as a granularity floor",
        "2.5%" in row["conflict"],
        row["conflict"],
    )


# --------------------------------------------------------------------------- #
# Route 2 — the runtime, re-parsed from the configs
# --------------------------------------------------------------------------- #


def verify_runtime(c: Checks, report: dict[str, Any]) -> None:
    exchange = EXCHANGE_CFG.read_text(encoding="utf-8")
    runtime_cfg = report["authorized_runtime"]
    c.check(
        "venue and account type are the authorized ones",
        yaml_scalar(exchange, "id") == "binance"
        and yaml_scalar(exchange, "account_type") == "spot"
        and runtime_cfg["venue"] == "binance"
        and runtime_cfg["account_type"] == "spot",
        (yaml_scalar(exchange, "id"), runtime_cfg["venue"]),
    )
    c.check(
        "derivatives stay excluded from the runtime",
        "Derivatives" in runtime_cfg["excluded_markets"],
        runtime_cfg["excluded_markets"],
    )
    c.check(
        "the report records the runtime's own default order posture",
        runtime_cfg["default_order_posture"]["post_only_default"] is True
        and runtime_cfg["default_order_posture"]["time_in_force_default"] == "GTC",
        runtime_cfg["default_order_posture"],
    )
    c.check(
        "the default posture is flagged as buying no fee saving",
        any(
            "post_only" in (row.get("conflict") or "")
            and "no fee saving" in (row.get("conflict") or "")
            for row in report["cost_audit"]["applicability"]
        ),
        [row["assumption"] for row in report["cost_audit"]["applicability"]],
    )
    c.check("live trading is disabled in the config", yaml_scalar(EXCHANGE_CFG.read_text(encoding="utf-8"), "sandbox") == "true", None)
    c.check(
        "reference capital is the runtime's 200 USDT",
        runtime_cfg["reference_capital_usdt"] == CAPITAL,
        runtime_cfg["reference_capital_usdt"],
    )
    c.check(
        "the direction is long/cash only",
        "long/cash only" in runtime_cfg["direction"],
        runtime_cfg["direction"],
    )


# --------------------------------------------------------------------------- #
# Route 3 — horizon medians from the 1-hour series, verdicts re-derived
# --------------------------------------------------------------------------- #


def _measure(report: dict[str, Any]) -> dict[str, dict[str, float]]:
    measured: dict[str, dict[str, float]] = {}
    toll = report["break_even"]["minimum_gross_move_bps_per_round_trip"]
    for horizon, (timeframe, bars, offset) in VERIFIER_HORIZONS.items():
        moves: list[float] = []
        for asset in ASSETS:
            opens = [float(r[1]) for r in read_json(PRICE_DIR / f"{asset}_{timeframe}.json")]
            start = offset
            while start + bars < len(opens):
                moves.append(abs(opens[start + bars] / opens[start] - 1.0) * BPS)
                start += bars
        moves.sort()
        measured[horizon] = {
            "median": statistics.median(moves),
            "observations": len(moves),
            "share_below_cost": sum(1 for m in moves if m < toll) / len(moves),
        }
    return measured


def verify_horizons(c: Checks, report: dict[str, Any]) -> None:
    measured = _measure(report)
    published = report["horizon_measurement"]["per_horizon"]
    for horizon, values in measured.items():
        reported = published[horizon]
        relative = abs(values["median"] - reported["median_abs_move_bps"]) / reported["median_abs_move_bps"]
        c.check(
            f"median move at {horizon} reproduces from the 1h/15m/5m series (shifted windows)",
            relative <= MEDIAN_TOLERANCE,
            f"report={reported['median_abs_move_bps']} recomputed={values['median']:.4f} "
            f"relative={relative:.3f}",
        )

    families = report["family_classification"]
    c.check(
        "all six families are classified",
        set(families["families"]) == set(FAMILY_HORIZONS),
        sorted(families["families"]),
    )
    toll = report["break_even"]["minimum_gross_move_bps_per_round_trip"]
    boundary = families["boundary_capture"]
    for family, horizon in FAMILY_HORIZONS.items():
        row = families["families"][family]
        median = measured[horizon]["median"]
        expected = (
            "NOT_COST_COMPATIBLE"
            if median <= toll
            else ("COST_BOUNDARY" if toll / median >= boundary else "COST_COMPATIBLE")
        )
        c.check(
            f"{family}: cost verdict re-derives from the verifier's own median",
            row["cost_verdict"] == expected and row["cost_verdict"] in COST_VERDICTS,
            f"report={row['cost_verdict']} re-derived={expected} median={median:.4f}",
        )
        c.close(
            f"{family}: capture required equals toll over the measured median",
            row["capture_required_to_break_even"],
            toll / median,
            0.05,
        )
        share = row["share_of_windows_below_cost"]
        c.check(
            f"{family}: share of windows below the toll reproduces",
            share is not None
            and abs(share - measured[horizon]["share_below_cost"]) <= SHARE_TOLERANCE,
            f"report={share} recomputed={measured[horizon]['share_below_cost']:.4f}",
        )
        c.check(
            f"{family}: edge existence is not claimed",
            row["edge_existence"] == "NOT_DEMONSTRATED",
            row["edge_existence"],
        )
    c.check(
        "a cost-compatible family is not presented as validated",
        "not thereby validated" in REPORT_MD.read_text(encoding="utf-8"),
        None,
    )
    scalping = families["families"]["scalping"]
    c.check(
        "scalping is recorded as not cost-compatible at its own horizon",
        scalping["cost_verdict"] == "NOT_COST_COMPATIBLE"
        and scalping["capture_required_to_break_even"] > 1.0,
        scalping["cost_verdict"],
    )
    c.check(
        "the horizon table is measured on the raw files, not authored",
        all(v["observations"] > 0 for v in published.values())
        and published["5m"]["observations"] > 100_000,
        {k: v["observations"] for k, v in published.items()},
    )


# --------------------------------------------------------------------------- #
# Route 4 — break-even, turnover and size arithmetic
# --------------------------------------------------------------------------- #


def verify_break_even(c: Checks, report: dict[str, Any], costs: dict[str, Any]) -> None:
    section = report["break_even"]
    toll = costs["recomputed_200"]
    cost_per_op = CAPITAL * toll / BPS
    stress = costs["stress_multiple"]
    c.close("minimum gross move per round trip", section["minimum_gross_move_bps_per_round_trip"], toll, EXACT)
    c.close("minimum gross move in USDT", section["minimum_gross_move_usdt_per_round_trip"], cost_per_op, MONEY)
    c.close(
        "minimum expectancy to be net positive is the toll",
        section["minimum_expectancy_bps_to_be_net_positive"],
        toll,
        EXACT,
    )
    c.close("stressed requirement uses the documented multiple", section["required_gross_edge_bps_at_1p5x_stress"], toll * stress, EXACT)
    stress_field = f"required_gross_edge_bps_at_{str(stress).replace('.', 'p')}x_stress"
    c.check(
        "the published stress field name encodes the multiple actually used",
        stress_field in section and stress == 1.5,
        (stress_field, sorted(section)),
    )
    frozen = section["frozen_campaign_comparison"]
    c.close("the frozen campaign figure is quoted", frozen["frozen_admission_bps"], costs["recorded_1000"], EXACT)
    c.close("the frozen stress threshold is quoted", frozen["frozen_stress_threshold_bps"], costs["recorded_1000"] * stress, EXACT)
    c.close("the delta to the 200 USDT toll is right", frozen["delta_vs_200_usdt_bps"], toll - costs["recorded_1000"], EXACT)
    c.check(
        "the frozen gate is stated to be at least as demanding as the 200 USDT stress",
        frozen["stress_delta_bps"] >= 0.0,
        frozen["stress_delta_bps"],
    )

    maker = section["maker_modality"]
    c.close("maker modality cost", maker["round_trip_bps_at_200_usdt"], costs["maker_recomputed"], EXACT)
    c.check("the maker modality is not admissible", maker["admissible"] is False, maker["admissible"])
    c.check(
        "the maker modality is declared size-invariant",
        maker["size_invariant"] is True,
        maker["size_invariant"],
    )

    three = section["three_daily_round_trips_illustrative"]
    c.close("three round trips cost per day", three["cost_per_day_usdt"], cost_per_op * 3, MONEY)
    c.close("three round trips annual multiple of capital", three["cost_per_year_multiple_of_capital"], cost_per_op * 3 * 365 / CAPITAL, EXACT)

    for row in section["size_sensitivity"]:
        size = float(row["size_usd"])
        expected = _taker_bps_from_constants(costs, size)
        c.close(f"size {size:.0f}: round trip reproduces", row["round_trip_bps"], expected, EXACT)
        c.close(
            f"size {size:.0f}: cost per round trip in USDT",
            row["cost_per_round_trip_usdt"],
            size * expected / BPS,
            MONEY,
        )
        c.close(
            f"size {size:.0f}: fee share",
            row["fees_share_of_round_trip"],
            20.0 / expected,
            EXACT,
        )

    target_usdt = CAPITAL * TARGET_NET_ANNUAL
    c.check(
        "the target is the one documented in the operating model",
        read_json(OPERATING_MODEL)["answers"]["what_can_200_usdt_earn"].startswith(
            "A small absolute amount: at a 20% net annual return it is 40 USDT/year"
        )
        and read_json(OPERATING_MODEL)["reference_capital_usdt"] == CAPITAL,
        None,
    )
    c.close("the target is 20% of the 200 USDT capital", section["turnover_sensitivity"]["target_net_usdt"], target_usdt, MONEY)
    for row in section["turnover_sensitivity"]["rows"]:
        per_day = float(row["round_trips_per_day"])
        per_year = per_day * 365.0
        annual_cost = per_year * cost_per_op
        net_margin = (target_usdt / per_year) / CAPITAL * BPS
        gross = toll + net_margin
        c.close(f"{per_day}/day: annual cost", row["annual_cost_usdt"], annual_cost, MONEY)
        c.close(f"{per_day}/day: cost vs capital", row["annual_cost_pct_of_capital"], annual_cost / CAPITAL, EXACT)
        c.close(f"{per_day}/day: net margin needed", row["net_margin_bps_per_trade"], net_margin, EXACT)
        c.close(f"{per_day}/day: gross needed", row["gross_bps_per_trade_to_net_target"], gross, EXACT)
        c.close(f"{per_day}/day: margin share", row["net_margin_share_of_gross"], net_margin / gross, EXACT)
    high = next(r for r in section["turnover_sensitivity"]["rows"] if r["round_trips_per_day"] == 10.0)
    c.check(
        "high turnover is shown to leave a thin margin over the toll",
        high["net_margin_share_of_gross"] < 0.05,
        high["net_margin_share_of_gross"],
    )
    low = next(r for r in section["turnover_sensitivity"]["rows"] if r["round_trips_per_day"] == 0.2)
    c.check(
        "low turnover leaves a materially larger margin over the toll",
        low["net_margin_share_of_gross"] > high["net_margin_share_of_gross"],
        (low["net_margin_share_of_gross"], high["net_margin_share_of_gross"]),
    )


def _taker_bps_from_constants(costs: dict[str, Any], size: float) -> float:
    constants = costs["constants"]
    reference = float(constants["reference_notional_usd"])
    size_factor = 1.0 + math.sqrt(size / reference)
    return (
        20.0
        + 1.0
        + float(constants["base_slippage_bps"]) * size_factor * 2.0
        + float(constants["base_impact_bps"]) * (size_factor - 1.0) * 2.0
    )


# --------------------------------------------------------------------------- #
# Route 5 — the RFC-046 evidence, re-derived from the recorded artefacts
# --------------------------------------------------------------------------- #


def verify_rfc046_review(c: Checks, report: dict[str, Any]) -> None:
    review = report["rfc046_review"]
    run_report = read_json(RUN_JSON)
    forensics = read_json(FORENSICS)
    c.check(
        "the review quotes the recorded artefacts by hash",
        review["sources"]["run_report_sha256"] == sha256(RUN_JSON)
        and review["sources"]["cost_forensics_sha256"] == sha256(FORENSICS),
        review["sources"],
    )
    c1 = forensics["candidates"]["CAND-046-001"]
    c2 = forensics["candidates"]["CAND-046-002"]
    c3 = forensics["candidates"]["CAND-046-003"]
    claim1 = review["confirmations"]["CAND-046-001_has_no_gross_edge_out_of_sample"]
    c.check(
        "CAND-046-001 has no gross edge out of sample (re-derived from the forensics)",
        c1["oos_gross_expectancy_bps"] < 0.0
        and "final_oos" in c1["partitions_without_gross_edge"]
        and claim1["confirmed"] is True
        and claim1["oos_gross_bps"] == c1["oos_gross_expectancy_bps"],
        (c1["oos_gross_expectancy_bps"], claim1),
    )
    claim2 = review["confirmations"]["CAND-046-002_loses_before_costs"]
    c.check(
        "CAND-046-002 loses before costs (re-derived from the forensics)",
        c2["gross_expectancy_bps"] < 0.0
        and claim2["confirmed"] is True
        and claim2["gross_bps"] == c2["gross_expectancy_bps"],
        (c2["gross_expectancy_bps"], claim2),
    )
    claim3 = review["confirmations"]["CAND-046-003_stays_zero_sample"]
    c.check(
        "CAND-046-003 stays zero sample (re-derived from the forensics)",
        c3["zero_sample"] is True
        and c3["trades_total"] == 0
        and claim3["confirmed"] is True
        and claim3["trades_total"] == c3["trades_total"],
        (c3["zero_sample"], claim3),
    )
    c.check(
        "the three candidates are still the rejected set",
        all(
            forensics["candidates"][cid]["verdict"] in ("COST_DISQUALIFIED", "NO_GROSS_EDGE", "ZERO_SAMPLE")
            for cid in ("CAND-046-001", "CAND-046-002", "CAND-046-003")
        ),
        {cid: forensics["candidates"][cid]["verdict"] for cid in forensics["candidates"]},
    )

    policy = review["oos_policy"]
    recorded_hashes = {r["hypothesis_id"]: r["spec_hash"] for r in run_report["runs"]}
    recomputed_hashes = {
        path.stem: hashlib.sha256(
            json.dumps(read_json(path), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for path in sorted(SPECS.glob("HYP-*.json"))
    }
    c.check(
        "the frozen specs are unchanged since the campaign",
        recomputed_hashes == recorded_hashes and policy["spec_hashes"] == recorded_hashes,
        (recomputed_hashes, recorded_hashes),
    )
    c.check(
        "no fourth spec was added",
        len(recomputed_hashes) == 3 and policy["spec_count"] == 3,
        len(recomputed_hashes),
    )
    c.check(
        "the final OOS is not reused for selection",
        policy["reused_for_selection"] is False
        and policy["new_hypotheses_generated"] == 0
        and policy["candidates_re_evaluated"] == 0,
        policy,
    )
    c.check(
        "no second campaign is opened",
        policy["second_campaign"] == "NOT_AUTHORIZED"
        and report["decision"]["next_campaign"] == "NOT_AUTHORIZED",
        (policy["second_campaign"], report["decision"]["next_campaign"]),
    )


# --------------------------------------------------------------------------- #
# Route 6 — policy and standing limits, read from the governance documents
# --------------------------------------------------------------------------- #


def verify_policy(c: Checks, report: dict[str, Any]) -> None:
    run_report = read_json(RUN_JSON)
    rfc = read_json(RFC046)
    operating = read_json(OPERATING_MODEL)
    state = report["standing_state"]
    exemption = operating["next_action_policy"]["rfc046_limited_exemption"]

    c.check(
        "the campaign is still the failed one",
        run_report["campaign"]["campaign_status"] == "DISCOVERY_CAMPAIGN_FAILED"
        == state["campaign_status"]
        == state["discovery_campaign_failed"],
        state["campaign_status"],
    )
    c.check(
        "no trade is authorized",
        rfc["runtime_state"]["trades_authorized"] == 0 == state["trades_authorized"],
        state["trades_authorized"],
    )
    c.check(
        "profitability is not verified",
        rfc["runtime_state"]["profitability_verified"] is False
        and state["profitability_verified"] is False,
        state["profitability_verified"],
    )
    c.check(
        "live trading stays disabled",
        rfc["runtime_state"]["live_trading_enabled"] is False and state["live_trading"] is False,
        state["live_trading"],
    )
    c.check(
        "the business reentry gate stays closed",
        exemption["gate_state"]["G_BUSINESS_REENTRY"] == "NOT_PASS"
        == state["G_BUSINESS_REENTRY"],
        state["G_BUSINESS_REENTRY"],
    )
    c.check(
        "offline discovery stays the only authorized activity",
        rfc["runtime_state"]["discovery_offline_authorized"] is True
        and state["discovery_offline_authorized"] is True,
        state["discovery_offline_authorized"],
    )
    c.check(
        "the exemption still refuses paper, live and real orders",
        {"paper trading", "live trading", "real orders"} <= set(exemption["not_authorized"]),
        exemption["not_authorized"],
    )
    c.check(
        "the policy that rejects real orders is still in force",
        "real trading" in rfc["forbidden_by_this_rfc"]
        and rfc["invariants_while_active"]["real_orders"] == "REFUSED_BY_POLICY",
        rfc["invariants_while_active"],
    )
    c.check(
        "the risk engine stays deterministic",
        state["risk_engine"] == "DETERMINISTIC",
        state["risk_engine"],
    )
    c.check("false success is zero", state["false_success"] == 0 and report["false_success"] == 0, state["false_success"])
    c.check(
        "the report names the stop rule a cost overrun would trigger",
        any("ST-6" in item for item in report["decision"]["violated_if"]),
        report["decision"]["violated_if"],
    )
    stop_rules = (REPO / "docs" / "governance" / "DISCOVERY_STOP_RULES.md").read_text(encoding="utf-8")
    c.check(
        "ST-6 exists in the stop rules (the cited rule is real)",
        "ST-6" in stop_rules and "realised cost" in stop_rules.lower(),
        None,
    )


def verify_verdicts(c: Checks, report: dict[str, Any]) -> None:
    scope = report["decision"]
    c.check(
        "the scope recommendation is inside the allowed vocabulary",
        scope["scope_recommendation"] in SCOPE_VERDICTS,
        scope["scope_recommendation"],
    )
    c.check(
        "the report declares itself not an edge claim",
        scope["not_an_edge_claim"] is True and scope["edge_status"] == "NOT_DEMONSTRATED",
        (scope["not_an_edge_claim"], scope["edge_status"]),
    )
    c.check(
        "a second campaign is not authorized by the report",
        scope["next_campaign"] == "NOT_AUTHORIZED",
        scope["next_campaign"],
    )
    text = REPORT_MD.read_text(encoding="utf-8")
    payload = json.dumps(report, ensure_ascii=False)
    for token in FORBIDDEN_TOKENS:
        c.check(f"the artefact never claims {token}", token not in payload and token not in text, token)
    for field in REQUIRED_FIELDS:
        c.check(f"required field present: {field}", field in report, field)
    stamp = report["generated_at_utc"]
    c.check(
        "the report carries a computed UTC instant",
        bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp)),
        stamp,
    )
    forensics_stamp = read_json(FORENSICS)["generated_at_utc"]
    c.check(
        "the report is not older than the forensics it follows",
        stamp >= forensics_stamp,
        (stamp, forensics_stamp),
    )
    c.check(
        "the report records the commit it ran at",
        bool(re.fullmatch(r"[0-9a-f]{40}", report["head_at_run"])),
        report["head_at_run"],
    )
    c.check(
        "the builder is not the verifier",
        report["builder_equals_verifier"] is False and report["builder"].endswith("rfc046_economic_gate.py"),
        report["builder"],
    )
    c.check(
        "the report says it admits nothing",
        "NONE" in report["admission_effect"] and "admits nothing" in report["admission_effect"],
        report["admission_effect"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    c = Checks()
    report = read_json(REPORT)
    costs = recomputed_costs()

    verify_cost_audit(c, report, costs)
    verify_runtime(c, report)
    verify_horizons(c, report)
    verify_break_even(c, report, costs)
    verify_rfc046_review(c, report)
    verify_policy(c, report)
    verify_verdicts(c, report)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()
    result = {
        "artifact": "RFC-046_ECONOMIC_FEASIBILITY_VERIFICATION",
        "verifier": "scripts/rfc046_economic_gate_verify.py",
        "builder": "scripts/rfc046_economic_gate.py",
        "builder_equals_verifier": False,
        "verified_artifact": str(REPORT.relative_to(REPO)),
        "verified_artifact_sha256": sha256(REPORT),
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": head,
        "checks_total": c.total,
        "checks_passed": c.passed,
        "mismatches": len(c.failed),
        "failures": c.failed,
        "false_success": 0 if not c.failed else len(c.failed),
        "status": "PASS" if not c.failed else "FAIL",
        "method": "toll recomputed from the frozen JSON constants and cross-checked against the "
        "library; horizon medians recomputed from the 1-hour series with shifted windows; family "
        "verdicts re-derived from those medians; turnover and size tables recomputed; RFC-046 "
        "confirmations re-derived from the recorded artefacts; standing limits read from the "
        "governance documents",
    }
    out = Path(args.out)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{result['status']} {c.passed}/{c.total} checks, {result['mismatches']} mismatches, "
        f"FALSE_SUCCESS = {result['false_success']}"
    )
    for failure in c.failed:
        print(f"  FAIL {failure}")
    print(f"written -> {out.relative_to(REPO)}")
    return 1 if c.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
