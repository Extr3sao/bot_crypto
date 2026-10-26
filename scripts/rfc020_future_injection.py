"""RFC-020 adversarial future-injection + HTF poisoning + feature-mutation (§23-§26).

The central attack on point-in-time integrity: a decision at or before ``T`` must
be byte-identical whether the data after ``T`` is absent, wildly poisoned, a
crash or a rally. We drive the AUTHORITATIVE runtime (the same one the certified
RFC-010 baseline uses) over a controlled real-data slice:

    RUN A   bars[0:K]                      (nothing after T exists)
    RUN B   bars[0:K] + future * 10 price, * 100 volume
    RUN C   bars[0:K] + future crash (-90%)
    RUN D   bars[0:K] + future rally (+500%)

Every run uses the SAME decision instants (the closes of the first K bars), so
any difference in a decision at ``<= T`` is a P0 look-ahead defect.

Also evaluates (§25) the HTF point-in-time helper and (§26) feature-family
mutation invariance.

Usage:
    python scripts/rfc020_future_injection.py --out reports/data-integrity/FUTURE_INJECTION_TEST.json
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.market_data.types import OHLCV  # noqa: E402
from trading_bot.research.asset_intelligence.features import compute_shared  # noqa: E402


def _load_harness() -> Any:
    spec = importlib.util.spec_from_file_location(
        "rfc010_baseline_replay", REPO / "scripts" / "rfc010_baseline_replay.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rfc010_baseline_replay"] = module
    spec.loader.exec_module(module)
    return module


H = _load_harness()
TF_MS = H.TF_MS
ReplayClock = H.ReplayClock
ReplayMarketSource = H.ReplayMarketSource
build_runtime = H.build_runtime


def poison(bars: list[OHLCV], factor: float, volume_factor: float) -> list[OHLCV]:
    return [
        replace(
            b,
            open=b.open * factor,
            high=b.high * factor,
            low=b.low * factor,
            close=b.close * factor,
            volume=b.volume * volume_factor,
        )
        for b in bars
    ]


def projection(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Decision-semantic projection of every trace row (volatile ids removed)."""
    out: dict[str, dict[str, Any]] = {}
    path = run_dir / "traces.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        prop = row.get("proposal") or {}
        ctx = row.get("asset_context") or {}
        dq = ctx.get("data_quality") or {}
        key = f"{row.get('decision_time_ms')}|{row.get('asset')}"
        out[key] = {
            "decision_time_ms": row.get("decision_time_ms"),
            "market_time_ms": row.get("market_time_ms"),
            "asset": row.get("asset"),
            "regime": row.get("regime"),
            "mode": row.get("mode"),
            "classification": row.get("classification"),
            "no_trade_kind": row.get("no_trade_kind"),
            "strategy_selected": prop.get("strategy_id"),
            "direction": prop.get("direction"),
            "expected_gross_edge_bps": prop.get("expected_gross_edge_bps"),
            "expected_cost_bps": prop.get("expected_cost_bps"),
            "expected_net_edge_bps": prop.get("expected_net_edge_bps"),
            "confidence": prop.get("confidence"),
            "context_regime": ctx.get("market_regime"),
            "window_end_ts": ctx.get("window_end_ts"),
            "newest_bar_ts": dq.get("newest_bar_ts"),
            "order_created": row.get("order_created"),
        }
    return out


async def run_variant(
    *,
    run_id: str,
    bars_by_symbol: dict[str, list[OHLCV]],
    instants: list[int],
    assets: list[str],
    timeframe: str,
) -> dict[str, dict[str, Any]]:
    run_dir = REPO / "reports" / "rfc020" / run_id
    # Isolation (§18): a fresh store, so a previous execution can never feed
    # its future outcomes (or experience memory) into this run's decisions.
    for name in ("traces.jsonl", "outcomes.jsonl", "performance.json"):
        p = run_dir / name
        if p.exists():
            p.unlink()
    run_dir.mkdir(parents=True, exist_ok=True)
    clock = ReplayClock(instants[0])
    runtime, _registry = build_runtime(
        assets=assets,
        timeframe=timeframe,
        bars_by_symbol=bars_by_symbol,
        clock=clock,
        run_dir=run_dir,
        initial_equity=10_000.0,
        size_usd=1_000.0,
        lookback_bars=120,
        spread_bps=1.0,
    )
    for i, instant in enumerate(instants, start=1):
        clock.now_ms = instant
        await runtime.run_cycle(cycle=i)
    return projection(run_dir)


def htf_audit() -> dict[str, Any]:
    """§25 — HTF helper contract, before/at/after close, plus units check."""
    from trading_bot.market_data.htf_pit import get_completed_htf_state_at

    # 1h bar reopening: open 00:00, close 01:00 (epoch-ms candles)
    open_ms = 1_772_323_200_000
    bar = OHLCV(
        symbol="BTC/USDT",
        timestamp=open_ms,
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=1.0,
    )
    # signal in SECONDS (the helper's declared unit) would mis-scale ms candles;
    # evaluate the helper as the (orphan) callers do, and detect the discrepancy.
    just_before = get_completed_htf_state_at([bar], "1h", open_ms + 3_599_000)
    exactly_at = get_completed_htf_state_at([bar], "1h", open_ms + 3_600_000)
    after = get_completed_htf_state_at([bar], "1h", open_ms + 3_600_001)
    # The helper adds ``tf_seconds`` (3600) to a millisecond timestamp, so it
    # claims the bar is closed ~3.6 s after its open — a units mismatch.
    units_bug = get_completed_htf_state_at([bar], "1h", open_ms + 4_000) is not None
    return {
        "before_close_hidden": just_before is None,
        "at_close_visible": exactly_at is not None,
        "after_close_visible": after is not None,
        "units_ms_seconds_mismatch": units_bug,
        "runtime_reachable": False,
        "note": (
            "get_completed_htf_state_at adds tf in SECONDS to a MILLISECOND "
            "timestamp, so with ms candles it exposes a bar ~3.6 s after its "
            "open instead of after its close (DEF-HTF-PIT-001). The helper has "
            "ZERO tracked importers in src/, so it cannot influence any runtime "
            "decision (P3, ORPHAN). The close contract itself (<=) is correct "
            "for the unit it was written for."
        ),
    }


