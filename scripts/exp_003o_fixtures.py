"""exp_003o_fixtures — deterministic synthetic series for functional coverage.

A cell with no real sample cannot be certified by two empty lists. These fixtures give every
zero-sample family a series on which its rule is known to fire, and a second series on which it
must stay silent, so the two implementations can be compared on a *decision* rather than on an
absence.

The series are synthetic, deterministic and independent of the market: a fixed LCG drives the
noise, and one named event (a breakout bar, a flush, a pullback) is placed at a fixed index.
They prove implementation behaviour under known conditions. They prove nothing about regimes,
costs or edge, and they are not evidence for any economic claim.

Usage
-----
``python scripts/exp_003o_fixtures.py --out fixtures``
``python scripts/exp_003o_fixtures.py --search`` (prints, per family, where the rule first fires)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for extra in (REPO / "scripts", REPO / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from exp_003o_contract import OUT, TIMEFRAME_MS, write_json  # noqa: E402

GENERATOR = "synthetic_lcg_v1"
BARS = 1400
START_MS = 1_700_000_000_000


class Lcg:
    """A 31-bit linear congruential generator: deterministic, seeded, no library state."""

    def __init__(self, seed: int) -> None:
        self.state = (seed * 2_654_435_761 + 1) % (2**31)

    def uniform(self) -> float:
        self.state = (1_103_515_245 * self.state + 12_345) % (2**31)
        return self.state / float(2**31)


def _bar(ts: int, open_price: float, close: float, wick: float, volume: float) -> dict[str, float]:
    return {
        "ts_ms": float(ts),
        "open": open_price,
        "high": max(open_price, close) * (1.0 + wick),
        "low": min(open_price, close) * (1.0 - wick),
        "close": close,
        "volume": volume,
    }


def rising_breakout(seed: int, bars: int = BARS, event: int = 1000) -> list[dict[str, float]]:
    """Up drift with a volatility cycle; one impulse bar clears the trailing channel."""

    rng = Lcg(seed)
    price = 100.0
    out: list[dict[str, float]] = []
    for index in range(bars):
        volatility = 0.0035 + 0.0025 * (1.0 + math.sin(2.0 * math.pi * index / 240.0))
        shock = 0.006 if index == event else 0.0
        if index == event:
            volatility = 0.0055
        step = 0.00035 + (rng.uniform() - 0.5) * volatility + shock
        close = price * (1.0 + step)
        volume = 100.0 * (1.0 + rng.uniform()) * (3.0 if index == event else 1.0)
        out.append(_bar(START_MS + index * 3_600_000, price, close, volatility * 0.4, volume))
        price = close
    return out


def flat_no_breakout(seed: int) -> list[dict[str, float]]:
    """A mean-reverting range: no close ever clears the trailing channel."""

    rng = Lcg(seed)
    out: list[dict[str, float]] = []
    price = 100.0
    for index in range(BARS):
        target = 100.0 + 0.9 * math.sin(2.0 * math.pi * index / 96.0)
        close = price + 0.25 * (target - price) + (rng.uniform() - 0.5) * 0.25
        volume = 100.0 * (1.0 + 0.2 * rng.uniform())
        out.append(_bar(START_MS + index * 3_600_000, price, close, 0.0012, volume))
        price = close
    return out


def trend_with_pullback(seed: int, bars: int = BARS, event: int = 900) -> list[dict[str, float]]:
    """Steady uptrend, a six-bar dip under the fast mean, then the reclaim."""

    rng = Lcg(seed)
    price = 100.0
    out: list[dict[str, float]] = []
    for index in range(bars):
        dip = -0.0035 if event <= index < event + 6 else 0.0
        reclaim = 0.025 if index == event + 6 else 0.0
        step = 0.00045 + (rng.uniform() - 0.5) * 0.0025 + dip + reclaim
        close = price * (1.0 + step)
        volume = 100.0 * (1.0 + 0.3 * rng.uniform())
        out.append(_bar(START_MS + index * 3_600_000, price, close, 0.0012, volume))
        price = close
    return out


def monotone_decline(seed: int) -> list[dict[str, float]]:
    rng = Lcg(seed)
    price = 100.0
    out: list[dict[str, float]] = []
    for index in range(BARS):
        step = -0.00055 + (rng.uniform() - 0.5) * 0.0015
        close = price * (1.0 + step)
        volume = 100.0 * (1.0 + 0.2 * rng.uniform())
        out.append(_bar(START_MS + index * 3_600_000, price, close, 0.0010, volume))
        price = close
    return out


def flush_in_range(seed: int, bars: int = BARS, event: int = 1000) -> list[dict[str, float]]:
    """Decaying volatility, then a two-sigma flush on a volume spike."""

    rng = Lcg(seed)
    price = 100.0
    out: list[dict[str, float]] = []
    for index in range(bars):
        scale = 2.0 if index < 200 else max(0.1, 2.0 - 1.9 * (index - 200) / 900.0)
        step = (rng.uniform() - 0.5) * 0.006 * scale
        if index == event:
            step -= 0.006
        close = price * (1.0 + step)
        volume = 100.0 * (1.0 + 0.4 * rng.uniform()) * (5.0 if index == event else 1.0)
        out.append(_bar(START_MS + index * 3_600_000, price, close, 0.0015, volume))
        price = close
    return out


def quiet_range(seed: int) -> list[dict[str, float]]:
    rng = Lcg(seed)
    price = 100.0
    out: list[dict[str, float]] = []
    for index in range(BARS):
        step = (rng.uniform() - 0.5) * 0.0015
        close = price * (1.0 + step)
        volume = 100.0 * (1.0 + 0.1 * rng.uniform())
        out.append(_bar(START_MS + index * 3_600_000, price, close, 0.0008, volume))
        price = close
    return out


BUILDERS: dict[str, Any] = {
    "vol_regime_breakout_active": rising_breakout,
    "vol_regime_breakout_quiet": flat_no_breakout,
    "trend_pullback_active": trend_with_pullback,
    "trend_pullback_quiet": monotone_decline,
    "mean_reversion_vol_liq_active": flush_in_range,
    "mean_reversion_vol_liq_quiet": quiet_range,
}


def build(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for spec in protocol["fixtures"]:
        fixture_id = str(spec["fixture_id"])
        builder = BUILDERS[fixture_id]
        bars = builder(int(spec["generator_seed"]))
        payloads.append(
            {
                "fixture_id": fixture_id,
                "family": spec["family"],
                "cell_id": f"{spec['family']}@{spec['timeframe']}",
                "timeframe": spec["timeframe"],
                "generator": GENERATOR,
                "generator_seed": int(spec["generator_seed"]),
                "regime": spec["regime"],
                "expected": spec["expected"],
                "bars": bars,
            }
        )
    return payloads


def _frozen_bars(payload: dict[str, Any]) -> list[Any]:
    from trading_bot.research.economic_recovery.experiments import Bar

    return [
        Bar(
            ts_ms=int(item["ts_ms"]),
            open=float(item["open"]),
            high=float(item["high"]),
            low=float(item["low"]),
            close=float(item["close"]),
            volume=float(item["volume"]),
        )
        for item in payload["bars"]
    ]


def search(protocol: dict[str, Any]) -> int:
    """Report where each frozen fixture makes the frozen machine fire, if it does.

    The count is of **ENTRY decisions**, not of closed trades: a position still open at the
    last bar is a legitimate activation, and a search that only counted closed trades would
    call it silence.
    """

    from trading_bot.research.economic_recovery.pit15 import machine_for

    failures = 0
    for payload in build(protocol):
        params = dict(
            next(
                cell["parameters"]
                for cell in protocol["cells"]
                if cell["cell_id"] == payload["cell_id"]
            )
        )
        machine = machine_for(payload["family"], params)
        entries: list[int] = []
        in_position = False
        for index, bar in enumerate(_frozen_bars(payload)):
            decision = machine.on_closed_bar(index, bar, in_position=in_position)
            if decision is not None and decision.kind == "ENTRY":
                entries.append(index)
                in_position = True
                machine.notify_fill("ENTRY", index + 1, bar.close)
            elif decision is not None and decision.kind == "EXIT":
                in_position = False
                machine.notify_fill("EXIT", index + 1, bar.close)
        expected_active = "active" in payload["fixture_id"]
        ok = bool(entries) == expected_active
        failures += int(not ok)
        print(
            f"[003o-fixtures] {payload['fixture_id']}: entries={len(entries)} "
            f"first={entries[0] if entries else None} expected_active={expected_active} "
            f"{'OK' if ok else 'FAIL'}"
        )
    return 0 if failures == 0 else 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EXP-003O synthetic fixtures")
    parser.add_argument("--protocol", default=str(OUT / "design" / "PROTOCOL.json"))
    parser.add_argument("--out", default=str(OUT / "fixtures"))
    parser.add_argument("--search", action="store_true")
    args = parser.parse_args(argv)
    protocol = json.loads(Path(args.protocol).read_text(encoding="utf-8"))
    if args.search:
        return search(protocol)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for payload in build(protocol):
        target = out / f"{payload['fixture_id']}.json"
        target.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        manifest.append(
            {
                "fixture_id": payload["fixture_id"],
                "family": payload["family"],
                "cell_id": payload["cell_id"],
                "bars": len(payload["bars"]),
                "bytes": target.stat().st_size,
                "expected": payload["expected"],
                "generator": GENERATOR,
                "generator_seed": payload["generator_seed"],
                "interval_ms": TIMEFRAME_MS[str(payload["timeframe"])],
            }
        )
        print(f"[003o-fixtures] wrote {target.name} ({len(payload['bars'])} bars)")
    write_json(out / "FIXTURE_MANIFEST.json", {"generator": GENERATOR, "fixtures": manifest})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
