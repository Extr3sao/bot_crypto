"""RFC-049 DISCOVERY 2 — Phase B DEV/VAL engine (builder).

Implements the two frozen hypotheses (S-049-001 stablerail-liquidity impulse and
S-049-002 USD net-liquidity regime) in the research plane, computes their economic
experiments on the RESEARCH_EXPOSED partitions (development + validation) under the
frozen cost model, and emits the Discovery 2 artifacts into ``data/rfc049/discovery2/``.

By construction this module:

* consumes only frozen inputs and aborts if any frozen hash has drifted;
* computes no quantity for the sealed forward window (which starts
  ``2026-10-11T00:00:00Z`` and opens only at its own gate);
* never changes a threshold, a rule or a partition, and performs no parameter search;
* writes nothing outside ``data/rfc049/discovery2/`` and modifies no historical file;
* is the *builder*.  ``scripts/rfc049c_verify.py`` re-derives these numbers with an
  independent implementation and must not import this module.

Preregistration: ``data/rfc049/discovery2/DISCOVERY2_EXECUTION_PLAN.md`` (written before
this run; its sha256 is recorded in the output).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import statistics
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rfc049"
D2 = DATA / "discovery2"
SPECS = DATA / "specs"
VENDOR_RAW = DATA / "vendor" / "raw"
PRICE_DIR = ROOT / "data" / "raw" / "alpha001"

MANIFEST = DATA / "PREREGISTRATION_MANIFEST.json"
EXECUTION_PLAN = D2 / "DISCOVERY2_EXECUTION_PLAN.md"
AUTHORIZATION = D2 / "CAMPAIGN_AUTHORIZATION.json"

# --------------------------------------------------------------------------- #
# frozen procedure constants (all fixed before the run; none may be tuned)
# --------------------------------------------------------------------------- #

STAKE_USDT = 200.0
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_BLOCK_DAYS = 7.0
BOOTSTRAP_SEED = 490049
SUBWINDOW_COUNT = 3
EXPECTED_COST_200_BPS = 23.353553391
EXPECTED_STRESS_150_BPS = 35.030330086
COST_TOLERANCE_BPS = 1e-6
ASOF_MAX_REACHBACK_DAYS = 7

EXPECTED_GRID_FIRST = "2018-12-30"
EXPECTED_GRID_LAST = "2026-10-04"
EXPECTED_GRID_COUNT = 406

EXPECTED_TRIPS = {
    "H-049-001": {"development": 14, "validation": 9, "all_exposed": 23},
    "H-049-002": {"development": 26, "validation": 22, "all_exposed": 48},
}

SEALED_OOS_START = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
FREEZE_INSTANT = datetime(2026, 10, 10, 11, 26, 20, tzinfo=timezone.utc)

DEV_END = date(2023, 12, 31)
VAL_START = date(2024, 1, 1)
DECISION_HOUR_UTC = 23

ASSETS = {"BTCUSDT": "BTC-USDT_1d.json", "ETHUSDT": "ETH-USDT_1d.json"}

CHECKS: list[dict[str, Any]] = []


class EngineError(RuntimeError):
    """Raised when a frozen input has drifted or a frozen invariant fails."""


def log(message: str) -> None:
    print(f"[rfc049c] {message}", flush=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check(name: str, passed: bool, detail: str) -> None:
    CHECKS.append({"check": name, "result": "PASS" if passed else "FAIL", "detail": detail})
    if not passed:
        raise EngineError(f"frozen invariant failed: {name}: {detail}")


# --------------------------------------------------------------------------- #
# frozen input loading
# --------------------------------------------------------------------------- #


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_fred_csv(path: Path) -> dict[date, float | None]:
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    out: dict[date, float | None] = {}
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        raw = (row[1] if len(row) > 1 else "").strip()
        out[date.fromisoformat(row[0])] = float(raw) if raw not in ("", ".", "null") else None
    return out


def load_bars(path: Path) -> list[tuple[int, float, float]]:
    """[(open_time_ms, open, close)]. open executes; close feeds the trend baseline only."""
    rows = load_json(path)
    bars = [(int(r[0]), float(r[1]), float(r[4])) for r in rows]
    bars.sort(key=lambda b: b[0])
    return bars


def defillama_rows(path: Path) -> list[tuple[date, float, float]]:
    data = load_json(path)
    out: list[tuple[date, float, float]] = []
    for row in data:
        day = datetime.fromtimestamp(int(row["date"]), timezone.utc).date()
        usd = (row.get("totalCirculatingUSD") or {}).get("peggedUSD")
        qty = (row.get("totalCirculating") or {}).get("peggedUSD")
        if usd is None or qty is None:
            continue
        out.append((day, float(usd), float(qty)))
    out.sort(key=lambda r: r[0])
    return out


def verified_inputs() -> dict[str, Any]:
    """Re-hash every frozen input against the preregistration manifest and the vendor manifest."""
    manifest = load_json(MANIFEST)
    vendor = load_json(DATA / "vendor" / "VENDOR_MANIFEST.json")

    spec_ref = {}
    for hid, row in manifest["spec_hashes"].items():
        if row["status"] != "SPEC_FROZEN":
            continue
        digest = sha256_file(ROOT / row["spec_file"])
        check(
            f"input:spec:{hid}",
            digest == row["spec_file_sha256"],
            f"{row['spec_file']} sha256={digest[:16]}…",
        )
        spec_ref[hid] = digest

    for rel, row in manifest["dataset_hashes"]["price_series"].items():
        digest = sha256_file(ROOT / rel)
        check(f"input:price:{Path(rel).name}", digest == row["sha256"], f"{rel}")
    for name, row in manifest["dataset_hashes"]["signal_series"].items():
        digest = sha256_file(VENDOR_RAW / name)
        check(f"input:signal:{name}", digest == row["sha256"], f"vendor/raw/{name}")

    cost_path = ROOT / "docs" / "COST_MODEL_V3.json"
    check(
        "input:cost_model",
        sha256_file(cost_path) == manifest["cost_model_hash"],
        "docs/COST_MODEL_V3.json",
    )

    # vendor manifest byte agreement for the traded series
    vendor_series = vendor.get("series", {})
    for name in (
        "defillama_stablecoin_supply_all.json",
        "fred_WALCL.csv",
        "fred_RRPONTSYD.csv",
        "fred_WTREGEN.csv",
    ):
        row = vendor_series.get(name)
        if row is None:
            continue
        digest = sha256_file(VENDOR_RAW / name)
        expected = row.get("sha256") or row.get("file_sha256")
        if expected:
            check(f"input:vendor:{name}", digest == expected, f"vendor/raw/{name}")
    return {"manifest": manifest, "vendor_manifest": vendor, "spec_hashes": spec_ref}


def derived_cost_bps() -> dict[str, float]:
    """Re-derive the frozen round-trip cost at the campaign's own stake, never typed by hand."""
    from trading_bot.research.microstructure.cost_model_v3 import default_model

    model = default_model("BINANCE_SPOT_STANDARD_TAKER")
    all_in = model.evaluate(
        size_usd=STAKE_USDT,
        liquidity_regime="normal",
        horizon_minutes=25.0,
        entry_order_type="market",
        exit_order_type="market",
    )
    bps = float(all_in.round_trip_bps)
    check(
        "cost:matches_frozen_200",
        abs(bps - EXPECTED_COST_200_BPS) <= COST_TOLERANCE_BPS,
        f"derived {bps!r} vs frozen {EXPECTED_COST_200_BPS}",
    )
    stressed = bps * 1.5
    check(
        "cost:matches_frozen_stress",
        abs(stressed - EXPECTED_STRESS_150_BPS) <= COST_TOLERANCE_BPS,
        f"derived {stressed!r} vs frozen {EXPECTED_STRESS_150_BPS}",
    )
    return {
        "round_trip_bps_200_usdt": bps,
        "round_trip_bps_1000_usdt": float(
            model.evaluate(size_usd=1000.0, horizon_minutes=25.0).round_trip_bps
        ),
        "stress_1_25x_bps": bps * 1.25,
        "stress_1_5x_bps": stressed,
        "scenario": "BINANCE_SPOT_STANDARD_TAKER",
        "stake_usdt": STAKE_USDT,
        "components": [
            {"name": c.name, "value_bps": round(c.value_bps, 9), "knowledge": c.knowledge}
            for c in all_in.components
        ],
    }


