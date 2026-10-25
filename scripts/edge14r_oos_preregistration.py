"""edge14r_oos_preregistration — freeze the protocol, then capture the holdout.

The order is the point: this script writes and hashes the preregistration **before** it
touches the network, so its timestamp precedes every row of the data it later captures.
A preregistration written after the capture is a description, not a commitment.

Nothing here selects anything. The captured slice is written to this package's scratch
space, marked `OOS_RESERVED`, and no routine in this project is allowed to read it when
choosing a strategy.

    python scripts/edge14r_oos_preregistration.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-014R"
FROZEN = OUT / "scratch" / "PAPER_REPLAY_BARS.jsonl"
PREREG = OUT / "OOS_PREREGISTRATION.json"
CAPTURE = OUT / "OOS_CAPTURE_MANIFEST.json"
SLICE = OUT / "scratch" / "OOS_SLICE_1H.jsonl"

#: The frozen corpus is exhausted for selection purposes: it has been used for engine
#: comparison and for the candidate experiments, so it can never be a holdout again.
EXHAUSTED_WINDOW = {
    "start_utc": "2026-09-05T00:00:00Z",
    "end_utc": "2026-10-16T15:00:00Z",
    "last_bar_closed_utc": "2026-10-16T14:00:00Z",
}

PROTOCOL: dict[str, Any] = {
    "schema_version": "EDGE14R_OOS_PREREGISTRATION_V1",
    "work_package": "WP-EDGE-14R/P3",
    "kind": "PROSPECTIVE_HOLDOUT",
    "why_a_new_slice_is_needed": (
        "the frozen corpus has been read by candidate experiments and by the engine "
        "comparison, so any further scoring on it is in-sample. Mechanical parity between "
        "engines can and has been tested on historical bars; economic inference requires a "
        "slice that no decision has touched"
    ),
    "strategies_and_parameters": {
        "family": "ema_crossover",
        "parameters": {"fast": 12, "slow": 26},
        "parameter_source": "frozen before capture; no fitting, no search, no walk-forward",
        "admission_gate": "the committed strategy_admission ledger, unchanged",
    },
    "instruments_and_timeframes": {
        "symbols": ["BTC/USDT", "ETH/USDT"],
        "timeframe": "1h",
        "venue": "binance (public OHLCV through ccxt, read-only, no credentials)",
    },
    "costs": {
        "fees_bps_per_side": 10.0,
        "spread_bps_per_round_trip": 0.0,
        "slippage_bps_per_side": 0.0,
        "why": (
            "the same declared parity inputs the engine comparison used, so the holdout is "
            "scored under the same model rather than a kinder one; spread and slippage are "
            "held at zero here because they are model inputs and the paper broker's 1 bps "
            "per side is reported separately"
        ),
    },
    "entry_and_exit_rules": {
        "entry": "long while ema(12) > ema(26) on the previous closed 1h bar; fill at the open of the next bar",
        "exit": "flat when ema(12) < ema(26) on a closed bar; fill at the open of the next bar",
        "open_position_at_window_end": "force-closed at the final bar's open on both engines",
    },
    "hypothesis": (
        "H0: this rule's net expectancy per trade is <= 0 after the declared costs. "
        "H1: it is > 0. The measurement window is exhausted at 2026-10-16T15:00:00Z, so "
        "every bar at or after that instant is prospective with respect to it"
    ),
    "acceptance_thresholds_frozen_now": {
        "min_closed_trades_per_strategy": 200,
        "net_expectancy_bps_per_trade_min": 0.0,
        "profit_factor_min": 1.2,
        "max_drawdown_bps_max": 2000.0,
        "cost_sensitivity_must_stay_positive_at_fees_bps_per_side": 15.0,
        "notes": (
            "a slice that has not reached 200 closed trades cannot accept or reject "
            "anything, and is reported as ACCRUING rather than as a verdict"
        ),
    },
    "comparator_CURRENT": (
        "the runtime as it stands: no strategy admitted, no trades, flat equity. A "
        "candidate must beat that flat line net of the declared costs, not merely exist"
    ),
    "reserved": {
        "selection_may_read": False,
        "state_until_thresholds_are_met": "OOS_ACCRUING",
        "routine_that_may_score_it": "scripts/edge14r_oos_score.py (not run by this script)",
    },
}


def _capture(symbols: list[str], start_ms: int, end_ms: int, exchange_id: str) -> dict[str, Any]:
    import ccxt

    exchange = getattr(ccxt, exchange_id)()
    out: dict[str, list[list[float]]] = {}
    for symbol in symbols:
        raw = exchange.fetch_ohlcv(symbol, "1h", since=start_ms, limit=1000)
        rows = [
            [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
            for r in (raw or [])
            if start_ms <= int(r[0]) < end_ms
        ]
        out[symbol] = rows
        time.sleep(exchange.rateLimit / 1000.0)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-14R OOS preregistration")
    parser.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    parser.add_argument("--exchange", default="binance")
    args = parser.parse_args()

    frozen_sha = hashlib.sha256(FROZEN.read_bytes()).hexdigest() if FROZEN.is_file() else None

    # 1) freeze the protocol, and hash the file, before any capture happens
    preregistration = {
        **PROTOCOL,
        "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "exhausted_window": EXHAUSTED_WINDOW,
        "exhausted_corpus": {"path": str(FROZEN), "sha256": frozen_sha},
        "prospective_boundary_ms": 1_792_162_800_000,
    }
    PREREG.write_text(
        json.dumps(preregistration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    prereg_sha = hashlib.sha256(PREREG.read_bytes()).hexdigest()

    md = f"""# WP-EDGE-14R/P3 — prospective holdout preregistration

