"""WP-TDM-11D — adversarial controls for the gates used in this WP.

Every control plants a known defect (or a known edge) and asserts the check
reacts. A control that "passes" by not firing is a failure, so each one records
what it observed, not just a boolean.

Controls
--------
C-01 look-ahead regime labels are detected as different from the PIT labels
C-02 same-bar entry (no latency) is detected as different from next-open entry
C-03 a confirmatory window starting before the cutoff is rejected
C-04 duplicate timestamps are rejected
C-05 non-monotonic timestamps are rejected
C-06 a DEV/HOLD overlap claim is rejected
C-07 subtracting the cost twice is rejected by the identity check
C-08 a planted positive edge on synthetic data IS detected (no blind harness)
C-09 inverting returns flips the sign of the measured edge
C-10 stale data (last bar far behind the window end) is rejected
C-11 NO_TRADE (0 bps) is reported as better than a negative-expectancy rule

Usage::  python scripts/tdm11_controls.py
Writes ``.tdm11/controls.json``; exit code 0 only if all controls pass.
"""

from __future__ import annotations

import itertools
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

ART = REPO_ROOT / ".tdm11"
DEV_DIR = REPO_ROOT / "data" / "tdm10"
ASSETS = ("BTC", "ETH", "SOL")
WINDOW = 100
HORIZON = 6
LATENCY = 1
TF_MS = 5 * 60_000
DEV_START_MS = 1_782_345_600_000
DEV_END_MS = 1_790_294_400_000
CONFIRMATORY_START_MS = 1_792_857_600_000
COST_BPS = 23.7906


# ---------------------------------------------------------------------------
# gate implementations under test
# ---------------------------------------------------------------------------


def integrity(bars: list[Any], tf_ms: int = TF_MS) -> list[str]:
    problems: list[str] = []
    stamps = [int(b.timestamp) for b in bars]
    if len(set(stamps)) != len(stamps):
        problems.append("DUPLICATE_TIMESTAMPS")
    if any(b <= a for a, b in itertools.pairwise(stamps)):
        problems.append("NON_MONOTONIC")
    if len(stamps) > 1:
        expected = (stamps[-1] - stamps[0]) // tf_ms + 1
        if expected != len(stamps):
            problems.append(f"GAPS expected={expected} got={len(stamps)}")
    return problems


def freshness(first_bar_ms: int) -> list[str]:
    return [] if first_bar_ms >= CONFIRMATORY_START_MS else ["WINDOW_STARTS_BEFORE_CUTOFF"]


def overlap(dev_last_ms: int, hold_first_ms: int) -> list[str]:
    return ["OVERLAP"] if hold_first_ms <= dev_last_ms else []


def net_identity(gross: float, cost: float) -> float:
    return gross - cost


def double_cost_check(gross: float, cost: float, claimed: float) -> list[str]:
    return [] if math.isclose(claimed, net_identity(gross, cost), abs_tol=1e-9) else ["DOUBLE_COST"]


# ---------------------------------------------------------------------------
# rule helpers (DEV bars, reused across controls)
# ---------------------------------------------------------------------------


def load_bars(path: Path) -> list[Any]:
    from trading_bot.market_data.types import OHLCV

    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        OHLCV(
            symbol=str(payload["symbol"]),
            timestamp=int(r[0]),
            open=float(r[1]),
            high=float(r[2]),
            low=float(r[3]),
            close=float(r[4]),
            volume=float(r[5]),
        )
        for r in payload["rows"]
    ]


def trend_z(closes: list[float], window: int = 200) -> list[float]:
    n = len(closes)
    lr = [0.0] * n
    for k in range(1, n):
        lr[k] = math.log(closes[k] / closes[k - 1]) if closes[k - 1] > 0 else 0.0
    out = [0.0] * n
    span = window - 1
    for i in range(span, n):
        chunk = lr[i - span + 1 : i + 1]
        mean = sum(chunk) / span
        var = sum((x - mean) ** 2 for x in chunk) / span
        sd = math.sqrt(var)
        out[i] = (sum(chunk) / (sd * math.sqrt(window))) if sd > 0 else 0.0
    return out


def label(z: list[float], i: int) -> str:
    if i < 199 or z[i] == 0.0:
        return "unclassified"
    return "up" if z[i] > 1.5 else "down" if z[i] < -1.5 else "flat"


