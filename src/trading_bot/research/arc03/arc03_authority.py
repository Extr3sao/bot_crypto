"""ARC-03 participation authority reader + frozen feature layer (PIT-causal).

Frozen ARC-03 primitives (all parameter-free by construction):

* **PARTICIPATION_SHOCK** at bar ``t``: ``volume(t)`` is strictly greater than the
  volume at the SAME 5m time-of-day slot on EACH of the previous 30 calendar days
  (a same-slot participation record). All 30 reference observations must be present,
  otherwise the decision fails closed.
* **DISPROPORTIONATE_RESPONSE** at bar ``t``: ``range(t) = high - low`` is strictly
  greater than the range at the same 5m slot on each of the same previous 30 days.
* **EXHAUSTION**: the close retraces strictly more than half of the bar's excursion
  against the body direction:
    body > 0 and (high - close) > range/2   -> the up-push was rejected
    body < 0 and (close - low)  > range/2   -> the down-push was rejected
* **DIRECTION** (contrarian to the rejected push): up-push rejected -> SHORT;
  down-push rejected -> LONG.

Time semantics (PIT):

* a bar is usable only once COMPLETE: ``bar_close_time_ms`` (provider field 6) is the
  decision instant;
* ``decision_time_ms = bar_close_time_ms``; the signal bar is never read before it closes;
* every reference observation satisfies ``data_time <= decision_time``;
* entry is the OPEN of the first bar with ``bar_open_time_ms > decision_time_ms``
  (strictly after the decision);
* exit is the OPEN of the bar at ``entry_open_time_ms + HOLDING_BARS * BAR_MS``.
"""

from __future__ import annotations

import json
import os
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trading_bot.research.arc03.arc03_normalize import BAR_MS, canonical_json, sha256_bytes, sha256_file

REPO = Path(__file__).resolve().parents[4]
PARTITION_RELPATH = Path("data") / "processed" / "arc03_klines_5m"
PARTITION_DIR = REPO / PARTITION_RELPATH


def resolve_partition_dir(data_root: Path | str | None = None) -> Path:
    """Partition directory under an explicit or env-provided data root.

    Resolution order: explicit ``data_root`` argument -> ``ARC03_DATA_ROOT`` env ->
    the certified in-tree repository root. Used by the portable read-only verifier so
    a wrong data root can be detected and failed closed instead of being trusted.
    """
    if data_root is None:
        env = os.environ.get("ARC03_DATA_ROOT")
        if env:
            data_root = env
    base = Path(data_root) if data_root is not None else REPO
    if not base.is_absolute():
        raise ValueError(f"ARC03 data root must be an absolute path, got {base!r}")
    return base / PARTITION_RELPATH

ASSETS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

# ---- frozen ARC-03 constants -------------------------------------------------
REFERENCE_DAYS: int = 30
DAY_MS: int = 86_400_000
REQUIRED_REFERENCE_OBSERVATIONS: int = REFERENCE_DAYS
HOLDING_BARS: int = 12
HOLDING_MS: int = HOLDING_BARS * BAR_MS  # 60 minutes
NULL_SEED: int = 20260915
BOOTSTRAP_SEED: int = 20260915
BOOTSTRAP_RESAMPLES: int = 10_000
PERMUTATION_DRAWS: int = 10_000
PERMUTATION_ALPHA: float = 0.05
COST_SCENARIOS_BPS: tuple[int, ...] = (0, 10, 20, 40)
PRIMARY_COST_BPS: int = 10
G1_MIN_TOTAL_TRADES: int = 120
G1_MIN_TRADES_PER_ASSET: int = 40
G4_MIN_PROFIT_FACTOR: float = 1.15
G5_MIN_SHARPE: float = 0.50
MAX_ABS_DAILY_PNL_CORRELATION: float = 0.50

LONG = "LONG"
SHORT = "SHORT"
NO_SIGNAL = "NO_SIGNAL"

#: Frozen NO_SIGNAL precedence (first satisfied reason wins).
NO_SIGNAL_PRECEDENCE: tuple[str, ...] = (
    "OUTSIDE_COMMON_WINDOW",
    "REFERENCE_HISTORY_INCOMPLETE",
    "NO_PARTICIPATION_SHOCK",
    "NO_EXCURSION_RECORD",
    "NO_EXHAUSTION",
    "POSITION_ALREADY_OPEN",
    "INSUFFICIENT_FORWARD_PRICE_DATA",
)