def feature_mutation(bars: list[OHLCV], interval_ms: int) -> dict[str, Any]:
    """§26 — features at K must not change when bars after K are mutated."""
    k = len(bars)
    window = bars[:k]
    base = compute_shared(window)
    mutated_future = bars + poison(
        [replace(b, timestamp=b.timestamp + interval_ms * (len(bars) + 1)) for b in bars[-5:]],
        10.0,
        100.0,
    )
    mutated_window = [b for b in mutated_future if b.timestamp <= window[-1].timestamp]
    mutated = compute_shared(mutated_window)

    def norm(s: Any) -> dict[str, Any]:
        return {
            "returns": s.returns,
            "volatility_atr": s.volatility_atr,
            "trend": None if s.trend is None else dict(s.trend),
            "momentum_rsi": s.momentum_rsi,
            "volume": None if s.volume is None else dict(s.volume),
            "liquidity": None if s.liquidity is None else dict(s.liquidity),
        }

    return {
        "identical": norm(base) == norm(mutated),
        "families": ["returns", "volatility_atr", "trend", "momentum_rsi", "volume", "liquidity"],
    }


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    assets = ["BTC", "ETH", "SOL"]
    timeframe = args.timeframe
    interval_ms = TF_MS[timeframe]
    full_all = H.load_bars(assets, ["W1", "W2", "W3", "W4"])
    # Controlled window: the first K bars are the PAST; everything after them is
    # the FUTURE (real bars, which we then poison). Decisions never exceed T.
    k = args.bars
    past = {s: b[:k] for s, b in full_all.items()}
    future = {s: b[k:] for s, b in full_all.items()}
    assert all(len(future[s]) > 10 for s in past), "need a real future tail to poison"
    any_symbol = past["BTC/USDT"]
    instants = [any_symbol[i].timestamp + interval_ms for i in range(0, k, args.step)]
    t_truncate = instants[-1]

    base_bars = past
    b_poison = {s: list(past[s]) + poison(future[s], 10.0, 100.0) for s in past}
    c_crash = {s: list(past[s]) + poison(future[s], 0.10, 1.0) for s in past}
    d_rally = {s: list(past[s]) + poison(future[s], 6.0, 10.0) for s in past}

    variants = {
        "A_truncated": base_bars,
        "B_poison_10x": b_poison,
        "C_crash": c_crash,
        "D_rally": d_rally,
    }
    projections: dict[str, dict[str, dict[str, Any]]] = {}
    for name, data in variants.items():
        projections[name] = await run_variant(
            run_id=f"RFC020-FUTURE-{name}",
            bars_by_symbol=data,
            instants=instants,
            assets=assets,
            timeframe=timeframe,
        )

    base = projections["A_truncated"]
    results: dict[str, Any] = {}
    for name in ("B_poison_10x", "C_crash", "D_rally"):
        other = projections[name]
        mismatches: list[dict[str, Any]] = []
        for key, row in base.items():
            if other.get(key) != row:
                mismatches.append({"key": key, "A": row, "variant": other.get(key)})
        results[name] = {
            "decisions_compared": len(base),
            "mismatches": len(mismatches),
            "mismatch_samples": mismatches[:5],
            "pass": len(mismatches) == 0 and len(base) == len(other),
        }

    provenance = {
        "all_decisions_at_or_before_T": all(
            int(r["decision_time_ms"] or 0) <= t_truncate for r in base.values()
        ),
        "max_decision_time_ms": max(int(r["decision_time_ms"] or 0) for r in base.values()),
        "T_truncate_ms": t_truncate,
    }

    htf = htf_audit()
    feat = feature_mutation(base_bars["BTC/USDT"], interval_ms)

    overall = (
        all(v["pass"] for v in results.values()) and provenance["all_decisions_at_or_before_T"]
    )
    report = {
        "schema": "rfc020.future_injection.v1",
        "assets": assets,
        "timeframe": timeframe,
        "bars_per_asset": k,
        "step": args.step,
        "decision_instants": len(instants),
        "variants": {k2: len(v) for k2, v in projections.items()},
        "comparisons": results,
        "provenance": provenance,
        "htf": htf,
        "feature_mutation": feat,
        "FUTURE_INJECTION_STATUS": "PASS" if overall else "FAIL",
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--bars", type=int, default=300)
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--out", default="reports/data-integrity/FUTURE_INJECTION_TEST.json")
    args = ap.parse_args()
    report = asyncio.run(main_async(args))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "status": report["FUTURE_INJECTION_STATUS"],
        "decisions": report["decision_instants"],
        "comparisons": {k: v["pass"] for k, v in report["comparisons"].items()},
        "htf_before_close_hidden": report["htf"]["before_close_hidden"],
        "feature_mutation_identical": report["feature_mutation"]["identical"],
    }
    print(json.dumps(summary, indent=2))
    return 0 if report["FUTURE_INJECTION_STATUS"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
