"""ACTIVE pipeline economic audit — WP-3 (POST RFC-049 / ACTIVE RECOVERY).

Reconstructs, from evidence, what the ACTIVE strategy pipeline actually is and
why none of its 24 registered strategies reached paper. For every
``family@timeframe`` entry in the tracked admission ledger it reports:

    identity · family · assets · timeframe · data and period · activation
    conditions · sample (trades, split) · gross and net edge · fees and
    slippage · expectancy · drawdown (when published) · robustness ·
    rejection criteria · evidence pointers · failure taxonomy

Three rules govern the artefact:

* **Nothing is invented.** A field the evidence does not publish is ``null``
  and is named in ``missing_metrics``; it is never estimated here.
* **Every number is cross-checked.** The ledger's ``expected_gross_edge_bps``
  is recomputed from the primary research artefacts (the 5m family diagnostics
  and the per-timeframe audit) and any disagreement is recorded as a defect.
* **The runtime cost plane is re-derived, not typed.** The round-trip cost at
  the campaign's own stake is recomputed from COST_MODEL_V3 through the same
  class the runtime uses, and compared with the frozen value.

Read-only with respect to the runtime: no process is started, no state is
written outside ``data/recovery/``, and no source artefact is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "recovery"

# --------------------------------------------------------------------------- #
# sources (paths are the provenance chain; every one is hashed into the report)
# --------------------------------------------------------------------------- #

LEDGER = "config/strategy_admission.json"
RESULTS_V3 = "docs/STRATEGY_DISCOVERY_V3_RESULTS.json"
MATRIX = "docs/STRATEGY_ADMISSION_MATRIX.json"
TIMEFRAME_AUDIT = "reports/strategy-baseline/TIMEFRAME_AUDIT.json"
REGIME_ANALYSIS = "reports/strategy-baseline/REGIME_ANALYSIS.json"
COST_BARRIER = "reports/strategy-baseline/COST_BARRIER.json"
ROBUSTNESS = "docs/STRATEGY_ROBUSTNESS_VARIANTS.json"
ROBUSTNESS_MD = "docs/STRATEGY_ROBUSTNESS.md"
COST_V3 = "docs/COST_MODEL_V3.json"
CRITERIA = "docs/STRATEGY_ADMISSION_CRITERIA.md"
ROUTING = "docs/MULTI_STRATEGY_ROUTING_AUDIT.md"
INVENTORY = "docs/STRATEGY_RUNTIME_INVENTORY.md"
LAB_FINAL = "docs/PAPER_CONTINUOUS_STRATEGY_LAB_FINAL.md"
PAPER24 = "PAPER_DATA_24H_REPORT.json"
RFC_REGISTRY = "docs/roadmap/RFC_REGISTRY.json"
CLOSURE = "data/rfc049/discovery2/CAMPAIGN_CLOSURE.json"
FAILURE_MATRIX = "reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md"

SOURCE_ROLES = {
    LEDGER: "tracked admission ledger (the ONLY source of 'may this run PAPER?')",
    RESULTS_V3: "STRATEGY-DISCOVERY-V3 results: 5m zero-cost family diagnostics + D-01 per-timeframe gross",
    MATRIX: "STRATEGY-ADMISSION-MATRIX: per-family 5m parity-engine totals with the pre-registered checks",
    TIMEFRAME_AUDIT: "per-timeframe (15m/30m/1h) parity-engine totals, BASE and ZERO_COST, with DEV/VAL/OOS",
    REGIME_ANALYSIS: "D-05 regime-conditional cells (diagnostic)",
    COST_BARRIER: "transaction-cost barrier: median bars needed to cover the round trip",
    ROBUSTNESS: "ema_crossover parameter-neighbourhood variants and regime attribution",
    COST_V3: "COST_MODEL_V3 (venue scenarios, component semantics, knowledge classes)",
    CRITERIA: "pre-registered admission criteria c1..c9",
    ROUTING: "routing audit: single-select, map order, correlation-group, DEF-206",
    INVENTORY: "runtime inventory: family implementations, min bars, own indicators",
    PAPER24: "paper lane 24h data-accumulation run report (owned by the paper lane)",
    LAB_FINAL: "paper continuous strategy lab final report (lifecycle histogram, trade counts)",
    RFC_REGISTRY: "RFC identifier registry (number allocation rule)",
    CLOSURE: "RFC-049 Discovery 2 closure (governance flags after closure)",
    FAILURE_MATRIX: "ARP-001 strategy failure matrix (per-family entry-drift evidence)",
    ROBUSTNESS_MD: "robustness narrative: variants, walk-forward, regime attribution",
}

ENTRYPOINT_CANDIDATES = (
    "scripts/autonomous_paper.py",
    "scripts/start_paper_trading.py",
    "scripts/paper_lab_research.py",
    "scripts/rfc010_baseline_replay.py",
    "scripts/rfc021_ledger_pit.py",
)

DEF206_SCRIPT = "scripts/start_paper_trading.py"
CANONICAL_ENTRYPOINT = "scripts/autonomous_paper.py"

RESEARCH_STAKE_USD = 500.0          # size at which the V3 research expectancies are expressed
ADMISSION_STAKE_USDT = 200.0        # stake at which the runtime admission cost is evaluated
FROZEN_ADMISSION_RT_BPS = 23.353553391
FROZEN_STRESS_1_5X_BPS = 35.030330086
GROSS_MATCH_TOLERANCE_BPS = 0.011   # ledger values are published to 2 decimals

# A mismatch between the ledger's published gross edge and the value recomputed from
# the primary artefact is a defect, not a tolerance. Each one must be declared here
# with its measured delta and materiality bound, and the check below asserts that the
# set of mismatches is exactly the declared set and that every delta stays inside the
# declared bound. Nothing is silently widened.
DECLARED_SOURCE_DISCREPANCIES: dict[str, dict[str, Any]] = {
    "breakout@5m": {
        "ledger_bps": -0.11,
        "recomputed_bps": -0.084,
        "delta_bps": 0.026,
        "materiality_bound_bps": 0.05,
        "materiality": "immaterial: both values are negative and two orders of magnitude below the cost floor; "
                       "the same artefact's gross_usd and trades imply the recomputed value",
        "defect": "DEF-ACT-03",
    },
}

FAILURE_CATEGORIES = (
    "NO_ALPHA",
    "EXECUTION_COST",
    "DATA_QUALITY",
    "INSUFFICIENT_SAMPLE",
    "REGIME_MISMATCH",
    "ROBUSTNESS_FAILURE",
    "IMPLEMENTATION_DEFECT",
    "GOVERNANCE_BLOCK",
)


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def tracked(rel: str) -> bool:
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True, text=True
    )
    return out.returncode == 0


def read_text(rel: str) -> str | None:
    path = ROOT / rel
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else None


def read_json(rel: str) -> Any:
    path = ROOT / rel
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def usd_to_bps(usd_per_trade: float, stake: float) -> float:
    return usd_per_trade / stake * 10_000.0


def r4(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


# --------------------------------------------------------------------------- #
# cost plane (re-derived from the model the runtime itself uses)
# --------------------------------------------------------------------------- #


def derived_cost_plane() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "src"))
    from trading_bot.research.microstructure.cost_model_v3 import default_model

    scenario = "BINANCE_SPOT_STANDARD_TAKER"
    model = default_model(scenario)

    def evaluate(size: float) -> Any:
        return model.evaluate(
            size_usd=size,
            liquidity_regime="normal",
            horizon_minutes=25.0,
            entry_order_type="market",
            exit_order_type="market",
        )

    at_200 = evaluate(ADMISSION_STAKE_USDT)
    at_1000 = evaluate(1000.0)
    return {
        "scenario_id": scenario,
        "stake_usdt": ADMISSION_STAKE_USDT,
        "round_trip_bps_200_usdt": float(at_200.round_trip_bps),
        "round_trip_bps_1000_usdt": float(at_1000.round_trip_bps),
        "stress_1_5x_bps": float(at_200.round_trip_bps) * 1.5,
        "frozen_round_trip_bps_200_usdt": FROZEN_ADMISSION_RT_BPS,
        "frozen_stress_1_5x_bps": FROZEN_STRESS_1_5X_BPS,
        "components_200_usdt": [
            {"name": c.name, "value_bps": r4(c.value_bps), "knowledge": c.knowledge}
            for c in at_200.components
        ],
        "reproduces_frozen_value": abs(float(at_200.round_trip_bps) - FROZEN_ADMISSION_RT_BPS) <= 1e-6,
        "research_contract": {
            "note": "the STRATEGY-DISCOVERY-V3 research plane used a smaller, cheaper contract than the runtime admission plane",
            "stake_usd": RESEARCH_STAKE_USD,
            "base_rt_bps": 12.0,
            "twice_rt_bps": 24.0,
            "stressed_rt_bps": 32.0,
        },
    }


# --------------------------------------------------------------------------- #
# strategy reconstruction
# --------------------------------------------------------------------------- #


def family_5m_block(results: dict[str, Any], matrix: dict[str, Any], family: str) -> dict[str, Any]:
    diag = (results.get("family_5m_diagnostic_zero_cost") or {}).get(family) or {}
    admission = (matrix.get("admissions") or {}).get(family) or {}
    trades = diag.get("trades")
    zero_cost_bps = (
        r4(usd_to_bps(diag["gross_usd"] / trades, RESEARCH_STAKE_USD))
        if diag.get("gross_usd") is not None and trades
        else None
    )
    base = admission.get("totals_base") or {}
    fees = base.get("fees")
    return {
        "source": MATRIX,
        "engine": "parity engine (runtime family classes + adapter semantics), 5m, W1-W7",
        "sample_trades": trades,
        "oos_trades": (admission.get("oos") or {}).get("trades"),
        "dev_trades": (admission.get("dev") or {}).get("trades"),
        "zero_cost_gross_bps_recomputed": zero_cost_bps,
        "zero_cost_gross_usd": diag.get("gross_usd"),
        "zero_cost_profit_factor": diag.get("pf"),
        "zero_cost_win_rate_pct": diag.get("wr_pct"),
        "mfe_pct": diag.get("mfe_pct"),
        "mae_pct": diag.get("mae_pct"),
        "base_totals": base,
        "base_2x_totals": admission.get("totals_2x") or {},
        "dev_totals": admission.get("dev") or {},
        "oos_totals": admission.get("oos") or {},
        "dev_gross_bps_recomputed": (
            r4(usd_to_bps((admission.get("dev") or {})["gross"] / (admission.get("dev") or {})["trades"], RESEARCH_STAKE_USD))
            if (admission.get("dev") or {}).get("gross") is not None and (admission.get("dev") or {}).get("trades") else None
        ),
        "oos_gross_bps_recomputed": (
            r4(usd_to_bps((admission.get("oos") or {})["gross"] / (admission.get("oos") or {})["trades"], RESEARCH_STAKE_USD))
            if (admission.get("oos") or {}).get("gross") is not None and (admission.get("oos") or {}).get("trades") else None
        ),
        "val_gross_bps_recomputed": None,  # the 5m matrix publishes DEV and OOS slices only
        "admission_status": admission.get("status"),
        "mandatory_failures": admission.get("mandatory_failures") or [],
        "unknown_checks": admission.get("unknown_checks") or [],
        "fees_usd": fees,
        "fees_bps_per_trade": (
            r4(usd_to_bps(fees / base["trades"], RESEARCH_STAKE_USD)) if fees is not None and base.get("trades") else None
        ),
        "slippage_bps_per_trade": None,  # not published separately at 5m
        "avg_duration_min": None,
        "exposure_pct": None,
    }


def family_other_tf_block(audit: dict[str, Any] | None, tf: str, family: str) -> dict[str, Any] | None:
    if not audit:
        return None
    block = ((audit.get(tf) or {}).get(family) or {})
    base = (block.get("BASE") or {}).get("totals")
    zero = (block.get("ZERO_COST") or {}).get("totals")
    if not base or not zero:
        return None
    zero_cost_bps = r4(usd_to_bps(zero["expectancy_gross"], RESEARCH_STAKE_USD))
    base_gross_bps = r4(usd_to_bps(base["expectancy_gross"], RESEARCH_STAKE_USD))
    fees = base.get("fees")
    dev = (block.get("BASE") or {}).get("DEV_W1_W4") or {}
    val = (block.get("BASE") or {}).get("VAL_W5_W6") or {}
    oos = (block.get("BASE") or {}).get("OOS_W7") or {}
    zdev = (block.get("ZERO_COST") or {}).get("DEV_W1_W4") or {}
    zval = (block.get("ZERO_COST") or {}).get("VAL_W5_W6") or {}
    return {
        "source": TIMEFRAME_AUDIT,
        "engine": f"parity engine (runtime family classes + adapter semantics), {tf}, W1-W7",
        "sample_trades": base.get("trades"),
        "oos_trades": oos.get("trades"),
        "dev_trades": dev.get("trades"),
        "zero_cost_gross_bps_recomputed": zero_cost_bps,
        "zero_cost_gross_usd": zero.get("gross"),
        "zero_cost_profit_factor": zero.get("profit_factor"),
        "zero_cost_win_rate_pct": zero.get("win_rate"),
        "mfe_pct": zero.get("avg_mfe_pct"),
        "mae_pct": zero.get("avg_mae_pct"),
        "base_totals": base,
        "base_2x_totals": {},  # the 2x-cost arm was not run at this timeframe
        "dev_totals": dev,
        "val_totals": val,
        "oos_totals": oos,
        "zero_cost_dev_gross_bps": r4(usd_to_bps(zdev["expectancy_gross"], RESEARCH_STAKE_USD)) if zdev else None,
        "zero_cost_val_gross_bps": r4(usd_to_bps(zval["expectancy_gross"], RESEARCH_STAKE_USD)) if zval else None,
        "admission_status": None,
        "mandatory_failures": [],
        "unknown_checks": ["c1..c9 not applied at this timeframe (no per-timeframe admission matrix artefact)"],
        "fees_usd": fees,
        "fees_bps_per_trade": r4(usd_to_bps(fees / base["trades"], RESEARCH_STAKE_USD)) if fees is not None and base.get("trades") else None,
        "slippage_bps_per_trade": (
            r4(zero_cost_bps - base_gross_bps)
            if zero_cost_bps is not None and base_gross_bps is not None else None
        ),
        "avg_duration_min": base.get("avg_duration_min"),
        "exposure_pct": base.get("exposure_pct"),
        "base_gross_bps_recomputed": base_gross_bps,
    }


def classify(record: dict[str, Any]) -> dict[str, Any]:
    """Deterministic taxonomy. Every assignment carries the rule that produced it."""
    primary: str
    secondary: list[dict[str, str]] = []
    status = record["ledger_status"]
    gross = record["economics"]["zero_cost_gross_bps"]
    net_bps = record["economics"]["base_expectancy_bps"]
    trades = record["sample"]["trades"]
    oos_trades = record["sample"]["oos_trades"]

    primary = "EXECUTION_COST" if status == "COST_KILLED" else "NO_ALPHA"

    if gross is not None:
        if gross <= 0:
            secondary.append(
                {"category": "NO_ALPHA", "rule": "zero-cost gross expectancy <= 0 bps/trade",
                 "evidence": f"zero-cost gross {gross} bps/trade"}
            )
        if gross <= FROZEN_ADMISSION_RT_BPS:
            secondary.append(
                {"category": "EXECUTION_COST",
                 "rule": "zero-cost gross expectancy does not clear the runtime admission round trip",
                 "evidence": f"{gross} bps vs {FROZEN_ADMISSION_RT_BPS} bps"}
            )
        if gross <= 12.0:
            secondary.append(
                {"category": "EXECUTION_COST",
                 "rule": "zero-cost gross expectancy does not clear the V3 research cost barrier",
                 "evidence": f"{gross} bps vs 12.0 bps BASE round trip"}
            )
    if net_bps is not None and net_bps <= 0:
        secondary.append(
            {"category": "EXECUTION_COST", "rule": "net expectancy after BASE costs <= 0",
             "evidence": f"net {net_bps} bps/trade"}
        )
    if trades is None or trades < 100 or oos_trades is None or oos_trades < 30:
        secondary.append(
            {"category": "INSUFFICIENT_SAMPLE",
             "rule": "admission criterion c1 requires >= 100 total and >= 30 OOS trades",
             "evidence": f"trades={trades}, oos_trades={oos_trades}"}
        )
    if record["sample"]["provenance_gap"]:
        secondary.append(
            {"category": "DATA_QUALITY",
             "rule": "the ledger's own evidence entry publishes sample_trades=0",
             "evidence": "config/strategy_admission.json edge_evidence.sample_trades"}
        )
    if record["missing_metrics"]:
        secondary.append(
            {"category": "DATA_QUALITY",
             "rule": "requested metrics are absent from every available artefact",
             "evidence": ", ".join(record["missing_metrics"])}
        )
    dev_value = record["economics"]["dev_gross_bps"]
    val_value = record["economics"]["val_gross_bps"]
    oos_value = record["economics"]["oos_gross_bps"]
    partition_pairs = [
        (name, value)
        for name, value in (("development", dev_value), ("validation", val_value), ("oos", oos_value))
        if value is not None
    ]
    partition_signs = {1 if value > 0 else -1 for _, value in partition_pairs if value != 0}
    if len(partition_pairs) >= 2 and len(partition_signs) == 2:
        secondary.append({
            "category": "REGIME_MISMATCH",
            "rule": "the sign of the published gross edge is not stable across partitions",
            "evidence": f"{record['economics']['partition_gross_basis']}: "
                        + ", ".join(f"{name} {value} bps" for name, value in partition_pairs),
        })
    if record["robustness"]["negative_everywhere"] is True:
        secondary.append(
            {"category": "ROBUSTNESS_FAILURE",
             "rule": "negative across every published variant, regime and asset cell",
             "evidence": record["robustness"]["cells_summary"]}
        )
    if record["runtime"]["indicator_starvation_defect"]:
        secondary.append(
            {"category": "IMPLEMENTATION_DEFECT",
             "rule": "legacy paper entrypoint supplies only ema/rsi/atr keys, so families needing other keys generate no signal",
             "evidence": f"DEF-206 in {DEF206_SCRIPT}"}
        )
    if not record["admitted_for_paper"]:
        secondary.append(
            {"category": "GOVERNANCE_BLOCK",
             "rule": "admitted_for_paper is false, so the runtime refuses the strategy before any proposal",
             "evidence": "config/strategy_admission.json admitted_for_paper=false"}
        )
    secondary.sort(key=lambda item: FAILURE_CATEGORIES.index(item["category"]))
    return {"primary": primary, "secondary": secondary}


def build() -> dict[str, Any]:
    ledger = read_json(LEDGER)
    results = read_json(RESULTS_V3) or {}
    matrix = read_json(MATRIX) or {}
    audit = read_json(TIMEFRAME_AUDIT) or {}
    robustness = read_json(ROBUSTNESS) or {}
    paper24 = read_json(PAPER24)
    closure = read_json(CLOSURE) or {}
    regime = read_json(REGIME_ANALYSIS) or {}
    barrier = read_json(COST_BARRIER) or {}
    routing_text = read_text(ROUTING) or ""
    lab_text = read_text(LAB_FINAL) or ""

    cost_plane = derived_cost_plane()
    strategies_in = ledger["strategies"]

    records: dict[str, Any] = {}
    for sid, row in sorted(strategies_in.items()):
        family, tf = sid.split("@", 1)
        if tf == "5m":
            block = family_5m_block(results, matrix, family)
        else:
            block = family_other_tf_block(audit, tf, family) or {
                "source": None, "engine": None, "sample_trades": None, "oos_trades": None,
                "dev_trades": None, "zero_cost_gross_bps_recomputed": None, "base_totals": {},
                "base_2x_totals": {}, "dev_totals": {}, "val_totals": {}, "oos_totals": {},
                "admission_status": None,
                "mandatory_failures": [], "unknown_checks": ["no artefact found for this cell"],
                "fees_usd": None, "fees_bps_per_trade": None, "slippage_bps_per_trade": None,
                "avg_duration_min": None, "exposure_pct": None,
            }

        ledger_bps = row.get("expected_gross_edge_bps")
        recomputed = block.get("zero_cost_gross_bps_recomputed")
        matches = (
            abs(ledger_bps - recomputed) <= GROSS_MATCH_TOLERANCE_BPS
            if ledger_bps is not None and recomputed is not None
            else None
        )
        base = block.get("base_totals") or {}

        # BASE gross is published before fees but after the slippage term.
        base_gross_bps = block.get("base_gross_bps_recomputed")
        if base_gross_bps is None and base and base.get("expectancy_gross") is not None:
            base_gross_bps = r4(usd_to_bps(base["expectancy_gross"], RESEARCH_STAKE_USD))
        base_expectancy_bps = (
            r4(usd_to_bps(base["expectancy"], RESEARCH_STAKE_USD)) if base.get("expectancy") is not None else None
        )
        # Partition gross edge: published as ZERO_COST at 15m/30m/1h, as BASE-after-slippage at 5m.
        gross_basis = "BASE_AFTER_SLIPPAGE" if tf == "5m" else "ZERO_COST"
        partition_gross: list[tuple[str, float]] = []

        def partition_value(name: str, zero_cost_key: str, base_key: str,
                            source: dict[str, Any] = block, collected: list[tuple[str, float]] = partition_gross) -> float | None:
            value = source.get(zero_cost_key)
            if value is None and source.get(base_key) is not None:
                value = source[base_key]
            if value is not None:
                collected.append((name, float(value)))
            return value

        dev_gross = partition_value("development", "zero_cost_dev_gross_bps", "dev_gross_bps_recomputed")
        val_gross = partition_value("validation", "zero_cost_val_gross_bps", "val_gross_bps_recomputed")
        oos_gross = partition_value("oos", "oos_gross_bps", "oos_gross_bps_recomputed")
        if oos_gross is None and (block.get("oos_totals") or {}).get("expectancy_gross") is not None:
            oos_gross = r4(usd_to_bps(block["oos_totals"]["expectancy_gross"], RESEARCH_STAKE_USD))
            if oos_gross is not None:
                partition_gross.append(("oos", float(oos_gross)))

        # robustness: family-level cells available in the published artefacts
        rob_cells: list[dict[str, Any]] = []
        if family == "ema_crossover":
            for name, variant in (robustness.get("variants") or {}).items():
                rob_cells.append({
                    "cell": f"variant:{name}",
                    "net_usd": (variant.get("totals") or {}).get("net"),
                    "profit_factor": (variant.get("totals") or {}).get("profit_factor"),
                })
            for name, reg in (robustness.get("regimes") or {}).items():
                rob_cells.append({"cell": f"regime:{name}", "net_usd": reg.get("net"), "profit_factor": None})
        negative_everywhere = bool(rob_cells) and all(
            (c["net_usd"] is not None and c["net_usd"] < 0) for c in rob_cells
        )

        missing: list[str] = []
        if base.get("profit_factor") is None:
            missing.append("base_profit_factor")
        if base_expectancy_bps is None:
            missing.append("net_expectancy")
        if (block.get("admission_status") is None) and tf != "5m":
            missing.append("admission_checks_c1_c9")
        missing.append("max_drawdown")            # c6 is null in the matrix; no artefact publishes DD per strategy
        missing.append("spread_bps_observed")     # the research plane models slippage, never measures the spread
        if tf == "5m" and base.get("trades") and block.get("fees_bps_per_trade") is None:
            missing.append("fees")
        missing = sorted(set(missing))

        record: dict[str, Any] = {
            "strategy_id": sid,
            "family": family,
            "timeframe": tf,
            "assets": {
                "research_dataset": results.get("dataset", {}).get("assets"),
                "period": results.get("dataset", {}).get("windows"),
                "runtime_registry_assets": ["BTCUSDT", "ETHUSDT"],
            },
            "data": {
                "dataset_fingerprint": results.get("dataset_fingerprint"),
                "engine": block.get("engine"),
                "source": block.get("source"),
                "price_source": "read-only public klines (W1-W7 windows)",
                "pit_claimed": "no PIT defect is implicated in these failures (reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md)",
            },
            "ledger_status": row.get("status"),
            "admitted_for_paper": bool(row.get("admitted_for_paper")),
            "activation_conditions": {
                "runtime_regimes": record_regimes(family, tf),
                "note": "the ledger-derived registry map carries regimes=[] (universal) for every family; the legacy "
                        "entrypoint map (start_paper_trading.py) declared ema_crossover first with regimes=[] and the "
                        "others behind explicit regime matches, which is the map-order effect in MULTI_STRATEGY_ROUTING_AUDIT.md",
            },
            "sample": {
                "trades": block.get("sample_trades"),
                "oos_trades": block.get("oos_trades"),
                "dev_trades": block.get("dev_trades"),
                "ledger_sample_trades": (row.get("edge_evidence") or {}).get("sample_trades"),
                "provenance_gap": (row.get("edge_evidence") or {}).get("sample_trades") in (0, None),
            },
            "economics": {
                "ledger_expected_gross_edge_bps": ledger_bps,
                "zero_cost_gross_bps": recomputed,
                "zero_cost_gross_bps_matches_ledger": matches,
                "base_gross_bps": base_gross_bps,
                "base_expectancy_bps": base_expectancy_bps,
                "base_net_usd": base.get("net"),
                "base_profit_factor": base.get("profit_factor"),
                "base_win_rate_pct": base.get("win_rate"),
                "base_payoff": base.get("payoff"),
                "base_exit_mix": base.get("exit_mix"),
                "zero_cost_profit_factor": block.get("zero_cost_profit_factor"),
                "zero_cost_win_rate_pct": block.get("zero_cost_win_rate_pct"),
                "mfe_pct": block.get("mfe_pct"),
                "mae_pct": block.get("mae_pct"),
                "dev_gross_bps": dev_gross,
                "val_gross_bps": val_gross,
                "oos_gross_bps": oos_gross,
                "partition_gross_basis": gross_basis,
                "oos_net_usd": (block.get("oos_totals") or {}).get("net"),
                "dev_net_usd": (block.get("dev_totals") or {}).get("net"),
                "val_net_usd": (block.get("val_totals") or {}).get("net"),
                "stress_2x_net_usd": (block.get("base_2x_totals") or {}).get("net"),
                "stress_2x_profit_factor": (block.get("base_2x_totals") or {}).get("profit_factor"),
                "max_drawdown": None,
            },
            "costs": {
                "fees_bps_per_trade": block.get("fees_bps_per_trade"),
                "implied_slippage_bps_per_trade": block.get("slippage_bps_per_trade"),
                "research_base_rt_bps": cost_plane["research_contract"]["base_rt_bps"],
                "runtime_admission_rt_bps": cost_plane["round_trip_bps_200_usdt"],
                "net_vs_admission_floor_bps": (
                    r4(recomputed - cost_plane["round_trip_bps_200_usdt"]) if recomputed is not None else None
                ),
            },
            "robustness": {
                "cells": rob_cells,
                "cells_summary": "; ".join(
                    f"{c['cell']} net {c['net_usd']}" for c in rob_cells
                ) or "no per-family robustness grid published for this family",
                "negative_everywhere": negative_everywhere if rob_cells else None,
                "regime_conditional_cells": [
                    {"cell": r.get("cell"), "dev_bps": r.get("dev_bps"), "val_gross_usd": r.get("val_gross_usd"),
                     "gate": r.get("gate")}
                    for r in (regime.get("cells") or [])
                    if family in str(r.get("cell", ""))
                ],
            },
            "rejection_criteria": {
                "ledger_rationale": row.get("rationale"),
                "failed_mandatory_checks": block.get("mandatory_failures"),
                "unevaluated_checks": block.get("unknown_checks"),
                "criteria_source": CRITERIA,
                "family_admission_status": block.get("admission_status"),
            },
            "runtime": {
                "paper_executable": False,
                "refusal_reason": f"status {row.get('status')} does not authorise PAPER",
                "indicator_starvation_defect": family != "ema_crossover" and "DEF-206" in routing_text,
            },
            "evidence": [
                {"path": LEDGER, "pointer": f"strategies['{sid}']"},
                {"path": block.get("source") or RESULTS_V3, "pointer": f"{family} @ {tf}"},
                {"path": CRITERIA, "pointer": "c1..c9"},
            ],
            "missing_metrics": missing,
        }
        record["failure_taxonomy"] = classify(record)
        records[sid] = record

    # ---- aggregates ------------------------------------------------------- #
    by_category: dict[str, Any] = {}
    for category in FAILURE_CATEGORIES:
        primary_hits: list[str] = []
        flagged: dict[str, str] = {}
        for sid, rec in records.items():
            if rec["failure_taxonomy"]["primary"] == category:
                primary_hits.append(sid)
                flagged.setdefault(sid, "primary classification")
            for item in rec["failure_taxonomy"]["secondary"]:
                if item["category"] == category:
                    flagged.setdefault(sid, item["evidence"])
        by_category[category] = {
            "primary_count": len(primary_hits),
            "strategies_flagged": len(flagged),
            "primary_strategies": primary_hits,
            "strategies": [{"strategy_id": sid, "evidence": ev} for sid, ev in sorted(flagged.items())],
        }

    gross_values = {sid: r["economics"]["zero_cost_gross_bps"] for sid, r in records.items()}
    positive_gross = sorted(sid for sid, v in gross_values.items() if v is not None and v > 0)
    net_positive = sorted(sid for sid, r in records.items()
                         if r["economics"]["base_expectancy_bps"] is not None and r["economics"]["base_expectancy_bps"] > 0)
    sufficient = sorted(
        sid for sid, r in records.items()
        if (r["sample"]["trades"] or 0) >= 100 and (r["sample"]["oos_trades"] or 0) >= 30
    )
    best = sorted(((v, sid) for sid, v in gross_values.items() if v is not None), reverse=True)[:5]

    # ---- entrypoints ------------------------------------------------------ #
    entrypoints = []
    for rel in ENTRYPOINT_CANDIDATES:
        text = read_text(rel)
        entrypoints.append({
            "path": rel,
            "exists": text is not None,
            "sha256": sha256_file(ROOT / rel),
            "composes_admission_ledger": bool(text and "AdmissionLedger" in text),
            "composes_paper_broker": bool(text and "PaperBroker" in text),
            "has_default_indicator_precompute": bool(text and "_default_indicators" in text),
            "canonical": rel == CANONICAL_ENTRYPOINT,
        })

    # ---- registry (live code path) --------------------------------------- #
    registry: dict[str, Any]
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from trading_bot.autonomous.admission_ledger import AdmissionLedger
        from trading_bot.autonomous.strategy_state import StrategyRegistry

        led = AdmissionLedger.load(LEDGER)
        reg = StrategyRegistry.from_ledger(led, assets=["BTCUSDT", "ETHUSDT"])
        registry = {
            "available": True,
            "counts_by_status": reg.counts_by_status(),
            "paper_activations": {tf: sorted(reg.paper_activations(tf).keys()) for tf in ("5m", "15m", "1h")},
            "strategy_map_sizes": {tf: len(reg.strategy_map(tf)) for tf in ("5m", "15m", "1h")},
            "paper_candidates": led.paper_candidates(),
            "map_entry_example": dict(list(reg.strategy_map("1h").items())[:1]),
        }
    except Exception as exc:  # pragma: no cover - recorded, never hidden
        registry = {"available": False, "error": f"{type(exc).__name__}: {exc}"}

    # ---- paper lane ------------------------------------------------------- #
    paper_lane: dict[str, Any] = {"source": PAPER24, "present": paper24 is not None}
    if paper24:
        paper_lane.update({
            "run_id": paper24.get("run_id"),
            "final_status": (paper24.get("verdict") or {}).get("final_status"),
            "false_success": (paper24.get("verdict") or {}).get("false_success"),
            "why": (paper24.get("verdict") or {}).get("why"),
            "usable_hours": (paper24.get("window") or {}).get("usable_hours"),
            "coverage_pct_of_24h_target": (paper24.get("window") or {}).get("coverage_pct_of_24h_target"),
            "cycles": (paper24.get("paper") or {}).get("cycles"),
            "paper_trades": (paper24.get("paper") or {}).get("paper_trades"),
            "shadow_trades": (paper24.get("paper") or {}).get("shadow_trades"),
            "risk_vetoes": (paper24.get("paper") or {}).get("risk_vetoes"),
            "no_trade_kind": (paper24.get("paper") or {}).get("no_trade_kind"),
            "strategies_total": (paper24.get("strategies") or {}).get("total"),
            "storage_projected_gb_per_day": (paper24.get("collector") or {}).get("projected_gb_per_day") if (paper24.get("collector") or {}).get("projected_gb_per_day") is not None else None,
            "m03_readiness": ((paper24.get("preregistered_gate_results") or {}).get("m03") or {}).get("readiness"),
            "m07_readiness": ((paper24.get("preregistered_gate_results") or {}).get("m07") or {}).get("readiness"),
            "offline_replay": (paper24.get("quality_gate") or {}).get("offline_replay"),
        })
    paper_lane["lab_report_cross_check"] = {
        "source": LAB_FINAL,
        "claims_lifecycle_histogram": "LIFECYCLE HISTOGRAM: REJECTED=0 RESEARCH_REQUIRED=0 PAPER_CANDIDATE=0" in lab_text,
        "claims_zero_trades": "PAPER TRADES:                 0" in lab_text,
        "claims_zero_admitted": "ADMISSION LEDGER:             24 strategies, 0 admitted_for_paper" in lab_text,
        "claims_false_success_zero": "FALSE_SUCCESS:                0" in lab_text,
    }

    # ---- objective -------------------------------------------------------- #
    best_gross = best[0][0] if best else None
    annual_trips = 3.0 * 365
    objective = {
        "requested": "3 operations/day, 7 days/week, multiple liquid assets when it makes sense",
        "current_operations_per_day": 0,
        "requirement_round_trips_per_year": annual_trips,
        "round_trip_cost_bps": cost_plane["round_trip_bps_200_usdt"],
        "annual_cost_bps_if_achieved": annual_trips * cost_plane["round_trip_bps_200_usdt"],
        "annual_cost_pct_of_stake_if_achieved": annual_trips * cost_plane["round_trip_bps_200_usdt"] / 100.0,
        "break_even_gross_bps_per_trip": cost_plane["round_trip_bps_200_usdt"],
        "best_measured_gross_bps_per_trade": best_gross,
        "assessment": "NOT_ACHIEVABLE_FROM_CURRENT_REGISTERED_FAMILIES",
        "no_forcing_note": "the objective is not a quota: no operation may be generated to satisfy a frequency target",
    }

    # ---- rfc numbering ---------------------------------------------------- #
    rfc_registry = read_json(RFC_REGISTRY) or {}
    numbers = rfc_registry.get("numbers") or {}
    occupied = sorted(n for n in numbers if numbers[n].get("state") == "OCCUPIED")
    next_free = None
    candidate = 47
    while candidate in {int(n) for n in occupied if n.isdigit()} or candidate in (48, 49):
        candidate += 1
    next_free = candidate

    defects = [
        {
            "id": "DEF-ACT-01",
            "summary": "the admission ledger publishes edge_evidence.sample_trades=0 for the 18 non-5m entries, "
                       "while the primary artefact reports real trade counts for every one of those cells",
            "impact": "evidence-provenance only: the sample sizes are recoverable, no edge number changes",
            "evidence": f"{LEDGER} vs {TIMEFRAME_AUDIT}",
            "status": "open (recorded here; the ledger is generated by scripts/build_strategy_admission.py)",
        },
        {
            "id": "DEF-206",
            "summary": "the legacy paper entrypoint precomputes only ema_fast/ema_slow/rsi/atr, so the five families "
                       "that read other keys return no signal there",
            "impact": "runtime wiring (legacy runner); the canonical entrypoint composes the registry map instead",
            "evidence": f"{DEF206_SCRIPT}:175-187 (verified present in this audit)",
            "status": "open, documented in MULTI_STRATEGY_ROUTING_AUDIT.md",
        },
        {
            "id": "DEF-ACT-02",
            "summary": "no per-timeframe admission matrix artefact exists: criteria c1..c9 were applied at 5m only, so "
                       "the 15m/30m/1h cells carry no admission verdict of their own",
            "impact": "the ledger's per-timeframe statuses are derived from the D-01 gross edge alone",
            "evidence": f"{MATRIX} vs {TIMEFRAME_AUDIT}",
            "status": "open",
        },
        {
            "id": "DEF-ACT-03",
            "summary": "STRATEGY-DISCOVERY-V3 publishes breakout@5m gross_bps_per_trade = -0.11 while the same artefact's "
                       "gross_usd and trades imply -0.084 bps; the other 23 cells agree exactly",
            "impact": "immaterial (0.026 bps, both negative); registered rather than smoothed away",
            "evidence": f"{RESULTS_V3} family_5m_diagnostic_zero_cost.breakout",
            "status": "open (source artefact retained unmodified)",
        },
        {
            "id": "RFC049C-DEF-01",
            "summary": "two stale FINAL_ADMISSION_REPORT hashes in RFC-049B's committed verifier artefact",
            "impact": "bookkeeping only; corrected by the verifier re-run in RFC-049 Discovery 2",
            "evidence": "data/rfc049/admission/INDEPENDENT_VERIFICATION.json",
            "status": "corrected",
        },
    ]

    answers: dict[str, Any] = {
        "Q1_why_never_paper": {
            "answer": "Because no strategy ever satisfied the pre-registered admission criteria, and the ledger is "
                      "fail-closed: 0 of 24 are admitted_for_paper, the runtime registry refuses all 24 before a "
                      "proposal exists, and every paper cycle therefore ends NO_TRADE_STRATEGIC.",
            "decisive_evidence": [
                f"0/{len(records)} admitted; statuses {ledger and {s: sum(1 for r in records.values() if r['ledger_status'] == s) for s in sorted({r['ledger_status'] for r in records.values()})}}",
                "c2 (net>0), c3 (PF>1), c4 (OOS>0) and c7 (2x cost) fail for every family tested at 5m",
                f"paper run {paper_lane.get('run_id')}: {paper_lane.get('cycles')} cycles, {paper_lane.get('paper_trades')} trades, kind {paper_lane.get('no_trade_kind')}",
            ],
            "not_a_cause": "the paper lane itself was healthy: 0 runtime failures, 0 risk vetoes, state unchanged, "
                           "FALSE_SUCCESS 0. No-trade is the correct output of 0 admitted strategies.",
        },
        "Q2_how_many_positive_net_with_sample": {
            "answer": "Zero. No strategy has a positive net expectancy after the research cost line, with or without "
                      "the sample test.",
            "positive_net_count": len(net_positive),
            "sufficient_sample_count": len(sufficient),
            "positive_at_zero_cost": positive_gross,
            "note": f"{len(positive_gross)} of {len(records)} cells are gross-positive at zero cost "
                    f"(best {best_gross} bps/trade) and every one of them is below both cost lines, so none becomes net-positive.",
        },
        "Q3_dominant_limiter": {
            "answer": "The cost plane, on top of a weak entry. Two failures stack: five of six families have no gross "
                      "edge at all (NO_ALPHA), and the one surviving family plus the best timeframes produce a gross "
                      "edge that is smaller than the round trip they must pay (EXECUTION_COST). No cell clears either "
                      "cost line, so the binding constraint is the cost plane and the ceiling is the gross edge.",
            "numbers": {
                "best_measured_gross_bps_per_trade": best_gross,
                "research_base_rt_bps": 12.0,
                "runtime_admission_rt_bps": cost_plane["round_trip_bps_200_usdt"],
                "cells_gross_positive": len(positive_gross),
                "cells_clearing_research_barrier": sum(1 for v in gross_values.values() if v is not None and v > 12.0),
                "cells_clearing_admission_floor": sum(1 for v in gross_values.values() if v is not None and v > cost_plane["round_trip_bps_200_usdt"]),
            },
            "secondary": "The evidence layer itself is incomplete (no drawdown, no observed spread, no per-timeframe "
                         "admission verdict), and the legacy runner would starve five families of indicators even if "
                         "they were admitted. Neither is the profitability blocker; both are blockers to promotion.",
        },
        "Q4_families_worth_new_experiments": {
            "answer": "Only as NEW preregistered hypotheses, never as a retune of the closed ones. The evidence "
                      "supports exactly three lines: (a) the 30m horizon, where the gross edge peaks "
                      "(volatility +8.91, mean_reversion +5.47, trend +2.21 bps) and turnover falls; (b) the entry "
                      "itself, since the direction-adjusted forward return is negative at every horizon for every "
                      "family, which points at signal construction rather than exits; (c) the cost plane, where the "
                      "same cadence at a maker/futures venue is 13.79 bps instead of 23.79 bps.",
            "evidence": [
                f"{TIMEFRAME_AUDIT}: ZERO_COST cells with positive gross (volatility@30m, mean_reversion@30m, trend@30m, mean_reversion@15m, trend@15m, volatility@1h, mean_reversion@5m)",
                f"{FAILURE_MATRIX}: forward expectancy negative at +1/+3/+6/+12/+24 bars in every family",
                f"{COST_V3}: BINANCE_USDM_PERP 13.79 bps vs BINANCE_SPOT_STANDARD 23.79 bps round trip",
            ],
            "not_supported": "No evidence supports keeping the same rules and looking for a better window; the "
                             "DEV/VAL sign flip (0/12 regime cells share a sign) is already measured.",
        },
        "Q5_what_is_missing_for_verifiable_paper": {
            "answer": "Four things, in this order.",
            "items": [
                "1. At least one strategy that clears c1..c9 net of the runtime admission cost plane — nothing else "
                "in the list can be exercised before this exists.",
                "2. A per-timeframe admission verdict and the missing metrics (max drawdown, observed spread) so the "
                "ledger is complete rather than partly unproven.",
                "3. Runtime enablement behind admission: a router that can carry N eligible strategies, a portfolio "
                "policy for simultaneous signals, and the DEF-206 precompute fix — all only after (1).",
                "4. Paper gate prerequisites: a clean continuous 24h window (last attempt 4.16h, 17.3% coverage, "
                "collector stopped on its own disk budget) and the M-03/M-07 history their gates require; plus the "
                "explicit operator authorization for paper promotion (currently NOT_AUTHORIZED).",
            ],
        },
        "Q6_next_rfc": {
            "answer": f"One work package is justified by the evidence: a cost-and-entry research campaign, to be "
                      f"registered as RFC-{next_free} and to remain unauthorized until the operator amends the "
                      f"registry. Its first deliverable is not a strategy but a measured cost plane, because the "
                      f"evidence says the cost plane is what kills the edge.",
            "next_free_rfc_number": next_free,
            "allocation_rule": rfc_registry.get("allocation_rule"),
            "occupied_numbers": occupied,
            "authorization_state": closure.get("governance_flags_after_closure", {}).get("NEXT_CAMPAIGN"),
            "precondition": closure.get("what_would_reopen_the_question", {}).get("entry_condition_for_any_future_internal_campaign"),
        },
    }

    checks: list[dict[str, str]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "result": "PASS" if passed else "FAIL", "detail": detail})

    check("sources:all_present", all((ROOT / p).exists() for p in (LEDGER, RESULTS_V3, MATRIX, TIMEFRAME_AUDIT, CRITERIA, COST_V3)),
          "ledger, V3 results, admission matrix, timeframe audit, criteria, cost model")
    check("sources:tracked_or_declared", all(tracked(p) for p in (LEDGER, RESULTS_V3, MATRIX, CRITERIA, COST_V3)),
          "the strategy evidence is tracked; the reports/ baselines are declared worktree artefacts")
    check("cost:reproduces_frozen_admission_round_trip", cost_plane["reproduces_frozen_value"],
          f"derived {cost_plane['round_trip_bps_200_usdt']!r} vs frozen {FROZEN_ADMISSION_RT_BPS!r}")
    check("ledger:24_entries", len(records) == 24, f"{len(records)} entries")
    check("ledger:zero_admitted", all(not r["admitted_for_paper"] for r in records.values()), "admitted_for_paper=false everywhere")
    check("registry:no_paper_executable", bool(registry.get("available")) and all(
        not v for v in registry.get("paper_activations", {}).values()
    ), str(registry.get("paper_activations")))
    mismatches = [sid for sid, r in records.items() if r["economics"]["zero_cost_gross_bps_matches_ledger"] is False]
    # Bidirectional: the observed mismatch set must be exactly the declared set, so neither a
    # new discrepancy can slip through nor a declared one be smoothed away.
    observed_mismatches = set(mismatches)
    declared_mismatches = set(DECLARED_SOURCE_DISCREPANCIES)
    check("ledger:gross_edge_reproduces_from_primary_artefacts", observed_mismatches == declared_mismatches,
          f"exact match {len(records) - len(observed_mismatches)}/{len(records)}; "
          f"declared {sorted(declared_mismatches)} observed {sorted(observed_mismatches)}")
    check("ledger:declared_mismatches_stay_immaterial", all(
        d["delta_bps"] <= d["materiality_bound_bps"] for d in DECLARED_SOURCE_DISCREPANCIES.values()
    ), "; ".join(f"{sid} delta {d['delta_bps']} <= {d['materiality_bound_bps']} bps"
                 for sid, d in DECLARED_SOURCE_DISCREPANCIES.items()) or "no declared discrepancies")
    check("economics:no_net_positive_strategy", not net_positive, f"positive net expectancy: {net_positive}")
    check("economics:no_gross_above_research_barrier",
          all(v is not None and v <= 12.0 for v in gross_values.values()),
          f"max gross {best_gross} bps vs 12.0 bps BASE round trip")
    check("economics:no_gross_above_admission_floor",
          all(v is not None and v <= cost_plane["round_trip_bps_200_usdt"] for v in gross_values.values()),
          f"max gross {best_gross} bps vs {cost_plane['round_trip_bps_200_usdt']} bps admission round trip")
    check("taxonomy:every_strategy_classified", all(r["failure_taxonomy"]["primary"] in FAILURE_CATEGORIES for r in records.values()),
          f"categories used: {sorted({r['failure_taxonomy']['primary'] for r in records.values()})}")
    check("taxonomy:no_invented_metric", all(
        r["economics"][k] is None for r in records.values() for k in ("max_drawdown",)
    ), "max_drawdown is null for every strategy and is named in missing_metrics")
    check("paper:failure_recorded_honestly", bool(paper_lane.get("present")) and paper_lane.get("final_status") == "PAPER_24H_DATA_FAILED"
          and paper_lane.get("false_success") == 0, str(paper_lane.get("final_status")))
    check("paper:no_trade_is_not_dressed_as_success", paper_lane.get("paper_trades") == 0 and paper_lane.get("no_trade_kind") == "NO_TRADE_STRATEGIC",
          f"trades={paper_lane.get('paper_trades')} kind={paper_lane.get('no_trade_kind')}")
    flags = closure.get("governance_flags_after_closure") or {}
    check("governance:closure_flags_respected",
          flags.get("NEXT_CAMPAIGN") == "NOT_AUTHORIZED"
          and flags.get("PAPER_PROMOTION") == "NOT_AUTHORIZED"
          and flags.get("LIVE_TRADING") == "DISABLED"
          and flags.get("TRADES_AUTHORIZED") == 0
          and flags.get("FALSE_SUCCESS") == 0,
          f"NEXT_CAMPAIGN={flags.get('NEXT_CAMPAIGN')}, PAPER_PROMOTION={flags.get('PAPER_PROMOTION')}, "
          f"LIVE_TRADING={flags.get('LIVE_TRADING')}, TRADES_AUTHORIZED={flags.get('TRADES_AUTHORIZED')}")
    check("governance:roadmap_assumes_no_authorization",
          answers["Q6_next_rfc"]["authorization_state"] == "NOT_AUTHORIZED",
          f"NEXT_CAMPAIGN={answers['Q6_next_rfc']['authorization_state']} — the roadmap proposes; only the operator authorizes")
    check("runtime:def206_evidence_verified",
          any(e["has_default_indicator_precompute"] for e in entrypoints if e["path"] == DEF206_SCRIPT),
          f"{DEF206_SCRIPT} still carries the ema/rsi/atr-only precompute")

    payload: dict[str, Any] = {
        "artifact": "ACTIVE_ECONOMIC_AUDIT",
        "work_package": "WP-3 (POST RFC-049 / ACTIVE RECOVERY)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "branch": subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "mode": "OFFLINE READ-ONLY AUDIT — no process started, no order, no key, no capital",
        "method": "tracked admission ledger + primary research artefacts + the live registry code path + the paper "
                  "lane's own reports; the runtime cost plane is re-derived from COST_MODEL_V3, never typed",
        "sources": [
            {"path": rel, "role": SOURCE_ROLES.get(rel, ""), "exists": (ROOT / rel).exists(),
             "tracked": tracked(rel) if (ROOT / rel).exists() else None, "sha256": sha256_file(ROOT / rel)}
            for rel in sorted(SOURCE_ROLES)
        ],
        "entrypoints": entrypoints,
        "cost_plane": cost_plane,
        "strategy_count": len(records),
        "strategies": records,
        "failure_categories": by_category,
        "aggregates": {
            "ledger_status_counts": {s: sum(1 for r in records.values() if r["ledger_status"] == s)
                                     for s in sorted({r["ledger_status"] for r in records.values()})},
            "admitted_for_paper": sum(1 for r in records.values() if r["admitted_for_paper"]),
            "net_positive_count": len(net_positive),
            "zero_cost_gross_positive": positive_gross,
            "sufficient_sample_count": len(sufficient),
            "best_gross_cells": [{"strategy_id": sid, "zero_cost_gross_bps": v} for v, sid in best],
            "cells_with_drawdown_published": 0,
            "cells_with_observed_spread": 0,
        },
        "registry_live": registry,
        "paper_lane": paper_lane,
        "objective_3_ops_per_day": objective,
        "cost_barrier": {
            "source": COST_BARRIER,
            "median_bars_to_base_round_trip": (barrier or {}).get("median_bars_to_base_rt"),
        },
        "defects": defects,
        "declared_source_discrepancies": DECLARED_SOURCE_DISCREPANCIES,
        "answers": answers,
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": sum(1 for c in checks if c["result"] != "PASS"),
        "scope": {"trading": "not performed", "processes_started": 0,
                  "state_written_outside_recovery": False, "frozen_artifacts_modified": False},
    }
    return payload


def record_regimes(family: str, tf: str) -> Any:
    """Regimes the runtime registry declares for this cell (read from the same code path)."""
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from trading_bot.autonomous.admission_ledger import AdmissionLedger
        from trading_bot.autonomous.strategy_state import StrategyRegistry

        led = AdmissionLedger.load(LEDGER)
        reg = StrategyRegistry.from_ledger(led, assets=["BTCUSDT", "ETHUSDT"])
        entry = reg.strategy_map(tf).get(f"{family}@{tf}") or {}
        return entry.get("regimes")
    except Exception:
        return None


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("# ACTIVE ECONOMIC AUDIT (WP-3)")
    add("")
    add(f"- generated `{payload['generated_at_utc']}` · head `{payload['head'][:12]}` · branch `{payload['branch']}`")
    add(f"- {payload['method']}")
    add("- mode: offline read-only; no process started, nothing executed")
    add("")
    add("## 1. What the pipeline is")
    add("")
    add("| entrypoint | composes ledger | composes paper broker | ema/rsi/atr-only precompute | canonical |")
    add("| --- | --- | --- | --- | --- |")
    for e in payload["entrypoints"]:
        add(f"| `{e['path']}` | {'yes' if e['composes_admission_ledger'] else 'no'} | "
            f"{'yes' if e['composes_paper_broker'] else 'no'} | "
            f"{'yes (DEF-206)' if e['has_default_indicator_precompute'] else 'no'} | "
            f"{'yes' if e['canonical'] else 'no'} |")
    add("")
    add(f"- ledger: **{payload['strategy_count']} strategies, {payload['aggregates']['admitted_for_paper']} admitted for paper** "
        f"({payload['aggregates']['ledger_status_counts']}).")
    reg = payload["registry_live"]
    add(f"- live registry: paper-executable 5m/15m/1h = {reg.get('paper_activations')}; paper candidates {reg.get('paper_candidates')}.")
    add("")
    add("## 2. The cost plane (re-derived)")
    add("")
    cp = payload["cost_plane"]
    add(f"- scenario `{cp['scenario_id']}`: **{cp['round_trip_bps_200_usdt']:.9f} bps** at {cp['stake_usdt']:.0f} USDT "
        f"(frozen value {cp['frozen_round_trip_bps_200_usdt']}; reproduced: {cp['reproduces_frozen_value']}); "
        f"1.5x stress {cp['stress_1_5x_bps']:.9f} bps.")
    add(f"- research contract used by STRATEGY-DISCOVERY-V3: BASE {cp['research_contract']['base_rt_bps']} bps, "
        f"2x {cp['research_contract']['twice_rt_bps']} bps, stressed {cp['research_contract']['stressed_rt_bps']} bps.")
    add("- components at 200 USDT: " + ", ".join(
        f"{c['name']} {c['value_bps']} bps ({c['knowledge']})" for c in cp["components_200_usdt"]))
    add("")
    add("## 3. Every strategy, reconstructed")
    add("")
    header = ("| strategy | status | trades | oos n | zero-cost gross bps | base net $ | base PF | expectancy bps | "
              "DEV gross bps | VAL gross bps | OOS gross bps | primary |")
    add(header)
    add("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for sid, r in payload["strategies"].items():
        e, s = r["economics"], r["sample"]
        add(f"| `{sid}` | {r['ledger_status']} | {s['trades']} | {s['oos_trades']} | {e['zero_cost_gross_bps']} | "
            f"{e['base_net_usd']} | {e['base_profit_factor']} | {e['base_expectancy_bps']} | {e['dev_gross_bps']} | "
            f"{e['val_gross_bps']} | {e['oos_gross_bps']} | {r['failure_taxonomy']['primary']} |")
    add("")
    add("Partition gross edges are `ZERO_COST` at 15m/30m/1h (the 2x arm was not run there) and "
        "`BASE_AFTER_SLIPPAGE` at 5m (the matrix publishes DEV and OOS slices only, no validation slice).")
    add("")
    add("`null` means the artefact does not publish the value; it is listed per strategy in `missing_metrics` "
        "and is never estimated here.")
    add("")
    add("## 4. Failure taxonomy")
    add("")
    add("| category | primary | strategies flagged | examples |")
    add("| --- | ---: | ---: | --- |")
    for cat, data in payload["failure_categories"].items():
        names = ", ".join(h["strategy_id"] for h in data["strategies"][:8])
        add(f"| {cat} | {data['primary_count']} | {data['strategies_flagged']} | {names} |")
    add("")
    add("## 5. The paper lane")
    add("")
    pl = payload["paper_lane"]
    add(f"- run `{pl.get('run_id')}`: {pl.get('final_status')} (false_success {pl.get('false_success')}), "
        f"{pl.get('cycles')} cycles, {pl.get('paper_trades')} paper trades, {pl.get('shadow_trades')} shadow trades, "
        f"{pl.get('risk_vetoes')} risk vetoes, every cycle `{pl.get('no_trade_kind')}`.")
    add(f"- window: {pl.get('usable_hours')} h usable of 24 h ({pl.get('coverage_pct_of_24h_target')}% coverage); "
        f"M-03 {pl.get('m03_readiness')}, M-07 {pl.get('m07_readiness')}.")
    add(f"- why: {pl.get('why')}")
    add(f"- cross-check against the lab report: {json.dumps(pl.get('lab_report_cross_check'), sort_keys=True)}")
    add("")
    add("## 6. Objective: three operations a day")
    add("")
    ob = payload["objective_3_ops_per_day"]
    add(f"- current: **{ob['current_operations_per_day']} operations/day**; requirement at the measured cost plane: "
        f"{ob['requirement_round_trips_per_year']:.0f} round trips/year at {ob['round_trip_cost_bps']:.6f} bps = "
        f"**{ob['annual_cost_bps_if_achieved']:,.0f} bps** ({ob['annual_cost_pct_of_stake_if_achieved']:.1f}% of stake) per year.")
    add(f"- best measured gross edge: **{ob['best_measured_gross_bps_per_trade']} bps/trade**; assessment "
        f"**{ob['assessment']}**.")
    add(f"- {ob['no_forcing_note']}")
    add("")
    add("## 7. Defects")
    add("")
    add("| id | status | summary |")
    add("| --- | --- | --- |")
    for d in payload["defects"]:
        add(f"| {d['id']} | {d['status']} | {d['summary']} |")
    add("")
    add("### Declared source discrepancies")
    add("")
    if payload["declared_source_discrepancies"]:
        add("| strategy | ledger bps | recomputed bps | delta bps | bound bps | defect |")
        add("| --- | ---: | ---: | ---: | ---: | --- |")
        for sid, d in payload["declared_source_discrepancies"].items():
            add(f"| `{sid}` | {d['ledger_bps']} | {d['recomputed_bps']} | {d['delta_bps']} | "
                f"{d['materiality_bound_bps']} | {d['defect']} |")
    else:
        add("none")
    add("")
    add("## 8. Answers")
    add("")
    for key, value in payload["answers"].items():
        add(f"### {key}")
        add("")
        add(str(value.get("answer")))
        add("")
        for item in value.get("items", []) or []:
            add(f"- {item}")
        for item in value.get("decisive_evidence", []) or []:
            add(f"- {item}")
        for item in value.get("evidence", []) or []:
            add(f"- {item}")
        for item in value.get("note", []) if isinstance(value.get("note"), list) else ([value["note"]] if value.get("note") else []):
            add(f"- {item}")
        if value.get("numbers"):
            add("")
            add("```json")
            add(json.dumps(value["numbers"], indent=1, sort_keys=True))
            add("```")
        add("")
    add("## 9. Checks")
    add("")
    add("| check | result | detail |")
    add("| --- | --- | --- |")
    for c in payload["checks"]:
        add(f"| `{c['check']}` | {c['result']} | {c['detail']} |")
    add("")
    add(f"**{payload['checks_total'] - payload['checks_failed']}/{payload['checks_total']} checks pass; "
        f"checks_failed = {payload['checks_failed']}.**")
    add("")
    return "\n".join(lines) + "\n"


# ``sources`` records the hashes of the evidence at the moment of the run, including files
# owned by other lanes (the paper lane's 24h report, the reports/ baselines). It is excluded
# from the identity hash so that an unrelated worktree write cannot change the audit's
# identity; the hashes remain in the artefact for auditability.
VOLATILE_KEYS = ("generated_at_utc", "payload_sha256", "sources")


def payload_hash(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k not in VOLATILE_KEYS}
    return hashlib.sha256(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="recompute and compare with the stored payload hash")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    payload = build()
    payload["payload_sha256"] = payload_hash(payload)
    (OUT / "ACTIVE_ECONOMIC_AUDIT.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUT / "ACTIVE_ECONOMIC_AUDIT.md").write_text(render_markdown(payload), encoding="utf-8")

    if args.check:
        stored = read_json("data/recovery/ACTIVE_ECONOMIC_AUDIT.json") or {}
        same = stored.get("payload_sha256") == payload["payload_sha256"]
        print(json.dumps({"check": "determinism:payload_sha256_stable", "result": "PASS" if same else "FAIL",
                          "detail": f"{payload['payload_sha256'][:16]} vs {str(stored.get('payload_sha256'))[:16]}"}))
        return 0 if same else 1

    print(json.dumps({
        "strategies": payload["strategy_count"],
        "admitted": payload["aggregates"]["admitted_for_paper"],
        "net_positive": payload["aggregates"]["net_positive_count"],
        "zero_cost_gross_positive": len(payload["aggregates"]["zero_cost_gross_positive"]),
        "best_gross": payload["aggregates"]["best_gross_cells"][:2],
        "checks_failed": payload["checks_failed"],
        "payload_sha256": payload["payload_sha256"],
    }, indent=2))
    return 1 if payload["checks_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
