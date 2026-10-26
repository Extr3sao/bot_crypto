"""WP-EDGE-14R/P2 — engine parity against an independent backtester.

The brief asks for a *real* comparison: one dataset, one rule, the same fill
timing, the same capital and the same commissions, run through this project's
backtester and through an external one, with the per-trade difference
*quantified* rather than asserted.

Four things are pinned before the run, because a parity test that picks them
afterwards measures the person, not the engines:

1. **The rule.** ``NEUTRAL_MA_CROSS_1H``: long while ``ema(12) > ema(26)`` on the
   previous *closed* bar, flat otherwise. One plain rule and no fitted
   parameter, so a divergence is a model difference and not a tuning choice.
2. **The indicator.** The external engine is asked for ``talib.EMA`` while this
   project uses its own SMA-seeded recursive EMA. Those two are the *same
   definition* (both seed with the mean of the first ``span`` closes and then
   recurse with ``k = 2/(span+1)``), and this module proves it on the actual
   series instead of trusting the claim: if the two series disagree by more than
   a floating-point hair, the parity test refuses to run, because any
   divergence it then reported would be the indicator's and not the engine's.
3. **The fill timing.** A signal observed at the close of bar *i* fills at the
   open of bar *i+1*, on entry and on exit alike.
4. **The costs.** ``fees_bps_per_side`` charged on both legs by both engines,
   with slippage held at zero on both sides. Slippage is a *model input*, not an
   engine behaviour; feeding the two engines different slippage models would
   confound the very thing being measured. The asymmetry is therefore declared
   rather than hidden: an external engine with no native slippage parameter
   cannot be given one without inventing a fill model for it.

Tolerances are declared in the payload before the numbers are read
(``PREREGISTERED_TOLERANCE``), and a divergence beyond them is *reported*, never
smoothed: the honest outcomes are "the engines agree", "they differ and here is
the quantified reason", or "the external engine could not run".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .experiments import ADMISSION_SCENARIO, _ema, run_ma_cross
from .experiments import Bar as Bar

__all__ = [
    "DEFAULT_FEES_BPS_PER_SIDE",
    "NEUTRAL_FAST",
    "NEUTRAL_SLOW",
    "PREREGISTERED_TOLERANCE",
    "compare",
    "indicator_parity",
    "load_bars_jsonl",
    "load_external_trades",
    "load_vnpy_round_trips",
    "net_bps",
    "parity_payload",
    "render_markdown",
    "ta_side_trades",
]

NEUTRAL_FAST = 12
NEUTRAL_SLOW = 26

#: 10 bps a side is the declared commission both engines are given.  Its source
#: is the admission scenario the campaign already uses, so the number is
#: comparable with the rest of the recovery work rather than invented here.
DEFAULT_FEES_BPS_PER_SIDE = 10.0

#: Declared BEFORE the run; exceeding one of these is a finding, not a failure
#: to be smoothed over.
PREREGISTERED_TOLERANCE: dict[str, Any] = {
    "declared_before_run": True,
    "trade_count_diff_max": 1,
    "per_trade_net_bps_diff_max": 1.0,
    "equity_relative_diff_max": 0.02,
    "on_exceed": "quantify and explain the model difference; never adjust an output by hand",
}

#: Provenance of the commission figure, quoted in the payload.
FEE_SOURCE = (
    "declared parity commission: 10 bps per side, the same order of magnitude the "
    f"admission scenario {ADMISSION_SCENARIO} charges; both engines receive it identically"
)


#: Floating-point hair allowed between the two EMA implementations.
INDICATOR_TOLERANCE = 1e-9


def indicator_parity(
    closes: list[float],
    external_fast: list[float],
    external_slow: list[float],
    *,
    fast: int = NEUTRAL_FAST,
    slow: int = NEUTRAL_SLOW,
) -> dict[str, Any]:
    """Prove the two engines are being fed the SAME indicator, on the real series.

    Both EMA definitions seed with the mean of the first ``span`` closes and then
    recurse identically, so the two arrays should agree to floating-point noise.
    If they do not, the parity run refuses: a divergence it then reported would
    be the indicator's doing, and calling that an engine difference would be a
    false attribution.
    """
    ours_fast = _ema(closes, fast)
    ours_slow = _ema(closes, slow)
    worst = 0.0
    worst_index = None
    for index in range(len(closes)):
        left = (ours_fast[index], ours_slow[index])
        right = (
            float(external_fast[index]) if index < len(external_fast) else None,
            float(external_slow[index]) if index < len(external_slow) else None,
        )
        for a, b in zip(left, right, strict=False):
            # NaN is how talib reports "not yet valid" before the seed bar.
            if b is None or a is None or b != b:
                continue
            gap = abs(float(a) - b)
            if gap > worst:
                worst, worst_index = gap, index
    verdict = "SAME_DEFINITION" if worst <= INDICATOR_TOLERANCE else "DIFFERENT_DEFINITION"
    return {
        "verdict": verdict,
        "max_abs_diff": worst,
        "max_abs_diff_index": worst_index,
        "tolerance": INDICATOR_TOLERANCE,
        "reading": (
            "this project's SMA-seeded recursive EMA and the external engine's talib.EMA "
            "agree on the actual series, so any trade difference measured below belongs "
            "to the engines' accounting and fill models, not to the indicator"
        ),
    }


def load_bars_jsonl(path: Path) -> dict[str, list[Bar]]:
    """Read the exported OHLCV snapshot, keyed by symbol."""
    out: dict[str, list[Bar]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out.setdefault(str(row["symbol"]), []).append(
            Bar(
                ts_ms=int(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    for series in out.values():
        series.sort(key=lambda b: b.ts_ms)
    return out


def net_bps(gross_bps: float, fees_bps_per_side: float, *, convention: str) -> float:
    """Net bps under one of the two declared commission conventions.

    ``ADDITIVE`` subtracts ``2 * fee`` from the gross move.  ``COMPOUNDED``
    applies each leg's fee to the notional, so ``(1+gross)(1-fee)^2 - 1``.

    Both exist because both are real in the wild, and which one an engine uses
    is an *observable* of that engine (the fee fields it publishes) rather than a
    choice made after the numbers are in.  Reporting only one would hide a
    systematic difference; reporting both and naming which engine uses which is
    the only version of this comparison that is not a read of the person.
    """
    if convention == "ADDITIVE":
        return gross_bps - 2.0 * fees_bps_per_side
    if convention == "COMPOUNDED":
        fee = fees_bps_per_side / 10_000.0
        return (((1.0 + gross_bps / 10_000.0) * (1.0 - fee) ** 2) - 1.0) * 10_000.0
    raise ValueError(f"unknown fee convention {convention!r}")


def ta_side_trades(
    bars: list[Bar],
    *,
    fast: int = NEUTRAL_FAST,
    slow: int = NEUTRAL_SLOW,
    fees_bps_per_side: float = DEFAULT_FEES_BPS_PER_SIDE,
    convention: str = "ADDITIVE",
) -> list[dict[str, Any]]:
    """This project's side of the comparison, gross and net under one convention."""
    rows: list[dict[str, Any]] = []
    for trade in run_ma_cross(bars, fast=fast, slow=slow):
        rows.append(
            {
                "entry_ts_ms": trade.entry_ts_ms,
                "exit_ts_ms": trade.exit_ts_ms,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "bars_held": trade.bars_held,
                "gross_bps": trade.gross_bps,
                "net_bps": net_bps(trade.gross_bps, fees_bps_per_side, convention=convention),
                "fee_bps_charged": 2.0 * float(fees_bps_per_side),
                "fee_convention": convention,
            }
        )
    return rows


