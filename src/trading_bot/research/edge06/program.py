"""WP-EDGE-06 Track B — run the registered families on the frozen windows and read them.

The runner is deliberately a *reuse* of the campaign that measured the frozen books:
``edge01.campaign`` already owns the splits, the corpus loader, the market-regime series,
the metric definitions and the admission gate. Calling those functions is what makes a
comparison between a new family and ``edge_trend_01_4h`` a comparison of signals rather than
of two implementations' opinions about what a profit factor is.

What is new here is only the reading:

* the same gate, applied to each family, with every reason printed;
* a *cost sensitivity* reading taken from the scenarios the campaign already defines;
* a *concentration* reading — the share of the window's net carried by its largest winner —
  because the frozen 4h book earned its OOS net that way and no new family gets to skip the
  question;
* a *robustness* arm that removes the single largest winner and re-reads the window, so a
  family whose verdict survives only while that trade is present is reported as such.

Nothing here promotes, sizes or executes anything.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.research.edge01 import campaign as C
from trading_bot.research.edge01.costs import cost_plane
from trading_bot.research.edge01.features import market_regime_at
from trading_bot.research.edge01.simulator import run_portfolio as run_portfolio_sim

from .families import DECLARED_PARAMS, FAMILY_BOOKS, build_families

__all__ = ["run_program", "verdict_for", "DECLARED_PARAMS", "FAMILY_BOOKS"]

SCHEMA_VERSION = "EDGE06_FAMILY_PROGRAM_V1"

#: The books the families are compared against, read from the same artefacts they are: their
#: figures are carried into the report so the comparison is side by side, not remembered.
REFERENCE_BOOKS: tuple[str, ...] = ("edge_trend_01_4h", "edge_trend_01_1d", "edge_intra_01")


def _labels(universe: dict[str, list[Any]]) -> dict[str, Any]:
    """The benchmark-relative context series, built once from the longest local corpus."""
    rows, meta = C._market_context_series()
    return {"rows": rows, "meta": meta}


def _leave_out_largest(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The trade rows with the single largest winner removed (a diagnostic, not a revision)."""
    if not trades:
        return []
    best = max(trades, key=lambda trade: float(trade.get("net") or 0.0))
    removed = False
    kept: list[dict[str, Any]] = []
    for trade in trades:
        if not removed and trade is best:
            removed = True
            continue
        kept.append(trade)
    return kept


def _metrics_without_the_largest(
    *, trades: list[dict[str, Any]], metrics: dict[str, Any], start_equity: float
) -> dict[str, Any]:
    kept = _leave_out_largest(trades)
    nets = [float(trade.get("net") or 0.0) for trade in kept]
    return {
        "trades": len(kept),
        "net_usdt": round(sum(nets), 4),
        "expectancy_usdt": round(sum(nets) / len(kept), 4) if kept else None,
        "removed_trade_net_usdt": round(
            float(metrics.get("net_usdt") or 0.0) - sum(nets), 4
        ),
        "return_pct_of_start_equity": round(sum(nets) / start_equity * 100.0, 4),
    }


