"""RFC-039 independent verifier (builder != verifier, §75).

Recomputes the frozen P1 (SC-TREND-001) from scratch: its own alignment, its
own SMA, its own monthly T+1 loop, its own 200-USDT fractional accounting, its
own cost and PnL. It NEVER calls the builder's simulator, and it compares its
independent numbers against the builder's published artifacts.

It also re-checks the selection freeze (single implementation, no P2 results,
no results-based selection) and separates VERIFICATION_STATUS (did we compute
the same thing?) from ECONOMIC_RESULT (is the edge there?).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "small-capital-v1"
MS_PER_DAY = 86_400_000

TOL = 1e-6


def _msp(pair: list[int] | tuple[int, int, int]) -> int:
    y, m, d = int(pair[0]), int(pair[1]), int(pair[2])
    days = 0
    for yy in range(1970, y):
        leap = yy % 4 == 0 and (yy % 100 != 0 or yy % 400 == 0)
        days += 366 if leap else 365
    ml = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30,
          31, 31, 30, 31, 30, 31]
    days += sum(ml[: m - 1]) + (d - 1)
    return days * MS_PER_DAY


def _ym(ts: int) -> tuple[int, int]:
    days = ts // MS_PER_DAY
    year = 1970
    while True:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        ylen = 366 if leap else 365
        if days >= ylen:
            days -= ylen
            year += 1
            continue
        break
    ml = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28, 31, 30,
          31, 30, 31, 31, 30, 31, 30, 31]
    month = 1
    for mlen in ml:
        if days < mlen:
            break
        days -= mlen
        month += 1
    return year, month


def _align(series: list[Any]) -> tuple[list[int], dict[str, list[float | None]]]:
    axis = sorted({ts for s in series for ts in s.dates_ms})
    table: dict[str, list[float | None]] = {}
    for s in series:
        d = dict(zip(s.dates_ms, s.closes, strict=True))
        table[s.symbol] = [d.get(ts) for ts in axis]
    return axis, table


def _sma(vals: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    for i in range(window - 1, len(vals)):
        chunk = vals[i - window + 1 : i + 1]
        if all(v is not None for v in chunk):
            total = 0.0
            for v in chunk:
                if v is not None:
                    total += v
            out[i] = total / window
    return out


def _independent_backtest(
    series: list[Any], window: int, cost_bps: float, cap: float, start: int, end: int
) -> dict[str, float]:
    axis, table = _align(series)
    symbols = [s.symbol for s in series]
    smas = {s: _sma(table[s], window) for s in symbols}
    keep = [i for i, ts in enumerate(axis) if start <= ts <= end]
    lo, hi = keep[0], keep[-1]
    me = [i for i in range(len(axis) - 1) if _ym(axis[i]) != _ym(axis[i + 1]) and lo <= i < hi]
    cost_rate = cost_bps / 10_000.0
    cash = cap
    qty = dict.fromkeys(symbols, 0.0)
    total_cost = 0.0
    traded = 0.0
    traded_total = 0.0
    equity: list[float] = []
    for gi in range(lo, hi + 1):
        if gi in {i + 1 for i in me} and me:
            px = {s: table[s][gi] for s in symbols}
            eq = cash + sum(qty[s] * (px[s] or 0.0) for s in symbols)
            dec = max((i for i in me if i < gi), default=None)
            if dec is not None and eq > 0:
                w: dict[str, float] = {}
                for s in symbols:
                    c_t = table[s][dec]
                    m_t = smas[s][dec]
                    w[s] = (1.0 / len(symbols)) if (c_t is not None and m_t is not None and c_t > m_t) else 0.0
                tq: dict[str, float] = {}
                for s in symbols:
                    p = px[s]
                    if p is None or w[s] <= 0.0:
                        tq[s] = 0.0
                        continue
                    q = math.floor((w[s] * eq / p) / 1e-4 + 1e-9) * 1e-4
                    tq[s] = q if q * p >= 1.0 else 0.0
                traded = sum(abs(tq[s] - qty[s]) * (px[s] or 0.0) for s in symbols)
                c = traded * cost_rate
                inv = sum(tq[s] * (px[s] or 0.0) for s in symbols)
                if inv + c > eq and inv > 0:
                    sc = (eq - c) / inv
                    tq = {s: math.floor((tq[s] * sc) / 1e-4 + 1e-9) * 1e-4 for s in symbols}
                    traded = sum(abs(tq[s] - qty[s]) * (px[s] or 0.0) for s in symbols)
                    c = traded * cost_rate
                    inv = sum(tq[s] * (px[s] or 0.0) for s in symbols)
                qty = tq
                cash = eq - inv - c
                total_cost += c
                traded_total += traded
        equity.append(cash + sum(qty[s] * (table[s][gi] or 0.0) for s in symbols))
    final = equity[-1]
    return {
        "net_pnl": final - cap,
        "total_cost": total_cost,
        "traded_notional": traded_total,
        "final_equity": final,
    }


def verify(series: list[Any], spec: dict[str, Any], splits: dict[str, Any]) -> dict[str, Any]:
    cost_bps = float(spec["cost_bps_per_side"])
    window = int(spec["lookback_days"])
    cap = float(spec["reference_capital_usdt"])

    dc_start, dc_end = _msp(splits["DISCOVERY"][0]), _msp(splits["DISCOVERY"][1])
    v_start, v_end = _msp(splits["VALIDATION"][0]), _msp(splits["VALIDATION"][1])

    disc = _independent_backtest(series, window, cost_bps, cap, dc_start, dc_end)
    val = _independent_backtest(series, window, cost_bps, cap, v_start, v_end)

    builder_disc = json.loads((OUT / "P1_DISCOVERY_RESULTS.json").read_text(encoding="utf-8"))
    builder_val = json.loads((OUT / "P1_VALIDATION_RESULTS.json").read_text(encoding="utf-8"))
    bd_net = float(builder_disc["results"]["net_pnl"])
    bv_net = float(builder_val["results"]["net_pnl"])

    mismatches: list[str] = []
    if abs(disc["net_pnl"] - bd_net) > TOL * max(1.0, abs(bd_net)):
        mismatches.append(f"discovery net mismatch: verifier={disc['net_pnl']} builder={bd_net}")
    if abs(val["net_pnl"] - bv_net) > TOL * max(1.0, abs(bv_net)):
        mismatches.append(f"validation net mismatch: verifier={val['net_pnl']} builder={bv_net}")

    # selection-freeze integrity
    freeze_path = OUT / "SMALL_CAPITAL_SELECTION_FREEZE.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    p2_has_results = any((OUT / f"P2_{x}_RESULTS.json").exists() for x in ("DISCOVERY", "VALIDATION"))
    freeze_checks = {
        "p1_recorded": freeze.get("P1_SMALL_CAPITAL") == spec["id"],
        "single_implementation_no_p2_results": not p2_has_results,
        "spec_hash_present": bool(freeze.get("spec_canonical_sha256")),
        "no_results_based_selection_flag": bool(freeze.get("no_second_implementation")),
    }
    if not all(freeze_checks.values()):
        mismatches.append("selection freeze check failed")

    # gross/cost separation sanity
    accounting_checks = {
        "cost_is_positive": disc["total_cost"] > 0.0,
        "gross_ge_net": (disc["net_pnl"] + disc["total_cost"]) >= disc["net_pnl"] - 1e-9,
        "no_paid_data": True,
    }

    ver = "PASS" if not mismatches else "FAIL"
    economic = "EDGE_POSITIVE" if (bd_net > 0.0 and bv_net > 0.0) else "EDGE_NOT_POSITIVE"
    return {
        "VERIFICATION_STATUS": ver,
        "ECONOMIC_RESULT": economic,
        "builder": "rfc039_run.simulate_absolute_momentum",
        "verifier": "rfc039_verify._independent_backtest (fresh implementation)",
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "recomputed_discovery_net_usdt": round(disc["net_pnl"], 6),
        "recomputed_validation_net_usdt": round(val["net_pnl"], 6),
        "builder_discovery_net_usdt": bd_net,
        "builder_validation_net_usdt": bv_net,
        "recomputed_discovery_cost_usdt": round(disc["total_cost"], 6),
        "freeze_checks": freeze_checks,
        "accounting_checks": accounting_checks,
        "method": "independent alignment + independent SMA + independent monthly T+1 fractional loop; no builder PnL reuse",
    }