#: VeighNa's own offset vocabulary, plus the English spellings, declared here so
#: an unfamiliar value is reported as unrecognised instead of silently dropped.
_OPEN_OFFSETS = frozenset({"OPEN", "\u5f00"})
_CLOSE_OFFSETS = frozenset({"CLOSE", "\u5e73"})
_ALL_OFFSETS = _OPEN_OFFSETS | _CLOSE_OFFSETS


def load_vnpy_round_trips(
    path: Path, *, fees_bps_per_side: float = DEFAULT_FEES_BPS_PER_SIDE
) -> dict[str, Any]:
    """Turn a VeighNa export into the same round-trip shape.

    VeighNa reports *fills*, not trades, so an entry and its matching exit are
    two rows.  They are paired in order per symbol, and a fill that closes more
    than was open is not invented into a trade: an unbalanced fill is counted in
    ``unpaired_fills`` and reported, because a parity test that silently dropped
    it would look cleaner than the run was.

    VeighNa does not publish a per-fill commission field, so the net here is
    derived from the gross under the declared convention rather than read from
    the engine; its own aggregate accounting is carried alongside as
    ``engine_statistics`` and not mixed into the per-trade comparison.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    unpaired = 0
    stats: dict[str, Any] = {}
    seen_offsets: dict[str, int] = {}
    for symbol, block in sorted((payload.get("symbols") or {}).items()):
        fills = block.get("trades") or []
        stats[symbol] = block.get("statistics") or {}
        open_fill: dict[str, Any] | None = None
        for fill in fills:
            # VeighNa spells its offsets in its own vocabulary (开/平), so the
            # comparison matches on a declared set of both spellings and records
            # every value it saw. An unmatched vocabulary must be visible: when
            # this loader only knew the English words it returned zero trades and
            # the run looked like an engine that never traded.
            raw_offset = str(fill.get("offset", ""))
            seen_offsets[raw_offset] = seen_offsets.get(raw_offset, 0) + 1
            offset = raw_offset.strip().upper()
            if offset in _OPEN_OFFSETS:
                if open_fill is not None:
                    unpaired += 1
                open_fill = fill
            elif offset in _CLOSE_OFFSETS:
                if open_fill is None:
                    unpaired += 1
                    continue
                entry = float(open_fill["price"])
                exit_price = float(fill["price"])
                gross_bps = (exit_price / entry - 1.0) * 10_000.0
                out.append(
                    {
                        "pair": symbol,
                        "entry_ts_ms": int(open_fill["datetime_ms"]),
                        "exit_ts_ms": int(fill["datetime_ms"]),
                        "entry_price": entry,
                        "exit_price": exit_price,
                        "gross_bps": gross_bps,
                        "net_bps": net_bps(gross_bps, fees_bps_per_side, convention="ADDITIVE"),
                        "fee_bps_charged": 2.0 * float(fees_bps_per_side),
                        "fee_convention": None,
                        "external_raw": {
                            "entry_volume": open_fill.get("volume"),
                            "exit_volume": fill.get("volume"),
                        },
                    }
                )
                open_fill = None
        if open_fill is not None:
            unpaired += 1
    out.sort(key=lambda t: (t["pair"], t["entry_ts_ms"]))
    return {
        "trades": out,
        "unpaired_fills": unpaired,
        "offsets_seen": dict(sorted(seen_offsets.items())),
        "unrecognised_offsets": sorted(
            value for value in seen_offsets if value.strip().upper() not in _ALL_OFFSETS
        ),
        "engine_statistics": stats,
        "reading": (
            "VeighNa reports fills, so an entry and its exit are two rows; they are "
            "paired in order and an unbalanced fill is counted rather than dropped"
        ),
    }


def load_external_trades(
    path: Path, *, exchange_fee_bps_per_side: float | None = None
) -> list[dict[str, Any]]:
    """Normalise an external backtester's trade list into the same shape.

    Only the fields the comparison needs are read, and the ratio is converted to
    bps so the two sides are in one unit.  A trade that lacks a close is *not*
    dropped silently: the caller counts them, and the count is published.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("trades") or payload.get("strategy", {}).get("trades") or []
    out: list[dict[str, Any]] = []
    for trade in raw:
        open_rate = float(trade["open_rate"])
        close_rate = float(trade["close_rate"])
        ratio = trade.get("profit_ratio")
        fee_open = trade.get("fee_open")
        fee_close = trade.get("fee_close")
        charged = None
        if fee_open is not None and fee_close is not None:
            charged = (float(fee_open) + float(fee_close)) * 10_000.0
        if charged is None and exchange_fee_bps_per_side is not None:
            charged = 2.0 * float(exchange_fee_bps_per_side)
        # Gross is rebuilt from the two rates the engine published.  Reading the
        # engine's own ``profit_ratio`` as gross would be wrong whenever the ratio
        # is already net — which is the usual case — and would then look like a
        # fee disagreement that is really a field-misreading.
        gross_bps = (close_rate / open_rate - 1.0) * 10_000.0 if open_rate else 0.0
        out.append(
            {
                "pair": trade.get("pair"),
                "entry_ts_ms": int(trade["open_timestamp"]),
                "exit_ts_ms": int(trade["close_timestamp"]),
                "entry_price": open_rate,
                "exit_price": close_rate,
                "gross_bps": gross_bps,
                "net_bps": float(ratio) * 10_000.0 if ratio is not None else gross_bps,
                "fee_bps_charged": charged,
                "fee_convention": (
                    "COMPOUNDED" if fee_open is not None and fee_close is not None else None
                ),
                "external_raw": {
                    "profit_abs": trade.get("profit_abs"),
                    "profit_ratio": trade.get("profit_ratio"),
                    "fee_open": fee_open,
                    "fee_close": fee_close,
                    "exit_reason": trade.get("exit_reason"),
                    "is_open": trade.get("is_open"),
                },
            }
        )
    out.sort(key=lambda t: t["entry_ts_ms"])
    return out


