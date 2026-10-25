"""RFC-040 independent verifier (builder != verifier).

Recomputes SC-DUALMOM-002 from scratch — own alignment, own calendar-month
detection, own relative/absolute momentum decision, own fractional accounting,
own cost, own Sharpe and own risk-matched benchmark — then compares its numbers
with the builder's published artifacts and with the builder's gate result.

It never calls the builder's simulator and never reuses a builder PnL.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "small-capital-dual-momentum-v1"
MS_PER_DAY = 86_400_000
TOL = 1e-6

RISK_A = "SXR8.DE"
RISK_B = "EUNK.DE"
DEFENSIVE = "DBZB.DE"
CASH = "XEON.DE"
EQUITY_BENCH = "EUNL.DE"


def _msp(pair: list[int] | tuple[int, int, int]) -> int:
    y, m, d = int(pair[0]), int(pair[1]), int(pair[2])
    days = 0
    for yy in range(1970, y):
        days += 366 if (yy % 4 == 0 and (yy % 100 != 0 or yy % 400 == 0)) else 365
    leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
    ml = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return (days + sum(ml[: m - 1]) + (d - 1)) * MS_PER_DAY


def _ym(ts: int) -> tuple[int, int]:
    days = ts // MS_PER_DAY
    year = 1970
    while True:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        ylen = 366 if leap else 365
        if days < ylen:
            break
        days -= ylen
        year += 1
    ml = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28, 31, 30,
          31, 30, 31, 31, 30, 31, 30, 31]
    month = 1
    for mlen in ml:
        if days < mlen:
            break
        days -= mlen
        month += 1
    return year, month


def _align(series: list[Any]) -> tuple[list[int], dict[str, list[float]]]:
    common: set[int] | None = None
    for s in series:
        d = set(s.dates_ms)
        common = d if common is None else (common & d)
    assert common
    axis = sorted(common)
    table: dict[str, list[float]] = {}
    for s in series:
        m = dict(zip(s.dates_ms, s.closes, strict=True))
        table[s.symbol] = [m[t] for t in axis]
    return axis, table


def _sim(
    axis: list[int],
    table: dict[str, list[float]],
    *,
    lookback: int,
    cost_bps: float,
    cap: float,
    start: int,
    end: int,
    two_assets: tuple[str, str] | None = None,
    fixed_weight: float | None = None,
) -> dict[str, float]:
    lo = next(i for i, ts in enumerate(axis) if ts >= start)
    hi = max(i for i, ts in enumerate(axis) if ts <= end)
    all_me = [i for i in range(len(axis) - 1) if _ym(axis[i]) != _ym(axis[i + 1])]
    all_me.append(len(axis) - 1)
    me = [i for i in all_me if lo <= i < hi]  # rebalance points need a next day
    marks = [i for i in all_me if lo <= i <= hi]  # monthly marks, matches the builder
    exec_days = {i + 1 for i in me}
    cost_rate = cost_bps / 10_000.0
    cash = cap
    qty: dict[str, float] = dict.fromkeys(table, 0.0)
    equity: list[float] = []
    total_cost = 0.0
    traded_total = 0.0
    switches = 0
    prev_hold = ""

    for gi in range(lo, hi + 1):
        if gi in exec_days and me:
            px = {s: table[s][gi] for s in table}
            eq = cash + sum(qty[s] * px[s] for s in table)
            dec = max((i for i in me if i < gi), default=None)
            if dec is not None and eq > 0.0:
                if fixed_weight is not None:
                    heavy, light = EQUITY_BENCH, CASH
                    target = {heavy: fixed_weight, light: 1.0 - fixed_weight}
                else:
                    assert two_assets
                    ra, rb = two_assets
                    ret_a = table[ra][dec] / table[ra][dec - lookback] - 1.0
                    ret_b = table[rb][dec] / table[rb][dec - lookback] - 1.0
                    if ret_a >= ret_b:
                        winner, wret = ra, ret_a
                    else:
                        winner, wret = rb, ret_b
                    hold = winner if wret > 0.0 else DEFENSIVE
                    if prev_hold and hold != prev_hold:
                        switches += 1
                    prev_hold = hold
                    target = {hold: 1.0}
                tq = dict.fromkeys(table, 0.0)
                for sym, w in target.items():
                    if w <= 0.0:
                        continue
                    q = math.floor((w * eq / px[sym]) / 1e-4 + 1e-9) * 1e-4
                    if q * px[sym] >= 1.0:
                        tq[sym] = q
                traded = sum(abs(tq[s] - qty[s]) * px[s] for s in table)
                c = traded * cost_rate
                inv = sum(tq[s] * px[s] for s in table)
                if inv + c > eq and inv > 0.0:
                    k = (eq - c) / inv
                    tq = {s: math.floor((tq[s] * k) / 1e-4 + 1e-9) * 1e-4 for s in table}
                    traded = sum(abs(tq[s] - qty[s]) * px[s] for s in table)
                    c = traded * cost_rate
                    inv = sum(tq[s] * px[s] for s in table)
                qty = tq
                cash = eq - inv - c
                total_cost += c
                traded_total += traded
        equity.append(cash + sum(qty[s] * table[s][gi] for s in table))
    monthly = [equity[mi - lo] for mi in marks]
    return {
        "net_pnl": equity[-1] - cap,
        "total_cost": total_cost,
        "traded_notional": traded_total,
        "sharpe": _sharpe(monthly),
        "vol": _vol(monthly),
        "max_drawdown": _maxdd(equity),
        "n_switches": float(switches),
    }


def _rets(monthly: list[float]) -> list[float]:
    return [monthly[i] / monthly[i - 1] - 1.0 for i in range(1, len(monthly)) if monthly[i - 1] > 0]


def _sharpe(monthly: list[float]) -> float:
    r = _rets(monthly)
    if len(r) < 2:
        return 0.0
    m = sum(r) / len(r)
    var = sum((x - m) ** 2 for x in r) / (len(r) - 1)
    sd = math.sqrt(var)
    return 0.0 if sd <= 0 else (m / sd) * math.sqrt(12.0)


def _vol(monthly: list[float]) -> float:
    r = _rets(monthly)
    if len(r) < 2:
        return 0.0
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(12.0)


def _maxdd(equity: list[float]) -> float:
    peak, worst = -math.inf, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def verify(
    series: list[Any],
    spec: dict[str, Any],
    splits: dict[str, Any],
    freeze: dict[str, Any],
    builder: dict[str, Any],
) -> dict[str, Any]:
    lookback = int(spec["lookback_days"])
    cost_bps = float(spec["cost_bps_per_side"])
    cap = float(spec["reference_capital_eur"])
    axis, table = _align(series)

    d_a, d_b = _msp(splits["DISCOVERY"][0]), _msp(splits["DISCOVERY"][1])
    v_a, v_b = _msp(splits["VALIDATION"][0]), _msp(splits["VALIDATION"][1])

    disc = _sim(axis, table, lookback=lookback, cost_bps=cost_bps, cap=cap,
                start=d_a, end=d_b, two_assets=(RISK_A, RISK_B))
    val = _sim(axis, table, lookback=lookback, cost_bps=cost_bps, cap=cap,
               start=v_a, end=v_b, two_assets=(RISK_A, RISK_B))
    eq_bench = _sim(axis, table, lookback=lookback, cost_bps=cost_bps, cap=cap,
                    start=v_a, end=v_b, fixed_weight=1.0)
    weight = min(1.0, val["vol"] / eq_bench["vol"]) if eq_bench["vol"] > 0 else 1.0
    rm = _sim(axis, table, lookback=lookback, cost_bps=cost_bps, cap=cap,
              start=v_a, end=v_b, fixed_weight=weight)
    excess = val["net_pnl"] - rm["net_pnl"]

    mismatches: list[str] = []
    b_disc = float(builder["DM_DISCOVERY"]["results"]["net_pnl"])
    b_val = float(builder["DM_VALIDATION"]["results"]["net_pnl"])
    b_exc = float(builder["BUSINESS_EDGE_GATE"]["net_excess_vs_risk_matched_eur"])
    for label, got, want in (
        ("discovery net", disc["net_pnl"], b_disc),
        ("validation net", val["net_pnl"], b_val),
        ("risk-matched excess", excess, b_exc),
    ):
        if abs(got - want) > TOL * max(1.0, abs(want)):
            mismatches.append(f"{label} mismatch: verifier={got:.6f} builder={want:.6f}")

    rm_sharpe_builder = float(builder["BUSINESS_EDGE_GATE"]["risk_matched_passive"]["sharpe"])
    if abs(rm["sharpe"] - rm_sharpe_builder) > 1e-4:
        mismatches.append(
            f"risk-matched sharpe mismatch: verifier={rm['sharpe']:.6f} builder={rm_sharpe_builder:.6f}"
        )

    # the business gate must be reproducible, not asserted
    independent_business = bool(
        val["net_pnl"] > 0.0 and val["sharpe"] > rm["sharpe"] and excess > 0.0
    )
    builder_business = builder["BUSINESS_EDGE_GATE"]["result"] == "PASS"
    if independent_business != builder_business:
        mismatches.append(
            f"business gate disagreement: verifier={independent_business} builder={builder_business}"
        )

    freeze_checks = {
        "spec_hash_present": bool(freeze.get("spec_canonical_sha256")),
        "dataset_hash_present": bool(freeze.get("dataset_sha256")),
        "no_p3_artifacts": not any(OUT.glob("P3_*")),
        "single_candidate": freeze.get("candidate") == "SC-DUALMOM-002",
    }
    if not all(freeze_checks.values()):
        mismatches.append("freeze integrity check failed")

    return {
        "VERIFICATION_STATUS": "PASS" if not mismatches else "FAIL",
        "ECONOMIC_RESULT": "BUSINESS_EDGE_FAIL" if not independent_business else "BUSINESS_EDGE_PASS",
        "builder": "small_capital_dual_momentum_v1.simulate_dual_momentum",
        "verifier": "rfc040_verify._sim (fresh implementation)",
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "recomputed_discovery_net_eur": round(disc["net_pnl"], 6),
        "recomputed_validation_net_eur": round(val["net_pnl"], 6),
        "recomputed_validation_sharpe": round(val["sharpe"], 6),
        "recomputed_risk_matched_sharpe": round(rm["sharpe"], 6),
        "recomputed_risk_matched_weight": round(weight, 6),
        "recomputed_net_excess_eur": round(excess, 6),
        "independent_business_gate": "PASS" if independent_business else "FAIL",
        "freeze_checks": freeze_checks,
        "method": (
            "independent intersection alignment + independent month detection + independent "
            "dual-momentum decision + independent fractional accounting; no builder PnL reused"
        ),
    }