@dataclass(frozen=True)
class Kline5m:
    """Certified 5m participation partition for one symbol (PIT-causal reads)."""

    symbol: str
    t: tuple[int, ...]
    ct: tuple[int, ...]
    o: tuple[float, ...]
    h: tuple[float, ...]
    l: tuple[float, ...]
    c: tuple[float, ...]
    v: tuple[float, ...]
    qv: tuple[float, ...]
    n: tuple[int, ...]
    tb: tuple[float, ...]
    tq: tuple[float, ...]
    sha256: str
    path: str
    rows: int
    index: dict[int, int] = field(default_factory=dict, repr=False)

    def slot_index(self, open_time_ms: int) -> int | None:
        return self.index.get(open_time_ms)

    def last_completed_index(self, decision_time_ms: int) -> int | None:
        """Position of the last bar whose provided close_time_ms <= decision_time_ms."""
        pos = bisect_right(self.ct, decision_time_ms) - 1
        return pos if pos >= 0 else None

    def first_index_strictly_after(self, t_ms: int) -> int | None:
        pos = bisect_right(self.t, t_ms)
        return pos if pos < len(self.t) else None


def load_partition(symbol: str, *, partition_dir: Path | None = None, verify: bool = True) -> Kline5m:
    base = partition_dir if partition_dir is not None else resolve_partition_dir()
    path = base / f"{symbol}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"missing ARC-03 partition: {path}")
    ts: list[int] = []
    cts: list[int] = []
    o: list[float] = []
    h: list[float] = []
    l: list[float] = []
    c: list[float] = []
    v: list[float] = []
    qv: list[float] = []
    n: list[int] = []
    tb: list[float] = []
    tq: list[float] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            ts.append(int(r["t"]))
            cts.append(int(r["ct"]))
            o.append(float(r["o"]))
            h.append(float(r["h"]))
            l.append(float(r["l"]))
            c.append(float(r["c"]))
            v.append(float(r["v"]))
            qv.append(float(r["qv"]))
            n.append(int(r["n"]))
            tb.append(float(r["tb"]))
            tq.append(float(r["tq"]))
    order = sorted(range(len(ts)), key=lambda i: ts[i])
    if order != list(range(len(ts))):
        ts = [ts[i] for i in order]
        cts = [cts[i] for i in order]
        o = [o[i] for i in order]
        h = [h[i] for i in order]
        l = [l[i] for i in order]
        c = [c[i] for i in order]
        v = [v[i] for i in order]
        qv = [qv[i] for i in order]
        n = [n[i] for i in order]
        tb = [tb[i] for i in order]
        tq = [tq[i] for i in order]
    if len(set(ts)) != len(ts):
        raise ValueError(f"CONFLICTING_OR_DUPLICATE_SLOT in {symbol}")
    index = {t: i for i, t in enumerate(ts)}
    digest = sha256_file(path) if verify else ""
    return Kline5m(
        symbol=symbol,
        t=tuple(ts),
        ct=tuple(cts),
        o=tuple(o),
        h=tuple(h),
        l=tuple(l),
        c=tuple(c),
        v=tuple(v),
        qv=tuple(qv),
        n=tuple(n),
        tb=tuple(tb),
        tq=tuple(tq),
        sha256=digest,
        path=str(path),
        rows=len(ts),
        index=index,
    )


def reference_slots(open_time_ms: int, days: int = REFERENCE_DAYS) -> list[int]:
    """The same 5m time-of-day slot on each of the previous ``days`` calendar days."""
    return [open_time_ms - DAY_MS * j for j in range(1, days + 1)]


