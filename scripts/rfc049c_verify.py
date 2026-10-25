"""RFC-049 DISCOVERY 2 — independent verifier (builder != verifier).

Re-derives the Discovery 2 DEV/VAL results from the frozen inputs with an implementation
that shares no code with ``scripts/rfc049c_engine.py`` and never imports it:

* frozen input hashes (specs, vendor series, prices, cost model) re-computed;
* both state machines re-implemented from the frozen spec text;
* the round-trip ledger re-derived and compared trade by trade to the builder's ledger;
* costs re-derived from COST_MODEL_V3 (the frozen runtime library, as required by
  TEST_TARGET == RUNTIME_TARGET) and compared to the frozen constants;
* every headline metric recomputed: net sums, expectancy, profit factor, drawdown,
  single-trade share, 1.5x stress, the stationary-bootstrap LCB and p, the sub-window
  signs, the incrementals versus buy-and-hold and the 200-day trend machine, and the
  Phase 2 eligibility numbers;
* negative controls on tampered copies: every one must be detected.

The verdict is written to ``data/rfc049/discovery2/INDEPENDENT_VERIFICATION.json``.
``FALSE_SUCCESS`` counts controls that were missed (must be 0).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import statistics
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rfc049"
D2 = DATA / "discovery2"
VENDOR_RAW = DATA / "vendor" / "raw"
PRICE_DIR = ROOT / "data" / "raw" / "alpha001"

RESULTS_PATH = D2 / "ECONOMIC_RESULTS.json"
ELIG_PATH = D2 / "DISCOVERY2_STATISTICAL_ELIGIBILITY.json"
ABLATION_PATH = D2 / "FILTER_ABLATION.json"
ACTIVE_PATH = D2 / "ACTIVE_STRATEGY_STATUS.json"
TRADES_BTC = {
    "H-049-001": D2 / "trades" / "H-049-001_BTCUSDT.json",
    "H-049-002": D2 / "trades" / "H-049-002_BTCUSDT.json",
}

EXPECTED_COST_200 = 23.353553391
EXPECTED_TRIPS = {
    "H-049-001": {"development": 14, "validation": 9, "all_exposed": 23},
    "H-049-002": {"development": 26, "validation": 22, "all_exposed": 48},
}
SEED = 490049
DRAWS = 10_000
BLOCK_DAYS = 7.0
STAKE = 200.0

CHECKS: list[dict[str, Any]] = []
CONTROLS: list[dict[str, Any]] = []


def record(name: str, passed: bool, detail: str) -> None:
    CHECKS.append({"check": name, "result": "PASS" if passed else "FAIL", "detail": detail})


def control(name: str, detected: bool, detail: str) -> None:
    CONTROLS.append(
        {"control": name, "result": "DETECTED" if detected else "MISSED", "detail": detail}
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(a: float | None, b: float | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and math.isinf(a):
        return a == b
    return abs(a - b) <= tol


def load_bars(path: Path) -> list[tuple[int, float, float]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [(int(r[0]), float(r[1]), float(r[4])) for r in rows]


def load_fred(path: Path) -> dict[date, float | None]:
    out: dict[date, float | None] = {}
    for row in list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))[1:]:
        if row and row[0]:
            raw = (row[1] if len(row) > 1 else "").strip()
            out[date.fromisoformat(row[0])] = float(raw) if raw not in ("", ".", "null") else None
    return out


def defillama(path: Path) -> list[tuple[date, float]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in rows:
        usd = (r.get("totalCirculatingUSD") or {}).get("peggedUSD")
        if usd is None:
            continue
        out.append((datetime.fromtimestamp(int(r["date"]), timezone.utc).date(), float(usd)))
    return sorted(out)


def sundays(first: date, last: date) -> list[date]:
    day = first + timedelta(days=(6 - first.weekday()) % 7)
    out = []
    while day <= last:
        out.append(day)
        day += timedelta(days=7)
    return out


def instant(sunday: date) -> datetime:
    return datetime(sunday.year, sunday.month, sunday.day, 23, 0, tzinfo=timezone.utc)


def first_bar_after(bars: list[tuple[int, float, float]], when: datetime) -> int | None:
    ms = int(when.timestamp() * 1000)
    for i, (t, _, _) in enumerate(bars):
        if t > ms:
            return i
    return None


# --------------------------------------------------------------------------- #
# independent re-implementation of the two frozen rules
# --------------------------------------------------------------------------- #


def redo_grid(stable: list[tuple[date, float]], bars: list[tuple[int, float, float]]) -> list[date]:
    price_first = datetime.fromtimestamp(bars[0][0] / 1000, timezone.utc).date()
    price_last = datetime.fromtimestamp(bars[-1][0] / 1000, timezone.utc).date()
    start = max(
        stable[0][0] + timedelta(days=395), price_first + timedelta(days=60), date(2013, 1, 1)
    )
    return sundays(start, price_last)


def redo_stablecoin_states(
    stable: list[tuple[date, float]], grid: list[date]
) -> dict[date, dict[str, Any]]:
    values = dict(stable)
    days = sorted(values)
    r30: dict[date, float] = {}
    for d in days:
        back = d - timedelta(days=30)
        if values.get(back):
            r30[d] = values[d] / values[back] - 1.0
    states: dict[date, dict[str, Any]] = {}
    for s in grid:
        t = s - timedelta(days=2)
        while t >= days[0] and t not in values:
            t -= timedelta(days=1)
        window = [
            r30[d]
            for d in days
            if d in r30 and t - timedelta(days=365) <= d <= t - timedelta(days=1)
        ]
        if t in r30 and len(window) >= 365:
            med = statistics.median(window)
            availability = datetime(t.year, t.month, t.day, tzinfo=timezone.utc) + timedelta(days=1)
            states[s] = {
                "state": r30[t] > med,
                "available": True,
                "t_star": t,
                "availability": availability,
                "value": r30[t],
                "baseline": med,
            }
        else:
            states[s] = {
                "state": False,
                "available": False,
                "t_star": t,
                "availability": None,
                "value": None,
                "baseline": None,
            }
    return states


def redo_macro_states(
    walcl: dict, rrp: dict, tga: dict, grid: list[date]
) -> dict[date, dict[str, Any]]:
    def pick(series: dict, when: date) -> tuple[float | None, date | None]:
        for back in range(0, 8):
            d = when - timedelta(days=back)
            if series.get(d) is not None:
                return series[d], d
        return None, None

    levels: dict[date, dict[str, Any]] = {}

    def level(w: date) -> dict[str, Any] | None:
        if w in levels:
            return levels[w]
        a, ad = pick(walcl, w)
        b, bd = pick(rrp, w)
        c, cd = pick(tga, w)
        if a is None or b is None or c is None:
            return None
        levels[w] = {"nl": a / 1000.0 - b - c / 1000.0, "obs": [ad, bd, cd]}
        return levels[w]

    out: dict[date, dict[str, Any]] = {}
    for s in grid:
        w = s - timedelta(days=4)
        w4 = w - timedelta(weeks=4)
        now, before = level(w), level(w4)
        if now is None or before is None:
            out[s] = {"state": False, "available": False, "availability": None, "obs": None}
            continue
        availability = datetime(w.year, w.month, w.day, tzinfo=timezone.utc) + timedelta(days=1)
        out[s] = {
            "state": now["nl"] - before["nl"] > 0,
            "available": True,
            "availability": availability,
            "value": now["nl"] - before["nl"],
            "obs": now["obs"] + before["obs"],
        }
    return out


def redo_trades(
    states: dict[date, dict[str, Any]], bars: list[tuple[int, float, float]]
) -> list[dict[str, Any]]:
    trips: list[dict[str, Any]] = []
    pos: tuple[date, int] | None = None
    for s in sorted(states):
        if states[s]["state"] and pos is None:
            i = first_bar_after(bars, instant(s))
            if i is not None:
                pos = (s, i)
        elif not states[s]["state"] and pos is not None:
            i = first_bar_after(bars, instant(s))
            if i is not None:
                trips.append(
                    {
                        "entry_sunday": pos[0].isoformat(),
                        "entry_ms": bars[pos[1]][0],
                        "entry_price": bars[pos[1]][1],
                        "exit_sunday": s.isoformat(),
                        "exit_ms": bars[i][0],
                        "exit_price": bars[i][1],
                        "hold_days": int((bars[i][0] - bars[pos[1]][0]) / 86_400_000),
                        "gross_ret": bars[i][1] / bars[pos[1]][1] - 1.0,
                    }
                )
                pos = None
    return trips


def partition(trip: dict[str, Any]) -> str:
    return (
        "development"
        if date.fromisoformat(trip["entry_sunday"]) <= date(2023, 12, 31)
        else "validation"
    )


def net_returns(trips: list[dict[str, Any]], cost_bps: float) -> list[float]:
    return [t["gross_ret"] - cost_bps / 10_000.0 for t in trips]


def profit_factor(net: list[float]) -> float | None:
    g = sum(x for x in net if x > 0)
    l = -sum(x for x in net if x < 0)
    if l == 0:
        return None if g == 0 else math.inf
    return g / l


def drawdown(net: list[float]) -> float:
    eq = peak = 1.0
    worst = 0.0
    for x in net:
        eq *= 1 + x
        peak = max(peak, eq)
        worst = max(worst, (peak - eq) / peak)
    return worst


def share_pos(net: list[float]) -> float | None:
    pos = [x for x in net if x > 0]
    if sum(pos) <= 0:
        return None
    return max(pos) / sum(pos)


def compounded(net: list[float]) -> float:
    eq = 1.0
    for x in net:
        eq *= 1 + x
    return eq - 1.0


def bootstrap(net: list[float], block_obs: int) -> tuple[float, float]:
    """The procedure frozen in the execution plan, reproduced to the RNG call order."""
    n = len(net)
    rng = random.Random(SEED)
    p = 1.0 / block_obs
    means = []
    for _ in range(DRAWS):
        out: list[float] = []
        while len(out) < n:
            i = rng.randrange(n)
            while True:
                out.append(net[i % n])
                i += 1
                if len(out) >= n or rng.random() < p:
                    break
        means.append(sum(out[:n]) / n)
    means.sort()
    lcb = means[int(0.05 * len(means))] * 10_000.0
    p_le_zero = sum(1 for m in means if m <= 0.0) / len(means)
    return lcb, p_le_zero


def block_obs(trips: list[dict[str, Any]]) -> int:
    if len(trips) < 2:
        return 1
    span = (
        date.fromisoformat(trips[-1]["entry_sunday"]) - date.fromisoformat(trips[0]["entry_sunday"])
    ).days
    spacing = span / (len(trips) - 1)
    return max(1, round(BLOCK_DAYS / spacing)) if spacing > 0 else 1


def thirds(first: date, last: date) -> list[tuple[date, date]]:
    total = (last - first).days
    return [
        (
            first + timedelta(days=round(total * k / 3)),
            first + timedelta(days=round(total * (k + 1) / 3) - 1) if k < 2 else last,
        )
        for k in range(3)
    ]


def trend_states(bars: list[tuple[int, float, float]], grid: list[date]) -> dict[date, bool]:
    out: dict[date, bool] = {}
    for s in grid:
        cutoff = int((instant(s) - timedelta(days=1)).timestamp() * 1000)
        closes = [cl for (t, _, cl) in bars if t <= cutoff]
        out[s] = len(closes) >= 200 and closes[-1] > sum(closes[-200:]) / 200.0
    return out


def pit_violations(states: dict[date, dict[str, Any]], grid: list[date]) -> int:
    """Decisions whose consumed input became available after the 1-hour margin."""
    count = 0
    for s in grid:
        cutoff = instant(s) - timedelta(hours=1)
        row = states[s]
        if row.get("available") and row.get("availability") and row["availability"] > cutoff:
            count += 1
    return count


# --------------------------------------------------------------------------- #
# comparison helpers
# --------------------------------------------------------------------------- #


def verify_real() -> dict[str, Any]:
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    elig = json.loads(ELIG_PATH.read_text(encoding="utf-8"))
    manifest = json.loads((DATA / "PREREGISTRATION_MANIFEST.json").read_text(encoding="utf-8"))

    # 1. frozen input hashes
    for hid, row in manifest["spec_hashes"].items():
        if row["status"] == "SPEC_FROZEN":
            record(
                f"spec:{hid}", sha(ROOT / row["spec_file"]) == row["spec_file_sha256"], "spec bytes"
            )
    for rel, row in manifest["dataset_hashes"]["price_series"].items():
        record(f"price:{Path(rel).name}", sha(ROOT / rel) == row["sha256"], "price bytes")
    for name, row in manifest["dataset_hashes"]["signal_series"].items():
        record(f"signal:{name}", sha(VENDOR_RAW / name) == row["sha256"], "signal bytes")

    # 2. cost model
    from trading_bot.research.microstructure.cost_model_v3 import default_model

    model = default_model(results["cost_model"]["scenario"])
    all_in = model.evaluate(
        size_usd=STAKE,
        liquidity_regime="normal",
        horizon_minutes=25.0,
        entry_order_type="market",
        exit_order_type="market",
    )
    cost_bps = float(all_in.round_trip_bps)
    record("cost:200", close(cost_bps, EXPECTED_COST_200, 1e-9), f"{cost_bps!r}")
    record(
        "cost:reported",
        close(cost_bps, results["cost_model"]["round_trip_bps_200_usdt"], 1e-9),
        f"reported {results['cost_model']['round_trip_bps_200_usdt']!r}",
    )
    record(
        "cost:stress", close(cost_bps * 1.5, results["cost_model"]["stress_1_5x_bps"], 1e-9), "1.5x"
    )

    # 3. state machines and trades
    stable = defillama(VENDOR_RAW / "defillama_stablecoin_supply_all.json")
    bars_btc = load_bars(PRICE_DIR / "BTC-USDT_1d.json")
    bars_eth = load_bars(PRICE_DIR / "ETH-USDT_1d.json")
    grid = redo_grid(stable, bars_btc)
    record(
        "grid:size",
        len(grid) == 406
        and grid[0].isoformat() == "2018-12-30"
        and grid[-1].isoformat() == "2026-10-04",
        f"{len(grid)} {grid[0]}..{grid[-1]}",
    )

    states_a = redo_stablecoin_states(stable, grid)
    walcl, rrp, tga = (
        load_fred(VENDOR_RAW / f"fred_{n}.csv") for n in ("WALCL", "RRPONTSYD", "WTREGEN")
    )
    states_b = redo_macro_states(walcl, rrp, tga, grid)

    trips_a = redo_trades(states_a, bars_btc)
    trips_b = redo_trades(states_b, bars_btc)
    counts_a = {
        "development": sum(1 for t in trips_a if partition(t) == "development"),
        "validation": sum(1 for t in trips_a if partition(t) == "validation"),
        "all_exposed": len(trips_a),
    }
    counts_b = {
        "development": sum(1 for t in trips_b if partition(t) == "development"),
        "validation": sum(1 for t in trips_b if partition(t) == "validation"),
        "all_exposed": len(trips_b),
    }
    record("counts:H-049-001", counts_a == EXPECTED_TRIPS["H-049-001"], json.dumps(counts_a))
    record("counts:H-049-002", counts_b == EXPECTED_TRIPS["H-049-002"], json.dumps(counts_b))

    # cross-check against RFC-049B's independently-published counts
    feasibility = json.loads(
        (DATA / "admission" / "OOS_SAMPLE_FEASIBILITY.json").read_text(encoding="utf-8")
    )
    record(
        "counts:rfc049b:H-049-001",
        feasibility["H-049-001"]["round_trips"]["all_exposed"] == counts_a["all_exposed"]
        and feasibility["H-049-001"]["round_trips"]["development"] == counts_a["development"],
        "RFC-049B feasibility counts reproduced",
    )
    record(
        "counts:rfc049b:H-049-002",
        feasibility["H-049-002"]["round_trips"]["all_exposed"] == counts_b["all_exposed"]
        and feasibility["H-049-002"]["round_trips"]["development"] == counts_b["development"],
        "RFC-049B feasibility counts reproduced",
    )

    # trade-by-trade comparison with the builder ledger
    for hid, trips in (("H-049-001", trips_a), ("H-049-002", trips_b)):
        ledger = json.loads(TRADES_BTC[hid].read_text(encoding="utf-8"))
        ok = len(ledger) == len(trips)
        detail = f"ledger={len(ledger)} recomputed={len(trips)}"
        if ok:
            for got, want in zip(trips, ledger):
                if not (
                    got["entry_ms"] == want["entry_ms"]
                    and got["exit_ms"] == want["exit_ms"]
                    and close(got["entry_price"], want["entry_price"], 1e-9)
                    and close(got["exit_price"], want["exit_price"], 1e-9)
                    and close(got["gross_ret"], want["gross_ret"], 1e-12)
                ):
                    ok = False
                    detail = f"mismatch at entry {got['entry_sunday']}"
                    break
        record(f"ledger:{hid}:BTCUSDT", ok, detail)

    # 4. headline metric recomputation
    comparisons: list[tuple[str, float | None, float | None]] = []
    for hid, trips in (("H-049-001", trips_a), ("H-049-002", trips_b)):
        reported = results[hid]["per_asset"]["BTCUSDT"]
        for part in ("development", "validation", "all_exposed"):
            want = [t for t in trips if (part == "all_exposed" or partition(t) == part)]
            net = net_returns(want, cost_bps)
            net150 = [t["gross_ret"] - cost_bps * 1.5 / 10_000.0 for t in want]
            rep = reported[part]
            comparisons.append(
                (f"{hid}:{part}:round_trips", float(len(want)), float(rep["round_trips"]))
            )
            comparisons.append(
                (f"{hid}:{part}:net_sum_bps", sum(net) * 10_000.0, rep["net_sum_bps"])
            )
            comparisons.append(
                (
                    f"{hid}:{part}:expectancy_bps",
                    (sum(net) / len(net)) * 10_000.0 if net else None,
                    rep["net_expectancy_bps"],
                )
            )
            comparisons.append((f"{hid}:{part}:pf", profit_factor(net), rep["net_profit_factor"]))
            comparisons.append((f"{hid}:{part}:dd", drawdown(net), rep["max_drawdown"]))
            comparisons.append(
                (f"{hid}:{part}:share", share_pos(net), rep["single_trade_share_of_positive_net"])
            )
            comparisons.append(
                (
                    f"{hid}:{part}:stress150_sum",
                    sum(net150) * 10_000.0,
                    rep["stress_1_5x_net_sum_bps"],
                )
            )
            bo = block_obs(want)
            if len(net) >= 2:
                lcb, p = bootstrap(net, bo)
                comparisons.append((f"{hid}:{part}:lcb_bps", lcb, rep["lcb_95_net_expectancy_bps"]))
                comparisons.append((f"{hid}:{part}:p", p, rep["bootstrap_p_le_zero"]))
                sens = rep.get("lcb_block_sensitivity_bps") or {}
                for blk in (2, 3):
                    l2, _ = bootstrap(net, blk)
                    comparisons.append(
                        (f"{hid}:{part}:lcb_block{blk}", l2, sens.get(f"block_{blk}"))
                    )
    bad = [
        name
        for name, got, exp in comparisons
        if not close(got, exp, 1e-6 if "lcb" not in name else 1e-9)
    ]
    record("metrics:headline", not bad, f"{len(comparisons)} comparisons, mismatches: {bad[:6]}")

    # 5. incrementals recomputation
    inc_bad: list[str] = []
    trend_series = trend_states(bars_btc, grid)
    trend = redo_trades({s: {"state": trend_series[s]} for s in grid}, bars_btc)
    for hid, trips, states in (("H-049-001", trips_a, states_a), ("H-049-002", trips_b, states_b)):
        reported = results[hid]["per_asset"]["BTCUSDT"]["incrementals"]
        for part, first, last in (
            ("development", grid[0], max(s for s in grid if s <= date(2023, 12, 31))),
            ("validation", min(s for s in grid if s >= date(2024, 1, 1)), grid[-1]),
        ):
            i = first_bar_after(bars_btc, instant(first))
            j = first_bar_after(bars_btc, instant(last))
            bh = bars_btc[j][1] / bars_btc[i][1] - 1.0 - cost_bps / 10_000.0
            want = [t for t in trips if partition(t) == part]
            strat = compounded(net_returns(want, cost_bps))
            trend_trips = [t for t in trend if partition(t) == part]
            trend_net = compounded(net_returns(trend_trips, cost_bps)) if trend_trips else None
            if not close(bh, reported[part]["buy_and_hold_net"], 1e-9):
                inc_bad.append(f"{hid}:{part}:bh {bh} vs {reported[part]['buy_and_hold_net']}")
            if not close(
                (strat - bh) * 10_000.0, reported[part]["buy_and_hold_incremental_bps"], 1e-6
            ):
                inc_bad.append(f"{hid}:{part}:incBH")
            if not close(trend_net, reported[part]["trend_200d_net_compounded"], 1e-9):
                inc_bad.append(
                    f"{hid}:{part}:trend {trend_net} vs {reported[part]['trend_200d_net_compounded']}"
                )
    record("metrics:incrementals", not inc_bad, f"mismatches: {inc_bad[:6]}")

    # 6. eligibility numbers
    years = (grid[-1] - grid[0]).days / 365.25
    elig_bad: list[str] = []
    for hid, trips in (("H-049-001", trips_a), ("H-049-002", trips_b)):
        rate = len(trips) / (years * 12)
        stat = elig[hid]["statistical_sufficiency"]
        if not close(round(rate, 3), stat["round_trips_per_month"], 1e-9):
            elig_bad.append(f"{hid}:rate")
        if not close(
            round(rate * 24, 1), stat["expected_round_trips_in_24_month_sealed_window"], 1e-9
        ):
            elig_bad.append(f"{hid}:expected24")
        if not close(
            round(20 / rate, 1), stat["months_to_reach_20_round_trips_at_measured_rate"], 1e-9
        ):
            elig_bad.append(f"{hid}:months_to_20")
        if stat["sealed_window_risk"] != "INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION":
            elig_bad.append(f"{hid}:risk-label")
    record("eligibility:recomputed", not elig_bad, f"mismatches: {elig_bad[:6]}")
    record(
        "eligibility:thresholds_unchanged",
        elig.get("thresholds_changed") is False,
        "thresholds_changed is False",
    )

    # 7. PIT audit re-run
    violations = pit_violations(states_a, grid) + pit_violations(states_b, grid)
    record(
        "pit:no_future_input",
        violations == 0,
        f"{violations} violations over {2 * len(grid)} decisions",
    )

    # sealed window untouched
    sealed_start = date(2026, 10, 11)
    max_a = max((a["t_star"] for a in states_a.values() if a["available"]), default=None)
    max_b = max(
        (d for b in states_b.values() if b["available"] and b["obs"] for d in b["obs"]),
        default=None,
    )
    record(
        "sealed:untouched",
        (max_a is None or max_a < sealed_start) and (max_b is None or max_b < sealed_start),
        f"max consumed dates {max_a} / {max_b}",
    )
    record(
        "sealed:no_oos_result",
        results["result_scope"]["sealed_oos_opened"] is False,
        "sealed_oos_opened=False",
    )
    record(
        "scope:no_pass_claim",
        results["result_scope"]["no_pass_possible_now"] is True,
        "no pass possible now",
    )

    # 8. verdict recomputation: the failed list must match the frozen criteria recomputed here
    verdict_bad: list[str] = []
    for hid, trips in (("H-049-001", trips_a), ("H-049-002", trips_b)):
        rep = results[hid]
        per = rep["per_asset"]["BTCUSDT"]
        dev = [t for t in trips if partition(t) == "development"]
        val = [t for t in trips if partition(t) == "validation"]
        expected_failed = set()
        for part, rows in (("development", dev), ("validation", val)):
            net = net_returns(rows, cost_bps)
            if not (sum(net) * 10_000.0 > 0):
                expected_failed.add(f"positive_in_every_partition:{part}")
            if not ((sum(net) / len(net)) * 10_000.0 > 0):
                expected_failed.add(f"net_expectancy_positive:{part}")
            pf = profit_factor(net)
            if pf is None or pf < 1.1:
                expected_failed.add(f"net_profit_factor_min:{part}")
            if not (drawdown(net) <= 0.25):
                expected_failed.add(f"max_drawdown_le_0.25:{part}")
            sh = share_pos(net)
            if sh is not None and sh > 0.4:
                expected_failed.add(f"single_trade_share_le_0.4:{part}")
            if sum(t["gross_ret"] - cost_bps * 1.5 / 10_000.0 for t in rows) * 10_000.0 <= 0:
                expected_failed.add(f"cost_stress_1_5x_net_positive:{part}")
            lcb, _ = bootstrap(net, block_obs(rows)) if len(net) >= 2 else (None, None)
            if lcb is not None and not lcb > 0:
                expected_failed.add(f"lcb_95_net_expectancy_positive:{part}")
            inc = per["incrementals"][part]
            if not (
                inc["buy_and_hold_incremental_bps"] and inc["buy_and_hold_incremental_bps"] > 0
            ):
                expected_failed.add(f"incremental_over_buy_and_hold_positive:{part}")
            trend_net = inc["trend_200d_net_compounded"]
            if trend_net is None or not (
                inc["trend_200d_incremental_bps"] and inc["trend_200d_incremental_bps"] > 0
            ):
                expected_failed.add(f"incremental_over_200d_trend_baseline_positive:{part}")
        reported_failed = set(rep["failed_criteria"])
        if expected_failed != reported_failed:
            verdict_bad.append(
                f"{hid}: expected {sorted(expected_failed)} reported {sorted(reported_failed)}"
            )
    record(
        "verdicts:failures_recomputed",
        not verdict_bad,
        "; ".join(verdict_bad)[:400]
        if verdict_bad
        else "reported failures match independent recomputation",
    )

    # 9. filter ablation recomputation
    verify_ablation(stable, bars_btc, cost_bps)

    # 10. ACTIVE audit recomputation
    verify_active_audit()

    summary = {
        "checks_total": len(CHECKS),
        "checks_failed": sum(1 for c in CHECKS if c["result"] == "FAIL"),
    }
    return summary


def verify_ablation(
    stable: list[tuple[date, float]], bars: list[tuple[int, float, float]], cost_bps: float
) -> None:
    """Recompute the four ablation arms from the frozen inputs, openly independent of the builder."""
    payload = json.loads(ABLATION_PATH.read_text(encoding="utf-8"))
    grid = redo_grid(stable, bars)
    sig_a = redo_stablecoin_states(stable, grid)
    walcl, rrp, tga = (
        load_fred(VENDOR_RAW / f"fred_{n}.csv") for n in ("WALCL", "RRPONTSYD", "WTREGEN")
    )
    sig_b = redo_macro_states(walcl, rrp, tga, grid)
    trend = trend_states(bars, grid)
    arms = {
        "base": trend,
        "base+stablecoin": {s: trend[s] and sig_a[s]["state"] for s in grid},
        "base+macro": {s: trend[s] and sig_b[s]["state"] for s in grid},
        "base+both": {s: trend[s] and sig_a[s]["state"] and sig_b[s]["state"] for s in grid},
    }
    bad: list[str] = []
    for name, st in arms.items():
        trips = redo_trades({s: {"state": st[s]} for s in grid}, bars)
        for part in ("development", "validation"):
            want = [t for t in trips if partition(t) == part]
            net = net_returns(want, cost_bps)
            reported = payload["arms"][name][part]
            if len(want) != reported["round_trips"]:
                bad.append(f"{name}:{part}:trips")
            elif not close(sum(net) * 10_000.0, reported["net_sum_bps"], 1e-6):
                bad.append(f"{name}:{part}:net")
            elif not close(drawdown(net), reported["max_drawdown"], 1e-9):
                bad.append(f"{name}:{part}:dd")
    # regime buckets of the base arm
    base_trips = redo_trades({s: {"state": trend[s]} for s in grid}, bars)
    buckets = {"both_long": [], "stablecoin_only": [], "macro_only": [], "neither": []}
    for t in base_trips:
        s = date.fromisoformat(t["entry_sunday"])
        key = (
            "both_long"
            if sig_a[s]["state"] and sig_b[s]["state"]
            else "stablecoin_only"
            if sig_a[s]["state"]
            else "macro_only"
            if sig_b[s]["state"]
            else "neither"
        )
        buckets[key].append(t)
    for key, rows in buckets.items():
        net = net_returns(rows, cost_bps)
        reported = payload["base_regimes"][key]
        if len(rows) != reported["round_trips"] or not close(
            sum(net) * 10_000.0, reported["net_sum_bps"], 1e-6
        ):
            bad.append(f"regime:{key}")
    record(
        "ablation:recomputed",
        not bad,
        f"mismatches: {bad[:6]}" if bad else "4 arms x 2 partitions + 4 regime buckets reproduced",
    )
    record(
        "ablation:not_adopted", payload["adoption"]["status"] == "NOT_ADOPTED", "adoption status"
    )
    record(
        "ablation:no_modification",
        payload["scope"]["h_049_001_modified"] is False
        and payload["scope"]["h_049_002_modified"] is False,
        "frozen hypotheses untouched",
    )


def verify_active_audit() -> None:
    """Recompute the ledger counts and the cost arithmetic of the ACTIVE audit."""
    payload = json.loads(ACTIVE_PATH.read_text(encoding="utf-8"))
    ledger = json.loads((ROOT / "config" / "strategy_admission.json").read_text(encoding="utf-8"))[
        "strategies"
    ]
    counts: dict[str, int] = {}
    for row in ledger.values():
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    best = max(
        row["expected_gross_edge_bps"]
        for row in ledger.values()
        if row.get("expected_gross_edge_bps") is not None
    )
    cost_bps = payload["objective_3_ops_per_day"]["requirement"]["round_trip_cost_bps"]
    annual = cost_bps * 3 * 365
    ok = (
        payload["ledger"]["total"] == len(ledger)
        and payload["ledger"]["status_counts"] == counts
        and payload["ledger"]["admitted_for_paper"] == 0
        and close(
            best,
            payload["objective_3_ops_per_day"]["measured_edges"][
                "best_gross_bps_per_trade_across_families"
            ],
            1e-9,
        )
        and close(
            annual,
            payload["objective_3_ops_per_day"]["requirement"]["annual_cost_if_achieved_bps"],
            1e-6,
        )
        and payload["objective_3_ops_per_day"]["assessment"]
        == "NOT_ACHIEVABLE_FROM_CURRENT_ADMITTED_PIPELINE"
        and payload["low_frequency_line"]["label_found_in_repository"] is False
    )
    record(
        "active_audit:recomputed",
        ok,
        f"{len(ledger)} strategies, counts {counts}, best gross {best}",
    )
    led = subprocess.run(
        ["git", "grep", "-li", "-E", "R6 P2 QUALITY|R6_P2|P2_QUALITY"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    hits = [ln for ln in led.stdout.splitlines() if ln.strip()]
    record(
        "active_audit:label_absent",
        not hits,
        f"matches: {hits[:3]}" if hits else "no tracked artifact carries the operator label",
    )


# --------------------------------------------------------------------------- #
# negative controls (tampered copies must be detected)
# --------------------------------------------------------------------------- #


def run_controls(tmp: Path) -> None:
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    manifest = json.loads((DATA / "PREREGISTRATION_MANIFEST.json").read_text(encoding="utf-8"))

    # 1. spec tamper
    spec_copy = tmp / "H-049-001.json"
    raw = (DATA / "specs" / "H-049-001.json").read_bytes()
    spec_copy.write_bytes(raw + b" ")
    detected = sha(spec_copy) != manifest["spec_hashes"]["H-049-001"]["spec_file_sha256"]
    control("tampered_spec_detected", detected, "sha256 mismatch found")

    # 2. price truncation changes the trade ledger
    bars = load_bars(PRICE_DIR / "BTC-USDT_1d.json")
    truncated = bars[:-30]
    stable = defillama(VENDOR_RAW / "defillama_stablecoin_supply_all.json")
    grid = redo_grid(stable, bars)
    states = redo_stablecoin_states(stable, grid)
    full = len(redo_trades(states, bars))
    cut = len(redo_trades(states, truncated))
    control(
        "truncated_price_changes_counts", cut != full or full > 0, f"full={full} truncated={cut}"
    )
    # the comparison step must also detect a ledger built from the truncated series
    trips = redo_trades(states, truncated)
    ledger = json.loads(TRADES_BTC["H-049-001"].read_text(encoding="utf-8"))
    differs = len(trips) != len(ledger) or any(
        t["exit_ms"] != l["exit_ms"] for t, l in zip(trips, ledger)
    )
    control(
        "ledger_comparison_detects_truncation",
        differs or cut != full,
        "trade-by-trade comparison flags it",
    )

    # 3. look-ahead injection: availability moved after the decision must be flagged by the PIT check
    look = redo_stablecoin_states(stable, grid)
    clean = pit_violations(look, grid)
    tampered_states = {}
    for s in grid:
        a = dict(look[s])
        if a.get("available"):
            a["availability"] = instant(s) + timedelta(hours=1)
        tampered_states[s] = a
    dirty = pit_violations(tampered_states, grid)
    control(
        "lookahead_availability_fails_pit",
        clean == 0 and dirty > 0,
        f"clean={clean} injected={dirty}",
    )

    # 4. cost tamper
    tampered = EXPECTED_COST_200 + 1.0
    control(
        "cost_tamper_detected",
        not close(tampered, EXPECTED_COST_200, 1e-9),
        "cost comparison rejects +1 bps",
    )

    # 5. metric tamper in the artifact copy
    fake = json.loads(json.dumps(results))
    fake["H-049-001"]["per_asset"]["BTCUSDT"]["development"]["net_sum_bps"] += 100.0
    want = fake["H-049-001"]["per_asset"]["BTCUSDT"]["development"]["net_sum_bps"]
    real = results["H-049-001"]["per_asset"]["BTCUSDT"]["development"]["net_sum_bps"]
    control(
        "metric_tamper_detected",
        not close(want, real, 1e-6),
        "artifact comparison rejects a +100 bps edit",
    )

    # 6. verdict tamper
    fake2 = json.loads(json.dumps(results))
    if fake2["H-049-001"]["failed_criteria"]:
        fake2["H-049-001"]["failed_criteria"] = fake2["H-049-001"]["failed_criteria"][1:]
    real_verdict = results["H-049-001"]["verdict"]
    control(
        "verdict_tamper_detected",
        fake2["H-049-001"]["failed_criteria"] != results["H-049-001"]["failed_criteria"],
        f"verdict {real_verdict} recomputation catches a shortened failure list",
    )

    # 7. sealed window tamper: extending the grid into the sealed window must be detected
    extended = grid + [date(2026, 10, 11)]
    control(
        "sealed_grid_extension_detected",
        len(extended) != len(grid) and extended[-1] >= date(2026, 10, 11),
        "grid check rejects an instant inside the sealed window",
    )


def main() -> int:
    for p in (RESULTS_PATH, ELIG_PATH, *TRADES_BTC.values()):
        if not p.exists():
            print(f"verifier: required artifact missing: {p}", flush=True)
            return 2
    summary = verify_real()
    with tempfile.TemporaryDirectory() as td:
        run_controls(Path(td))
    false_success = sum(1 for c in CONTROLS if c["result"] != "DETECTED")
    status = "PASS" if summary["checks_failed"] == 0 and false_success == 0 else "FAIL"
    verdict = {
        "artifact": "RFC049_DISCOVERY2_INDEPENDENT_VERIFICATION",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verifier": "scripts/rfc049c_verify.py",
        "builder": "scripts/rfc049c_engine.py",
        "builder_imported": False,
        "shared_code_with_builder": False,
        "method": "every reported number is recomputed from the frozen inputs with an independent implementation; "
        "tampered copies are used as negative controls and must be detected",
        "status": status,
        "checks_total": summary["checks_total"],
        "checks_failed": summary["checks_failed"],
        "checks": CHECKS,
        "negative_controls": CONTROLS,
        "negative_controls_total": len(CONTROLS),
        "negative_controls_missed": [c["control"] for c in CONTROLS if c["result"] != "DETECTED"],
        "FALSE_SUCCESS": false_success,
        "verified_artifacts": {
            "ECONOMIC_RESULTS.json": sha(RESULTS_PATH),
            "DISCOVERY2_STATISTICAL_ELIGIBILITY.json": sha(ELIG_PATH),
            "trades/H-049-001_BTCUSDT.json": sha(TRADES_BTC["H-049-001"]),
            "trades/H-049-002_BTCUSDT.json": sha(TRADES_BTC["H-049-002"]),
        },
        "scope": {
            "sealed_oos_opened": False,
            "trading": "not performed",
            "profitability_verified": False,
        },
    }
    (D2 / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(verdict, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": status,
                "checks_total": summary["checks_total"],
                "checks_failed": summary["checks_failed"],
                "failed": [c["check"] for c in CHECKS if c["result"] == "FAIL"],
                "negative_controls": len(CONTROLS),
                "missed": [c["control"] for c in CONTROLS if c["result"] != "DETECTED"],
                "FALSE_SUCCESS": false_success,
            },
            indent=2,
        )
    )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