*Frozen at `{preregistration["frozen_at_utc"]}`, before any row of the holdout was
captured. Its sha256 is `{prereg_sha}`.*

## Why a new slice

The frozen corpus (`sha256:{str(frozen_sha)[:16]}…`, {EXHAUSTED_WINDOW["start_utc"]} →
{EXHAUSTED_WINDOW["end_utc"]}) has been read by the candidate experiments and by the
engine comparison. Any further scoring on it is in-sample. Mechanical parity between
engines can and has been tested on historical bars; **economic inference needs a slice no
decision has touched**.

## Frozen now

| axis | value |
| --- | --- |
| family | `{PROTOCOL["strategies_and_parameters"]["family"]}` |
| parameters | fast={PROTOCOL["strategies_and_parameters"]["parameters"]["fast"]}, slow={PROTOCOL["strategies_and_parameters"]["parameters"]["slow"]} |
| parameter source | {PROTOCOL["strategies_and_parameters"]["parameter_source"]} |
| instruments | {", ".join(PROTOCOL["instruments_and_timeframes"]["symbols"])} |
| timeframe | {PROTOCOL["instruments_and_timeframes"]["timeframe"]} |
| fees | {PROTOCOL["costs"]["fees_bps_per_side"]} bps per side |
| spread | {PROTOCOL["costs"]["spread_bps_per_round_trip"]} bps per round trip |
| slippage | {PROTOCOL["costs"]["slippage_bps_per_side"]} bps per side |
| entry | {PROTOCOL["entry_and_exit_rules"]["entry"]} |
| exit | {PROTOCOL["entry_and_exit_rules"]["exit"]} |
| hypothesis | {PROTOCOL["hypothesis"]} |
| comparator | {PROTOCOL["comparator_CURRENT"]} |

## Acceptance thresholds, frozen before the data exists