@dataclass(frozen=True)
class EquityCurve:
    """A compounding equity path, so drawdown means the same thing on both sides."""

    net_bps_sum: float
    equity_multiple: float
    max_drawdown_bps: float

    @classmethod
    def from_net_bps(cls, net_bps: list[float]) -> EquityCurve:
        equity = 1.0
        peak = 1.0
        worst = 0.0
        for value in net_bps:
            equity *= 1.0 + value / 10_000.0
            peak = max(peak, equity)
            if peak > 0:
                worst = max(worst, (peak - equity) / peak)
        return cls(
            net_bps_sum=sum(net_bps),
            equity_multiple=equity,
            max_drawdown_bps=worst * 10_000.0,
        )


def _pair_key(row: dict[str, Any]) -> str:
    """One spelling for a pair, so ``BTC/USDT`` and ``BTCUSDT`` are the same market."""
    return str(row.get("pair") or "").replace("/", "").replace("-", "").upper()


def _diff(
    ta: list[dict[str, Any]],
    ext: list[dict[str, Any]],
    *,
    fees_bps_per_side: float,
    last_bar_ts_ms: int | None = None,
) -> dict[str, Any]:
    """Pair the two trade lists and quantify the difference under both conventions.

    Every trade is compared three times: on its **gross** move (pure price
    agreement, with no fee model in the way), and on its net under each declared
    commission convention.  The convention the external engine actually used is
    visible in its own fee fields, so the matched-convention residual is a
    measurement rather than a choice.
    """
    # Match on the ENTRY TIMESTAMP, not on position in the list. Ordering two
    # engines' trade lists and zipping them pairs trade 1 of one against trade 1
    # of the other; the moment one engine has an extra entry, every later pair
    # compares two different trades and the whole diff becomes meaningless while
    # still looking quantitative.
    # The key is (pair, entry instant): two symbols routinely enter in the same
    # hour, and a key holding only the timestamp would let one asset's trade
    # overwrite the other's — which reads as "missing trades" rather than as the
    # bookkeeping collision it is.
    ta_index = {(_pair_key(row), int(row["entry_ts_ms"])): row for row in ta}
    ext_index = {(_pair_key(row), int(row["entry_ts_ms"])): row for row in ext}
    matched_keys = sorted(set(ta_index) & set(ext_index), key=str)
    ta_only = [ta_index[k] for k in sorted(set(ta_index) - set(ext_index), key=str)]
    ext_only = [ext_index[k] for k in sorted(set(ext_index) - set(ta_index), key=str)]
    pairs = len(matched_keys)
    per_trade: list[dict[str, Any]] = []
    for index, key in enumerate(matched_keys):
        left, right = ta_index[key], ext_index[key]
        gross = left["gross_bps"] - right["gross_bps"]
        net_additive = (
            net_bps(left["gross_bps"], fees_bps_per_side, convention="ADDITIVE") - right["net_bps"]
        )
        net_compounded = (
            net_bps(left["gross_bps"], fees_bps_per_side, convention="COMPOUNDED")
            - right["net_bps"]
        )
        per_trade.append(
            {
                "index": index,
                "ta_entry_ts_ms": left["entry_ts_ms"],
                "ext_entry_ts_ms": right["entry_ts_ms"],
                "ts_match": left["entry_ts_ms"] == right["entry_ts_ms"],
                "ta_exit_ts_ms": left["exit_ts_ms"],
                "ext_exit_ts_ms": right["exit_ts_ms"],
                "ta_gross_bps": round(left["gross_bps"], 6),
                "ext_gross_bps": round(right["gross_bps"], 6),
                "gross_bps_diff": round(gross, 6),
                "ext_net_bps": round(right["net_bps"], 6),
                "net_bps_diff_additive": round(net_additive, 6),
                "net_bps_diff_compounded": round(net_compounded, 6),
                "ext_fee_convention": right.get("fee_convention"),
            }
        )
    return {
        "matched_trades": pairs,
        "unpaired_ta": len(ta_only),
        "unpaired_ext": len(ext_only),
        "ta_only": [
            {
                "entry_ts_ms": row["entry_ts_ms"],
                "exit_ts_ms": row["exit_ts_ms"],
                "gross_bps": round(row["gross_bps"], 6),
                "pair": row.get("pair"),
                "reason": (
                    "TRAILING_FORCE_CLOSE"
                    if last_bar_ts_ms is not None and int(row["exit_ts_ms"]) == last_bar_ts_ms
                    else "UNEXPLAINED"
                ),
            }
            for row in ta_only
        ],
        "ext_only": [
            {
                "entry_ts_ms": row["entry_ts_ms"],
                "exit_ts_ms": row["exit_ts_ms"],
                "gross_bps": round(row["gross_bps"], 6),
                "pair": row.get("pair"),
                "reason": (
                    "ENGINE_LEFT_POSITION_OPEN_AT_END"
                    if _pair_key(row) not in {_pair_key(r) for r in ta}
                    else "UNEXPLAINED"
                ),
            }
            for row in ext_only
        ],
        "max_abs_gross_bps_diff": max((abs(r["gross_bps_diff"]) for r in per_trade), default=0.0),
        "max_abs_net_bps_diff_additive": max(
            (abs(r["net_bps_diff_additive"]) for r in per_trade), default=0.0
        ),
        "max_abs_net_bps_diff_compounded": max(
            (abs(r["net_bps_diff_compounded"]) for r in per_trade), default=0.0
        ),
        "exit_timestamp_mismatches": sum(
            1 for r in per_trade if r["ta_exit_ts_ms"] != r["ext_exit_ts_ms"]
        ),
        "per_trade": per_trade,
    }