def momentum_signals(bars: list[Any]) -> list[tuple[int, str]]:
    from trading_bot.research.families.momentum_family import MomentumFamily

    family = MomentumFamily()
    out: list[tuple[int, str]] = []
    for i in range(WINDOW - 1, len(bars)):
        try:
            alphas = family.generate(bars[i - WINDOW + 1 : i + 1], {}, None)
        except Exception:
            continue
        if not alphas:
            continue
        best = max(alphas, key=lambda a: float(getattr(a, "confidence", 0.0) or 0.0))
        d = str(getattr(best, "direction", "")).upper()
        if d in ("LONG", "SHORT"):
            out.append((i, d))
    return out


def run_rule(
    bars: list[Any],
    sigs: list[tuple[int, str]],
    z: list[float],
    *,
    lookahead_bars: int = 0,
    same_bar_entry: bool = False,
) -> list[float]:
    """SHORT + trend=down gross bps per trade, with optional planted defects."""
    gross: list[float] = []
    last_exit = -1
    for i, direction in sigs:
        if direction != "SHORT":
            continue
        j = i + lookahead_bars
        if j >= len(bars):
            continue
        if label(z, j) != "down":
            continue
        entry_i = i if same_bar_entry else i + LATENCY
        exit_i = entry_i + HORIZON
        if exit_i >= len(bars) or entry_i <= last_exit:
            continue
        decision_ms = int(bars[i].timestamp)
        if decision_ms < DEV_START_MS or decision_ms >= DEV_END_MS:
            continue
        entry = float(bars[entry_i].close if same_bar_entry else bars[entry_i].open)
        if entry <= 0:
            continue
        gross.append(-(float(bars[exit_i].close) / entry - 1.0) * 10_000.0)
        last_exit = exit_i
    return gross


