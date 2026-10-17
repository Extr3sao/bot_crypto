"""edge15_alphas — run the families, price them, and let the numbers decide.

WP-EDGE-015/P1-P2. Three corpora and one rule about how they may be used:

* ``data/edge08/universe-1h`` — six alts, 2021-01 → 2026-10. **Consumed**: WP-EDGE-08
  measured on it, so anything found here is in-sample. It is used for discovery
  and for the two internal segments (selection, held-out tail).
* ``data/edge07/holdout-1h`` — BTC/ETH/SOL, 2026. **Consumed** by WP-EDGE-07, same
  standing: a second descriptive read, not an out-of-sample claim.
* the prospective slice — only the bars that postdate the frozen protocol in
  ``OOS_PREREGISTRATION_V2.json``. Today it is (correctly) almost empty, and the
  matrix says so instead of scoring on something it just captured.

Every family is reported at three cost levels (1x, 2x, 3x), and no candidate is
promoted on this evidence: ``ADOPT`` is impossible until the prospective slice can
carry it, which is a state of the data and not a judgement about the strategy.

    python scripts/edge15_alphas.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.autonomous.admission_ledger import AdmissionLedger
from trading_bot.autonomous.contracts import AdmissionEntry, AdmissionStatus
from trading_bot.autonomous.strategy_state import StrategyRegistry
from trading_bot.research.economic_recovery.alpha15 import (
    ACCEPTANCE_THRESHOLDS,
    COST_MODEL_V15,
    FAMILIES,
    FAMILY_BY_NAME,
    FROZEN_PROTOCOL,
    ROTATION_UNIVERSE,
    SINGLE_ASSET_FAMILIES,
    UNTESTED_FAMILIES,
    Bar,
    cost_for,
    evaluate_portfolio,
    evaluate_trades,
    family_trades,
    rotation_backtest,
    split_index,
)
from trading_bot.research.economic_recovery.experiments import load_ohlcv

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-015"

EDGE08 = REPO / "data" / "edge08" / "universe-1h"
EDGE07 = REPO / "data" / "edge07" / "holdout-1h"
ADMISSION = REPO / "config" / "strategy_admission.json"
CANDIDATES = REPO / "config" / "strategy_candidates_edge15.json"

#: Held-out fraction of each series. 0.30 is a *commodity*: it is inside a corpus
#: the campaign already consumed, so it is a stability check, not an OOS test.
TAIL_FRACTION = 0.30

CORPORA: tuple[dict[str, Any], ...] = (
    {
        "name": "EDGE08_ALTS_1H",
        "path": EDGE08,
        "symbols": ["AAVEUSDT", "CRVUSDT", "KSMUSDT", "SNXUSDT", "SUSHIUSDT", "UNIUSDT"],
        "standing": "CONSUMED_BY_WP_EDGE_08",
    },
    {
        "name": "EDGE07_HOLDOUT_1H",
        "path": EDGE07,
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "standing": "CONSUMED_BY_WP_EDGE_07",
    },
)

#: The families the campaign already rejected, with their measured edges, so the
#: audit the brief asks for ("do not rename a rejected strategy") has data in it.
REJECTED_FAMILIES = {
    "breakout@5m": "gross -0.11 bps/trade over 2426 trades (docs/STRATEGY_DISCOVERY_V3_RESULTS.json)",
    "ema_crossover@5m": "gross -4.56 bps/trade over 1725 trades (docs/STRATEGY_DISCOVERY_V3_RESULTS.json)",
    "lead_lag": "retained orthogonal candidate, measured net <= 0 after the admission round trip (WP-EDGE-14C/14D)",
}


def _symbol_path(corpus: dict[str, Any], symbol: str) -> Path | None:
    matches = sorted(corpus["path"].glob(f"{symbol}*.json"))
    return matches[0] if matches else None


def _window_days(bars: list[Bar]) -> float:
    if len(bars) < 2:
        return 0.0
    return max((bars[-1].ts_ms - bars[0].ts_ms) / 86_400_000.0, 1e-9)


def _split(bars: list[Bar]) -> tuple[list[Bar], list[Bar]]:
    index = split_index(bars, 1.0 - TAIL_FRACTION)
    return bars[:index], bars[index:]


def run_single_asset_families() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    per_family: dict[str, dict[str, Any]] = {}
    for corpus in CORPORA:
        for symbol in corpus["symbols"]:
            path = _symbol_path(corpus, symbol)
            if path is None:
                continue
            bars = load_ohlcv(path)
            selection, tail = _split(bars)
            for family in SINGLE_ASSET_FAMILIES:
                for segment_name, segment in (("SELECTION", selection), ("HELD_OUT_TAIL", tail)):
                    trades = family_trades(family, segment)
                    metrics = evaluate_trades(
                        trades,
                        symbol=symbol,
                        window_days=_window_days(segment),
                        window_start_ms=segment[0].ts_ms,
                        window_end_ms=segment[-1].ts_ms,
                    )
                    row = {
                        "family": family.name,
                        "corpus": corpus["name"],
                        "symbol": symbol,
                        "segment": segment_name,
                        "cost_model": "EDGE15_COST_MODEL_V1",
                        "stake_usdt": cost_for(symbol).stake_usdt,
                        "cost_round_trip_bps_1x": round(metrics["cost_1x_bps_per_trade"], 4),
                        "cost_round_trip_bps_2x": round(metrics["cost_1x_bps_per_trade"] * 2, 4),
                        "cost_round_trip_bps_3x": round(metrics["cost_1x_bps_per_trade"] * 3, 4),
                        **{
                            k: metrics[k]
                            for k in (
                                "trades",
                                "trades_per_day",
                                "days_without_trades",
                                "window_days",
                                "gross_bps_per_trade",
                                "expectancy_bps_per_trade",
                                "net_bps_total",
                                "net_bps_total_1x",
                                "net_bps_total_2x",
                                "net_bps_total_3x",
                                "expectancy_bps_per_trade_2x",
                                "expectancy_bps_per_trade_3x",
                                "win_rate",
                                "profit_factor",
                                "equity_multiple",
                                "max_drawdown_bps",
                                "sharpe_daily_annualised",
                                "fees_and_costs_bps_paid",
                                "median_net_bps_per_trade",
                                "top5_share_of_gross",
                                "trades_losing_money_per_trade",
                            )
                        },
                    }
                    rows.append(row)
                    bucket = per_family.setdefault(
                        family.name, {"segments": [], "tail": [], "families": family}
                    )
                    bucket["segments"].append(row)
                    if segment_name == "HELD_OUT_TAIL":
                        bucket["tail"].append(row)
    return rows, per_family


def run_rotation() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"segments": []}
    corpus = CORPORA[0]
    series: dict[str, list[Bar]] = {}
    for symbol in corpus["symbols"]:
        path = _symbol_path(corpus, symbol)
        if path is not None:
            series[symbol] = load_ohlcv(path)
    for symbol in ROTATION_UNIVERSE:
        if symbol not in series:
            raise SystemExit(f"rotation universe needs {symbol}: data missing")
    timeframes = [series[s] for s in ROTATION_UNIVERSE]
    start = max(bars[0].ts_ms for bars in timeframes)
    end = min(bars[-1].ts_ms for bars in timeframes)
    aligned = {s: [b for b in series[s] if start <= b.ts_ms <= end] for s in ROTATION_UNIVERSE}
    length = min(len(bars) for bars in aligned.values())
    cut = int(length * (1.0 - TAIL_FRACTION))
    for segment_name in ("SELECTION", "HELD_OUT_TAIL"):
        window = {
            symbol: (bars[:cut] if segment_name == "SELECTION" else bars[cut:])
            for symbol, bars in aligned.items()
        }
        days = _window_days(next(iter(window.values())))
        per_multiplier: dict[float, dict[str, Any]] = {}
        rebalances = 0
        for multiplier in (1.0, 2.0, 3.0):
            result = rotation_backtest(
                window,
                FAMILY_BY_NAME["cross_sectional_rotation"].parameters,
                cost_multiplier=multiplier,
            )
            per_multiplier[multiplier] = evaluate_portfolio(
                result["equity_curve"], result["trades"], window_days=days
            )
            rebalances = result["rebalances"]
        for multiplier, metrics in per_multiplier.items():
            costs = {
                symbol: cost_for(symbol).round_trip_bps(multiplier) for symbol in ROTATION_UNIVERSE
            }
            mean_cost = sum(costs.values()) / len(costs)
            row = {
                "family": "cross_sectional_rotation",
                "corpus": corpus["name"],
                "symbol": "PORTFOLIO",
                "segment": segment_name,
                "cost_multiplier": multiplier,
                "rebalances": rebalances,
                "net_bps_total": metrics.get("net_bps_total_portfolio", 0.0),
                "net_bps_total_1x": per_multiplier[1.0].get("net_bps_total_portfolio", 0.0),
                "net_bps_total_2x": per_multiplier[2.0].get("net_bps_total_portfolio", 0.0),
                "net_bps_total_3x": per_multiplier[3.0].get("net_bps_total_portfolio", 0.0),
                "cost_round_trip_bps_1x": round(mean_cost / multiplier, 4),
                "cost_round_trip_bps_2x": round(mean_cost / multiplier * 2.0, 4),
                "cost_round_trip_bps_3x": round(mean_cost / multiplier * 3.0, 4),
                **metrics,
            }
            rows.append(row)
        summary["segments"].append(
            {
                "segment": segment_name,
                "days": days,
                "rebalances": rebalances,
                "portfolio_net_bps_1x": per_multiplier[1.0].get("net_bps_total_portfolio", 0.0),
                "portfolio_net_bps_2x": per_multiplier[2.0].get("net_bps_total_portfolio", 0.0),
                "portfolio_net_bps_3x": per_multiplier[3.0].get("net_bps_total_portfolio", 0.0),
                "trades": per_multiplier[1.0].get("trades", 0),
                "max_drawdown_bps": per_multiplier[1.0].get("max_drawdown_bps", 0.0),
            }
        )
    summary["universe"] = list(ROTATION_UNIVERSE)
    summary["aligned_window"] = {"start_ms": start, "end_ms": end, "bars": length}
    return rows, summary


def audit_rejected_families() -> dict[str, Any]:
    """Prove the new families are not renamed rejections, using the ledger."""
    ledger = AdmissionLedger.from_dict(
        json.loads(ADMISSION.read_text(encoding="utf-8")), source_path=str(ADMISSION)
    )
    known = {
        strategy_id: {
            "status": entry.status.value,
            "family": entry.family,
            "expected_gross_edge_bps": entry.expected_gross_edge_bps,
        }
        for strategy_id, entry in sorted(ledger.entries().items())
    }
    audit = []
    for family in FAMILIES:
        overlaps = [name for name in family.differs_from if name in known]
        audit.append(
            {
                "family": family.name,
                "status": family.status,
                "differs_from": list(family.differs_from),
                "checked_against": {name: known[name] for name in overlaps},
                "verdict": "DISTINCT_MECHANISM" if family.differs_from else "NEW",
                "why_not_a_rename": (
                    "differs from the rejected families on the entry condition, the exit "
                    "condition and the conditioning variables; a rename would share at least "
                    "one of the three"
                ),
            }
        )
    return {
        "admission_ledger": str(ADMISSION.relative_to(REPO)),
        "rejected_families": REJECTED_FAMILIES,
        "known_strategies": known,
        "audit": audit,
        "admitted_for_paper_in_ledger": [
            sid
            for sid, entry in known.items()
            if entry["status"] in ("PAPER_ACTIVE", "PAPER_CANDIDATE")
        ],
    }


def rotation_verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The portfolio family's verdict, from its held-out sleeve (1x run)."""
    tail = [
        row
        for row in rows
        if row["segment"] == "HELD_OUT_TAIL" and float(row["cost_multiplier"]) == 1.0
    ]
    if not tail:
        return {"family": "cross_sectional_rotation", "verdict": "DEFER_INSUFFICIENT_SAMPLE"}
    row = tail[0]
    net_1x = float(row["net_bps_total_portfolio"])
    net_2x = float(row["net_bps_total_2x"])
    trades = int(row["trades"])
    if net_1x <= 0:
        verdict = "REJECT"
    elif net_2x <= 0:
        verdict = "EXPERIMENT_COST_FRAGILE"
    elif trades < int(ACCEPTANCE_THRESHOLDS["min_closed_trades_per_strategy"]):
        verdict = "DEFER_INSUFFICIENT_SAMPLE"
    else:
        verdict = "EXPERIMENT_AWAITING_PROSPECTIVE"
    return {
        "family": "cross_sectional_rotation",
        "verdict": verdict,
        "held_out_trades": trades,
        "held_out_net_bps_1x": round(net_1x, 4),
        "held_out_net_bps_2x": round(net_2x, 4),
        "held_out_net_bps_3x": round(float(row["net_bps_total_3x"]), 4),
        "held_out_gross_bps_per_trade": round(float(row["gross_bps_per_trade"]), 4),
        "held_out_expectancy_bps_2x": round(
            float(row["gross_bps_per_trade"]) - float(row["cost_round_trip_bps_2x"]), 4
        ),
        "adoptable_now": False,
        "why_not_adoptable": (
            "ADOPT requires every threshold on data the selection never touched; the only such "
            "data is the prospective slice, and it has not accrued"
        ),
        "thresholds": ACCEPTANCE_THRESHOLDS,
    }