def evaluate_bar(k: Kline5m, i: int) -> dict[str, Any]:
    """Frozen ARC-03 feature evaluation for bar position ``i`` (no outcome information)."""
    t = k.t[i]
    close_time = k.ct[i]
    refs = reference_slots(t)
    ref_volumes: list[float] = []
    ref_ranges: list[float] = []
    missing = 0
    for slot in refs:
        j = k.index.get(slot)
        if j is None:
            missing += 1
            continue
        ref_volumes.append(k.v[j])
        ref_ranges.append(k.h[j] - k.l[j])
    out: dict[str, Any] = {
        "symbol": k.symbol,
        "bar_open_time_ms": t,
        "decision_time_ms": close_time,
        "reference_observations_present": len(ref_volumes),
        "reference_observations_required": REQUIRED_REFERENCE_OBSERVATIONS,
        "reference_missing": missing,
    }
    if missing:
        out.update(result=NO_SIGNAL, reason="REFERENCE_HISTORY_INCOMPLETE", emitted=False)
        return out

    range_ = k.h[i] - k.l[i]
    body = k.c[i] - k.o[i]
    out["volume"] = k.v[i]
    out["range"] = range_
    out["body"] = body
    out["reference_volume_max"] = max(ref_volumes)
    out["reference_range_max"] = max(ref_ranges)

    volume_record = k.v[i] > max(ref_volumes)
    range_record = range_ > max(ref_ranges)
    out["participation_shock"] = volume_record
    out["excursion_record"] = range_record

    if not volume_record:
        out.update(result=NO_SIGNAL, reason="NO_PARTICIPATION_SHOCK", emitted=False)
        return out
    if not range_record:
        out.update(result=NO_SIGNAL, reason="NO_EXCURSION_RECORD", emitted=False)
        return out
    if range_ <= 0.0 or body == 0.0:
        out.update(result=NO_SIGNAL, reason="NO_EXHAUSTION", emitted=False)
        return out

    if body > 0.0:
        exhausted = (k.h[i] - k.c[i]) > range_ / 2.0
        direction = SHORT
        wick_fraction = (k.h[i] - k.c[i]) / range_
    else:
        exhausted = (k.c[i] - k.l[i]) > range_ / 2.0
        direction = LONG
        wick_fraction = (k.c[i] - k.l[i]) / range_
    out["wick_fraction"] = wick_fraction
    if not exhausted:
        out.update(result=NO_SIGNAL, reason="NO_EXHAUSTION", emitted=False)
        return out
    out.update(result=direction, reason=None, emitted=True)
    return out


def common_causal_window(partitions: dict[str, Kline5m]) -> dict[str, Any]:
    """Exact intersection of the admitted 5m authority coverage across assets."""
    firsts = {s: k.t[0] for s, k in partitions.items()}
    lasts = {s: k.t[-1] for s, k in partitions.items()}
    start = max(firsts.values())
    end = min(lasts.values())
    return {
        "derivation": "max(first admitted bar open) .. min(last admitted bar open) across the three assets",
        "start_ms": start,
        "end_ms": end,
        "per_asset_first_open_ms": firsts,
        "per_asset_last_open_ms": lasts,
        "bound_semantics": "CLOSED interval on 5m bar-OPEN times: bar_open_time_ms in [start_ms, end_ms]",
        "window_span_days_inclusive": (end - start + BAR_MS) / DAY_MS,
    }


def partition_fingerprint(partitions: dict[str, Kline5m]) -> dict[str, Any]:
    return {
        "partition_sha256": {s: k.sha256 for s, k in partitions.items()},
        "rows": {s: k.rows for s, k in partitions.items()},
        "aggregate_sha256": sha256_bytes(canonical_json({s: k.sha256 for s, k in sorted(partitions.items())})),
    }


__all__ = [
    "ASSETS",
    "BAR_MS",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "COST_SCENARIOS_BPS",
    "DAY_MS",
    "G1_MIN_TOTAL_TRADES",
    "G1_MIN_TRADES_PER_ASSET",
    "G4_MIN_PROFIT_FACTOR",
    "G5_MIN_SHARPE",
    "HOLDING_BARS",
    "HOLDING_MS",
    "Kline5m",
    "LONG",
    "MAX_ABS_DAILY_PNL_CORRELATION",
    "NO_SIGNAL",
    "NO_SIGNAL_PRECEDENCE",
    "NULL_SEED",
    "PARTITION_DIR",
    "PARTITION_RELPATH",
    "resolve_partition_dir",
    "PERMUTATION_ALPHA",
    "PERMUTATION_DRAWS",
    "PRIMARY_COST_BPS",
    "REFERENCE_DAYS",
    "REQUIRED_REFERENCE_OBSERVATIONS",
    "SHORT",
    "common_causal_window",
    "evaluate_bar",
    "load_partition",
    "partition_fingerprint",
    "reference_slots",
]