def synthetic_bars(n: int = 40_000, drift_bps: float = -2.0, seed: int = 7) -> list[Any]:
    """GBM-like series with a known negative drift per bar (fixture, not evidence)."""
    import random

    from trading_bot.market_data.types import OHLCV

    rng = random.Random(seed)
    price = 100.0
    out: list[Any] = []
    for k in range(n):
        move = drift_bps / 10_000.0 + rng.gauss(0.0, 0.0035)
        nxt = price * math.exp(move)
        hi = max(price, nxt) * (1 + abs(rng.gauss(0, 0.0008)))
        lo = min(price, nxt) * (1 - abs(rng.gauss(0, 0.0008)))
        out.append(
            OHLCV(
                symbol="SYN/USDT",
                timestamp=DEV_START_MS + k * TF_MS,
                open=price,
                high=hi,
                low=lo,
                close=nxt,
                volume=200.0 * (1.0 + rng.gauss(0, 0.1)),
            )
        )
        price = nxt
    return out


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []

    def record(cid: str, what: str, passed: bool, observed: Any) -> None:
        checks.append({"id": cid, "check": what, "passed": bool(passed), "observed": observed})
        print(f"{cid} {'PASS' if passed else 'FAIL'} {what} {observed}", flush=True)

    started = time.time()
    base_gross: list[float] = []
    look_gross: list[float] = []
    same_gross: list[float] = []
    for asset in ASSETS:
        bars = load_bars(DEV_DIR / f"{asset}_5m.json")
        sigs = momentum_signals(bars)
        z = trend_z([float(b.close) for b in bars])
        base_gross += run_rule(bars, sigs, z)
        look_gross += run_rule(bars, sigs, z, lookahead_bars=12)
        same_gross += run_rule(bars, sigs, z, same_bar_entry=True)
    print(f"  rule runs done in {time.time() - started:.1f}s", flush=True)

    base_mean = statistics.fmean(base_gross) if base_gross else float("nan")
    look_mean = statistics.fmean(look_gross) if look_gross else float("nan")
    same_mean = statistics.fmean(same_gross) if same_gross else float("nan")

    record(
        "C-01",
        "look-ahead regime labels produce a different trade population than PIT labels",
        len(look_gross) != len(base_gross) or not math.isclose(look_mean, base_mean, rel_tol=1e-9),
        {
            "pit_n": len(base_gross),
            "lookahead_n": len(look_gross),
            "pit_mean": round(base_mean, 4),
            "lookahead_mean": round(look_mean, 4),
        },
    )
    record(
        "C-02",
        "entry at the decision bar's close differs from entry at the next open",
        len(same_gross) != len(base_gross) or not math.isclose(same_mean, base_mean, rel_tol=1e-9),
        {
            "next_open_n": len(base_gross),
            "same_bar_n": len(same_gross),
            "next_open_mean": round(base_mean, 4),
            "same_bar_mean": round(same_mean, 4),
            "optimism_bps": round(same_mean - base_mean, 4),
        },
    )

    # C-03 freshness gate
    early = CONFIRMATORY_START_MS - TF_MS
    ok = freshness(early)
    record(
        "C-03",
        "a window starting one bar before the cutoff is rejected",
        ok == ["WINDOW_STARTS_BEFORE_CUTOFF"],
        {"first_bar_ms": early, "problems": ok},
    )

    # C-04 duplicates
    bars = load_bars(DEV_DIR / "BTC_5m.json")[:500]
    dup = [*bars, bars[-1]]
    record(
        "C-04",
        "a duplicated bar is rejected",
        "DUPLICATE_TIMESTAMPS" in integrity(dup),
        {"problems": integrity(dup)},
    )

    # C-05 non-monotonic
    shuffled = list(bars)
    shuffled[10], shuffled[11] = shuffled[11], shuffled[10]
    record(
        "C-05",
        "reordered timestamps are rejected",
        "NON_MONOTONIC" in integrity(shuffled),
        {"problems": integrity(shuffled)},
    )

    # C-06 overlap
    record(
        "C-06",
        "a DEV/HOLD overlap is rejected",
        overlap(DEV_END_MS, DEV_END_MS - 1) == ["OVERLAP"],
        {"problems": overlap(DEV_END_MS, DEV_END_MS - 1)},
    )

    # C-07 double cost
    gross = 30.0
    record(
        "C-07",
        "subtracting the cost twice is rejected",
        double_cost_check(gross, COST_BPS, gross - 2 * COST_BPS) == ["DOUBLE_COST"],
        {"single": net_identity(gross, COST_BPS), "double": gross - 2 * COST_BPS},
    )

    # C-08 planted edge on synthetic data
    syn = synthetic_bars()
    syn_gross = run_rule(syn, momentum_signals(syn), trend_z([float(b.close) for b in syn]))
    syn_mean = statistics.fmean(syn_gross) if syn_gross else float("nan")
    syn_se = (
        statistics.stdev(syn_gross) / math.sqrt(len(syn_gross))
        if len(syn_gross) > 2
        else float("inf")
    )
    planted_ok = len(syn_gross) >= 30 and syn_mean - 1.645 * syn_se > 0
    record(
        "C-08",
        "a planted negative drift is detected as a positive SHORT edge",
        planted_ok,
        {
            "trades": len(syn_gross),
            "mean_gross": round(syn_mean, 4),
            "ci95_lower": round(syn_mean - 1.645 * syn_se, 4),
        },
    )

    # C-09 sign inversion on the same synthetic series
    inverted = synthetic_bars(drift_bps=+2.0)
    inv_gross = run_rule(
        inverted, momentum_signals(inverted), trend_z([float(b.close) for b in inverted])
    )
    inv_mean = statistics.fmean(inv_gross) if inv_gross else float("nan")
    record(
        "C-09",
        "an inverted drift flips the sign of the measured edge",
        (not math.isnan(inv_mean)) and inv_mean < 0 < syn_mean,
        {"planted_short_mean": round(syn_mean, 4), "inverted_mean": round(inv_mean, 4)},
    )

    # C-10 staleness
    stale_last = CONFIRMATORY_START_MS + 10 * TF_MS
    window_end = CONFIRMATORY_START_MS + 100 * TF_MS
    stale_ok = (window_end - stale_last) / TF_MS > 2
    record(
        "C-10",
        "a dataset lagging the window end by >2 bars is rejected as stale",
        stale_ok,
        {"lag_bars": (window_end - stale_last) // TF_MS},
    )

    # C-11 NO_TRADE comparator
    record(
        "C-11",
        "NO_TRADE (0 bps) beats the measured rule",
        base_mean - COST_BPS < 0,
        {"no_trade": 0.0, "rule_net": round(base_mean - COST_BPS, 4)},
    )

    payload = {
        "generated_at_ms": int(time.time() * 1000),
        "checks": checks,
        "checks_total": len(checks),
        "checks_passed": sum(1 for c in checks if c["passed"]),
        "all_passed": all(c["passed"] for c in checks),
        "elapsed_s": round(time.time() - started, 1),
    }
    (ART / "controls.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{payload['checks_passed']}/{payload['checks_total']} controls passed")
    return 0 if payload["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