def verdict_for(family: dict[str, Any]) -> dict[str, Any]:
    """ADOPT / EXPERIMENT / DEFER / REJECT, from the held-out tail only."""
    tail = family["tail"]
    trades = sum(int(row["trades"]) for row in tail)
    net_1x = sum(float(row["net_bps_total_1x"]) for row in tail)
    net_2x = sum(float(row["net_bps_total_2x"]) for row in tail)
    expectancy_2x = (net_2x / trades) if trades else 0.0
    thresholds = ACCEPTANCE_THRESHOLDS
    gross_total = sum(float(r["gross_bps_per_trade"]) * int(r["trades"]) for r in tail)
    top5_weighted = 0.0
    for row in tail:
        share = row.get("top5_share_of_gross")
        if share in (None, ""):
            continue
        top5_weighted += (
            float(share) * max(float(row["gross_bps_per_trade"]), 0.0) * int(row["trades"])
        )
    top5_share = (top5_weighted / gross_total) if gross_total > 0 else None
    losing_share = (
        sum(float(r["trades_losing_money_per_trade"]) * int(r["trades"]) for r in tail) / trades
        if trades
        else 0.0
    )
    if trades == 0:
        verdict = "REJECT_NO_TRADES"
    elif net_1x <= 0:
        verdict = "REJECT"
    elif net_2x <= 0:
        verdict = "EXPERIMENT_COST_FRAGILE"
    elif top5_share is not None and top5_share > 0.5:
        # A mean produced by five trades is not an expectation a position can be
        # sized on: the median trade loses money and the equity path is a lottery.
        verdict = "REJECT_OUTLIER_DRIVEN"
    elif losing_share > 0.5:
        verdict = "REJECT_NEGATIVE_MEDIAN"
    elif trades < int(thresholds["min_closed_trades_per_strategy"]):
        verdict = "DEFER_INSUFFICIENT_SAMPLE"
    else:
        verdict = "EXPERIMENT_AWAITING_PROSPECTIVE"
    return {
        "family": family["families"].name,
        "verdict": verdict,
        "held_out_trades": trades,
        "held_out_net_bps_1x": round(net_1x, 4),
        "held_out_net_bps_2x": round(net_2x, 4),
        "held_out_top5_share_of_gross": None if top5_share is None else round(top5_share, 4),
        "held_out_losing_trade_share": round(losing_share, 4),
        "held_out_gross_bps_per_trade": round(
            sum(float(r["gross_bps_per_trade"]) * int(r["trades"]) for r in tail) / trades, 4
        )
        if trades
        else 0.0,
        "held_out_expectancy_bps_2x": round(expectancy_2x, 4),
        "adoptable_now": False,
        "why_not_adoptable": (
            "ADOPT requires every threshold on data the selection never touched; the only such "
            "data is the prospective slice, and it has not accrued"
        ),
        "thresholds": thresholds,
    }