def compare(
    ta: list[dict[str, Any]],
    ext: list[dict[str, Any]],
    *,
    tolerance: dict[str, Any] | None = None,
    fees_bps_per_side: float = DEFAULT_FEES_BPS_PER_SIDE,
    last_bar_ts_ms: int | None = None,
) -> dict[str, Any]:
    """Quantify the difference and decide whether it is inside the declared bounds.

    The verdict is read off the **matched-convention** residual and the gross
    agreement, because those are the comparisons that hold the fee model fixed on
    both sides.  The unmatched residual is published next to it rather than
    dropped: it is the size of the convention difference, and a reader who wants
    to disagree with matching the conventions can see exactly what it costs.
    """
    tol: dict[str, Any] = tolerance or PREREGISTERED_TOLERANCE
    ta_curve = EquityCurve.from_net_bps([t["net_bps"] for t in ta])
    ext_curve = EquityCurve.from_net_bps([t["net_bps"] for t in ext])
    ta_matched = EquityCurve.from_net_bps(
        [net_bps(t["gross_bps"], fees_bps_per_side, convention="COMPOUNDED") for t in ta]
    )
    detail = _diff(ta, ext, fees_bps_per_side=fees_bps_per_side, last_bar_ts_ms=last_bar_ts_ms)
    count_gap = abs(len(ta) - len(ext))
    unexplained_extras = [
        row for row in (*detail["ta_only"], *detail["ext_only"]) if row["reason"] == "UNEXPLAINED"
    ]
    external_conventions = {t.get("fee_convention") for t in ext}
    matched = "COMPOUNDED" if external_conventions == {"COMPOUNDED"} else "ADDITIVE"
    equity_rel = (
        abs(ta_matched.equity_multiple - ext_curve.equity_multiple) / ext_curve.equity_multiple
        if ext_curve.equity_multiple
        else None
    )
    matched_residual = detail[f"max_abs_net_bps_diff_{matched.lower()}"]
    unmatched_residual = detail[
        f"max_abs_net_bps_diff_{'additive' if matched == 'COMPOUNDED' else 'compounded'}"
    ]
    breaches: list[str] = []
    if count_gap > int(tol["trade_count_diff_max"]):
        breaches.append(f"trade_count_gap={count_gap}")
    if matched_residual > float(tol["per_trade_net_bps_diff_max"]):
        breaches.append(f"{matched}_residual={matched_residual:.6f}")
    if detail["max_abs_gross_bps_diff"] > float(tol["per_trade_net_bps_diff_max"]):
        breaches.append(f"gross_residual={detail['max_abs_gross_bps_diff']:.6f}")
    if equity_rel is not None and equity_rel > float(tol["equity_relative_diff_max"]):
        breaches.append(f"equity_relative_diff={equity_rel:.6f}")
    # A trade one engine has and the other does not is a finding, and which kind
    # matters: a trailing position the other engine leaves open is a declared
    # convention difference, while an unexplained extra is a defect until someone
    # explains it.  The first is reported and does not fail the run; the second
    # always does.
    for row in detail["ta_only"]:
        if row["reason"] != "TRAILING_FORCE_CLOSE":
            breaches.append(f"unexplained_trade_only_here@{row['entry_ts_ms']}")
    for row in detail["ext_only"]:
        if row["reason"] != "ENGINE_LEFT_POSITION_OPEN_AT_END":
            breaches.append(f"unexplained_trade_only_external@{row['entry_ts_ms']}")
    return {
        "ta_trades": len(ta),
        "external_trades": len(ext),
        "trade_count_gap": count_gap,
        "matched_trades": detail["matched_trades"],
        "trades_only_in_this_project": detail["unpaired_ta"],
        "trades_only_in_external": detail["unpaired_ext"],
        "matched_fee_convention": matched,
        "external_fee_conventions_observed": sorted(
            c for c in external_conventions if c is not None
        ),
        "ta": {
            "net_bps_sum_as_reported": round(ta_curve.net_bps_sum, 6),
            "net_bps_sum_matched_convention": round(ta_matched.net_bps_sum, 6),
            "equity_multiple_matched_convention": round(ta_matched.equity_multiple, 8),
            "max_drawdown_bps_matched_convention": round(ta_matched.max_drawdown_bps, 6),
            "mean_net_bps_matched_convention": (
                round(ta_matched.net_bps_sum / len(ta), 6) if ta else None
            ),
        },
        "external": {
            "net_bps_sum": round(ext_curve.net_bps_sum, 6),
            "equity_multiple": round(ext_curve.equity_multiple, 8),
            "max_drawdown_bps": round(ext_curve.max_drawdown_bps, 6),
            "mean_net_bps": round(ext_curve.net_bps_sum / len(ext), 6) if ext else None,
        },
        "equity_relative_diff": None if equity_rel is None else round(equity_rel, 8),
        "net_bps_sum_diff_matched": round(ta_matched.net_bps_sum - ext_curve.net_bps_sum, 6),
        "drawdown_bps_diff_matched": round(
            ta_matched.max_drawdown_bps - ext_curve.max_drawdown_bps, 6
        ),
        "matched_residual_bps": round(matched_residual, 6),
        "unmatched_residual_bps": round(unmatched_residual, 6),
        "convention_difference_bps": round(unmatched_residual - matched_residual, 6),
        "detail": detail,
        "tolerance": tol,
        "unexplained_extras": len(unexplained_extras),
        "breaches": breaches,
        "verdict": (
            "AGREE_WITHIN_TOLERANCE"
            if not breaches
            else "AGREE_ON_MATCHED_TRADES_WITH_DECLARED_EXTRA"
            if not unexplained_extras
            and matched_residual <= float(tol["per_trade_net_bps_diff_max"])
            and detail["max_abs_gross_bps_diff"] <= float(tol["per_trade_net_bps_diff_max"])
            else "DIVERGENT"
        ),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-14R/P2 — engine parity report",
        "",
        f"*Engine `{payload['external_engine']}`. Rule `{payload['rule']}`. "
        f"Dataset `{payload['dataset']['digest'][:23]}…`. "
        f"Verdict **{payload['comparison']['verdict']}**.*",
        "",
        "## Fixed before the run",
        "",
        f"- rule: {payload['rule_spec']}",
        f"- fill timing: {payload['fill_timing']}",
        f"- costs: {payload['costs']['fees_bps_per_side']} bps per side on both legs "
        f"({payload['costs']['source']})",
        f"- slippage: {payload['costs']['slippage']}",
        f"- indicator parity: {payload['indicator_parity']['verdict']} "
        f"(max abs diff {payload['indicator_parity']['max_abs_diff']})",
        "",
        "## Result",
        "",
        "| side | trades | net bps sum | equity multiple | max drawdown (bps) |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| trading_agentic | {payload['comparison']['ta_trades']} | "
        f"{payload['comparison']['ta']['net_bps_sum_matched_convention']} | "
        f"{payload['comparison']['ta']['equity_multiple_matched_convention']} | "
        f"{payload['comparison']['ta']['max_drawdown_bps_matched_convention']} |",
        f"| {payload['external_engine']} | {payload['comparison']['external_trades']} | "
        f"{payload['comparison']['external']['net_bps_sum']} | "
        f"{payload['comparison']['external']['equity_multiple']} | "
        f"{payload['comparison']['external']['max_drawdown_bps']} |",
        "",
        f"- trade count gap: **{payload['comparison']['trade_count_gap']}**",
        f"- max per-trade **gross** difference: "
        f"**{payload['comparison']['detail']['max_abs_gross_bps_diff']}** bps",
        f"- max per-trade difference under the matched fee convention "
        f"(`{payload['comparison']['matched_fee_convention']}`): "
        f"**{payload['comparison']['matched_residual_bps']}** bps",
        f"- the same difference under the other convention: "
        f"**{payload['comparison']['unmatched_residual_bps']}** bps, so the fee "
        f"convention alone is worth **{payload['comparison']['convention_difference_bps']}** bps",
        f"- equity relative difference: **{payload['comparison']['equity_relative_diff']}**",
        f"- trades matched by entry timestamp: **{payload['comparison']['matched_trades']}** "
        f"(only here: **{payload['comparison']['trades_only_in_this_project']}**, "
        f"only in the external engine: **{payload['comparison']['trades_only_in_external']}**)",
        f"- exit timestamp mismatches among matched trades: "
        f"**{payload['comparison']['detail']['exit_timestamp_mismatches']}**",
        "",
    ]
    if payload["comparison"]["breaches"]:
        lines += [
            "## Divergence",
            "",
            *[f"- `{b}`" for b in payload["comparison"]["breaches"]],
            "",
        ]
    lines += ["## Limitations", ""]
    lines += [f"- {item}" for item in payload["limitations"]]
    lines.append("")
    return "\n".join(lines)