| threshold | value |
| --- | ---: |
| closed trades per strategy | >= {PROTOCOL["acceptance_thresholds_frozen_now"]["min_closed_trades_per_strategy"]} |
| net expectancy | > {PROTOCOL["acceptance_thresholds_frozen_now"]["net_expectancy_bps_per_trade_min"]} bps per trade |
| profit factor | >= {PROTOCOL["acceptance_thresholds_frozen_now"]["profit_factor_min"]} |
| max drawdown | <= {PROTOCOL["acceptance_thresholds_frozen_now"]["max_drawdown_bps_max"]} bps |
| cost sensitivity | stays positive at {PROTOCOL["acceptance_thresholds_frozen_now"]["cost_sensitivity_must_stay_positive_at_fees_bps_per_side"]} bps per side |

## Reservation

The holdout is `OOS_RESERVED`: **selection never reads it**. Until it reaches the
thresholds above it is `OOS_ACCRUING`, and a slice that has not reached them cannot accept
or reject anything.
"""
    (OUT / "OOS_PREREGISTRATION.md").write_text(md, encoding="utf-8")

    # 2) only now capture the slice
    boundary = int(preregistration["prospective_boundary_ms"])
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Start one bar after the boundary: the bar that *starts* at the boundary was
    # already forming while the exhausted window was being read, so it is not
    # prospective. Only later bars are.
    capture_from = boundary + 3_600_000
    now_ms = int(time.time() * 1000)
    end_ms = (now_ms // 3_600_000) * 3_600_000
    bars = _capture(symbols, capture_from, end_ms, args.exchange)

    SLICE.parent.mkdir(parents=True, exist_ok=True)
    with SLICE.open("w", encoding="utf-8") as handle:
        for symbol in symbols:
            for row in bars[symbol]:
                handle.write(
                    json.dumps(
                        {
                            "symbol": symbol,
                            "timestamp": row[0],
                            "open": row[1],
                            "high": row[2],
                            "low": row[3],
                            "close": row[4],
                            "volume": row[5],
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
    slice_bytes = SLICE.stat().st_size
    slice_sha = hashlib.sha256(SLICE.read_bytes()).hexdigest()

    manifest = {
        "schema_version": "EDGE14R_OOS_CAPTURE_V1",
        "work_package": "WP-EDGE-14R/P3",
        "preregistration": {
            "path": str(PREREG),
            "sha256": prereg_sha,
            "frozen_at_utc": preregistration["frozen_at_utc"],
        },
        "captured_at_utc": captured_at,
        "order_check": (
            "preregistration_frozen_at_utc < captured_at_utc: "
            + str(preregistration["frozen_at_utc"] < captured_at)
        ),
        "prospective_boundary_ms": boundary,
        "capture_from_ms": capture_from,
        "capture_from_reading": (
            "one bar after the boundary: the bar starting at the boundary was already "
            "forming while the exhausted window was in use, so it is excluded"
        ),
        "slice_path": str(SLICE),
        "slice_sha256": slice_sha,
        "slice_bytes": slice_bytes,
        "state": "OOS_ACCRUING",
        "symbols": {
            symbol: {
                "bars": len(bars[symbol]),
                "first_ms": bars[symbol][0][0] if bars[symbol] else None,
                "last_ms": bars[symbol][-1][0] if bars[symbol] else None,
            }
            for symbol in symbols
        },
        "selection_has_read_this_slice": False,
        "scoring_run": False,
        "reading": (
            "this is the first slice of a prospective holdout and it is small by "
            "construction: it starts at the instant the exhausted window ends. It cannot "
            "accept or reject anything yet, and no routine in this project selects on it"
        ),
    }
    CAPTURE.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    total = sum(len(v) for v in bars.values())
    print(
        f"[oos] preregistration frozen at {preregistration['frozen_at_utc']} (sha {prereg_sha[:16]})"
    )
    print(f"[oos] captured {total} bars at {captured_at} -> state OOS_ACCRUING")
    for symbol in symbols:
        rows = bars[symbol]
        print(f"[oos]   {symbol}: {len(rows)} bars")
    print(
        f"[oos] threshold to leave ACCRUING: "
        f"{PROTOCOL['acceptance_thresholds_frozen_now']['min_closed_trades_per_strategy']} closed trades"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