# --------------------------------------------------------------------------- #
# calendar helpers
# --------------------------------------------------------------------------- #


def sundays(first: date, last: date) -> list[date]:
    day = first + timedelta(days=(6 - first.weekday()) % 7)
    out: list[date] = []
    while day <= last:
        out.append(day)
        day += timedelta(days=7)
    return out


def asof(
    series: dict[date, float | None], when: date, max_reachback_days: int = ASOF_MAX_REACHBACK_DAYS
) -> tuple[float | None, date | None]:
    for back in range(0, max_reachback_days + 1):
        day = when - timedelta(days=back)
        value = series.get(day)
        if value is not None:
            return value, day
    return None, None


def decision_instant(sunday: date) -> datetime:
    return datetime(
        sunday.year, sunday.month, sunday.day, DECISION_HOUR_UTC, 0, tzinfo=timezone.utc
    )


def bar_after(bars: list[tuple[int, float, float]], instant: datetime) -> int | None:
    ms = int(instant.timestamp() * 1000)
    for i, (t, _, _) in enumerate(bars):
        if t > ms:
            return i
    return None


# --------------------------------------------------------------------------- #
# frozen state machines (PIT-enforced)
# --------------------------------------------------------------------------- #


def build_grid(
    stable: list[tuple[date, float, float]], bars: list[tuple[int, float, float]]
) -> list[date]:
    price_first = datetime.fromtimestamp(bars[0][0] / 1000, timezone.utc).date()
    price_last = datetime.fromtimestamp(bars[-1][0] / 1000, timezone.utc).date()
    first_signal = stable[0][0] + timedelta(days=395)
    grid_start = max(first_signal, price_first + timedelta(days=60), date(2013, 1, 1))
    grid = sundays(grid_start, price_last)
    check(
        "grid:matches_preregistered",
        grid[0].isoformat() == EXPECTED_GRID_FIRST
        and grid[-1].isoformat() == EXPECTED_GRID_LAST
        and len(grid) == EXPECTED_GRID_COUNT,
        f"{len(grid)} instants {grid[0]}..{grid[-1]}",
    )
    return grid


