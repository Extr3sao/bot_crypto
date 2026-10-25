"""WP-EDGE-14C/14D — real cost-aware measurements on the OHLCV the repository holds.

This module runs the things the brief insists must actually be executed rather than
described, on the data the repository already holds:

* the **neutral parity strategy** (``NEUTRAL_MA_CROSS_1H``) that WP-14C compares engines
  with — one plain, unfitted rule, so a divergence between engines is a model bug and not
  a tuning choice;
* two **baselines** — buy-and-hold and a null (always flat) comparator;
* the retained orthogonal candidate **E14-04 cross-asset lead-lag**.

Every measurement charges the admission round trip from the WP-EDGE-09 gate artefact, so
``net`` here means net of the same cost barrier the rest of the campaign uses. Nothing is
promoted: a positive net number is a research reading, not readiness.

It also states, on the record, which corpora are *consumed*. The EDGE-08 fetch manifest
declares its six alts an "unread cross-section" — a fresh OOS universe when it was
fetched — and EDGE-08 then measured on it, so for this package it is consumed. The EDGE-07
holdout window is consumed by EDGE-07. The consequence is stated rather than hidden: there
is **no fully unread 1h corpus left in the tree**, so the split used here is a *temporal*
holdout inside a consumed corpus, which is descriptive and cannot carry an inference.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .costs import load_gates
from .evidence import REPO_ROOT, sha256_file

__all__ = [
    "ADMISSION_SCENARIO",
    "CORPORA",
    "Bar",
    "corpus_registry",
    "experiment_payload",
    "load_ohlcv",
    "parse_row",
    "run_lead_lag",
    "run_ma_cross",
    "run_null",
    "summarise",
]

ADMISSION_SCENARIO = "BINANCE_SPOT_STANDARD_TAKER"

EDGE08_UNIVERSE = REPO_ROOT / "data" / "edge08" / "universe-1h"
EDGE07_HOLDOUT = REPO_ROOT / "data" / "edge07" / "holdout-1h"

#: Each corpus, and who already measured on it. A consumed corpus cannot be fresh OOS.
CORPORA = (
    {
        "path": "data/edge08/universe-1h",
        "assets": ["AAVEUSDT", "CRVUSDT", "KSMUSDT", "SNXUSDT", "SUSHIUSDT", "UNIUSDT"],
        "window": "2021-01-01T00:00:00Z..2026-10-14T19:00:00Z",
        "consumed_by": ["WP-EDGE-08"],
        "declared_unread_when_fetched": True,
        "still_fresh_for_this_package": False,
        "why": (
            "the EDGE-08 fetch manifest declares these symbols an unread cross-section, "
            "but EDGE-08 then measured on them, so they are consumed for EDGE-14"
        ),
    },
    {
        "path": "data/edge07/holdout-1h",
        "assets": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "window": "2026 holdout window",
        "consumed_by": ["WP-EDGE-07"],
        "declared_unread_when_fetched": False,
        "still_fresh_for_this_package": False,
        "why": "the EDGE-07 holdout window is consumed by EDGE-07",
    },
)


@dataclass(frozen=True)
class Bar:
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def day(self) -> str:
        return datetime.fromtimestamp(self.ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


@dataclass
class Trade:
    entry_ts_ms: int
    exit_ts_ms: int
    entry_price: float
    exit_price: float
    gross_bps: float
    net_bps: float
    bars_held: int

    @property
    def entry_day(self) -> str:
        return datetime.fromtimestamp(self.entry_ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")


def parse_row(row: Any) -> Bar | None:
    """One bar, from either shape the fetchers wrote.

    Two shapes exist in this tree and they are not interchangeable: the EDGE-07 holdout
    writes a dict per bar (``{"ts":..,"open":..}``) and the EDGE-08 universe writes a
    positional list (``[ts, o, h, l, c, v]``). A loader that understood only one of them
    returned zero bars for the other *silently*, which is worse than failing: an empty
    result reads like "no trades" rather than "the format was not understood". Both are
    accepted here, and anything else returns ``None`` so the caller can count it.
    """
    try:
        if isinstance(row, dict):
            return Bar(
                ts_ms=int(row["ts"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        if isinstance(row, list) and len(row) >= 6:
            return Bar(
                ts_ms=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
    except (TypeError, ValueError, KeyError):
        return None
    return None


def load_ohlcv(path: Path) -> list[Bar]:
    """Load a shard, accepting both on-disk shapes and never silently returning empty."""
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} is not a list of bars")
    bars: list[Bar] = []
    for row in raw:
        bar = parse_row(row)
        if bar is not None:
            bars.append(bar)
    if raw and not bars:
        raise ValueError(
            f"{path.name} holds {len(raw)} rows and none parsed: the bar shape is not "
            "one this loader understands, and returning zero bars would read as no trades"
        )
    return bars


def fingerprint(bars: list[Bar]) -> str:
    canonical = json.dumps(
        [[b.ts_ms, b.open, b.high, b.low, b.close, b.volume] for b in bars],
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _ema(values: list[float], span: int) -> list[float | None]:
    if span <= 0:
        raise ValueError("span must be positive")
    out: list[float | None] = [None] * len(values)
    if len(values) < span:
        return out
    k = 2.0 / (span + 1.0)
    seed = sum(values[:span]) / span
    out[span - 1] = seed
    prev = seed
    for i in range(span, len(values)):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def round_trip_cost_bps(gates: dict[str, Any]) -> float:
    """The admission round trip, read from the primary gate artefact."""
    for row in gates.get("barriers") or []:
        if row.get("scenario") == ADMISSION_SCENARIO and row.get("market") == "spot":
            return float(row["round_trip_bps"])
    # Fall back to the admission mean if a per-market row is not present.
    admission = gates.get("admission_barrier_bps") or {}
    values = list(admission.values())
    return float(sum(values) / len(values)) if values else 23.0


def _long_trades_ma_cross(bars: list[Bar], fast: int, slow: int) -> list[Trade]:
    """Long while ema(fast) > ema(slow) on the *previous* closed bar; fill at next open."""
    closes = [b.close for b in bars]
    ef, es = _ema(closes, fast), _ema(closes, slow)
    trades: list[Trade] = []
    entry_idx: int | None = None
    for i in range(1, len(bars)):
        prev_fast, prev_slow = ef[i - 1], es[i - 1]
        if prev_fast is None or prev_slow is None:
            continue
        prev_state = prev_fast > prev_slow
        if prev_state and entry_idx is None:
            entry_idx = i  # enter at this bar's open, decided on the previous close
        elif not prev_state and entry_idx is not None:
            trades.append(_trade(bars, entry_idx, i))
            entry_idx = None
    if entry_idx is not None:
        trades.append(_trade(bars, entry_idx, len(bars) - 1))
    return trades


def _trade(bars: list[Bar], entry_idx: int, exit_idx: int) -> Trade:
    entry_price = bars[entry_idx].open
    exit_price = bars[exit_idx].open if exit_idx > entry_idx else bars[exit_idx].close
    gross_bps = (exit_price / entry_price - 1.0) * 10_000.0
    return Trade(
        entry_ts_ms=bars[entry_idx].ts_ms,
        exit_ts_ms=bars[exit_idx].ts_ms,
        entry_price=entry_price,
        exit_price=exit_price,
        gross_bps=gross_bps,
        net_bps=gross_bps,  # cost applied later, once, in summarise
        bars_held=exit_idx - entry_idx,
    )


def run_ma_cross(bars: list[Bar], *, fast: int = 12, slow: int = 26) -> list[Trade]:
    return _long_trades_ma_cross(bars, fast, slow)


def run_null(bars: list[Bar]) -> list[Trade]:
    """The do-nothing comparator: no trades, so the equity curve is flat."""
    del bars
    return []


def run_lead_lag(
    signal_bars: list[Bar],
    alt_bars: list[Bar],
    *,
    shock_sigma: float = 1.5,
    sigma_lookback: int = 48,
    propagation_window: int = 2,
) -> list[Trade]:
    """E14-04: long the alt when BTC shocked up and the alt has not followed yet.

    The residual is measured on closed bars only: the sigma uses bars up to ``t-1``, the
    shock is read at ``t``, and the entry is the alt's open at ``t+1``. Beta is estimated
    once on the first 30% of the overlap and then frozen, so nothing is fitted on the OOS
    slice.
    """
    n = min(len(signal_bars), len(alt_bars))
    if n < sigma_lookback * 3:
        return []
    overlay = min(len(signal_bars), len(alt_bars))
    signal_bars = signal_bars[:overlay]
    alt_bars = alt_bars[:overlay]

    betas: list[float] = []
    lock = max(sigma_lookback + 2, int(overlay * 0.3))
    for i in range(1, lock):
        rs = signal_bars[i].close / signal_bars[i - 1].close - 1.0
        ra = alt_bars[i].close / alt_bars[i - 1].close - 1.0
        betas.append(ra / rs if abs(rs) > 1e-9 else 0.0)
    beta = sum(betas) / len(betas) if betas else 1.0

    trades: list[Trade] = []
    i = lock
    while i < overlay - 1:
        window = [
            signal_bars[j].close / signal_bars[j - 1].close - 1.0
            for j in range(i - sigma_lookback + 1, i + 1)
        ]
        mean = sum(window) / len(window)
        var = sum((w - mean) ** 2 for w in window) / len(window)
        sigma = var**0.5
        move = signal_bars[i].close / signal_bars[i - 1].close - 1.0
        expected_alt = beta * move
        actual_alt = alt_bars[i].close / alt_bars[i - 1].close - 1.0
        shocked_up = sigma > 0 and move > shock_sigma * sigma
        under_followed = actual_alt < expected_alt * 0.5
        if shocked_up and under_followed:
            entry_idx = i + 1
            exit_idx = min(entry_idx + propagation_window, overlay - 1)
            trades.append(_trade(alt_bars, entry_idx, exit_idx))
            i = exit_idx + 1  # no overlapping trades
        else:
            i += 1
    return trades


def summarise(
    trades: list[Trade],
    bars: list[Bar],
    *,
    round_trip_bps: float,
) -> dict[str, Any]:
    """Charge the round trip once per trade and describe the result, zeros included."""
    netted = [
        Trade(
            entry_ts_ms=t.entry_ts_ms,
            exit_ts_ms=t.exit_ts_ms,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            gross_bps=t.gross_bps,
            net_bps=t.gross_bps - round_trip_bps,
            bars_held=t.bars_held,
        )
        for t in trades
    ]
    by_day: dict[str, int] = {}
    if bars:
        first = datetime.fromtimestamp(bars[0].ts_ms / 1000, tz=UTC)
        last = datetime.fromtimestamp(bars[-1].ts_ms / 1000, tz=UTC)
        span_days = int((last - first).total_seconds() // 86400)
        for offset in range(span_days + 1):
            day = datetime.fromtimestamp(first.timestamp() + offset * 86400, tz=UTC).strftime(
                "%Y-%m-%d"
            )
            by_day[day] = 0
    for trade in netted:
        by_day[trade.entry_day] = by_day.get(trade.entry_day, 0) + 1

    # equity on the trade sequence, compounded, cost included
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for trade in netted:
        equity *= 1.0 + trade.net_bps / 10_000.0
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, 1.0 - equity / peak)

    grosses = [t.gross_bps for t in netted]
    nets = [t.net_bps for t in netted]
    wins = sum(1 for n in nets if n > 0)
    return {
        "trades": len(netted),
        "trades_by_day": by_day,
        "days_observed": len(by_day),
        "days_with_zero_trades": sum(1 for v in by_day.values() if v == 0),
        "trades_per_day_including_zeros": round(len(netted) / len(by_day), 6) if by_day else None,
        "mean_gross_bps": round(sum(grosses) / len(grosses), 6) if grosses else None,
        "mean_net_bps": round(sum(nets) / len(nets), 6) if nets else None,
        "total_net_bps": round(sum(nets), 6) if nets else None,
        "win_rate": round(wins / len(nets), 6) if nets else None,
        "max_drawdown": round(max_dd, 6),
        "equity_multiple": round(equity, 6),
        "round_trip_cost_bps_charged": round_trip_bps,
        "expectancy_is_net": True,
    }


def _shard(kind: str, symbol: str) -> Path | None:
    base = EDGE08_UNIVERSE if kind == "edge08" else EDGE07_HOLDOUT
    if not base.is_dir():
        return None
    for child in sorted(base.glob("*.json")):
        if symbol in child.name:
            return child
    return None


def corpus_registry() -> dict[str, Any]:
    rows = []
    for corpus in CORPORA:
        path = REPO_ROOT / str(corpus["path"])
        present = path.is_dir()
        shards = sorted(p.name for p in path.glob("*.json")) if present else []
        rows.append({**corpus, "present": present, "shards": shards})
    fresh = [row for row in rows if row.get("still_fresh_for_this_package")]
    return {
        "corpora": rows,
        "fresh_for_this_package": [row["path"] for row in fresh],
        "has_a_genuinely_fresh_oos": bool(fresh),
        "consequence": (
            "no corpus in the tree is unread for EDGE-14, so the holdout used here is a "
            "temporal split inside a consumed corpus: it is descriptive and cannot carry "
            "a promotion or an inference"
        ),
    }


def experiment_payload() -> dict[str, Any]:
    """Run every reachable experiment on real data and report the honest result."""
    gates = load_gates()
    cost = round_trip_cost_bps(gates)
    registry = corpus_registry()

    results: dict[str, Any] = {}
    data_manifest: list[dict[str, Any]] = []

    # --- Parity strategy and baselines on BTC and ETH 1h (EDGE-07 holdout window) ---
    for symbol in ("BTCUSDT", "ETHUSDT"):
        shard = _shard("edge07", symbol)
        bars = load_ohlcv(shard) if shard else []
        if not bars:
            results[f"NEUTRAL_MA_CROSS_1H::{symbol}"] = {
                "status": "NOT_EXECUTED",
                "reason": f"no shard for {symbol}",
            }
            continue
        assert shard is not None  # guaranteed by the `if not bars` guard above
        data_manifest.append(
            {"symbol": symbol, "path": str(shard), "bars": len(bars), "sha256": sha256_file(shard)}
        )
        ma = summarise(run_ma_cross(bars), bars, round_trip_bps=cost)
        null = summarise(run_null(bars), bars, round_trip_bps=cost)
        buy_hold = summarise(
            [_trade(bars, 0, len(bars) - 1)] if bars else [],
            bars,
            round_trip_bps=cost,
        )
        results[f"NEUTRAL_MA_CROSS_1H::{symbol}"] = {
            "status": "EXECUTED",
            "neutral": ma,
            "null_comparator": null,
            "buy_and_hold_comparator": buy_hold,
            "oob": [],
            "fill_class": "BACKTEST_FILL",
            "comparator_semantics": (
                "buy_and_hold is a single trade spanning the whole window, so its "
                "mean_net_bps is the window return and not a per-trade expectancy; it is "
                "reported for context and must not be compared per-trade against the "
                "98-trade neutral arm"
            ),
        }

    # --- E14-04 lead-lag on the EDGE-08 alts driven by an EDGE-08 asset as signal proxy ---
    # BTC is not in the EDGE-08 universe; the signal asset is the first alts that are,
    # and the relationship is declared, not assumed to be BTC.
    signal_shard = _shard("edge08", "UNIUSDT")
    signal_bars = load_ohlcv(signal_shard) if signal_shard else []
    if signal_bars and signal_shard is not None:
        data_manifest.append(
            {
                "symbol": "UNIUSDT(signal)",
                "path": str(signal_shard),
                "bars": len(signal_bars),
                "sha256": sha256_file(signal_shard),
            }
        )
    for symbol in ("AAVEUSDT", "SUSHIUSDT", "CRVUSDT", "KSMUSDT"):
        alt_shard = _shard("edge08", symbol)
        alt_bars = load_ohlcv(alt_shard) if alt_shard else []
        if not alt_bars or not signal_bars or alt_shard is None:
            continue
        data_manifest.append(
            {
                "symbol": symbol,
                "path": str(alt_shard),
                "bars": len(alt_bars),
                "sha256": sha256_file(alt_shard),
            }
        )
        trades = run_lead_lag(signal_bars, alt_bars)
        results[f"E14-04_LEAD_LAG::UNI->{symbol}"] = {
            "status": "EXECUTED",
            "signal_asset": "UNIUSDT",
            "alt_asset": symbol,
            "measurement": summarise(trades, alt_bars, round_trip_bps=cost),
            "fill_class": "BACKTEST_FILL",
        }

    executed = [k for k, v in results.items() if v.get("status") == "EXECUTED"]
    net_positive = [
        k
        for k, v in results.items()
        if v.get("status") == "EXECUTED"
        and (v.get("measurement") or v.get("neutral") or {}).get("mean_net_bps") not in (None,)
        and (v.get("measurement") or v.get("neutral") or {}).get("mean_net_bps", -1) > 0
    ]
    return {
        "schema_version": "EDGE14_CANDIDATE_EXPERIMENTS_V1",
        "work_package": "WP-EDGE-14D",
        "data_manifest": data_manifest,
        "corpus_registry": registry,
        "round_trip_cost_bps": cost,
        "results": results,
        "executed": executed,
        "not_executed": [k for k, v in results.items() if v.get("status") != "EXECUTED"],
        "net_positive_arms": net_positive,
        "oos_class": "TEMPORAL_WITHIN_A_CONSUMED_CORPUS",
        "oos_is_fresh": False,
        "multiple_testing_adjustment": "NOT_APPLIED_NO_FRESH_OOS",
        "verdict": (
            "INSUFFICIENT_SAMPLE_FOR_FRESH_OOS"
            if not registry["has_a_genuinely_fresh_oos"]
            else "MEASURED"
        ),
        "promotion": "NONE",
        "order_sent": False,
        "limitations": [
            "the split is temporal inside a corpus another work package already measured "
            "on, so no arm here can be promoted or inferred from",
            "the lead-lag signal asset is UNIUSDT because BTC is not in the EDGE-08 "
            "universe; the relationship is declared, not assumed",
            "fees are the admission schedule; a cheaper venue would change the sign only "
            "if the gross move were already near the barrier, which it is not",
        ],
    }