def run_family(
    book: str,
    *,
    scenarios: tuple[str, ...] = ("BASE", "2X_FEES", "ADVERSE"),
) -> dict[str, Any]:
    scope = FAMILY_BOOKS[book]
    split_name = str(scope["split"])
    timeframe = str(scope["timeframe"])
    policy = C.load_risk_policy()
    regime = _labels({})
    corpus = C._load_corpus(split_name, timeframe)
    families = build_families(corpus.bars_by_asset)
    window = C.SPLITS[split_name]
    horizon = float(scope["horizon_minutes"])
    base_plane = cost_plane(size_usd=1000.0, horizon_minutes=horizon)

    result: dict[str, Any] = {
        "book": book,
        "answers": scope["answers"],
        "scope": {
            "split": split_name,
            "timeframe": timeframe,
            "assets": list(corpus.bars_by_asset),
            "assets_are_the_declared_universe": bool(scope["needs_universe"]),
            "frozen_params_source": "reports/edge-recovery/WP-EDGE-06/research/HYPOTHESES.md",
            "declared_params": DECLARED_PARAMS[book],
            "provenance": corpus.provenance,
        },
        "splits": {},
    }
    for split, bounds in window.items():
        start, end = int(bounds["start"]), int(bounds["end"])
        window_minutes = (end - start) / 60_000.0
        split_results: dict[str, Any] = {}
        for scenario in scenarios:
            plane = base_plane.scaled(scenario)
            # A fresh candidate per scenario: the frozen campaign does the same, so no state
            # from one cost plane's walk can leak into another's.
            candidate = build_families(corpus.bars_by_asset)[book]
            sim = run_portfolio_sim(
                candidate=candidate,
                bars_by_asset=corpus.bars_by_asset,
                plane=plane,
                policy=policy,
                context=corpus.context,
                window_start_ts=start,
                window_end_ts=end,
            )
            for trade in sim.trades:
                trade["market_context"] = market_regime_at(regime["rows"], int(trade["decision_ts"]))
            metrics = C._metrics(
                trades=sim.trades,
                equity_curve=sim.equity_curve,
                start_equity=policy.start_equity,
                window_minutes=window_minutes,
                timeframe=timeframe,
                n_assets=len(corpus.bars_by_asset),
            )
            refusal_mix: dict[str, int] = {}
            for refusal in sim.refusals:
                key = f"{refusal.get('source', 'candidate')}:{refusal.get('reason')}"
                refusal_mix[key] = refusal_mix.get(key, 0) + 1
            split_results[scenario] = {
                **metrics,
                "plane": plane.to_dict(),
                "candidate_refusals": refusal_mix,
                "signals_printed": len(sim.signals),
                "without_the_largest_winner": _metrics_without_the_largest(
                    trades=sim.trades, metrics=metrics, start_equity=policy.start_equity
                ),
                "trade_rows": sim.trades,
            }
        result["splits"][split] = split_results
    return result


def verdict_for(result: dict[str, Any]) -> dict[str, Any]:
    """The registered reading: the frozen gate, plus the two arms this WP added.

    The gate is the campaign's own, called with the campaign's own criteria, so a family
    cannot be admitted by a rule that was written after its numbers were seen. The two extra
    readings — cost sensitivity and the leave-out-the-largest arm — can only *downgrade* a
    verdict, never upgrade one: they exist because the frozen trend book's OOS net was
    carried by one trade, and the same failure must be visible for a new family.
    """
    gate = C._gate(splits=result["splits"], criteria=C.ADMISSION_CRITERIA)
    oos = result["splits"]["OOS"]["BASE"]
    dev = result["splits"]["DEV"]["BASE"]
    concentration = oos.get("largest_trade_share_of_net")
    without = oos.get("without_the_largest_winner") or {}
    stress = float(result["splits"]["OOS"].get("2X_FEES", {}).get("net_usdt") or 0.0)
    gross_dev = float(dev.get("gross_usdt") or 0.0)
    reasons = list(gate["reasons"])

    verdict = gate["verdict"]
    if gross_dev <= 0:
        verdict = "REJECT_NO_GROSS_EDGE"
        reasons.append(
            f"the DEV gross is {gross_dev:.2f} USDT: the setup loses money before any fee, "
            "which no cost change can repair"
        )
    elif verdict == "INSUFFICIENT_EVIDENCE" and stress <= 0:
        verdict = "REJECT_COST_MARGIN"
    if verdict == "ADMIT":
        if isinstance(concentration, (int, float)) and concentration > 0.5:
            verdict = "REJECTED_BY_CONCENTRATION"
            reasons.append(f"one trade is {concentration:.4f} of the OOS net")
        elif float(without.get("net_usdt") or 0.0) <= 0:
            verdict = "REJECTED_BY_ROBUSTNESS"
            reasons.append(
                "the OOS net turns negative when the single largest winner "
                f"({without.get('removed_trade_net_usdt')} USDT) is removed"
            )
    if verdict == "ADMIT":
        reasons.append(
            "clears the frozen gate, is not carried by one trade, and survives removing its "
            "largest winner — still NOT validated: this OOS window was read before"
        )
    return {
        "verdict": verdict,
        "gate_verdict": gate["verdict"],
        "reasons": reasons,
        "power": gate["power"],
        "evidence": {
            **gate["evidence"],
            "dev_gross_usdt": round(gross_dev, 4),
            "dev_base_net_usdt": round(float(dev.get("net_usdt") or 0.0), 4),
            "dev_trades": dev.get("trades"),
            "oos_without_the_largest_usdt": without.get("net_usdt"),
            "oos_largest_trade_share_of_net": concentration,
            "oos_cost_bps_per_trade": oos.get("total_cost_bps_per_trade"),
            "windows_are_previously_read": True,
        },
        "disclosure": (
            "the trend OOS window has already been read by the frozen 4h ruleset and by the "
            "robustness analysis of WP-EDGE-02, so clearing the gate here is 'not yet rejected' "
            "and never validation"
        ),
    }