def stablecoin_states(
    rows: list[tuple[date, float, float]], grid: list[date]
) -> dict[date, dict[str, Any]]:
    """H-049-001: r30 growth vs its causal 365-day median, value dated t available at 00:00 t+1."""
    days = [r[0] for r in rows]
    series = {r[0]: r[1] for r in rows}
    index = {d: i for i, d in enumerate(days)}
    growth: dict[date, float] = {}
    for d in days:
        prior = d - timedelta(days=30)
        if prior in series and series[prior]:
            growth[d] = series[d] / series[prior] - 1.0
    baseline: dict[date, float] = {}
    for d in days:
        i = index[d]
        window = [growth[days[j]] for j in range(max(0, i - 365), i) if days[j] in growth]
        if len(window) >= 365:
            baseline[d] = statistics.median(window)

    out: dict[date, dict[str, Any]] = {}
    for sunday in grid:
        t_star = sunday - timedelta(days=2)  # value dated t is available at 00:00 of t+1
        while t_star >= days[0] and t_star not in series:
            t_star -= timedelta(days=1)
        if t_star < days[0]:
            out[sunday] = {"state": False, "available": False, "t_star": None}
            continue
        if t_star in growth and t_star in baseline:
            g, b = growth[t_star], baseline[t_star]
            availability = datetime(
                t_star.year, t_star.month, t_star.day, 0, 0, tzinfo=timezone.utc
            ) + timedelta(days=1)
            out[sunday] = {
                "state": g > b,
                "available": True,
                "t_star": t_star.isoformat(),
                "growth": g,
                "baseline": b,
                "availability_utc": availability.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        else:
            out[sunday] = {
                "state": False,
                "available": False,
                "t_star": t_star.isoformat() if t_star else None,
            }
    return out


def macro_states(
    inputs: dict[str, dict[date, float | None]], grid: list[date]
) -> tuple[dict[date, dict[str, Any]], dict[str, Any]]:
    """H-049-002: NL = WALCL/1000 − RRP − TGA/1000 on the Wednesday grid; delta over 4 weeks."""
    walcl, rrp, tga = inputs["WALCL"], inputs["RRPONTSYD"], inputs["WTREGEN"]
    cache: dict[date, dict[str, Any]] = {}
    stats = {"wednesdays_with_missing_input": 0, "reachback_days_used": [], "max_value_date": None}

    def level(wednesday: date) -> dict[str, Any] | None:
        if wednesday in cache:
            return cache[wednesday]
        w, wd = asof(walcl, wednesday, 7)
        t, td = asof(tga, wednesday, 7)
        r, rd = asof(rrp, wednesday, ASOF_MAX_REACHBACK_DAYS)
        if w is None or t is None or r is None:
            stats["wednesdays_with_missing_input"] += 1
            return None
        value = w / 1000.0 - r - t / 1000.0
        obs = [wd, td, rd]
        row = {
            "value": value,
            "obs_dates": [d.isoformat() for d in obs],
            "reachback_days": [(wednesday - d).days for d in obs],
        }
        cache[wednesday] = row
        for back in row["reachback_days"]:
            stats["reachback_days_used"].append(back)
        for d in obs:
            if stats["max_value_date"] is None or d.isoformat() > stats["max_value_date"]:
                stats["max_value_date"] = d.isoformat()
        return row

    out: dict[date, dict[str, Any]] = {}
    for sunday in grid:
        wednesday = sunday - timedelta(days=4)
        previous = wednesday - timedelta(weeks=4)
        now, before = level(wednesday), level(previous)
        if now is None or before is None:
            out[sunday] = {"state": False, "available": False, "wednesday": wednesday.isoformat()}
            continue
        delta = now["value"] - before["value"]
        serial_now = [sunday.year, sunday.month, sunday.day]
        availability = datetime(*serial_now, 0, 0, tzinfo=timezone.utc) - timedelta(days=4)
        availability += timedelta(
            days=1
        )  # conservative ≥1-day publication lag after the reference Wednesday
        out[sunday] = {
            "state": delta > 0,
            "available": True,
            "wednesday": wednesday.isoformat(),
            "nl_now": now["value"],
            "nl_prev": before["value"],
            "delta": delta,
            "obs_dates": now["obs_dates"],
            "availability_utc": availability.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    stats["reachback_days_used"] = sorted(set(stats["reachback_days_used"]))
    stats["max_reachback_days_used"] = (
        max(stats["reachback_days_used"]) if stats["reachback_days_used"] else None
    )
    return out, stats


def trend200_states(bars: list[tuple[int, float, float]], grid: list[date]) -> dict[date, bool]:
    """Own-price 200-day SMA long/cash state machine; closes strictly available at the decision."""
    closes: list[tuple[int, float]] = [(t, c) for (t, _, c) in bars]
    out: dict[date, bool] = {}
    for sunday in grid:
        cutoff_ms = int((decision_instant(sunday) - timedelta(days=1)).timestamp() * 1000)
        window = [c for (t, c) in closes if t <= cutoff_ms]
        if len(window) < 200:
            out[sunday] = False  # fail-closed before warmup
            continue
        out[sunday] = window[-1] > sum(window[-200:]) / 200.0
    return out


# --------------------------------------------------------------------------- #
# execution simulation
# --------------------------------------------------------------------------- #


def simulate(
    states: dict[date, bool], bars: list[tuple[int, float, float]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Closed long round trips; entry/exit at the first bar open strictly after the decision."""
    trips: list[dict[str, Any]] = []
    in_position = False
    entry: dict[str, Any] | None = None
    open_at_end: dict[str, Any] | None = None
    for sunday in sorted(states):
        instant = decision_instant(sunday)
        idx = bar_after(bars, instant)
        if states[sunday] and not in_position:
            if idx is None:
                continue
            in_position = True
            entry = {"sunday": sunday, "ms": bars[idx][0], "price": bars[idx][1]}
        elif not states[sunday] and in_position:
            if idx is None:
                continue
            exit_ms, exit_price = bars[idx][0], bars[idx][1]
            trips.append(
                {
                    "entry_sunday": entry["sunday"].isoformat(),
                    "entry_ms": entry["ms"],
                    "entry_price": entry["price"],
                    "exit_sunday": sunday.isoformat(),
                    "exit_ms": exit_ms,
                    "exit_price": exit_price,
                    "hold_days": int((exit_ms - entry["ms"]) / 86_400_000),
                    "gross_ret": exit_price / entry["price"] - 1.0,
                }
            )
            in_position = False
            entry = None
    if in_position and entry is not None:
        open_at_end = {
            "entry_sunday": entry["sunday"].isoformat(),
            "entry_ms": entry["ms"],
            "entry_price": entry["price"],
        }
    return trips, {"open_position_at_data_end": open_at_end, "transitions": len(trips)}


def partition_of(entry_sunday: str) -> str:
    return "development" if date.fromisoformat(entry_sunday) <= DEV_END else "validation"


# --------------------------------------------------------------------------- #
# statistics (procedure frozen in the execution plan)
# --------------------------------------------------------------------------- #


def stationary_bootstrap_means(
    net: list[float], draws: int, block_obs: int, seed: int
) -> list[float]:
    n = len(net)
    rng = random.Random(seed)
    p = 1.0 / block_obs
    means: list[float] = []
    for _ in range(draws):
        out: list[float] = []
        while len(out) < n:
            start = rng.randrange(n)
            i = start
            while True:
                out.append(net[i % n])
                i += 1
                if len(out) >= n or rng.random() < p:
                    break
        means.append(sum(out[:n]) / n)
    return means


def bootstrap_lcb(net: list[float], block_obs: int) -> dict[str, Any]:
    if len(net) < 2:
        return {"lcb_bps": None, "p_le_zero": None, "draws": 0, "block_obs": block_obs}
    means = sorted(stationary_bootstrap_means(net, BOOTSTRAP_DRAWS, block_obs, BOOTSTRAP_SEED))
    lcb = means[int(0.05 * len(means))]
    p = sum(1 for m in means if m <= 0.0) / len(means)
    return {
        "lcb_bps": lcb * 10_000.0,
        "p_le_zero": p,
        "draws": len(means),
        "block_obs": block_obs,
        "seed": BOOTSTRAP_SEED,
    }


def block_obs_for(trips: list[dict[str, Any]]) -> tuple[int, float | None]:
    if len(trips) < 2:
        return 1, None
    first = date.fromisoformat(trips[0]["entry_sunday"])
    last = date.fromisoformat(trips[-1]["entry_sunday"])
    spacing = (last - first).days / (len(trips) - 1)
    return max(1, round(BOOTSTRAP_BLOCK_DAYS / spacing)) if spacing > 0 else 1, spacing


def profit_factor(net: list[float]) -> float | None:
    gains = sum(r for r in net if r > 0)
    losses = -sum(r for r in net if r < 0)
    if losses == 0:
        return None if gains == 0 else math.inf
    return gains / losses


def max_drawdown(net: list[float]) -> float:
    equity, peak, worst = 1.0, 1.0, 0.0
    for r in net:
        equity *= 1.0 + r
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    return worst


def single_trade_share(net: list[float]) -> float | None:
    positives = [r for r in net if r > 0]
    total = sum(positives)
    if total <= 0:
        return None
    return max(positives) / total


def compounded(net: list[float]) -> float:
    eq = 1.0
    for r in net:
        eq *= 1.0 + r
    return eq - 1.0


def subwindow_splits(first: date, last: date, count: int) -> list[tuple[date, date]]:
    total = (last - first).days
    out = []
    for k in range(count):
        start = first + timedelta(days=round(total * k / count))
        end = first + timedelta(days=round(total * (k + 1) / count) - 1) if k < count - 1 else last
        out.append((start, end))
    return out


def metrics_for(
    trips: list[dict[str, Any]], cost_bps: float, span: tuple[date, date]
) -> dict[str, Any]:
    net = [t["gross_ret"] - cost_bps / 10_000.0 for t in trips]
    net125 = [t["gross_ret"] - cost_bps * 1.25 / 10_000.0 for t in trips]
    net150 = [t["gross_ret"] - cost_bps * 1.5 / 10_000.0 for t in trips]
    block_obs, spacing = block_obs_for(trips)
    lcb = bootstrap_lcb(net, block_obs)
    # preregistered robustness battery: LCB block-length sensitivity (1/2/3 trips)
    lcb2 = bootstrap_lcb(net, 2)
    lcb3 = bootstrap_lcb(net, 3)
    thirds = []
    for s, e in subwindow_splits(span[0], span[1], SUBWINDOW_COUNT):
        window = [t for t in trips if s <= date.fromisoformat(t["entry_sunday"]) <= e]
        wnet = [t["gross_ret"] - cost_bps / 10_000.0 for t in window]
        thirds.append(
            {
                "window": f"{s.isoformat()}..{e.isoformat()}",
                "round_trips": len(window),
                "net_sum_bps": sum(wnet) * 10_000.0 if window else None,
                "positive": (sum(wnet) > 0) if window else None,
            }
        )
    return {
        "round_trips": len(trips),
        "net_sum_bps": sum(net) * 10_000.0,
        "net_sum_usdt": STAKE_USDT * sum(net),
        "net_expectancy_bps": (sum(net) / len(net)) * 10_000.0 if net else None,
        "net_expectancy_usdt": STAKE_USDT * (sum(net) / len(net)) if net else None,
        "net_profit_factor": profit_factor(net),
        "net_compounded": compounded(net),
        "max_drawdown": max_drawdown(net),
        "single_trade_share_of_positive_net": single_trade_share(net),
        "stress_1_25x_net_sum_bps": sum(net125) * 10_000.0,
        "stress_1_5x_net_sum_bps": sum(net150) * 10_000.0,
        "stress_1_5x_expectancy_bps": (sum(net150) / len(net150)) * 10_000.0 if net150 else None,
        "lcb_95_net_expectancy_bps": lcb["lcb_bps"],
        "bootstrap_p_le_zero": lcb["p_le_zero"],
        "bootstrap_block_obs": block_obs,
        "lcb_block_sensitivity_bps": {
            "block_1": lcb["lcb_bps"],
            "block_2": lcb2["lcb_bps"],
            "block_3": lcb3["lcb_bps"],
        },
        "mean_entry_spacing_days": spacing,
        "subwindows": thirds,
        "subwindows_positive": sum(1 for t in thirds if t["positive"] is True),
        "subwindows_with_trips": sum(1 for t in thirds if t["round_trips"]),
        "median_hold_days": statistics.median([t["hold_days"] for t in trips]) if trips else None,
    }


def bh_net(
    bars: list[tuple[int, float, float]], first_sunday: date, last_sunday: date, cost_bps: float
) -> dict[str, Any]:
    i = bar_after(bars, decision_instant(first_sunday))
    j = bar_after(bars, decision_instant(last_sunday))
    if i is None or j is None or j <= i:
        return {"net": None, "note": "insufficient bars"}
    gross = bars[j][1] / bars[i][1] - 1.0
    return {
        "entry_ms": bars[i][0],
        "exit_ms": bars[j][0],
        "gross_ret": gross,
        "net_ret": gross - cost_bps / 10_000.0,
        "net_bps": (gross - cost_bps / 10_000.0) * 10_000.0,
    }


def bh_holm(p_values: dict[str, float]) -> dict[str, Any]:
    items = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(items)
    bh: dict[str, float] = {}
    prev = 1.0
    for rank in range(m, 0, -1):
        key, p = items[rank - 1]
        val = min(prev, p * m / rank)
        bh[key] = val
        prev = val
    holm: dict[str, float] = {}
    running = 0.0
    for rank, (key, p) in enumerate(items, start=1):
        val = min(1.0, max(running, (m - rank + 1) * p))
        holm[key] = val
        running = val
    return {
        "raw": p_values,
        "bh_adjusted": bh,
        "holm_adjusted": holm,
        "family_size": m,
        "note": "corrections are descriptive at the DEV/VAL stage; no threshold is moved by them",
    }


# --------------------------------------------------------------------------- #
# campaign evaluation
# --------------------------------------------------------------------------- #


def analyze_candidate(
    hid: str,
    states: dict[date, dict[str, Any]],
    grid: list[date],
    bars_by_asset: dict[str, list[tuple[int, float, float]]],
    cost: dict[str, float],
    plan_sha: str,
) -> dict[str, Any]:
    per_asset: dict[str, Any] = {}
    for asset, bars in bars_by_asset.items():
        trips, sim_meta = simulate({s: states[s]["state"] for s in grid}, bars)
        for t in trips:
            t["partition"] = partition_of(t["entry_sunday"])
        dev = [t for t in trips if t["partition"] == "development"]
        val = [t for t in trips if t["partition"] == "validation"]
        dev_span = (grid[0], DEV_END)
        val_span = (VAL_START, grid[-1])
        all_span = (grid[0], grid[-1])
        trend_states = trend200_states(bars, grid)
        trend_trips, _ = simulate(trend_states, bars)
        trend_dev = [t for t in trend_trips if partition_of(t["entry_sunday"]) == "development"]
        trend_val = [t for t in trend_trips if partition_of(t["entry_sunday"]) == "validation"]
        cost_bps = cost["round_trip_bps_200_usdt"]

        dev_m = metrics_for(dev, cost_bps, dev_span)
        val_m = metrics_for(val, cost_bps, val_span)
        all_m = metrics_for(trips, cost_bps, all_span)
        bh_dev = bh_net(bars, grid[0], max(s for s in grid if s <= DEV_END), cost_bps)
        bh_val = bh_net(bars, min(s for s in grid if s >= VAL_START), grid[-1], cost_bps)

        def trend_net(tt: list[dict[str, Any]]) -> float | None:
            if not tt:
                return None
            return compounded([t["gross_ret"] - cost_bps / 10_000.0 for t in tt])

        incrementals = {
            "development": {
                "strategy_net_compounded": dev_m["net_compounded"],
                "buy_and_hold_net": bh_dev["net_ret"],
                "buy_and_hold_incremental_bps": (dev_m["net_compounded"] - bh_dev["net_ret"])
                * 10_000.0,
                "trend_200d_net_compounded": trend_net(trend_dev),
                "trend_200d_incremental_bps": (
                    None
                    if trend_net(trend_dev) is None
                    else (dev_m["net_compounded"] - trend_net(trend_dev)) * 10_000.0
                ),
                "trend_200d_round_trips": len(trend_dev),
            },
            "validation": {
                "strategy_net_compounded": val_m["net_compounded"],
                "buy_and_hold_net": bh_val["net_ret"],
                "buy_and_hold_incremental_bps": (val_m["net_compounded"] - bh_val["net_ret"])
                * 10_000.0,
                "trend_200d_net_compounded": trend_net(trend_val),
                "trend_200d_incremental_bps": (
                    None
                    if trend_net(trend_val) is None
                    else (val_m["net_compounded"] - trend_net(trend_val)) * 10_000.0
                ),
                "trend_200d_round_trips": len(trend_val),
            },
        }
        straddlers = [
            t for t in trips if partition_of(t["entry_sunday"]) != partition_of(t["exit_sunday"])
        ]
        per_asset[asset] = {
            "development": dev_m,
            "validation": val_m,
            "all_exposed": all_m,
            "incrementals": incrementals,
            "straddling_trips": [
                {"entry_sunday": t["entry_sunday"], "exit_sunday": t["exit_sunday"]}
                for t in straddlers
            ],
            "simulation": sim_meta,
            "trend200_states_long_weeks": sum(1 for s in grid if trend_states[s]),
            "price_bars": {"count": len(bars), "first_ms": bars[0][0], "last_ms": bars[-1][0]},
        }

    # verdicts use the primary asset (BTCUSDT) with the frozen criteria computable on dev/val
    primary = per_asset["BTCUSDT"]
    criteria: dict[str, Any] = {}

    def row(name: str, value: Any, ok: bool | None, scope: str) -> None:
        criteria[name] = {"observed": value, "pass": ok, "scope": scope}

    dev, val = primary["development"], primary["validation"]
    row(
        "net_expectancy_positive:development",
        dev["net_expectancy_bps"],
        dev["net_expectancy_bps"] is not None and dev["net_expectancy_bps"] > 0,
        "computable",
    )
    row(
        "net_expectancy_positive:validation",
        val["net_expectancy_bps"],
        val["net_expectancy_bps"] is not None and val["net_expectancy_bps"] > 0,
        "computable",
    )
    row(
        "net_profit_factor_min:development",
        dev["net_profit_factor"],
        dev["net_profit_factor"] is not None and dev["net_profit_factor"] >= 1.1,
        "computable",
    )
    row(
        "net_profit_factor_min:validation",
        val["net_profit_factor"],
        val["net_profit_factor"] is not None and val["net_profit_factor"] >= 1.1,
        "computable",
    )
    row(
        "lcb_95_net_expectancy_positive:development",
        dev["lcb_95_net_expectancy_bps"],
        dev["lcb_95_net_expectancy_bps"] is not None and dev["lcb_95_net_expectancy_bps"] > 0,
        "computable",
    )
    row(
        "lcb_95_net_expectancy_positive:validation",
        val["lcb_95_net_expectancy_bps"],
        val["lcb_95_net_expectancy_bps"] is not None and val["lcb_95_net_expectancy_bps"] > 0,
        "computable",
    )
    row(
        "cost_stress_1_5x_net_positive:development",
        dev["stress_1_5x_net_sum_bps"],
        dev["stress_1_5x_net_sum_bps"] > 0,
        "computable",
    )
    row(
        "cost_stress_1_5x_net_positive:validation",
        val["stress_1_5x_net_sum_bps"],
        val["stress_1_5x_net_sum_bps"] > 0,
        "computable",
    )
    row(
        "positive_in_every_partition:development",
        dev["net_sum_bps"],
        dev["net_sum_bps"] > 0,
        "computable",
    )
    row(
        "positive_in_every_partition:validation",
        val["net_sum_bps"],
        val["net_sum_bps"] > 0,
        "computable",
    )
    row("positive_in_every_partition:sealed_oos", None, None, "deferred")
    row(
        "max_drawdown_le_0.25:development",
        dev["max_drawdown"],
        dev["max_drawdown"] <= 0.25,
        "computable",
    )
    row(
        "max_drawdown_le_0.25:validation",
        val["max_drawdown"],
        val["max_drawdown"] <= 0.25,
        "computable",
    )
    row(
        "single_trade_share_le_0.4:development",
        dev["single_trade_share_of_positive_net"],
        dev["single_trade_share_of_positive_net"] is None
        or dev["single_trade_share_of_positive_net"] <= 0.4,
        "computable",
    )
    row(
        "single_trade_share_le_0.4:validation",
        val["single_trade_share_of_positive_net"],
        val["single_trade_share_of_positive_net"] is None
        or val["single_trade_share_of_positive_net"] <= 0.4,
        "computable",
    )
    for part in ("development", "validation"):
        inc = primary["incrementals"][part]
        row(
            f"incremental_over_buy_and_hold_positive:{part}",
            inc["buy_and_hold_incremental_bps"],
            (inc["buy_and_hold_incremental_bps"] or -1) > 0,
            "computable",
        )
        row(
            f"incremental_over_200d_trend_baseline_positive:{part}",
            inc["trend_200d_incremental_bps"],
            (inc["trend_200d_incremental_bps"] or -1) > 0,
            "computable",
        )
    row("net_pnl_oos_positive", None, None, "deferred")
    row("minimum_oos_round_trips_or_months", None, None, "deferred")

    failed = [k for k, v in criteria.items() if v["pass"] is False]
    robustness_flags: list[str] = []
    for part in ("development", "validation"):
        m = primary[part]
        if m["subwindows_with_trips"] and m["subwindows_positive"] < m["subwindows_with_trips"]:
            if m["subwindows_positive"] <= m["subwindows_with_trips"] - 2:
                robustness_flags.append(f"SIGN_UNSTABLE:{part}")
            else:
                robustness_flags.append(f"PARTIAL_SIGN_STABILITY:{part}")
        sens = m["lcb_block_sensitivity_bps"]
        values = [v for v in sens.values() if v is not None]
        if values and not (all(v > 0 for v in values) or all(v <= 0 for v in values)):
            robustness_flags.append(f"LCB_FRAGILE:{part}")

    if failed:
        verdict = "CANDIDATE_REJECTED"
        verdict_reason = (
            "frozen criteria computable on the exposed partitions fail; the acceptance list can no longer "
            "be satisfied, so the candidate is closed at the DEV/VAL stage (policy §6)"
        )
    elif (
        "SIGN_UNSTABLE:development" in robustness_flags
        or "SIGN_UNSTABLE:validation" in robustness_flags
    ):
        verdict = "CANDIDATE_REJECTED"
        verdict_reason = "robustness battery: SIGN_UNSTABLE (hard robustness criterion, ST-3)"
    else:
        verdict = "PENDING_SEALED_OOS"
        verdict_reason = (
            "every computable criterion passes on the exposed partitions; the final verdict waits for the "
            "sealed forward window, which is closed today and no result here is confirmatory"
        )
    return {
        "per_asset": per_asset,
        "criteria": criteria,
        "failed_criteria": failed,
        "robustness_flags": robustness_flags,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "no_pass_possible_now": True,
    }


def pit_audit(
    grid: list[date],
    sig_a: dict[date, dict[str, Any]],
    sig_b: dict[date, dict[str, Any]],
) -> dict[str, Any]:
    """Every decision consumes only inputs available at least one hour before its instant."""
    audit: dict[str, Any] = {
        "H-049-001": {"violations": [], "max_value_date": None},
        "H-049-002": {"violations": [], "max_value_date": None},
    }
    for sunday in grid:
        cutoff = decision_instant(sunday) - timedelta(hours=1)
        a = sig_a[sunday]
        if a.get("available"):
            avail = datetime.strptime(a["availability_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if avail > cutoff:
                audit["H-049-001"]["violations"].append(
                    {"sunday": sunday.isoformat(), "availability": a["availability_utc"]}
                )
            if (
                audit["H-049-001"]["max_value_date"] is None
                or a["t_star"] > audit["H-049-001"]["max_value_date"]
            ):
                audit["H-049-001"]["max_value_date"] = a["t_star"]
        b = sig_b[sunday]
        if b.get("available"):
            avail = datetime.strptime(b["availability_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if avail > cutoff:
                audit["H-049-002"]["violations"].append(
                    {"sunday": sunday.isoformat(), "availability": b["availability_utc"]}
                )
            for d in b["obs_dates"]:
                if (
                    audit["H-049-002"]["max_value_date"] is None
                    or d > audit["H-049-002"]["max_value_date"]
                ):
                    audit["H-049-002"]["max_value_date"] = d
    check(
        "pit:H-049-001:no_future_input",
        not audit["H-049-001"]["violations"],
        f"{len(audit['H-049-001']['violations'])} violations",
    )
    check(
        "pit:H-049-002:no_future_input",
        not audit["H-049-002"]["violations"],
        f"{len(audit['H-049-002']['violations'])} violations",
    )
    for hid in audit:
        check(
            f"pit:{hid}:sealed_window_untouched",
            audit[hid]["max_value_date"] < SEALED_OOS_START.date().isoformat(),
            f"max consumed value date {audit[hid]['max_value_date']} < {SEALED_OOS_START.date()}",
        )
    return audit


def eligibility(
    trips_a: list[dict[str, Any]],
    trips_b: list[dict[str, Any]],
    grid: list[date],
    analysis_a: dict[str, Any],
    analysis_b: dict[str, Any],
) -> dict[str, Any]:
    """FASE 2 synthesis: technical, economic and statistical validity kept separate."""
    years = (grid[-1] - grid[0]).days / 365.25

    def feasibility(trips: list[dict[str, Any]]) -> dict[str, Any]:
        counts = {
            "development": sum(
                1 for t in trips if partition_of(t["entry_sunday"]) == "development"
            ),
            "validation": sum(1 for t in trips if partition_of(t["entry_sunday"]) == "validation"),
            "all_exposed": len(trips),
        }
        rate_month = len(trips) / (years * 12)
        return {
            "exposed_years_measured": round(years, 2),
            "round_trips": counts,
            "round_trips_per_year": round(len(trips) / years, 2),
            "round_trips_per_month": round(rate_month, 3),
            "expected_round_trips_in_24_month_sealed_window": round(rate_month * 24, 1),
            "months_to_reach_20_round_trips_at_measured_rate": round(20 / rate_month, 1)
            if rate_month
            else None,
            "sealed_window_risk": "INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION"
            if rate_month * 24 < 20
            else "floor reachable within 24 months at the measured rate",
        }

    def precision(rate_month: float) -> list[dict[str, Any]]:
        return [
            {
                "per_trip_information_ratio": ir,
                "round_trips_for_one_sided_95pct_precision": math.ceil((1.645 / ir) ** 2),
                "months_at_measured_rate": round(math.ceil((1.645 / ir) ** 2) / rate_month, 1),
            }
            for ir in (0.15, 0.20, 0.25, 0.30, 0.40)
        ]

    out: dict[str, Any] = {
        "artifact": "RFC049_DISCOVERY2_STATISTICAL_ELIGIBILITY",
        "generated_at_utc": utcnow(),
        "method": "frozen rules applied to research-exposed inputs; counts and rates only, no sealed data, thresholds unchanged",
        "statistical_criterion_unchanged": "20 round trips or 24 months, whichever comes first; fewer than 20 at 24 months is INSUFFICIENT_OOS_SAMPLE and is neither PASS nor REJECT",
        "thresholds_changed": False,
    }
    for hid, trips, analysis in (
        ("H-049-001", trips_a, analysis_a),
        ("H-049-002", trips_b, analysis_b),
    ):
        feas = feasibility(trips)
        verdict = analysis["verdict"]
        economic = {
            "verdict_at_devval_stage": verdict,
            "failed_criteria": analysis["failed_criteria"],
            "note": "economic validity is measured on RESEARCH_EXPOSED partitions; it is non-confirmatory and cannot promote anything",
        }
        statistical = {
            **feas,
            "promotion_blocker": (
                "the sealed OOS gate cannot be satisfied within the frozen 24-month window at the measured turnover; "
                "promotion as an independent strategy is therefore stopped regardless of the economic result"
                if feas["sealed_window_risk"] == "INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION"
                else "sealed OOS floor reachable at the measured turnover; promotion still requires the sealed opening"
            ),
        }
        out[hid] = {
            "technical_validity": {
                "spec": "SPEC_FROZEN",
                "pit": "PIT_CONSERVATIVE_PROXY" if hid == "H-049-001" else "PIT_VERIFIED",
                "pit_violations": 0,
                "contract_status": "valid",
            },
            "economic_validity": economic,
            "statistical_sufficiency": statistical,
            "precision_requirements": precision(len(trips) / (years * 12)),
        }
    out["independence_note"] = (
        "structural independence measured in RFC-049B is a property of the states, not of returns; "
        "return-level independence is what the DEV/VAL results of both candidates jointly show and is reported in ECONOMIC_RESULTS.json"
    )
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(description="RFC-049 Discovery 2 DEV/VAL engine (builder)")
    parser.add_argument(
        "--trades", action="store_true", help="also write per-candidate trade ledgers"
    )
    args = parser.parse_args()

    D2.mkdir(parents=True, exist_ok=True)
    log("stage: frozen input verification")
    verified = verified_inputs()
    plan_sha = sha256_file(EXECUTION_PLAN)
    auth = load_json(AUTHORIZATION)
    check(
        "authorization:scope",
        auth["authorization_scope"] == "OFFLINE_DEV_VAL_ONLY",
        auth["authorization_scope"],
    )

    log("stage: cost model re-derivation")
    cost = derived_cost_bps()

    log("stage: frozen series and grid")
    stable = defillama_rows(VENDOR_RAW / "defillama_stablecoin_supply_all.json")
    macro_inputs = {
        "WALCL": load_fred_csv(VENDOR_RAW / "fred_WALCL.csv"),
        "RRPONTSYD": load_fred_csv(VENDOR_RAW / "fred_RRPONTSYD.csv"),
        "WTREGEN": load_fred_csv(VENDOR_RAW / "fred_WTREGEN.csv"),
    }
    bars_by_asset = {asset: load_bars(PRICE_DIR / name) for asset, name in ASSETS.items()}
    grid = build_grid(stable, bars_by_asset["BTCUSDT"])

    log("stage: frozen-rule states")
    sig_a = stablecoin_states(stable, grid)
    sig_b, macro_stats = macro_states(macro_inputs, grid)
    pit = pit_audit(grid, sig_a, sig_b)

    trips_a, sim_a = simulate({s: sig_a[s]["state"] for s in grid}, bars_by_asset["BTCUSDT"])
    trips_b, sim_b = simulate({s: sig_b[s]["state"] for s in grid}, bars_by_asset["BTCUSDT"])
    counts_a = {
        "development": sum(1 for t in trips_a if partition_of(t["entry_sunday"]) == "development"),
        "validation": sum(1 for t in trips_a if partition_of(t["entry_sunday"]) == "validation"),
        "all_exposed": len(trips_a),
    }
    counts_b = {
        "development": sum(1 for t in trips_b if partition_of(t["entry_sunday"]) == "development"),
        "validation": sum(1 for t in trips_b if partition_of(t["entry_sunday"]) == "validation"),
        "all_exposed": len(trips_b),
    }
    check(
        "counts:H-049-001:match_rfc049b",
        counts_a == EXPECTED_TRIPS["H-049-001"],
        json.dumps(counts_a),
    )
    check(
        "counts:H-049-002:match_rfc049b",
        counts_b == EXPECTED_TRIPS["H-049-002"],
        json.dumps(counts_b),
    )

    log("stage: metrics and robustness")
    analysis_a = analyze_candidate("H-049-001", sig_a, grid, bars_by_asset, cost, plan_sha)
    analysis_b = analyze_candidate("H-049-002", sig_b, grid, bars_by_asset, cost, plan_sha)

    p_by_hypothesis_dev = {
        "H-049-001": analysis_a["per_asset"]["BTCUSDT"]["development"]["bootstrap_p_le_zero"],
        "H-049-002": analysis_b["per_asset"]["BTCUSDT"]["development"]["bootstrap_p_le_zero"],
    }
    p_by_hypothesis_val = {
        "H-049-001": analysis_a["per_asset"]["BTCUSDT"]["validation"]["bootstrap_p_le_zero"],
        "H-049-002": analysis_b["per_asset"]["BTCUSDT"]["validation"]["bootstrap_p_le_zero"],
    }
    corrections = {
        "development": bh_holm(p_by_hypothesis_dev),
        "validation": bh_holm(p_by_hypothesis_val),
    }

    log("stage: eligibility synthesis")
    elig = eligibility(trips_a, trips_b, grid, analysis_a, analysis_b)

    results = {
        "artifact": "RFC049_DISCOVERY2_ECONOMIC_RESULTS",
        "generated_at_utc": utcnow(),
        "builder": "scripts/rfc049c_engine.py",
        "head_at_run": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "execution_plan": {
            "path": "data/rfc049/discovery2/DISCOVERY2_EXECUTION_PLAN.md",
            "sha256": plan_sha,
        },
        "authorization": "data/rfc049/discovery2/CAMPAIGN_AUTHORIZATION.json",
        "frozen_inputs": {k: v for k, v in verified["spec_hashes"].items()},
        "cost_model": cost,
        "grid": {"first": grid[0].isoformat(), "last": grid[-1].isoformat(), "instants": len(grid)},
        "pit_audit": {
            "H-049-001": {
                "violations": len(pit["H-049-001"]["violations"]),
                "max_value_date": pit["H-049-001"]["max_value_date"],
            },
            "H-049-002": {
                "violations": len(pit["H-049-002"]["violations"]),
                "max_value_date": pit["H-049-002"]["max_value_date"],
            },
        },
        "macro_stats": macro_stats,
        "partition_policy": {
            "development": "entry Sunday <= 2023-12-31",
            "validation": "2024-01-01..2026-10-04",
            "sealed_oos": "CLOSED, not computed",
            "attribution": "partition of the entry Sunday; straddling trips listed",
        },
        "H-049-001": analysis_a,
        "H-049-002": analysis_b,
        "multiple_testing": corrections,
        "result_scope": {
            "classification": "RESEARCH_EXPOSED (development/validation), NON-CONFIRMATORY",
            "sealed_oos_opened": False,
            "no_pass_possible_now": True,
            "profitability_verified": False,
        },
        "checks": CHECKS,
        "checks_failed": sum(1 for c in CHECKS if c["result"] != "PASS"),
    }

    log("stage: writing artifacts")
    write_json(D2 / "ECONOMIC_RESULTS.json", results)
    write_json(D2 / "DISCOVERY2_STATISTICAL_ELIGIBILITY.json", elig)
    if args.trades:
        for hid, trips in (("H-049-001", trips_a), ("H-049-002", trips_b)):
            write_json(D2 / "trades" / f"{hid}_BTCUSDT.json", trips)

    for hid, res in (("H-049-001", analysis_a), ("H-049-002", analysis_b)):
        m = res["per_asset"]["BTCUSDT"]
        print(
            json.dumps(
                {
                    "hypothesis": hid,
                    "verdict": res["verdict"],
                    "development": {
                        "trips": m["development"]["round_trips"],
                        "net_sum_bps": round(m["development"]["net_sum_bps"], 2),
                        "expectancy_bps": round(m["development"]["net_expectancy_bps"], 2)
                        if m["development"]["net_expectancy_bps"] is not None
                        else None,
                    },
                    "validation": {
                        "trips": m["validation"]["round_trips"],
                        "net_sum_bps": round(m["validation"]["net_sum_bps"], 2),
                        "expectancy_bps": round(m["validation"]["net_expectancy_bps"], 2)
                        if m["validation"]["net_expectancy_bps"] is not None
                        else None,
                    },
                    "failed": res["failed_criteria"],
                    "flags": res["robustness_flags"],
                },
                indent=2,
            )
        )
    print(
        json.dumps(
            {"checks_total": len(CHECKS), "checks_failed": results["checks_failed"]}, indent=2
        )
    )
    return 1 if results["checks_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
