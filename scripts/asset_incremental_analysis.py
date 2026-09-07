"""PARALLEL-WORK-03 Track D — XRP/DOGE incremental-opportunity analysis.

OBSERVATIONAL ONLY: measures whether XRP/DOGE would add *independent
opportunity* relative to the existing BTC/ETH/SOL portfolio. No PnL claims,
no acceptance criteria, no selection, no promotion — outputs feed
ASSET_CANDIDATE records only. POC01 is untouched.

Analysis window = the LAST 7 days of the fetched fresh dataset (ends at the
latest closed candle). DECLARED OVERLAP: this range necessarily overlaps
previously defined experiment windows (EDGE-RESEARCH-002 confirmation/holdout,
R1 holdout). No EDGE/R1 candidate is evaluated, consulted, or modified here;
this analysis answers a different question (cross-asset opportunity
structure) and produces no promotion decision.

Public ccxt endpoints only: no API key, no secret, no private call. LIVE = 0.
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.discovery.dataset import DatasetFetcher, FRESH_START_UTC
from trading_bot.discovery.runner import evaluate_combo_with_ledger
from trading_bot.discovery.split import SplitWindows

PORTFOLIO = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT")
CANDIDATES = ("XRP/USDT:USDT", "DOGE/USDT:USDT")
SYMBOLS = PORTFOLIO + CANDIDATES
FAMILIES = ("momentum", "trend", "breakout", "mean_reversion", "ema_crossover")
ANALYSIS_DAYS = 7
# Occupancy proxy: a portfolio position opened by a signal is assumed to
# occupy a slot while any portfolio signal fired within +/- OCCUPANCY_HOURS.
OCCUPANCY_HOURS = 2.0
OUT = Path("reports/asset-incremental-analysis")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fetcher = DatasetFetcher(symbols=SYMBOLS)
    datasets = fetcher.fetch()
    last_close_ms = max(ds.quality.last_close_ms for ds in datasets.values())
    cutoff = datetime.fromtimestamp((last_close_ms + 1) / 1000, tz=UTC)
    start = cutoff - timedelta(days=ANALYSIS_DAYS)

    windows = SplitWindows(
        discovery_start=start,
        discovery_end_exclusive=cutoff,
        confirmation_end_exclusive=cutoff,
        holdout_end_exclusive=cutoff,
    )

    from trading_bot.discovery.split import SplitAccessor

    accessor = SplitAccessor(
        datasets=datasets, windows=windows,
        split_sha256=f"track-d-analysis-{start.isoformat()}-{cutoff.isoformat()}",
    )

    # entry timestamps per (symbol, family, direction); returns per symbol
    entries: dict[tuple[str, str, str], list[int]] = {}
    ledger_intervals: dict[tuple[str, str, str], list[tuple[int, int]]] = {}
    for sym in SYMBOLS:
        for fam in FAMILIES:
            for direction in ("LONG", "SHORT"):
                try:
                    run, ledger = evaluate_combo_with_ledger(
                        accessor, family_name=fam, symbol=sym,
                        regime_filter="ALL", direction_filter=direction,
                    )
                except Exception as exc:  # noqa: BLE001 — observational harness
                    entries[(sym, fam, direction)] = []
                    ledger_intervals[(sym, fam, direction)] = []
                    print(f"  skip {sym} {fam} {direction}: {exc}")
                    continue
                entries[(sym, fam, direction)] = [t.entry_ts for t in ledger.trades]
                ledger_intervals[(sym, fam, direction)] = [
                    (t.entry_ts, t.exit_ts) for t in ledger.trades
                ]

    def portfolio_entries() -> list[int]:
        return sorted(
            ts for (sym, _, _), tss in entries.items()
            if sym in PORTFOLIO for ts in tss
        )

    # Occupied intervals: union of open-position [entry_ts, exit_ts) across
    # every PORTFOLIO combo ledger (single-position per combo) — the honest
    # proxy for "portfolio already full" given POC01's MAX_POSITIONS gate.
    occupied: list[tuple[int, int]] = []
    for (sym, _f, _d), tss in entries.items():
        if sym in PORTFOLIO:
            for rec in ledger_intervals[(sym, _f, _d)]:
                occupied.append(rec)
    occupied.sort()
    merged: list[list[int]] = []
    for s, e in occupied:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    import bisect
    starts = [s for s, _ in merged]

    def in_occupied(ts: int) -> bool:
        i = bisect.bisect_right(starts, ts) - 1
        return i >= 0 and ts < merged[i][1]

    port_all = portfolio_entries()
    port_open_window_ms = int(OCCUPANCY_HOURS * 3600 * 1000)

    # 5m close returns + vol profile
    import bisect

    results: dict[str, dict] = {}
    for cand in CANDIDATES:
        ds = datasets[cand]
        closes = {c.timestamp: c.close for c in ds.candles}
        ts_sorted = sorted(closes)
        rets = {
            t: (closes[ts_sorted[i + 1]] / closes[t] - 1.0)
            for i, t in enumerate(ts_sorted[:-1])
        }
        cand_keys = [k for k in entries if k[0] == cand]
        all_cand_entries = sorted(ts for k, tss in entries.items() if k[0] == cand for ts in tss)
        sig_count = len(all_cand_entries)
        # overlap: candidate entry within ±1 bar of ANY portfolio entry
        overlap = sum(1 for ts in all_cand_entries
                      if any(abs(ts - p) <= 5 * 60 * 1000 for p in port_all))
        # incremental: entry OUTSIDE all portfolio open-position intervals
        incremental_pos = sum(1 for ts in all_cand_entries if not in_occupied(ts))
        # incremental (looser proxy): no portfolio signal within +/- OCCUPANCY_HOURS
        incremental = 0
        for ts in all_cand_entries:
            i = bisect.bisect_left(port_all, ts - port_open_window_ms)
            j = bisect.bisect_right(port_all, ts + port_open_window_ms)
            if j - i == 0:
                incremental += 1
        # correlations vs each portfolio asset
        corr = {}
        for p in PORTFOLIO:
            pc = {c.timestamp: c.close for c in datasets[p].candles}
            common = sorted(set(rets) & set(pc))
            if len(common) < 100:
                corr[p] = None
                continue
            xs, ys = [], []
            for i, t in enumerate(common[:-1]):
                xs.append(rets[t])
                ys.append(pc[common[i + 1]] / pc[t] - 1.0)
            mx, my = statistics.fmean(xs), statistics.fmean(ys)
            cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / len(xs)
            vx = statistics.pvariance(xs)
            vy = statistics.pvariance(ys)
            corr[p] = round(cov / ((vx * vy) ** 0.5), 4) if vx > 0 and vy > 0 else None
        sig = [v for v in rets.values()]
        results[cand] = {
            "analysis_window": [start.isoformat(), cutoff.isoformat()],
            "signals_total": sig_count,
            "signals_per_day": round(sig_count / ANALYSIS_DAYS, 2),
            "by_family": {
                f"{fam}-{direction}": len(entries[(cand, fam, direction)])
                for fam in FAMILIES for direction in ("LONG", "SHORT")
                if entries.get((cand, fam, direction))
            },
            "overlap_with_portfolio_pct": round(overlap / sig_count * 100, 1) if sig_count else None,
            "incremental_outside_open_positions_pct": round(incremental_pos / sig_count * 100, 1) if sig_count else None,
            "incremental_no_nearby_signal_pct": round(incremental / sig_count * 100, 1) if sig_count else None,
            "return_correlation_5m": corr,
            "realized_vol_5m_pct": round(statistics.pstdev(sig) * 100, 4) if sig else None,
            "direction_concentration": {
                "LONG": sum(1 for k, tss in entries.items() if k[0] == cand and k[2] == "LONG" for _ in tss),
                "SHORT": sum(1 for k, tss in entries.items() if k[0] == cand and k[2] == "SHORT" for _ in tss),
            },
        }

    portfolio_summary = {
        sym: {
            "signals_total": sum(len(entries[(sym, f, d)]) for f in FAMILIES for d in ("LONG", "SHORT")),
            "signals_per_day": round(sum(len(entries[(sym, f, d)]) for f in FAMILIES for d in ("LONG", "SHORT")) / ANALYSIS_DAYS, 2),
        }
        for sym in PORTFOLIO
    }
    payload = {
        "schema_version": "asset-incremental-analysis-v1",
        "purpose": "OBSERVATIONAL Track-D evidence; no selection/promotion",
        "analysis_window": [start.isoformat(), cutoff.isoformat()],
        "window_overlap_disclosure": (
            "Overlaps previously defined EDGE-RESEARCH-002 confirmation/holdout "
            "and R1 holdout ranges. No EDGE/R1 candidate evaluated/consulted; "
            "no promotion decision produced. EDGE confirmation remains BLOCKED."
        ),
        "occupancy_proxy_hours": OCCUPANCY_HOURS,
        "portfolio_baseline": portfolio_summary,
        "candidates": results,
    }
    (OUT / "ASSET_INCREMENTAL_ANALYSIS.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["candidates"], indent=1)[:2000])
    print("portfolio:", json.dumps(portfolio_summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
