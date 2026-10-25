"""RFC-022 Edge Discovery Sprint 002 - shared research library.

PIT-SAFE BY CONSTRUCTION
    Every feature at bar ``i`` is computed from bars ``<= i`` only. Events are
    detected on a closed bar ``i``; execution happens at the OPEN of bar
    ``i + 1`` (the first bar whose information did not exist when the decision
    was made). Forward outcomes (MFE/MAE, triple barrier) read bars ``> i`` and
    are RESEARCH-ONLY: they never feed signal generation.

COST CONVENTION (explicit, avoids the Sprint 001 double count)
    price_move_bps = direction * (exit_price / entry_price - 1) * 1e4
    gross_bps      = price_move_bps                    # execution-level edge
    cost_bps       = CERTIFIED_ROUND_TRIP_BPS          # 23.790569
    net_bps        = gross_bps - cost_bps

    Sprint 001 derived ``gross`` from the runtime simulator, whose fills already
    embedded 1 bp/side slippage, and then subtracted the full round-trip cost
    (which contains slippage again) -> ~2.632456 bps of double counting. This
    library removes the double count. Sprint 001 numbers are re-expressed under
    this convention where a comparison is required.

NO O(n^2). Rolling features use sliding windows over a single pass.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

REPO = Path(__file__).resolve().parents[1]
DATA_DIR = REPO / "reports" / "strategy-baseline" / "data"
OUT_DIR = REPO / "reports" / "edge-discovery" / "sprint002"

CERTIFIED_ROUND_TRIP_BPS = 23.790569
SLIPPAGE_COMPONENT_BPS = 2.632456
COST_STRESS: dict[str, float] = {
    "BASE": 23.790569,
    "PLUS_25": 29.738211,
    "PLUS_50": 35.685854,
    "PLUS_100": 47.581138,
}
ROOT_NOTIONAL = 500.0
MIN_TRADES = 50
TF_MIN: dict[str, float] = {
    "5m": 5.0,
    "15m": 15.0,
    "30m": 30.0,
    "1h": 60.0,
    "2h": 120.0,
    "4h": 240.0,
}
SPLITS: dict[str, tuple[str, ...]] = {
    "DISCOVERY": ("W1", "W2", "W3", "W4"),
    "VALIDATION": ("W5",),
    "HOLDOUT": ("W6", "W7"),
}
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

_FNAME = re.compile(
    r"^(?P<asset>[A-Z]{3}USDT)_(?P<win>W[1-7])_(?P<month>\d{4}-\d{2})"
    r"(?:_5m_(?P<tf>15m|30m|1h))?\.json$"
)


# ---------------------------------------------------------------------------
# dataset discovery + hashing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DatasetFile:
    path: Path
    name: str
    asset: str
    window: str
    timeframe: str


def dataset_files() -> list[DatasetFile]:
    out: list[DatasetFile] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        m = _FNAME.match(path.name)
        if not m:
            continue
        out.append(
            DatasetFile(
                path=path,
                name=path.name,
                asset=m.group("asset"),
                window=m.group("win"),
                timeframe=m.group("tf") or "5m",
            )
        )
    return out


def hash_files(files: list[DatasetFile]) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(f.path.read_bytes())
    return h.hexdigest()


def split_hashes() -> dict[str, dict[str, Any]]:
    files = dataset_files()
    out: dict[str, dict[str, Any]] = {}
    for split, windows in SPLITS.items():
        sel = [f for f in files if f.window in windows]
        rows = 0
        for f in sel:
            rows += len(json.loads(f.path.read_text(encoding="utf-8")))
        out[split] = {
            "windows": list(windows),
            "files": len(sel),
            "rows": rows,
            "sha256": hash_files(sel),
        }
    return out


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_obj(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def config_hash() -> str:
    return sha256_obj(
        {
            "cost_bps": CERTIFIED_ROUND_TRIP_BPS,
            "cost_stress": COST_STRESS,
            "min_trades": MIN_TRADES,
            "splits": {k: list(v) for k, v in SPLITS.items()},
            "assets": list(ASSETS),
        }
    )


# ---------------------------------------------------------------------------
# bars + deterministic resample
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Bars:
    ts: NDArray[Any]
    o: NDArray[Any]
    h: NDArray[Any]
    lo: NDArray[Any]
    c: NDArray[Any]
    v: NDArray[Any]

    def __len__(self) -> int:
        return int(self.ts.shape[0])


def load_bars(path: Path) -> Bars:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return Bars(
        ts=np.array([r["ts"] for r in rows], dtype=np.float64),
        o=np.array([r["open"] for r in rows], dtype=np.float64),
        h=np.array([r["high"] for r in rows], dtype=np.float64),
        lo=np.array([r["low"] for r in rows], dtype=np.float64),
        c=np.array([r["close"] for r in rows], dtype=np.float64),
        v=np.array([r["volume"] for r in rows], dtype=np.float64),
    )


def _emit(bars: Bars, idx: NDArray[Any], acc: dict[str, list[float]]) -> None:
    acc["ts"].append(float(bars.ts[idx[0]]))
    acc["o"].append(float(bars.o[idx[0]]))
    acc["h"].append(float(np.max(bars.h[idx])))
    acc["lo"].append(float(np.min(bars.lo[idx])))
    acc["c"].append(float(bars.c[idx[-1]]))
    acc["v"].append(float(np.sum(bars.v[idx])))


def resample(bars: Bars, tf_min: int, src_min: int = 5) -> Bars:
    """Deterministic complete-bucket resample, label = BAR_OPEN.

    Same semantics as scripts/resample_baseline_data.py: bucket = ts // tf_ms;
    a bucket is emitted only when it holds exactly ``tf_min // src_min`` source
    bars; the output label is the first source bar timestamp.
    """
    ms = tf_min * 60_000
    per = tf_min // src_min
    acc: dict[str, list[float]] = {k: [] for k in ("ts", "o", "h", "lo", "c", "v")}
    cur: list[int] = []
    bucket: int | None = None
    for i in range(len(bars)):
        bk = int(bars.ts[i]) // ms
        if bucket is None:
            bucket = bk
        if bk != bucket:
            if len(cur) == per:
                _emit(bars, np.array(cur, dtype=np.int64), acc)
            cur = []
            bucket = bk
        cur.append(i)
    # The trailing bucket is intentionally NOT emitted: this reproduces the
    # certified derived files (15m/30m/1h) exactly and keeps 2h/4h on the same
    # rule (complete buckets only, last bucket dropped).
    return Bars(
        ts=np.array(acc["ts"], dtype=np.float64),
        o=np.array(acc["o"], dtype=np.float64),
        h=np.array(acc["h"], dtype=np.float64),
        lo=np.array(acc["lo"], dtype=np.float64),
        c=np.array(acc["c"], dtype=np.float64),
        v=np.array(acc["v"], dtype=np.float64),
    )


# ---------------------------------------------------------------------------
# vectorised rolling features
# ---------------------------------------------------------------------------


def _win(x: NDArray[Any], n: int) -> NDArray[Any]:
    return np.lib.stride_tricks.sliding_window_view(x, n)


def rolling_mean(x: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    out[n - 1 :] = _win(x, n).mean(axis=1)
    return out


def rolling_std(x: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    out[n - 1 :] = _win(x, n).std(axis=1)
    return out


def rolling_max(x: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    out[n - 1 :] = _win(x, n).max(axis=1)
    return out


def rolling_min(x: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    out[n - 1 :] = _win(x, n).min(axis=1)
    return out


REGIME_CODES = {
    "HIGH_VOLATILITY": 1,
    "LOW_VOLATILITY": 2,
    "TREND_UP": 3,
    "TREND_DOWN": 4,
    "RANGE": 5,
}
REGIME_NAMES = {v: k for k, v in REGIME_CODES.items()}


def regime_labels(bundle: Bundle) -> NDArray[Any]:
    """ONLINE, PIT-safe regime label per bar.

    Mirrors BaseCryptoAssetAgent.classify_regime thresholds exactly (ATR% > 0.02 ->
    HIGH_VOLATILITY, < 0.004 -> LOW_VOLATILITY, else the EMA9/EMA21 spread sign at
    +/-0.004 -> TREND_UP / TREND_DOWN / RANGE). The EMA seed and multiplier are the
    runtime's. The runtime classifies a trailing 120-bar window; this vectorised form
    classifies the full history, which is a superset, so the label never uses a bar
    the runtime could not have used. Used for ANALYSIS only, never for signal
    generation.
    """
    n = len(bundle)
    out = np.zeros(n, dtype=np.int8)
    spread = np.full(n, np.nan, dtype=np.float64)
    ok = np.isfinite(bundle.ema21) & (bundle.ema21 > 0)
    spread[ok] = (bundle.ema9[ok] - bundle.ema21[ok]) / bundle.ema21[ok]
    for i in range(n):
        ap = bundle.atr_pct[i]
        if not np.isfinite(ap):
            out[i] = 0
            continue
        if ap > 0.02:
            out[i] = REGIME_CODES["HIGH_VOLATILITY"]
        elif ap < 0.004:
            out[i] = REGIME_CODES["LOW_VOLATILITY"]
        elif np.isfinite(spread[i]) and spread[i] > 0.004:
            out[i] = REGIME_CODES["TREND_UP"]
        elif np.isfinite(spread[i]) and spread[i] < -0.004:
            out[i] = REGIME_CODES["TREND_DOWN"]
        else:
            out[i] = REGIME_CODES["RANGE"]
    return out


# Cache maps id(bundle) -> (the bundle's own ts array, labels). Holding the ts
# array keeps the memory it points at alive so its id cannot be recycled, and the
# identity re-check makes a reused id recompute instead of returning stale labels.
# A size cap bounds memory for long-lived research processes.
_REGIME_CACHE: dict[int, tuple[NDArray[Any], NDArray[Any]]] = {}
_REGIME_CACHE_CAP = 512


def regime_labels_cached(bundle: Bundle) -> NDArray[Any]:
    key = id(bundle)
    ts = bundle.bars.ts
    ent = _REGIME_CACHE.get(key)
    if ent is not None and ent[0] is ts:
        return ent[1]
    labels = regime_labels(bundle)
    if len(_REGIME_CACHE) >= _REGIME_CACHE_CAP:
        _REGIME_CACHE.clear()
    _REGIME_CACHE[key] = (ts, labels)
    return labels


def shift1(x: NDArray[Any]) -> NDArray[Any]:
    """Value at bar i-1 (first element NaN). Used to build levels from PAST bars."""
    out = np.full(x.shape, np.nan, dtype=np.float64)
    out[1:] = x[:-1]
    return out


def rolling_rank_pct(x: NDArray[Any], n: int) -> NDArray[Any]:
    """Fraction of the trailing ``n`` values (inclusive) that are <= current."""
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    w = _win(x, n)
    cur = x[n - 1 :]
    finite = np.isfinite(w)
    counts = finite.sum(axis=1)
    ok = (counts == n) & np.isfinite(cur)
    le = (w <= cur[:, None]).sum(axis=1)
    out[n - 1 :] = np.where(ok, le / n, np.nan)
    return out


def ema(x: NDArray[Any], n: int) -> NDArray[Any]:
    """Runtime-parity EMA: seed = mean(first n), multiplier 1.0 + ignore."""
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if x.shape[0] < n:
        return out
    k = 2.0 / (n + 1.0)
    val = float(np.mean(x[:n]))
    out[n - 1] = val
    for i in range(n, x.shape[0]):
        val = (x[i] - val) * k + val
        out[i] = val
    return out


def wilder_atr(h: NDArray[Any], lo: NDArray[Any], c: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(c.shape, np.nan, dtype=np.float64)
    if c.shape[0] < n:
        return out
    pc = np.empty_like(c)
    pc[0] = c[0]
    pc[1:] = c[:-1]
    tr = np.maximum(h - lo, np.maximum(np.abs(h - pc), np.abs(lo - pc)))
    val = float(np.mean(tr[:n]))
    out[n - 1] = val
    for i in range(n, c.shape[0]):
        val = ((val * (n - 1.0)) + tr[i]) / n
        out[i] = val
    return out


def wilder_rsi(c: NDArray[Any], n: int) -> NDArray[Any]:
    out = np.full(c.shape, np.nan, dtype=np.float64)
    if c.shape[0] < n + 1:
        return out
    d = np.diff(c)
    gain = float(np.sum(np.where(d[:n] > 0, d[:n], 0.0)) / n)
    loss = float(np.sum(np.where(d[:n] < 0, -d[:n], 0.0)) / n)
    for i in range(n, c.shape[0]):
        g = max(float(d[i - 1]), 0.0)
        l_ = max(-float(d[i - 1]), 0.0)
        gain = (gain * (n - 1.0) + g) / n
        loss = (loss * (n - 1.0) + l_) / n
        if loss == 0.0:
            out[i] = 100.0 if gain > 0 else 50.0
        else:
            rs = gain / loss
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


# ---------------------------------------------------------------------------
# feature bundle
# ---------------------------------------------------------------------------

RANK_WINDOWS = (60, 120, 240)
LEVEL_WINDOWS = (20, 40, 60, 120)
RET_WINDOWS = (5, 10, 20, 40)


@dataclass(frozen=True, slots=True)
class Bundle:
    bars: Bars
    timeframe: str
    tf_min: float
    atr: NDArray[Any]
    atr_pct: NDArray[Any]
    rv20: NDArray[Any]
    ret1: NDArray[Any]
    ema9: NDArray[Any]
    ema21: NDArray[Any]
    ema50: NDArray[Any]
    rsi14: NDArray[Any]
    bb_up: NDArray[Any]
    bb_lo: NDArray[Any]
    kc_up: NDArray[Any]
    kc_lo: NDArray[Any]
    rank_atr: dict[int, NDArray[Any]] = field(default_factory=dict)
    rank_range: dict[int, NDArray[Any]] = field(default_factory=dict)
    rank_rv: dict[int, NDArray[Any]] = field(default_factory=dict)
    hh: dict[int, NDArray[Any]] = field(default_factory=dict)
    ll: dict[int, NDArray[Any]] = field(default_factory=dict)
    vol_rank: dict[int, NDArray[Any]] = field(default_factory=dict)
    ret: dict[int, NDArray[Any]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.bars)


def build_bundle(bars: Bars, timeframe: str) -> Bundle:
    c, h, lo, v = bars.c, bars.h, bars.lo, bars.v
    atr = wilder_atr(h, lo, c, 14)
    atr10 = wilder_atr(h, lo, c, 10)
    with np.errstate(invalid="ignore", divide="ignore"):
        atr_pct = np.where(c > 0, atr / c, np.nan)
        rng = (rolling_max(h, 20) - rolling_min(lo, 20)) / c
    ret1 = np.full(c.shape, np.nan, dtype=np.float64)
    ret1[1:] = np.diff(c) / c[:-1]
    rv20 = rolling_std(ret1, 20) * math.sqrt(20.0)
    ema20 = ema(c, 20)
    bb_mid = rolling_mean(c, 20)
    bb_sd = rolling_std(c, 20)
    return Bundle(
        bars=bars,
        timeframe=timeframe,
        tf_min=TF_MIN[timeframe],
        atr=atr,
        atr_pct=atr_pct,
        rv20=rv20,
        ret1=ret1,
        ema9=ema(c, 9),
        ema21=ema(c, 21),
        ema50=ema(c, 50),
        rsi14=wilder_rsi(c, 14),
        bb_up=bb_mid + 2.0 * bb_sd,
        bb_lo=bb_mid - 2.0 * bb_sd,
        kc_up=ema20 + 1.5 * atr10,
        kc_lo=ema20 - 1.5 * atr10,
        rank_atr={n: rolling_rank_pct(atr_pct, n) for n in RANK_WINDOWS},
        rank_range={n: rolling_rank_pct(rng, n) for n in RANK_WINDOWS},
        rank_rv={n: rolling_rank_pct(rv20, n) for n in RANK_WINDOWS},
        hh={n: rolling_max(h, n) for n in LEVEL_WINDOWS},
        ll={n: rolling_min(lo, n) for n in LEVEL_WINDOWS},
        vol_rank={n: rolling_rank_pct(v, n) for n in RANK_WINDOWS},
        ret={n: np.concatenate((np.full(n, np.nan), c[n:] / c[:-n] - 1.0)) for n in RET_WINDOWS},
    )


# ---------------------------------------------------------------------------
# event engine
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Trade:
    candidate_id: str
    hypothesis_id: str
    family: str
    asset: str
    window: str
    timeframe: str
    side: str
    entry_ts: float
    exit_ts: float
    entry: float
    exit: float
    reason: str
    hold_bars: int
    gross_bps: float
    cost_bps: float
    net_bps: float
    mfe_bps: float
    mae_bps: float
    atr_bps_at_entry: float
    regime: str = "UNKNOWN"


SignalFn = Callable[[Bundle], NDArray[Any]]


@dataclass(slots=True)
class Spec:
    """Frozen candidate specification: ENTRY / EXIT / INVALIDATION."""

    candidate_id: str
    hypothesis_id: str
    family: str
    timeframe: str
    signals: SignalFn
    warmup: int
    atr_target_mult: float
    atr_target_is_atr: bool
    atr_stop_mult: float
    hold_bars: int
    description: str = ""
    asset_scope: tuple[str, ...] = ASSETS

    def param_key(self) -> str:
        return (
            f"tf={self.timeframe}|tgt={self.atr_target_mult}"
            f"{'xATR' if self.atr_target_is_atr else 'xPX'}"
            f"|stop={self.atr_stop_mult}xATR|hold={self.hold_bars}"
            f"|sig={self.hypothesis_id}"
        )


def run_spec(
    spec: Spec,
    bundle: Bundle,
    asset: str,
    window: str,
    cost_bps: float = CERTIFIED_ROUND_TRIP_BPS,
    slip_mult: float = 1.0,
) -> list[Trade]:
    """Execute one frozen spec over one series, one position at a time.

    Entry at the OPEN of the bar after the signal bar (no same-bar lookahead).
    Exit priority inside a bar: stop first, then target (conservative).
    Time stop: exit at the OPEN of entry_bar + hold_bars.
    Slippage stress multiplies only the modelled slippage component.
    """
    bars = bundle.bars
    n = len(bars)
    sig = spec.signals(bundle)
    regimes = regime_labels_cached(bundle)
    eff_cost = cost_bps + (slip_mult - 1.0) * SLIPPAGE_COMPONENT_BPS
    trades: list[Trade] = []
    i = max(spec.warmup, 2)
    while i < n - 2:
        s = int(sig[i])
        if s == 0:
            i += 1
            continue
        entry_idx = i + 1
        entry = float(bars.o[entry_idx])
        a = float(bundle.atr[i])
        if entry <= 0.0 or not math.isfinite(a) or a <= 0.0:
            i += 1
            continue
        sgn = 1.0 if s > 0 else -1.0
        side = "LONG" if s > 0 else "SHORT"
        stop = entry - sgn * spec.atr_stop_mult * a
        if spec.atr_target_is_atr:
            target = entry + sgn * spec.atr_target_mult * a
        else:
            target = entry + sgn * spec.atr_target_mult
        time_idx = min(entry_idx + spec.hold_bars, n - 1)
        exit_price = float(bars.o[time_idx])
        exit_idx = time_idx
        reason = "time_stop"
        mfe = 0.0
        mae = 0.0
        for j in range(entry_idx, time_idx + 1):
            if sgn > 0:
                mfe = max(mfe, float(bars.h[j]) - entry)
                mae = max(mae, entry - float(bars.lo[j]))
                hit_stop = float(bars.lo[j]) <= stop
                hit_target = float(bars.h[j]) >= target
            else:
                mfe = max(mfe, entry - float(bars.lo[j]))
                mae = max(mae, float(bars.h[j]) - entry)
                hit_stop = float(bars.h[j]) >= stop
                hit_target = float(bars.lo[j]) <= target
            if hit_stop:
                exit_price, exit_idx, reason = stop, j, "stop"
                break
            if hit_target:
                exit_price, exit_idx, reason = target, j, "target"
                break
        g_bps = sgn * (exit_price / entry - 1.0) * 1e4
        trades.append(
            Trade(
                candidate_id=spec.candidate_id,
                hypothesis_id=spec.hypothesis_id,
                family=spec.family,
                asset=asset,
                window=window,
                timeframe=spec.timeframe,
                side=side,
                entry_ts=float(bars.ts[entry_idx]),
                exit_ts=float(bars.ts[exit_idx]),
                entry=entry,
                exit=exit_price,
                reason=reason,
                hold_bars=exit_idx - entry_idx,
                gross_bps=g_bps,
                cost_bps=eff_cost,
                net_bps=g_bps - eff_cost,
                mfe_bps=mfe / entry * 1e4,
                mae_bps=mae / entry * 1e4,
                atr_bps_at_entry=a / entry * 1e4,
                regime=REGIME_NAMES.get(int(regimes[entry_idx]), "UNKNOWN"),
            )
        )
        i = exit_idx + 1
    return trades


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def _sharpe(net: NDArray[Any], ts: NDArray[Any]) -> float | None:
    if net.shape[0] < 3:
        return None
    sd = float(np.std(net))
    if sd == 0.0:
        return None
    span_years = float(ts.max() - ts.min())
    span_years = span_years / (1000.0 * 3600 * 24 * 365)
    per_year = float(net.shape[0]) / span_years if span_years > 0 else 0.0
    return float(np.mean(net)) / sd * math.sqrt(per_year)


def _sortino(net: NDArray[Any], ts: NDArray[Any]) -> float | None:
    if net.shape[0] < 3:
        return None
    down = np.minimum(net, 0.0)
    dd = float(np.sqrt(np.mean(down * down)))
    if dd == 0.0:
        return None
    span_years = float(ts.max() - ts.min()) / (1000.0 * 3600 * 24 * 365)
    per_year = float(net.shape[0]) / span_years if span_years > 0 else 0.0
    return float(np.mean(net)) / dd * math.sqrt(per_year)


def _max_dd(net: NDArray[Any]) -> float:
    if net.shape[0] == 0:
        return 0.0
    cum = np.cumsum(net)
    peak = np.maximum.accumulate(cum)
    return float(np.max(peak - cum))


def metrics(trades: list[Trade], eval_bars: int, tf_min: float) -> dict[str, Any]:
    if not trades:
        return {"trades": 0}
    net = np.array([t.net_bps for t in trades], dtype=np.float64)
    gross = np.array([t.gross_bps for t in trades], dtype=np.float64)
    ts = np.array([t.entry_ts for t in trades], dtype=np.float64)
    exits = np.array([t.exit_ts for t in trades], dtype=np.float64)
    wins = net[net > 0]
    losses = net[net < 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.shape[0] else None
    n = int(net.shape[0])
    span_days = max(1.0, float(exits.max() - ts.min()) / (1000.0 * 86400))
    sd = float(np.std(net))
    t_stat = float(np.mean(net)) / (sd / math.sqrt(n)) if sd > 0 and n > 1 else None
    ex_best = float((net.sum() - net.max()) / (n - 1)) if n > 1 else None
    sh = _sharpe(net, ts)
    so = _sortino(net, ts)
    return {
        "trades": n,
        "trades_per_day": round(n / span_days, 3),
        "gross_bps": round(float(np.mean(gross)), 4),
        "cost_bps": round(float(np.mean([t.cost_bps for t in trades])), 4),
        "net_bps": round(float(np.mean(net)), 4),
        "median_net_bps": round(float(np.median(net)), 4),
        "gross_pnl_usdt": round(float(gross.sum()) / 1e4 * ROOT_NOTIONAL, 2),
        "net_pnl_usdt": round(float(net.sum()) / 1e4 * ROOT_NOTIONAL, 2),
        "profit_factor": round(pf, 4) if pf is not None else None,
        "win_rate": round(float(wins.shape[0]) / n, 4),
        "avg_win_bps": round(float(wins.mean()), 4) if wins.shape[0] else 0.0,
        "avg_loss_bps": round(float(losses.mean()), 4) if losses.shape[0] else 0.0,
        "sharpe": round(sh, 4) if sh is not None else None,
        "sortino": round(so, 4) if so is not None else None,
        "max_dd_bps": round(_max_dd(net), 4),
        "edge_cost_ratio": round(float(np.mean(gross)) / CERTIFIED_ROUND_TRIP_BPS, 4),
        "t_stat": round(t_stat, 4) if t_stat is not None else None,
        "net_bps_ex_best_trade": round(ex_best, 4) if ex_best is not None else None,
        "single_trade_dependency": bool(ex_best is not None and ex_best <= 0.0),
        "avg_hold_bars": round(float(np.mean([t.hold_bars for t in trades])), 2),
        "avg_hold_min": round(float(np.mean([t.hold_bars for t in trades])) * tf_min, 1),
        "avg_mfe_bps": round(float(np.mean([t.mfe_bps for t in trades])), 2),
        "avg_mae_bps": round(float(np.mean([t.mae_bps for t in trades])), 2),
        "avg_atr_bps": round(float(np.mean([t.atr_bps_at_entry for t in trades])), 2),
        "exposure_pct": round(float(sum(t.hold_bars for t in trades)) / eval_bars * 100.0, 2)
        if eval_bars
        else None,
        "exit_mix": {
            "stop": sum(1 for t in trades if t.reason == "stop"),
            "target": sum(1 for t in trades if t.reason == "target"),
            "time_stop": sum(1 for t in trades if t.reason == "time_stop"),
        },
    }


def edge_cost_band(ratio: float) -> str:
    if ratio < 1.0:
        return "COST_KILLED"
    if ratio < 1.10:
        return "FRAGILE"
    if ratio < 1.25:
        return "THIN"
    if ratio < 1.50:
        return "INTERESTING"
    if ratio < 2.00:
        return "STRONGER"
    return "HIGH_MARGIN"


# ---------------------------------------------------------------------------
# forward excursions (ex-post research only)
# ---------------------------------------------------------------------------

MFE_HORIZONS: dict[str, int] = {
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "8h": 480,
    "12h": 720,
    "24h": 1440,
}


def forward_extremes(bundle: Bundle, per: int) -> tuple[NDArray[Any], NDArray[Any]]:
    """Vectorised forward extremes after each bar (RESEARCH ONLY).

    ``hi_after[i]`` = max high over bars ``i+1 .. i+per``; ``lo_after[i]`` =
    min low over the same range. Aligned to the bar axis, first/last entries NaN
    where the window does not exist.
    """
    n = len(bundle.bars)
    hi = np.full(n, np.nan, dtype=np.float64)
    lo = np.full(n, np.nan, dtype=np.float64)
    if per < 1 or n <= per:
        return hi, lo
    w_hi = np.lib.stride_tricks.sliding_window_view(bundle.bars.h, per).max(axis=1)
    w_lo = np.lib.stride_tricks.sliding_window_view(bundle.bars.lo, per).min(axis=1)
    # w_hi[k] covers bars k..k+per-1 -> the window AFTER bar i is k = i+1
    hi[: n - per] = w_hi[1 : n - per + 1]
    lo[: n - per] = w_lo[1 : n - per + 1]
    return hi, lo


def directional_excursions(
    bundle: Bundle, idx: NDArray[Any], sides: NDArray[Any], per: int
) -> tuple[NDArray[Any], NDArray[Any]]:
    """Directional MFE/MAE in bps over the ``per`` bars after each event."""
    hi, lo = forward_extremes(bundle, per)
    c = bundle.bars.c
    mfe = np.full(idx.shape[0], np.nan, dtype=np.float64)
    mae = np.full(idx.shape[0], np.nan, dtype=np.float64)
    for k in range(idx.shape[0]):
        i = int(idx[k])
        if i >= hi.shape[0] or not np.isfinite(hi[i]) or c[i] <= 0:
            continue
        e = float(c[i])
        up = (float(hi[i]) / e - 1.0) * 1e4
        dn = (e - float(lo[i])) / e * 1e4
        if sides[k] >= 0:
            mfe[k], mae[k] = up, dn
        else:
            mfe[k], mae[k] = dn, up
    return mfe, mae


def forward_excursions(
    bundle: Bundle,
    idx: NDArray[Any],
    sides: NDArray[Any],
    horizon_min: int,
) -> tuple[NDArray[Any], NDArray[Any]]:
    """MFE/MAE in bps over ``horizon_min`` minutes after each event bar.

    RESEARCH ONLY. Reads bars after ``idx``; never used for signal generation.
    """
    bars = bundle.bars
    per = max(1, round(horizon_min / bundle.tf_min))
    n = len(bars)
    mfe = np.full(idx.shape[0], np.nan, dtype=np.float64)
    mae = np.full(idx.shape[0], np.nan, dtype=np.float64)
    for k in range(idx.shape[0]):
        i = int(idx[k])
        end = min(i + per, n - 1)
        if end <= i:
            continue
        hi = float(np.max(bars.h[i + 1 : end + 1]))
        lo = float(np.min(bars.lo[i + 1 : end + 1]))
        e = float(bars.c[i])
        if e <= 0:
            continue
        if sides[k] >= 0:
            mfe[k] = (hi / e - 1.0) * 1e4
            mae[k] = (e - lo) / e * 1e4
        else:
            mfe[k] = (e - lo) / e * 1e4
            mae[k] = (hi / e - 1.0) * 1e4
    return mfe, mae


def pct(x: NDArray[Any], q: float) -> float | None:
    finite = x[np.isfinite(x)]
    if finite.shape[0] == 0:
        return None
    return round(float(np.percentile(finite, q)), 2)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
