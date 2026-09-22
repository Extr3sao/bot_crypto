#!/usr/bin/env python3
"""H5-ORDERFLOW-IMBALANCE-CONTINUATION-01 — exactly-once economic execution runner.

Runs the H5 economic evaluation through the ResearchExecutionLedger flow:

    acquire -> STARTED (durable + fsync) -> load data -> features -> signals
    -> simulation -> metrics -> H5_EXECUTION_MARKER.json -> H5_RESULT.json
    -> ledger.finish_completed

Protocol (from H5_SPEC.json execution_protocol):
- Exactly one economic execution via ResearchExecutionLedger
- STARTED persisted + fsync'd BEFORE any economic work
- No performance statistic computed or observed before execution
- H5_EXECUTION_MARKER.json written before H5_RESULT.json
- No parameter tuning, no post-result changes

DO NOT tune H5 after observing any performance.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure src is on the path for imports
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.execution_ledger import (  # noqa: E402 - sys.path bootstrap must precede imports
    RunnerLedger,
)
from trading_bot.research.h1_regime_transition import (  # noqa: E402 - sys.path bootstrap must precede imports
    bootstrap_sharpe,
    max_drawdown_r,
    mc_dd95,
    permutation_p,
    profit_factor,
    simulate_proxy,
)
from trading_bot.research.h5_orderflow import (  # noqa: E402 - sys.path bootstrap must precede imports
    classify,
    compute_features,
    simulate_h5,
    summarize,
)

# ---- frozen constants (mirrored from H5_SPEC.json) ----
EXPERIMENT_ID = "H5-ORDERFLOW-IMBALANCE-CONTINUATION-01"
PREREG_COMMIT = "c426b35"
SPEC_SHA256 = "c743fba4a2a589dc1c3a15c7cd48b1b6ddf80255b8a157ea4f7ef19cc2f81023"
PROTOCOL_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "acquire": "atomic lock",
            "started_before_evaluation": True,
            "fsync": True,
            "marker_before_result": True,
            "exactly_once_ledger": True,
        },
        sort_keys=True,
    ).encode()
).hexdigest()

DATASET_DIR = ROOT / "docs" / "external-audit-01" / "h1-regime-transition-01" / "dataset"
ASSETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
OUTPUT_DIR = ROOT / "docs" / "external-audit-01" / "h5-orderflow-imbalance-01"
MARKER_PATH = OUTPUT_DIR / "H5_EXECUTION_MARKER.json"
RESULT_PATH = OUTPUT_DIR / "H5_RESULT.json"
COST_SCENARIOS_BPS = [0.0, 5.0, 10.0, 20.0, 40.0]

_SHIFT_SECONDS = 3_600_000  # 1h bar span in ms


def load_asset_data(asset: str) -> dict[str, list]:
    """Load frozen kline data for one asset from JSONL."""
    path = DATASET_DIR / f"{asset}_1h.jsonl"
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def parse_klines(rows: list[list]) -> dict[str, list]:
    """Parse 12-field klines into numpy-friendly arrays.

    Field mapping (Binance USDM klines):
    index 0: openTime
    index 1: open
    index 2: high
    index 3: low
    index 4: close
    index 5: volume
    index 6: closeTime
    index 7: quoteVolume
    index 8: numberOfTrades
    index 9: takerBuyBaseVolume
    index 10: takerBuyQuoteVolume
    index 11: ignore
    """
    import numpy as np

    n = len(rows)
    ts = np.zeros(n, dtype=np.int64)
    op = np.zeros(n)
    hi = np.zeros(n)
    lo = np.zeros(n)
    cl = np.zeros(n)
    volume = np.zeros(n)
    ntrades = np.zeros(n)
    taker_buy = np.zeros(n)

    for i, row in enumerate(rows):
        ts[i] = int(row[0])
        op[i] = float(row[1])
        hi[i] = float(row[2])
        lo[i] = float(row[3])
        cl[i] = float(row[4])
        volume[i] = float(row[5])
        # closeTime is row[6] but we derive it
        ntrades[i] = int(row[8])
        taker_buy[i] = float(row[9])

    return {
        "ts": ts,
        "op": op,
        "hi": hi,
        "lo": lo,
        "cl": cl,
        "volume": volume,
        "ntrades": ntrades,
        "taker_buy": taker_buy,
    }


def validate_data(data: dict[str, list], asset: str) -> list[str]:
    """Validate input data against H5 data contract (Track C)."""
    import numpy as np

    errors = []
    volume = data["volume"]
    ntrades = data["ntrades"]
    taker_buy = data["taker_buy"]
    ts = data["ts"]

    # volume >= 0
    if np.any(volume < 0):
        errors.append(f"{asset}: negative volume detected")

    # 0 <= takerBuyBaseVolume <= volume
    if np.any(taker_buy < 0) or np.any(taker_buy > volume):
        errors.append(f"{asset}: takerBuyBaseVolume out of bounds [0, volume]")

    # numberOfTrades >= 0
    if np.any(ntrades < 0):
        errors.append(f"{asset}: negative numberOfTrades")

    # timestamps monotonic
    if np.any(np.diff(ts) <= 0):
        errors.append(f"{asset}: non-monotonic timestamps")

    # no duplicates
    if len(set(ts.tolist())) != len(ts):
        errors.append(f"{asset}: duplicate timestamps")

    # no future timestamps (relative to now)
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    if np.any(ts > now_ms):
        errors.append(f"{asset}: future timestamps detected")

    return errors


def compute_orthogonality_diagnostics(
    h5_trades: list,
    proxy_trades: list,
    h1_trades: list,
) -> dict:
    """Compute orthogonality diagnostics (Track L) - diagnostic only."""
    import numpy as np

    result = {
        "h5_vs_roc_proxy": {},
        "h5_vs_h1": {},
        "h5_vs_h3": {},
    }

    # H5 vs ROC(24) proxy trades
    if h5_trades and proxy_trades:
        h5_entries = [t.entry_index for t in h5_trades]
        proxy_entries = [t.entry_index for t in proxy_trades]

        # Trade-time overlap
        overlap = 0
        for h_idx in h5_entries:
            if any(abs(h_idx - p_idx) <= 3 for p_idx in proxy_entries):
                overlap += 1
        overlap_ratio = overlap / len(h5_trades)

        # Daily PnL correlation
        def daily_r(trades):
            daily = {}
            for t in trades:
                day = t.exit_ts // 86_400_000
                daily[day] = daily.get(day, 0.0) + t.net_r
            return daily

        d1, d2 = daily_r(h5_trades), daily_r(proxy_trades)
        common = sorted(set(d1) & set(d2))
        corr = None
        if len(common) >= 30:
            xs = [d1[d] for d in common]
            ys = [d2[d] for d in common]
            mx, my = np.mean(xs), np.mean(ys)
            cov = np.sum((xs - mx) * (ys - my))
            sx, sy = np.std(xs), np.std(ys)
            if sx > 0 and sy > 0:
                corr = float(cov / (sx * sy))

        result["h5_vs_roc_proxy"] = {
            "trade_time_overlap": float(overlap_ratio),
            "daily_pnl_correlation": corr,
            "common_days": len(common),
            "redundant": overlap_ratio > 0.6 and corr is not None and corr > 0.7,
        }

    # H5 vs H1 (if H1 trades available from frozen dataset)
    if h1_trades:
        h5_entries = [t.entry_index for t in h5_trades]
        h1_entries = [t.entry_index for t in h1_trades]
        overlap = 0
        for h_idx in h5_entries:
            if any(abs(h_idx - h1_idx) <= 3 for h1_idx in h1_entries):
                overlap += 1
        overlap_ratio = overlap / len(h5_trades) if h5_trades else 0

        d1 = {t.exit_ts // 86_400_000: t.net_r for t in h5_trades}
        d2 = {t.exit_ts // 86_400_000: t.net_r for t in h1_trades}
        common = sorted(set(d1) & set(d2))
        corr = None
        if len(common) >= 30:
            xs = [d1[d] for d in common]
            ys = [d2[d] for d in common]
            mx, my = np.mean(xs), np.mean(ys)
            cov = np.sum((np.array(xs) - mx) * (np.array(ys) - my))
            sx, sy = np.std(xs), np.std(ys)
            if sx > 0 and sy > 0:
                corr = float(cov / (sx * sy))

        result["h5_vs_h1"] = {
            "trade_time_overlap": float(overlap_ratio),
            "daily_pnl_correlation": corr,
            "common_days": len(common),
            "redundant": overlap_ratio > 0.6 and corr is not None and corr > 0.7,
        }

    return result


def run_h5_evaluation() -> dict:
    """Run the full H5 economic evaluation.

    Returns the evaluation result dict.
    """
    import numpy as np

    all_trades = []
    all_errors = []
    data_fingerprints = {}
    per_asset_results = {}

    for asset in ASSETS:
        print(f"Loading {asset} data...")
        rows = load_asset_data(asset)

        # Compute fingerprint
        fp = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
        data_fingerprints[asset] = fp

        print(f"Validating {asset} data...")
        data = parse_klines(rows)
        errors = validate_data(data, asset)
        if errors:
            all_errors.extend(errors)
            print(f"  WARNING: {asset} validation issues: {errors}")
            # Continue anyway - H5 should handle invalid data gracefully

        n_bars = len(data["ts"])
        print(f"  {asset}: {n_bars} bars, fingerprint={fp[:16]}...")

        print(f"  Computing features for {asset}...")
        feat = compute_features(data["volume"], data["ntrades"], data["taker_buy"])

        print(f"  Simulating {asset}...")
        trades, skipped, blocked = simulate_h5(
            data["ts"],
            data["op"],
            data["hi"],
            data["lo"],
            data["cl"],
            data["volume"],
            data["ntrades"],
            data["taker_buy"],
            asset,
            feat=feat,
        )
        print(
            f"  {asset}: {len(trades)} trades, {skipped} skipped (incomplete), {blocked} blocked (cooldown)"
        )

        all_trades.extend(trades)
        per_asset_results[asset] = {
            "n_bars": n_bars,
            "n_trades": len(trades),
            "n_skipped_incomplete": skipped,
            "n_blocked_cooldown": blocked,
            "data_fingerprint": fp,
        }

    # Pool all trades
    print(f"\nTotal trades across all assets: {len(all_trades)}")

    # Summarize
    print("Computing summary metrics...")
    summary = summarize(all_trades)

    # Cost scenarios
    print("Computing cost scenarios...")
    cost_table = []
    for bps in COST_SCENARIOS_BPS:
        net_r = []
        for t in all_trades:
            scale = bps / 10.0  # COST_RT_BPS = 10
            net_r.append(t.gross_r - t.cost_r * scale)
        cost_table.append(
            {
                "bps": bps,
                "N": len(net_r),
                "net_expectancy_R": float(np.mean(net_r)) if net_r else 0.0,
                "PF_net": profit_factor(net_r) if net_r else 0.0,
            }
        )

    # Bootstrap Sharpe
    net_rs = [t.net_r for t in all_trades]
    if len(net_rs) >= 2:
        _s, _lo, _hi, _p_gt0 = bootstrap_sharpe(net_rs)
        perm_p = permutation_p(net_rs)
        max_drawdown_r(net_rs)
        mc_dd95_val = mc_dd95(net_rs)
    else:
        _s, _lo, _hi, _p_gt0 = 0.0, 0.0, 0.0, 0.0
        perm_p = 1.0
        mc_dd95_val = 0.0

    # Direction and asset cells
    long_trades = [t for t in all_trades if t.direction == "LONG"]
    short_trades = [t for t in all_trades if t.direction == "SHORT"]
    direction_cells = [len(long_trades), len(short_trades)]
    asset_cells = [per_asset_results[a]["n_trades"] for a in ASSETS]

    # Classification
    result_class = classify(summary, direction_cells, asset_cells)

    # Diagnostics per asset/direction
    diagnostics = {}
    for asset in ASSETS:
        asset_trades = [t for t in all_trades if t.asset == asset]
        diagnostics[asset] = {
            "N": len(asset_trades),
            "gross_expectancy_R": float(np.mean([t.gross_r for t in asset_trades]))
            if asset_trades
            else 0.0,
            "net_expectancy_R": float(np.mean([t.net_r for t in asset_trades]))
            if asset_trades
            else 0.0,
        }
        for direction in ["LONG", "SHORT"]:
            dt = [t for t in asset_trades if t.direction == direction]
            diagnostics[f"{asset}_{direction}"] = {
                "N": len(dt),
                "net_expectancy_R": float(np.mean([t.net_r for t in dt])) if dt else 0.0,
            }

    # Build result
    result = {
        "experiment_id": EXPERIMENT_ID,
        "result_class": result_class,
        "prereg_commit": PREREG_COMMIT,
        "spec_sha256": SPEC_SHA256,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        # Data
        "assets": ASSETS,
        "data_fingerprints": data_fingerprints,
        "per_asset": per_asset_results,
        # Trades
        "total_trades": len(all_trades),
        "direction_cells": {
            "LONG": len(long_trades),
            "SHORT": len(short_trades),
        },
        "asset_cells": {a: per_asset_results[a]["n_trades"] for a in ASSETS},
        # Metrics
        "metrics": {
            "N": summary.get("N", 0),
            "gross_expectancy_R": summary.get("gross_expectancy_R", 0.0),
            "net_expectancy_R": summary.get("net_expectancy_R", 0.0),
            "PF_gross": summary.get("PF_gross", 0.0),
            "PF_net": summary.get("PF_net", 0.0),
            "Sharpe": summary.get("Sharpe", 0.0),
            "Sharpe_CI95": summary.get("Sharpe_CI95", [0.0, 0.0]),
            "P_Sharpe_gt_0": summary.get("P_Sharpe_gt_0", 0.0),
            "permutation_p": perm_p,
            "max_drawdown_R": summary.get("max_drawdown_R", 0.0),
            "MC_DD95_R": mc_dd95_val,
            "cost_drag_R": summary.get("cost_drag_R", 0.0),
            "halves": summary.get("halves", []),
            "thirds": summary.get("thirds", []),
            "walk_forward_last_third_net_R": summary.get("walk_forward_last_third_net_R", 0.0),
            "mean_holding_bars": summary.get("mean_holding_bars", 0.0),
            "win_rate": summary.get("win_rate", 0.0),
            "wins": summary.get("wins", 0),
            "losses": summary.get("losses", 0),
        },
        # Cost scenarios
        "cost_scenarios": cost_table,
        # Diagnostics (report-only, not for decision)
        "diagnostics": diagnostics,
        # Validation
        "validation_errors": all_errors,
    }

    # Add orthogonality diagnostics (if we have proxy/H1 trades)
    # For now, compute simple proxy trades from the data for comparison
    print("\nComputing orthogonality diagnostics...")
    proxy_trades_all = []
    for asset in ASSETS:
        rows = load_asset_data(asset)
        data = parse_klines(rows)
        import numpy as np

        _proxy_trades, _ = (
            simulate_proxy.__wrapped__(  # Access wrapped function
                None,  # candles not needed for this call pattern
                asset,
            )
            if False
            else ([], 0)
        )  # Placeholder - need proper OHLCV tuple
        # Actually, let's compute proxy trades properly
        from trading_bot.market_data.types import OHLCV

        candles = tuple(
            OHLCV(
                symbol=asset,
                timestamp=int(data["ts"][i]),
                open=float(data["op"][i]),
                high=float(data["hi"][i]),
                low=float(data["lo"][i]),
                close=float(data["cl"][i]),
                volume=float(data["volume"][i]),
            )
            for i in range(len(data["ts"]))
        )
        from trading_bot.research.h1_regime_transition import simulate_proxy as h1_simulate_proxy

        asset_proxy = h1_simulate_proxy(candles, asset)
        proxy_trades_all.extend(asset_proxy)

    # Compute H5 vs proxy orthogonality
    if all_trades and proxy_trades_all:
        h5_entries = [t.entry_index for t in all_trades]
        proxy_entries = [t.entry_index for t in proxy_trades_all]
        overlap = sum(1 for h in h5_entries if any(abs(h - p) <= 3 for p in proxy_entries))
        overlap_ratio = overlap / len(all_trades)

        def daily_r(trades, prefix=""):
            daily = {}
            for t in trades:
                day = t.exit_ts // 86_400_000
                daily[day] = daily.get(day, 0.0) + t.net_r
            return daily

        d_h5 = daily_r(all_trades)
        d_proxy = daily_r(proxy_trades_all)
        common = sorted(set(d_h5) & set(d_proxy))
        corr = None
        if len(common) >= 30:
            import numpy as np

            xs = np.array([d_h5[d] for d in common])
            ys = np.array([d_proxy[d] for d in common])
            corr = float(np.corrcoef(xs, ys)[0, 1])  # proper Pearson correlation

        result["orthogonality_vs_roc_proxy"] = {
            "trade_time_overlap": float(overlap_ratio),
            "daily_pnl_correlation": corr,
            "common_days": len(common),
            "redundant": overlap_ratio > 0.6 and corr is not None and corr > 0.7,
        }

    # H3 relative-value trades for orthogonality (if available)
    # For now, note that H3 is DISCOVERY_FAIL and we can compute overlap from stored results
    h3_result_path = ROOT / "docs" / "external-audit-01" / "h3-relative-value-01" / "H3_RESULT.json"
    if h3_result_path.exists():
        with open(h3_result_path) as f:
            h3_result = json.load(f)
        # H3 trades stored in result
        h3_trades = h3_result.get("trades", [])
        if h3_trades and all_trades:
            h5_entries = [t.entry_index for t in all_trades]
            h3_entries = [t.get("entry_index", t.get("entry_index", 0)) for t in h3_trades]
            overlap = sum(1 for h in h5_entries if any(abs(h - h3) <= 3 for h3 in h3_entries))
            overlap_ratio = overlap / len(all_trades)

            d_h5 = {t.exit_ts // 86_400_000: t.net_r for t in all_trades}
            d_h3 = {
                t.get("exit_ts", t.get("exit_ts", 0)) // 86_400_000: t.get("net_r", 0.0)
                for t in h3_trades
            }
            common = sorted(set(d_h5) & set(d_h3))
            corr = None
            if len(common) >= 30:
                import numpy as np

                xs = np.array([d_h5[d] for d in common])
                ys = np.array([d_h3[d] for d in common])
                corr = float(np.corrcoef(xs, ys)[0, 1])

            result["orthogonality_vs_h3"] = {
                "trade_time_overlap": float(overlap_ratio),
                "daily_pnl_correlation": corr,
                "common_days": len(common),
                "redundant": overlap_ratio > 0.6 and corr is not None and corr > 0.7,
            }

    return result


def main() -> int:
    """Main entry point - runs H5 exactly once through the ledger."""
    print(f"\n{'=' * 70}")
    print("H5-ORDERFLOW-IMBALANCE-CONTINUATION-01")
    print("Exactly-Once Economic Execution")
    print(f"Prereg commit: {PREREG_COMMIT}")
    print(f"Spec SHA256: {SPEC_SHA256}")
    print(f"{'=' * 70}\n")

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Create ledger and acquire authority
    print("Acquiring execution authority...")
    ledger_dir = OUTPUT_DIR / "execution_ledger"
    runner = RunnerLedger(ledger_dir, EXPERIMENT_ID)

    try:
        attempt_id = runner.begin(
            spec_sha256=SPEC_SHA256,
            dataset_sha256="",  # Will be filled from actual data
            prereg_commit=PREREG_COMMIT,
            protocol_sha256=PROTOCOL_SHA256,
            code_commit="",  # Filled below
        )
        print(f"  Acquired: {attempt_id}")
    except RuntimeError as e:
        print(f"  FAILED to acquire: {e}")
        return 1

    # Compute code commit hash
    code_commit = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]

    try:
        # ---- Economic work begins HERE (after STARTED is durable) ----
        print("\n--- Economic Evaluation ---\n")

        result = run_h5_evaluation()

        # Compute dataset fingerprint (aggregate of all asset files)
        ds_fp_parts = []
        for asset in ASSETS:
            path = DATASET_DIR / f"{asset}_1h.jsonl"
            ds_fp_parts.append(f"{asset}={hashlib.sha256(path.read_bytes()).hexdigest()[:16]}")
        dataset_sha256 = hashlib.sha256("|".join(ds_fp_parts).encode()).hexdigest()

        # Update result with code commit and dataset fingerprint
        result["code_commit"] = code_commit
        result["dataset_sha256"] = dataset_sha256

        print("\n--- Result ---")
        print(f"Result class: {result['result_class']}")
        print(f"Total trades: {result['total_trades']}")
        print(f"Net expectancy R: {result['metrics']['net_expectancy_R']:.4f}")
        print(f"PF net: {result['metrics']['PF_net']:.4f}")
        print(f"Sharpe: {result['metrics']['Sharpe']:.4f}")
        print(f"P(Sharpe>0): {result['metrics']['P_Sharpe_gt_0']:.4f}")
        print(f"Permutation p: {result['metrics']['permutation_p']:.4f}")
        print(f"Max DD: {result['metrics']['max_drawdown_R']:.4f}")
        print(f"MC DD95: {result['metrics']['MC_DD95_R']:.4f}")

        # Write marker FIRST (exactly-once protocol)
        print("\nWriting execution marker...")
        marker = {
            "experiment_id": EXPERIMENT_ID,
            "attempt_id": attempt_id,
            "started_at": result.get("_started_at", ""),
            "completed_at": datetime.now(UTC).isoformat(),
            "result_class": result["result_class"],
            "total_trades": result["total_trades"],
            "marker_version": "1.0.0",
        }
        with open(MARKER_PATH, "w", encoding="utf-8") as f:
            json.dump(marker, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        print(f"  Written: {MARKER_PATH}")

        # Write result SECOND
        print("Writing result...")
        result_json = json.dumps(result, indent=2, sort_keys=True)
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            f.write(result_json)
            f.flush()
            os.fsync(f.fileno())

        # Compute result SHA256 for ledger
        result_sha = hashlib.sha256(result_json.encode()).hexdigest()
        print(f"  Result SHA256: {result_sha[:16]}...")
        print(f"  Written: {RESULT_PATH}")

        # Finish in ledger
        print("Finishing ledger entry...")
        runner.complete(RESULT_PATH)
        print(f"  Completed: {attempt_id}")

        print(f"\n{'=' * 70}")
        print("H5 EXECUTION COMPLETE")
        print(f"Result: {result['result_class']}")
        print(f"{'=' * 70}\n")

        return 0

    except Exception as e:
        print(f"\nERROR during economic evaluation: {e}")
        import traceback

        traceback.print_exc()

        # Record failure in ledger
        runner.fail(f"economic evaluation failed: {e}")
        print(f"  Failed: {attempt_id}")

        return 1


if __name__ == "__main__":
    sys.exit(main())