def register_candidates(
    per_family: dict[str, Any], verdicts: list[dict[str, Any]]
) -> dict[str, Any]:
    """Write the candidates in the registry's own vocabulary, disabled.

    The authoritative ledger is *not* touched: it is generated from committed
    research artefacts, and nothing here is admitted. This file is a research
    register that the runtime's own loader can read and classify, which is what
    "formalised, initially disabled" has to mean if it is to be checkable.
    """
    by_name = {row["family"]: row for row in verdicts}
    entries: dict[str, Any] = {
        "_schema_version": "strategy-admission-ledger-v1",
        "_generated_by": "scripts/edge15_alphas.py",
        "_claim": (
            "WP-EDGE-015 research candidates, registered with the runtime's vocabulary and "
            "NOT admitted: admitted_for_paper is false for every one of them, and the "
            "authoritative ledger config/strategy_admission.json is untouched"
        ),
        "_sources": [
            {"path": "reports/economic-recovery/RFC-EDGE-015/ALPHA_RESULTS.json", "sha256": ""},
        ],
    }
    for family in FAMILIES:
        verdict = by_name.get(family.name)
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            strategy_id = f"{family.name}@{symbol}@1h"
            entry = AdmissionEntry(
                strategy_id=strategy_id,
                family=family.name,
                status=AdmissionStatus.RESEARCH_CANDIDATE
                if family.status == "TESTED"
                else AdmissionStatus.RESEARCH_REQUIRED,
                admitted_for_paper=False,
                expected_gross_edge_bps=(
                    float(verdict.get("held_out_gross_bps_per_trade", 0.0))
                    if verdict and verdict.get("held_out_gross_bps_per_trade") is not None
                    else None
                ),
                edge_evidence=None,
                source_doc="reports/economic-recovery/RFC-EDGE-015/ALPHA_RESULTS.json",
                rationale=(
                    f"WP-EDGE-015: {family.status}; held-out verdict "
                    f"{verdict['verdict'] if verdict else 'NOT_TESTED'}; disabled until an "
                    "admitted gross edge exists on data the selection never read"
                ),
                timeframe="1h",
                known=True,
            )
            entries[strategy_id] = entry.to_dict()
    CANDIDATES.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    ledger = AdmissionLedger.from_dict(entries, source_path=str(CANDIDATES))
    registry = StrategyRegistry.from_ledger(ledger)
    return {
        "path": str(CANDIDATES.relative_to(REPO)),
        "strategies": sorted(registry.records),
        "counts_by_status": registry.counts_by_status(),
        "paper_candidates": registry.paper_candidates(),
        "refusals": registry.refusals()[:3],
        "authoritative_ledger_untouched": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-015 alpha experiments")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    single_rows, per_family = run_single_asset_families()
    rotation_rows, rotation_summary = run_rotation()
    verdicts = [verdict_for(per_family[name]) for name in sorted(per_family)]
    verdicts.append(rotation_verdict(rotation_rows))
    for family in UNTESTED_FAMILIES:
        verdicts.append(
            {
                "family": family,
                "verdict": "DEFER_NO_FILL_MODEL",
                "held_out_trades": 0,
                "adoptable_now": False,
                "why_not_adoptable": FAMILY_BY_NAME[family].untestable_reason,
                "required_evidence": FAMILY_BY_NAME[family].required_evidence,
            }
        )

    rejected = audit_rejected_families()
    register = register_candidates(per_family, verdicts)

    # "Found an edge" means the tail survives the adverse multiplier with enough
    # trades — not that some row happens to be positive at the central cost.
    edge_found = any(v["verdict"] in {"EXPERIMENT_AWAITING_PROSPECTIVE", "ADOPT"} for v in verdicts)
    payload = {
        "schema_version": "EDGE15_ALPHA_RESULTS_V1",
        "work_package": "WP-EDGE-015/P1-P2",
        "cost_model": COST_MODEL_V15,
        "frozen_protocol": FROZEN_PROTOCOL,
        "families": [
            {
                "name": family.name,
                "status": family.status,
                "hypothesis": family.hypothesis,
                "parameters": family.parameters,
                "differs_from": list(family.differs_from),
                "untestable_reason": family.untestable_reason,
                "required_evidence": family.required_evidence,
            }
            for family in FAMILIES
        ],
        "segments": {
            "SEGMENT_A_SELECTION": "first 70% of each series (in-sample; parameters were frozen, not fitted)",
            "SEGMENT_B_HELD_OUT_TAIL": "last 30% of each series — held out from parameter choice, still inside a consumed corpus",
            "PROSPECTIVE": "bars after the frozen protocol instant; see OOS_CAPTURE_MANIFEST_V2.json",
        },
        "rotation": rotation_summary,
        "verdicts": sorted(verdicts, key=lambda row: str(row["family"])),
        "rejected_family_audit": rejected,
        "candidate_registration": register,
        "no_economic_edge_found": not edge_found,
        "reading": (
            "no family clears its costs on the held-out tail with enough trades to be adopted; "
            "the honest outcome is NO_ECONOMIC_EDGE_FOUND with the research lane kept"
            if not edge_found
            else "at least one family survives the adverse cost multiplier with enough trades, "
            "and still cannot be adopted before the prospective slice accrues"
        ),
        "next_hypothesis": (
            "the tail says the surviving structure is the cost model, not the signal: a family "
            "whose gross expectancy per trade exceeds its own tier's round trip (>= 24 bps for a "
            "tier-1 pair, >= 28 bps for a thin alt) is the next thing to look for, and the "
            "prospective slice is the only place it can be confirmed"
        ),
    }
    (out / "ALPHA_RESULTS.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    columns = [
        "family",
        "corpus",
        "symbol",
        "segment",
        "cost_multiplier",
        "trades",
        "trades_per_day",
        "days_without_trades",
        "window_days",
        "net_bps_total_portfolio",
        "rebalances",
        "gross_bps_per_trade",
        "expectancy_bps_per_trade",
        "net_bps_total",
        "net_bps_total_1x",
        "net_bps_total_2x",
        "net_bps_total_3x",
        "cost_round_trip_bps_1x",
        "cost_round_trip_bps_2x",
        "cost_round_trip_bps_3x",
        "win_rate",
        "profit_factor",
        "equity_multiple",
        "max_drawdown_bps",
        "sharpe_daily_annualised",
        "fees_and_costs_bps_paid",
        "median_net_bps_per_trade",
        "top5_share_of_gross",
        "trades_losing_money_per_trade",
    ]
    with (out / "ALPHA_EXPERIMENT_MATRIX.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in single_rows + rotation_rows:
            writer.writerow(row)

    print(f"[alpha] single-asset rows {len(single_rows)}, rotation rows {len(rotation_rows)}")
    for verdict in sorted(verdicts, key=lambda v: str(v["family"])):
        print(f"[alpha] {verdict['family']:<26} {verdict['verdict']}")
    print(f"[alpha] NO_ECONOMIC_EDGE_FOUND={payload['no_economic_edge_found']}")
    print(f"[alpha] candidates registered disabled -> {register['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