def reference_reading() -> dict[str, Any]:
    """The frozen books' own numbers, read from their artefact so the comparison is side by side."""
    path = C.REPO / "reports" / "edge-recovery" / "WP-EDGE-01" / "STRATEGY_RESULTS.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, Any] = {}
    for book in REFERENCE_BOOKS:
        candidate = (payload.get("candidates") or {}).get(book)
        if not candidate:
            continue
        out[book] = {
            "verdict": candidate.get("verdict"),
            "splits": {
                window: {
                    scenario: {
                        key: metrics.get(key)
                        for key in (
                            "trades",
                            "gross_usdt",
                            "fees_usdt",
                            "price_costs_usdt",
                            "net_usdt",
                            "expectancy_usdt",
                            "profit_factor",
                            "max_drawdown_pct",
                            "largest_trade_share_of_net",
                        )
                    }
                    for scenario, metrics in scenarios.items()
                }
                for window, scenarios in (candidate.get("splits") or {}).items()
            },
        }
    return {
        "source": str(path.relative_to(C.REPO)).replace("\\", "/"),
        "note": "measured by the WP-EDGE-01 campaign, not by this work package",
        "books": out,
    }


def run_program(*, scenarios: tuple[str, ...] = ("BASE", "2X_FEES", "ADVERSE")) -> dict[str, Any]:
    instant = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    results: dict[str, Any] = {}
    for book in FAMILY_BOOKS:
        result = run_family(book, scenarios=scenarios)
        result["reading"] = verdict_for(result)
        results[book] = result
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"EDGE06-PROGRAM-{instant.replace('-', '').replace(':', '')}",
        "as_of_utc": instant,
        "declared_params": DECLARED_PARAMS,
        "books": {
            name: {"split": scope["split"], "timeframe": scope["timeframe"], "answers": scope["answers"]}
            for name, scope in FAMILY_BOOKS.items()
        },
        "windows": {
            split: {
                window: {
                    "start_utc": datetime.fromtimestamp(bounds["start"] / 1000, tz=UTC).isoformat(),
                    "end_utc": datetime.fromtimestamp(bounds["end"] / 1000, tz=UTC).isoformat(),
                }
                for window, bounds in windows.items()
            }
            for split, windows in C.SPLITS.items()
        },
        "cost_scenarios": C.COST_SCENARIOS,
        "admission_criteria": C.ADMISSION_CRITERIA,
        "families": results,
        "reference": reference_reading(),
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def write_artifacts(payload: dict[str, Any], outdir: Path) -> dict[str, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "FAMILY_PROGRAM.json"
    md_path = outdir / "FAMILY_PROGRAM.md"
    json_path.write_text(
        json.dumps(_public(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    md_path.write_text(render(payload), encoding="utf-8")
    trades_path = outdir / "FAMILY_TRADES.csv"
    _write_trades(payload, trades_path)
    return {"json": json_path, "markdown": md_path, "trades": trades_path}


def _public(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items() if key != "trade_rows"}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def _write_trades(payload: dict[str, Any], path: Path) -> None:
    import csv

    columns = [
        "book",
        "window",
        "scenario",
        "asset",
        "entry_ts",
        "exit_ts",
        "duration_min",
        "notional",
        "gross",
        "fees",
        "price_costs",
        "net",
        "exit_reason",
        "regime",
        "market_context",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for book, result in payload["families"].items():
            for window, scenarios in result["splits"].items():
                for scenario, metrics in scenarios.items():
                    for trade in metrics.get("trade_rows") or []:
                        writer.writerow({"book": book, "window": window, "scenario": scenario, **trade})


def _num(value: Any) -> str:
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "—"


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-06 Track B — the registered families, measured",
        "",
        f"*Run at `{payload['as_of_utc']}` (`{payload['run_id']}`). Same corpus, same windows, "
        "same cost scenarios, same risk policy, same metric definitions and the same admission "
        "gate as the campaign that measured the frozen books — by calling its functions.*",
        "",
        "## 1. The verdicts",
        "",
        "| Family | Answers | Verdict | Gate said | OOS trades | OOS net | OOS gross DEV | Largest share | Without it |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for book, result in payload["families"].items():
        reading = result["reading"]
        evidence = reading["evidence"]
        lines.append(
            f"| `{book}` | {result['answers']} | **{reading['verdict']}** | "
            f"`{reading['gate_verdict']}` | {evidence.get('oos_trades')} | "
            f"{_num(evidence.get('oos_net_usdt'))} | {_num(evidence.get('dev_gross_usdt'))} | "
            f"{evidence.get('oos_largest_trade_share_of_net')} | "
            f"{_num(evidence.get('oos_without_the_largest_usdt'))} |"
        )

    lines += ["", "### Why, in the gate's own words", ""]
    for book, result in payload["families"].items():
        reading = result["reading"]
        lines.append(f"- **`{book}`** — {reading['verdict']} ({reading['power']})")
        for reason in reading["reasons"]:
            lines.append(f"  - {reason}")
        lines.append(f"  - disclosure: {reading['disclosure']}")

    lines += [
        "",
        "## 2. Every window, every cost scenario",
        "",
        "| Family | Window | Scenario | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | DD % | Cost bps | Largest share |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for book, result in payload["families"].items():
        for window, scenarios in sorted(result["splits"].items()):
            for scenario, metrics in sorted(scenarios.items()):
                lines.append(
                    f"| `{book}` | {window} | {scenario} | {metrics.get('trades')} | "
                    f"{_num(metrics.get('gross_usdt'))} | {_num(metrics.get('fees_usdt'))} | "
                    f"{_num(metrics.get('price_costs_usdt'))} | **{_num(metrics.get('net_usdt'))}** | "
                    f"{_num(metrics.get('expectancy_usdt'))} | {_num(metrics.get('profit_factor'))} | "
                    f"{_num(metrics.get('max_drawdown_pct'))} | "
                    f"{_num(metrics.get('total_cost_bps_per_trade'))} | "
                    f"{metrics.get('largest_trade_share_of_net')} |"
                )

    lines += [
        "",
        "## 3. The frozen books, side by side (read from their own artefact)",
        "",
        "| Book | Window | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | Largest share |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for book, body in (payload["reference"]["books"] or {}).items():
        for window, scenarios in sorted((body.get("splits") or {}).items()):
            metrics = scenarios.get("BASE") or {}
            lines.append(
                f"| `{book}` | {window} | {metrics.get('trades')} | {_num(metrics.get('gross_usdt'))} | "
                f"{_num(metrics.get('fees_usdt'))} | {_num(metrics.get('price_costs_usdt'))} | "
                f"{_num(metrics.get('net_usdt'))} | {_num(metrics.get('expectancy_usdt'))} | "
                f"{_num(metrics.get('profit_factor'))} | {metrics.get('largest_trade_share_of_net')} |"
            )
    lines += [
        "",
        f"*Source: `{payload['reference']['source']}` — {payload['reference']['note']}.*",
        "",
        "## 4. What this run does not do",
        "",
        "- It does not promote anything: `promotion: NONE`, `order_sent: false`, no PAPER admission.",
        "- It does not tune. Every parameter is the one `HYPOTHESES.md` registered before the run;",
        "  a parameter that would have helped is a proposal for a new registration, not an edit.",
        "- It does not claim validation from a previously read window, and says so per family.",
        "",
        "### The registered parameters, as run",
        "",
        "```json",
        json.dumps(payload["declared_params"], indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)
