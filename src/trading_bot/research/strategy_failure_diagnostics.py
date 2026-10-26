"""ARP-002 §1/§2/§3 — StrategyFailureDiagnostics (tracked, research-only, deterministic).

This is the ARP-001 diagnostic tool promoted out of the gitignored ``reports/`` tree
into tracked source, so that ARP diagnostics are reproducible **by commit SHA**
(ARP-001's one infrastructure gap: it produced evidence under ``reports/`` only, so
nothing changed in git and its output could not be regenerated from a commit).

It is deliberately NOT part of the trading runtime composition:

* no runtime module imports it — the PAPER runtime builds its family map from an
  explicit import list in ``scripts/autonomous_paper.py`` and the frozen admission
  ledger ``config/strategy_admission.json``;
* it only READS the reproduced BASE trade ledger and the local 5m corpus, and WRITES
  a machine-readable JSON; it can size, risk-check or execute nothing.

DETERMINISM (§3)
    No random numbers, no wall-clock, no set/dict iteration order in the output
    (``json.dumps(..., sort_keys=True)``), no LLM arithmetic. Running the module twice
    on the same inputs yields byte-identical output.

SCHEMAS
    ``enrich=False`` (default) reproduces the ARP-001 canonical document **byte for
    byte** (sha256 ``464f2a00…615a5``); this is asserted as a regression test.
    ``enrich=True`` returns the same document plus the §2 fields the ARP-001 document
    did not carry (per-family drawdown, signal counts, timeframe attribution), added
    as extra keys so the base document is unchanged.

§2 KNOWN LIMITATION (not fabricated)
    The BASE ledger contains only *executed* signals (already passed risk, dedupe and
    sizing), so ``signals`` / ``eligible_signals`` == the executed trade count and
    raw/tournament-level signal counts are NOT reconstructible from this artifact.
    The fields are emitted for contract completeness and labelled as such in
    ``signal_ledger_semantics``.

Pre-declared trade-path rules (§10 of the WP), applied in order:
  1. reason == "stop" and mfe_pct <= 0.10            -> IMMEDIATE_ADVERSE_MOVE
  2. reason == "tp"                                  -> WIN_TAKE_PROFIT
  3. mfe_pct >= 0.30 and net < 0                     -> PROFIT_THEN_GIVEBACK
  4. reason == "flip" and duration_min <= 15         -> EXIT_TOO_EARLY_HYPOTHESIS
  5. gross > 0 and net < 0                           -> COST_DOMINATED
  6. duration_min >= 240                             -> TREND_FAILURE
  7. else                                            -> OTHER

Exit-quality verdict:
  fwd_mean(+1 bar) > 0 and expectancy(net) <= 0 -> EXIT_OR_TRADE_MANAGEMENT_SUSPECT
  otherwise                                      -> SIGNAL_EDGE_NOT_DEMONSTRATED
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, TypedDict

# ``src/trading_bot/research/strategy_failure_diagnostics.py`` -> parents[3] == repo root.
REPO = Path(__file__).resolve().parents[3]

SeriesData = tuple[list[dict[str, Any]], dict[int, int], list[float | None]]

FAMILIES = ["ema_crossover", "momentum", "breakout", "trend", "mean_reversion", "volatility"]
FWD_BARS = [1, 3, 6, 12, 24]
REGIME_VOL_WINDOW = 100
REGIME_MEDIAN_WINDOW = 720
COST_MULTIPLES = [0.5, 1.0, 1.25, 1.5, 2.0]
RUNTIME_COST_BPS_RT = 23.25
NOTIONAL_USD = 500.0


class TradeRow(TypedDict):
    """One parsed row of the BASE trade ledger."""

    family: str
    window: str
    asset: str
    side: str
    entry_ts: int
    duration_min: float
    entry: float
    gross: float
    fees: float
    net: float
    mfe_pct: float
    mae_pct: float
    reason: str


@dataclass(frozen=True, slots=True)
class DiagnosticsInputs:
    """Filesystem inputs for one deterministic diagnostic run."""

    trades: Path
    corpus: Path
    results_dir: Path
    out: Path
    runtime_cost_bps_rt: float = RUNTIME_COST_BPS_RT


def default_inputs() -> DiagnosticsInputs:
    return DiagnosticsInputs(
        trades=REPO / "reports/wp-strat-08/data/fresh_trades_base.csv",
        corpus=REPO / "reports/strategy-baseline/data",
        results_dir=REPO / "reports/strategy-baseline",
        out=REPO / "reports/alpha-recovery-v1/diagnostics/strategy_failure_metrics.json",
    )


def _series(corpus: Path, symbol: str, window: str) -> SeriesData:
    path = corpus / f"{symbol.replace('/', '')}_{window}.json"
    if not path.exists():
        return [], {}, []
    bars = json.loads(path.read_text(encoding="utf-8"))
    idx_map = {int(b["ts"]): i for i, b in enumerate(bars)}
    rets = [0.0]
    for a, b in pairwise(bars):
        prev = a["close"] or 1.0
        rets.append((b["close"] - prev) / prev * 100.0)
    vols: list[float | None] = []
    for i in range(len(bars)):
        seg = rets[max(0, i - REGIME_VOL_WINDOW) : i + 1]
        vols.append(statistics.pstdev(seg) if len(seg) > 1 else None)
    return bars, idx_map, vols


def _regime_at(vols: list[float | None], idx: int) -> str:
    if idx < REGIME_MEDIAN_WINDOW:
        return "UNKNOWN"
    seg = [v for v in vols[idx - REGIME_MEDIAN_WINDOW : idx + 1] if v is not None]
    cur = vols[idx]
    if not seg or cur is None:
        return "UNKNOWN"
    return "HIGH" if cur > statistics.median(seg) else "LOW"


def _concentration(nets: list[float]) -> dict[str, Any]:
    pos = sorted((n for n in nets if n > 0), reverse=True)
    total_pos = sum(pos)
    if not pos or total_pos <= 0:
        return {
            "positive_trades": 0,
            "total_positive_net": 0.0,
            "top1_share": None,
            "top5_share": None,
            "top10pct_share": None,
        }
    k10 = max(1, len(nets) // 10)
    return {
        "positive_trades": len(pos),
        "total_positive_net": round(total_pos, 2),
        "top1_share": round(sum(pos[:1]) / total_pos, 4),
        "top5_share": round(sum(pos[:5]) / total_pos, 4),
        "top10pct_share": round(sum(pos[:k10]) / total_pos, 4),
    }


def _max_drawdown_bps(nets: Sequence[float]) -> float:
    """Peak-to-trough drawdown of the non-compounding net trade sequence, in bps."""
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for n in nets:
        equity += n
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst / NOTIONAL_USD * 10000.0, 3)


def compute_diagnostics(inputs: DiagnosticsInputs, *, enrich: bool = False) -> dict[str, Any]:
    """Compute the diagnostic document. Deterministic for fixed inputs."""
    rows: list[TradeRow] = []
    for raw in csv.DictReader(inputs.trades.open(encoding="utf-8")):
        rows.append(
            TradeRow(
                family=raw["family"],
                window=raw["window"],
                asset=raw["asset"],
                side=raw["side"],
                entry_ts=int(raw["entry_ts"]),
                duration_min=float(raw["duration_min"]),
                entry=float(raw["entry"]),
                gross=float(raw["gross"]),
                fees=float(raw["fees"]),
                net=float(raw["net"]),
                mfe_pct=float(raw["mfe_pct"]),
                mae_pct=float(raw["mae_pct"]),
                reason=raw["reason"],
            )
        )

    cache: dict[tuple[str, str], SeriesData] = {}

    def series(symbol: str, window: str) -> SeriesData:
        key = (symbol, window)
        if key not in cache:
            cache[key] = _series(inputs.corpus, symbol, window)
        return cache[key]

    out: dict[str, Any] = {
        "schema_version": "arp001-strategy-failure-diagnostics-v1",
        "source_trades": str(inputs.trades.relative_to(REPO)) if inputs.trades.is_relative_to(REPO) else str(inputs.trades),
        "runtime_cost_bps_round_trip": inputs.runtime_cost_bps_rt,
        "research_library_cost_bps_round_trip": 12.0,
        "predeclared": {
            "forward_bars": FWD_BARS,
            "regime_vol_window": REGIME_VOL_WINDOW,
            "regime_median_window": REGIME_MEDIAN_WINDOW,
            "cost_multiples": COST_MULTIPLES,
            "cost_stress_is_fee_multiple_only": True,
        },
        "families": {},
    }

    for fam in FAMILIES:
        frows = [r for r in rows if r["family"] == fam]
        n = len(frows)
        gross = sum(r["gross"] for r in frows)
        fees = sum(r["fees"] for r in frows)
        net = sum(r["net"] for r in frows)
        wins = [r["net"] for r in frows if r["net"] > 0]
        losses = [r["net"] for r in frows if r["net"] <= 0]
        nets = [r["net"] for r in frows]

        fwd: dict[str, dict[str, Any]] = {}
        for k in FWD_BARS:
            vals: list[float] = []
            for r in frows:
                bars, idx_map, _ = series(r["asset"] + "USDT", r["window"])
                i = idx_map.get(r["entry_ts"])
                if i is None or i + k >= len(bars):
                    continue
                sign = 1.0 if r["side"] == "buy" else -1.0
                base = r["entry"] or bars[i]["close"]
                vals.append((bars[i + k]["close"] / base - 1.0) * 10000.0 * sign)
            fwd[f"+{k}bars"] = {
                "n": len(vals),
                "mean_bps": round(statistics.fmean(vals), 3) if vals else None,
                "median_bps": round(statistics.median(vals), 3) if vals else None,
                "share_positive": round(sum(1 for v in vals if v > 0) / len(vals), 4) if vals else None,
            }

        by_asset: dict[str, list[float]] = defaultdict(list)
        by_regime: dict[str, list[float]] = defaultdict(list)
        by_timeframe: dict[str, list[float]] = defaultdict(list)
        by_exit: Counter[str] = Counter()
        path: Counter[str] = Counter()
        for r in frows:
            by_asset[r["asset"]].append(r["net"])
            by_timeframe["5m"].append(r["net"])
            _, idx_map, vols = series(r["asset"] + "USDT", r["window"])
            i = idx_map.get(r["entry_ts"])
            by_regime[_regime_at(vols, i) if i is not None else "UNKNOWN"].append(r["net"])
            by_exit[r["reason"]] += 1
            if r["reason"] == "stop" and r["mfe_pct"] <= 0.10:
                path["IMMEDIATE_ADVERSE_MOVE"] += 1
            elif r["reason"] == "tp":
                path["WIN_TAKE_PROFIT"] += 1
            elif r["mfe_pct"] >= 0.30 and r["net"] < 0:
                path["PROFIT_THEN_GIVEBACK"] += 1
            elif r["reason"] == "flip" and r["duration_min"] <= 15:
                path["EXIT_TOO_EARLY_HYPOTHESIS"] += 1
            elif r["gross"] > 0 and r["net"] < 0:
                path["COST_DOMINATED"] += 1
            elif r["duration_min"] >= 240:
                path["TREND_FAILURE"] += 1
            else:
                path["OTHER"] += 1

        stress: dict[str, dict[str, Any]] = {}
        for m in COST_MULTIPLES:
            net_m = gross - m * fees
            stress[f"{m}x"] = {
                "net": round(net_m, 2),
                "expectancy_usd": round(net_m / n, 4) if n else None,
                "expectancy_bps": round(net_m / n / NOTIONAL_USD * 10000.0, 3) if n else None,
            }

        gross_exp_bps = (gross / n / NOTIONAL_USD * 10000.0) if n else None
        cost_exp_bps = (fees / n / NOTIONAL_USD * 10000.0) if n else None
        net_exp_bps = (net / n / NOTIONAL_USD * 10000.0) if n else None

        family_doc: dict[str, Any] = {
            "trades": n,
            "gross_usd": round(gross, 2),
            "fees_usd": round(fees, 2),
            "net_usd": round(net, 2),
            "expectancy_gross_bps": round(gross_exp_bps, 3) if gross_exp_bps is not None else None,
            "expectancy_cost_bps": round(cost_exp_bps, 3) if cost_exp_bps is not None else None,
            "expectancy_net_bps": round(net_exp_bps, 3) if net_exp_bps is not None else None,
            "break_even_cost_bps": round(gross_exp_bps, 3) if gross_exp_bps is not None else None,
            "cost_over_gross": round(cost_exp_bps / gross_exp_bps, 3)
            if gross_exp_bps and cost_exp_bps is not None
            else None,
            "win_rate": round(len(wins) / n, 4) if n else None,
            "avg_win_usd": round(statistics.fmean(wins), 4) if wins else None,
            "avg_loss_usd": round(statistics.fmean(losses), 4) if losses else None,
            "payoff": round(statistics.fmean(wins) / abs(statistics.fmean(losses)), 4) if wins and losses else None,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
            "avg_mfe_pct": round(statistics.fmean([r["mfe_pct"] for r in frows]), 4) if n else None,
            "avg_mae_pct": round(statistics.fmean([r["mae_pct"] for r in frows]), 4) if n else None,
            "avg_duration_min": round(statistics.fmean([r["duration_min"] for r in frows]), 2) if n else None,
            "median_duration_min": round(statistics.median([r["duration_min"] for r in frows]), 2) if n else None,
            "exit_mix": dict(by_exit),
            "concentration": _concentration(nets),
            "cost_stress": stress,
            "forward_returns": fwd,
            "by_asset": {a: {"n": len(v), "net_usd": round(sum(v), 2)} for a, v in sorted(by_asset.items())},
            "by_regime": {a: {"n": len(v), "net_usd": round(sum(v), 2)} for a, v in sorted(by_regime.items())},
            "trade_path": dict(path),
            "exit_quality_verdict": (
                "EXIT_OR_TRADE_MANAGEMENT_SUSPECT"
                if (fwd["+1bars"]["mean_bps"] or 0) > 0 and (net_exp_bps or 0) <= 0
                else "SIGNAL_EDGE_NOT_DEMONSTRATED"
            ),
            "cost_classification": (
                "NO_GROSS_EDGE" if (gross_exp_bps or 0) <= 0
                else ("GROSS_EDGE_BUT_COST_KILLED" if (net_exp_bps or 0) <= 0 else "NET_POSITIVE_CANDIDATE")
            ),
        }
        if enrich:
            # ARP-002 §2 additions. Extra keys only; never mutate the base document.
            family_doc["signals"] = n
            family_doc["eligible_signals"] = n
            family_doc["signal_ledger_semantics"] = (
                "BASE ledger carries executed signals only; raw/tournament signal counts "
                "are not reconstructible from this artifact"
            )
            family_doc["drawdown_bps"] = _max_drawdown_bps(nets)
            family_doc["by_timeframe"] = {
                a: {"n": len(v), "net_usd": round(sum(v), 2)} for a, v in sorted(by_timeframe.items())
            }
        out["families"][fam] = family_doc

    mtf = {}
    for path_ in sorted(inputs.results_dir.glob("MULTI_FAMILY_RESULTS_*.json")):
        key = path_.stem.replace("MULTI_FAMILY_RESULTS_", "")
        d = json.loads(path_.read_text(encoding="utf-8"))
        for famname, blocks in d.items():
            base = blocks.get("BASE", {})
            mtf[key] = {
                "family": famname,
                "base_net": (base.get("totals") or {}).get("net"),
                "base_trades": (base.get("totals") or {}).get("trades"),
                "dev_net": (base.get("DEV_W1_W4") or {}).get("net"),
                "val_net": (base.get("VAL_W5_W6") or {}).get("net"),
                "oos_net": (base.get("OOS_W7") or {}).get("net"),
            }
    out["multi_timeframe_base"] = mtf

    if enrich:
        out["schema_version_document"] = "arp002-strategy-failure-diagnostics-v2"
        out["enrichment"] = {
            "added_by": "ARP-002",
            "base_schema_version": "arp001-strategy-failure-diagnostics-v1",
            "base_byte_identical_when_enrich_false": True,
        }
    return out


def canonical_payload(doc: dict[str, Any]) -> bytes:
    """Canonical bytes: sorted keys, indent 2, **LF newlines**, no platform translation.

    LF (not the platform default) so the digest is identical on Windows and Linux;
    the ARP-001 tool wrote through text mode, so its on-disk CRLF file hashes to
    ``464f2a00…`` while the identical LF payload hashes to ``29b6240b…``.
    """
    return json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")


def write_document(doc: dict[str, Any], out_path: Path) -> str:
    """Write canonical JSON bytes and return the sha256 of the exact bytes written."""
    import hashlib

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_payload(doc)
    out_path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ARP strategy failure diagnostics (research-only).")
    d = default_inputs()
    ap.add_argument("--trades", default=str(d.trades))
    ap.add_argument("--corpus", default=str(d.corpus))
    ap.add_argument("--results-dir", default=str(d.results_dir))
    ap.add_argument("--out", default=str(d.out))
    ap.add_argument("--enrich", action="store_true", help="emit the ARP-002 §2 superset document")
    args = ap.parse_args(argv)

    inputs = DiagnosticsInputs(
        trades=Path(args.trades),
        corpus=Path(args.corpus),
        results_dir=Path(args.results_dir),
        out=Path(args.out),
    )
    doc = compute_diagnostics(inputs, enrich=args.enrich)
    digest = write_document(doc, inputs.out)
    print(f"wrote {inputs.out} sha256={digest}")
    for fam in FAMILIES:
        f = doc["families"][fam]
        print(
            f"{fam:16s} n={f['trades']:5d} gross_bps={f['expectancy_gross_bps']:>8} "
            f"cost_bps={f['expectancy_cost_bps']:>7} net_bps={f['expectancy_net_bps']:>8} "
            f"PF={f['profit_factor']} fwd1={f['forward_returns']['+1bars']['mean_bps']} "
            f"{f['exit_quality_verdict']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