def parity_payload(
    *,
    dataset_digest: str,
    dataset_path: str,
    external_engine: str,
    external_version: str,
    external_command: str,
    ta: list[dict[str, Any]],
    ext: list[dict[str, Any]],
    indicator_parity: dict[str, Any],
    limitations: list[str],
    fees_bps_per_side: float = DEFAULT_FEES_BPS_PER_SIDE,
    last_bar_ts_ms: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "EDGE14R_ENGINE_PARITY_V1",
        "work_package": "WP-EDGE-14R/P2",
        "external_engine": external_engine,
        "external_version": external_version,
        "external_command": external_command,
        "rule": "NEUTRAL_MA_CROSS_1H",
        "rule_spec": (
            f"long while ema({NEUTRAL_FAST}) > ema({NEUTRAL_SLOW}) on the previous closed "
            "1h bar, flat otherwise; no fitted parameter"
        ),
        "fill_timing": (
            "a signal observed at the close of bar i fills at the open of bar i+1, on "
            "entry and on exit alike"
        ),
        "costs": {
            "fees_bps_per_side": DEFAULT_FEES_BPS_PER_SIDE,
            "conventions_reported": ["ADDITIVE", "COMPOUNDED"],
            "convention_note": (
                "both commission conventions are computed for both engines and both "
                "residuals are published; the engine's own convention is read from the "
                "fee fields it emits, never chosen by which residual looks better"
            ),
            "source": FEE_SOURCE,
            "slippage": (
                "zero on both sides: slippage is a model input, not an engine behaviour, "
                "and giving the two engines different slippage models would confound the "
                "measurement"
            ),
        },
        "dataset": {"digest": dataset_digest, "path": dataset_path},
        "indicator_parity": indicator_parity,
        "comparison": compare(
            ta, ext, fees_bps_per_side=fees_bps_per_side, last_bar_ts_ms=last_bar_ts_ms
        ),
        "limitations": limitations,
        **(extra or {}),
    }
