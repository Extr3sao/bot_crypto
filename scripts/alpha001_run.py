"""ALPHA-001 — economic alpha discovery driver.

Fetches a real public OHLCV panel (Binance spot klines via ccxt, paginated to get
enough history), preregisters nothing new (the registry lives frozen in
``trading_bot.research.alpha001``), then runs the falsification pipeline:

    signal -> future return -> IC -> gross alpha -> cost screen -> power
    -> multiple testing -> best-of-N null -> winner's curse -> concentration
    -> stability -> admission -> one validation run

The HOLDOUT slice is never read: only its boundary index is computed.

Research only: no orders, no credentials, no capital.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import random
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from trading_bot.research import alpha001 as a1  # noqa: E402

CACHE_DIR = REPO / "data" / "raw" / "alpha001"
REPORT_DIR = REPO / "reports" / "alpha001"

UNIVERSE: tuple[str, ...] = (
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "SOL/USDT",
    "DOGE/USDT",
    "DOT/USDT",
    "LTC/USDT",
    "LINK/USDT",
    "TRX/USDT",
    "ETC/USDT",
    "XLM/USDT",
    "VET/USDT",
    "ATOM/USDT",
    "FIL/USDT",
    "ALGO/USDT",
    "AVAX/USDT",
    "BCH/USDT",
    "EOS/USDT",
)

DAILY_SINCE = "2017-01-01T00:00:00Z"
INTRADAY_SYMBOL = "BTC/USDT"
INTRADAY_SINCE = "2021-01-01T00:00:00Z"

DISCOVERY_FRACTION = 0.60
VALIDATION_FRACTION = 0.20
NULL_DRAWS = 1000
NULL_SEED = 20_261_003
BH_Q = 0.10
HOLM_ALPHA = 0.10
DESIGN_SIGMA_BPS = 400.0  # conservative per-decision gross sigma used to derive the hurdle


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #


def _cache_path(symbol: str, timeframe: str) -> Path:
    return CACHE_DIR / f"{symbol.replace('/', '-')}_{timeframe}.json"


def fetch_ohlcv(symbol: str, timeframe: str, since_iso: str) -> list[list[float]]:
    import ccxt

    exchange = ccxt.binance({"enableRateLimit": True})
    since = exchange.parse8601(since_iso)
    out: list[list[float]] = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        if not batch:
            break
        out.extend(batch)
        since = int(batch[-1][0]) + 1
        if len(batch) < 1000:
            break
        time.sleep(exchange.rateLimit / 1000.0)
    return out


def load_candles(symbol: str, timeframe: str, since_iso: str) -> list[list[float]]:
    path = _cache_path(symbol, timeframe)
    if path.is_file():
        loaded: list[list[float]] = json.loads(path.read_text(encoding="utf-8"))
        return loaded
    rows = fetch_ohlcv(symbol, timeframe, since_iso)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def dataset_hash(rows: Sequence[Sequence[float]]) -> str:
    payload = json.dumps(
        [[int(r[0])] + [round(float(v), 8) for v in r[1:6]] for r in rows], separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_closes(rows: Sequence[Sequence[float]]) -> dict[int, float]:
    return {int(r[0]): float(r[4]) for r in rows}


def _position_at_or_after(opens: Sequence[int], stamp: int) -> int:
    """First position whose open timestamp is >= ``stamp`` (calendar alignment)."""
    low, high = 0, len(opens)
    while low < high:
        middle = (low + high) // 2
        if opens[middle] < stamp:
            low = middle + 1
        else:
            high = middle
    return low


# --------------------------------------------------------------------------- #
# panel
# --------------------------------------------------------------------------- #


class Panel:
    def __init__(self, closes: dict[str, dict[int, float]], calendar: list[int]) -> None:
        self.closes = closes
        self.calendar = calendar
        self.index = {stamp: position for position, stamp in enumerate(calendar)}

    def price(self, symbol: str, stamp: int) -> float | None:
        return self.closes.get(symbol, {}).get(stamp)

    def returns(self, symbol: str, start: int, end: int, horizon: int = 1) -> list[float]:
        """Forward returns over ``horizon`` calendar steps for positions in [start, end)."""
        out: list[float] = []
        for position in range(start, end):
            if position + horizon >= len(self.calendar):
                break
            price_now = self.price(symbol, self.calendar[position])
            price_then = self.price(symbol, self.calendar[position + horizon])
            if price_now and price_then and price_now > 0:
                out.append(price_then / price_now - 1.0)
        return out


def build_panel(daily: Mapping[str, Sequence[Sequence[float]]]) -> Panel:
    closes = {symbol: to_closes(rows) for symbol, rows in daily.items()}
    calendar = sorted(closes["BTC/USDT"].keys())
    return Panel(closes, calendar)


# --------------------------------------------------------------------------- #
# causal helpers
# --------------------------------------------------------------------------- #


def rolling_mean_std(
    values: Sequence[float], window: int
) -> tuple[list[float | None], list[float | None]]:
    means: list[float | None] = []
    stds: list[float | None] = []
    for position in range(len(values)):
        if position < window:
            means.append(None)
            stds.append(None)
            continue
        chunk = values[position - window : position]
        means.append(statistics.fmean(chunk))
        deviation = statistics.pstdev(chunk)
        stds.append(deviation)
    return means, stds


def sign(value: float) -> float:
    return 1.0 if value > 0 else (-1.0 if value < 0 else 0.0)


# --------------------------------------------------------------------------- #
# hypothesis builders  (each returns aligned signal / forward / contribution)
# --------------------------------------------------------------------------- #


def _asset_forward(
    panel: Panel, symbol: str, start: int, end: int, horizon: int
) -> list[float | None]:
    out: list[float | None] = []
    for position in range(start, end):
        if position + horizon >= len(panel.calendar):
            out.append(None)
            continue
        price_now = panel.price(symbol, panel.calendar[position])
        price_then = panel.price(symbol, panel.calendar[position + horizon])
        out.append(
            price_then / price_now - 1.0 if price_now and price_then and price_now > 0 else None
        )
    return out


def _basket(
    closes: Mapping[str, Mapping[int, float]], calendar: Sequence[int], position: int
) -> list[float]:
    values = [closes[symbol].get(calendar[position]) for symbol in closes]
    return [value for value in values if value]


def build_dispersion(
    panel: Panel, start: int, end: int, *, change: bool, horizon: int = 1
) -> dict[str, list[Any]]:
    # cross-sectional std of 1d returns, causal (uses t-1 -> t)
    dispersion: list[float | None] = [None]
    for position in range(1, len(panel.calendar)):
        rets: list[float] = []
        for symbol in panel.closes:
            price_now = panel.price(symbol, panel.calendar[position])
            price_prev = panel.price(symbol, panel.calendar[position - 1])
            if price_now and price_prev and price_prev > 0:
                rets.append(price_now / price_prev - 1.0)
        dispersion.append(statistics.pstdev(rets) if len(rets) >= 5 else None)

    signal: list[float | None] = []
    forward = _asset_forward(panel, "BTC/USDT", start, end, horizon)
    for position in range(start, end):
        disp = dispersion[position]
        if change:
            previous = dispersion[position - 1] if position >= 1 else None
            signal.append(None if disp is None or previous is None else disp - previous)
        else:
            signal.append(disp)
    contributions: list[float] = []
    for sig, fwd in zip(signal, forward, strict=True):
        contributions.append(0.0 if sig is None or fwd is None else -sign(sig) * fwd * 1e4)
    return {"signal": signal, "forward": forward, "contributions": contributions}


def build_lead_lag(
    panel: Panel, start: int, end: int, *, lag_days: int, horizon: int = 1
) -> dict[str, list[Any]]:
    btc = panel.closes["BTC/USDT"]
    calendar = panel.calendar
    alts = [symbol for symbol in panel.closes if symbol != "BTC/USDT"]
    signal: list[float | None] = []
    forward: list[float | None] = []
    contributions: list[float] = []
    for position in range(start, end):
        if position - lag_days < 0 or position + horizon >= len(calendar):
            signal.append(None)
            forward.append(None)
            contributions.append(0.0)
            continue
        price_then = btc.get(calendar[position - lag_days])
        price_now = btc.get(calendar[position])
        sig = (
            (price_now / price_then - 1.0) if price_then and price_now and price_then > 0 else None
        )
        returns: list[float] = []
        for symbol in alts:
            p_now = panel.price(symbol, calendar[position])
            p_next = panel.price(symbol, calendar[position + horizon])
            if p_now and p_next and p_now > 0:
                returns.append(p_next / p_now - 1.0)
        fwd = statistics.fmean(returns) if returns else None
        signal.append(sig)
        forward.append(fwd)
        contributions.append(0.0 if sig is None or fwd is None else sign(sig) * fwd * 1e4)
    return {"signal": signal, "forward": forward, "contributions": contributions}


def build_breadth(
    panel: Panel, start: int, end: int, *, change_days: int | None, horizon: int
) -> dict[str, list[Any]]:
    calendar = panel.calendar
    breadth: list[float | None] = []
    for position in range(len(calendar)):
        above = 0
        total = 0
        for symbol in panel.closes:
            price = panel.price(symbol, calendar[position])
            if price is None or position < 20:
                continue
            past = panel.price(symbol, calendar[position - 20])
            if past and price:
                total += 1
                if price > past:
                    above += 1
        breadth.append(above / total if total >= 10 else None)
    signal: list[float | None] = []
    forward: list[float | None] = []
    contributions: list[float] = []
    for position in range(start, end):
        if change_days is None:
            sig = breadth[position] if breadth[position] is not None else None
            fwd = _asset_forward(panel, "BTC/USDT", position, position + 1, horizon)[0]
            direction = sign(sig - 0.5) if sig is not None else 0.0
        else:
            now = breadth[position]
            past = breadth[position - change_days] if position - change_days >= 0 else None
            sig = None if now is None or past is None else now - past
            returns: list[float] = []
            for symbol in panel.closes:
                p_now = panel.price(symbol, calendar[position])
                p_next = (
                    panel.price(symbol, calendar[position + horizon])
                    if position + horizon < len(calendar)
                    else None
                )
                if p_now and p_next and p_now > 0:
                    returns.append(p_next / p_now - 1.0)
            fwd = statistics.fmean(returns) if returns else None
            direction = sign(sig) if sig is not None else 0.0
        signal.append(sig)
        forward.append(fwd)
        contributions.append(0.0 if sig is None or fwd is None else direction * fwd * 1e4)
    return {"signal": signal, "forward": forward, "contributions": contributions}


def _mean_forward(panel: Panel, symbols: Sequence[str], position: int, horizon: int) -> float:
    calendar = panel.calendar
    if position + horizon >= len(calendar):
        return 0.0
    values: list[float] = []
    for symbol in symbols:
        now = panel.price(symbol, calendar[position])
        then = panel.price(symbol, calendar[position + horizon])
        if now and then and now > 0:
            values.append(then / now - 1.0)
    return statistics.fmean(values) if values else 0.0


def build_vol_ratio_xsec(
    panel: Panel, start: int, end: int, *, horizon: int = 5
) -> dict[str, list[Any]]:
    calendar = panel.calendar

    def realised(symbol: str, position: int, window: int) -> float | None:
        if position - window < 0:
            return None
        rets: list[float] = []
        for offset in range(position - window, position):
            a = panel.price(symbol, calendar[offset])
            b = panel.price(symbol, calendar[offset + 1]) if offset + 1 < len(calendar) else None
            if a and b and a > 0:
                rets.append(b / a - 1.0)
        return statistics.pstdev(rets) if len(rets) >= 3 else None

    signal: list[float | None] = []
    forward: list[float | None] = []
    contributions: list[float] = []
    for position in range(start, end):
        ratios: dict[str, float] = {}
        for symbol in panel.closes:
            short = realised(symbol, position, 5)
            long = realised(symbol, position, 20)
            if short is not None and long and long > 0:
                ratios[symbol] = short / long
        if len(ratios) < 8 or position + horizon >= len(calendar):
            signal.append(None)
            forward.append(None)
            contributions.append(0.0)
            continue
        ranked = sorted(ratios.items(), key=lambda item: item[1])
        k = max(1, len(ranked) // 4)
        lows = [symbol for symbol, _ in ranked[:k]]
        highs = [symbol for symbol, _ in ranked[-k:]]
        spread = _mean_forward(panel, lows, position, horizon) - _mean_forward(
            panel, highs, position, horizon
        )
        signal.append(ratios[ranked[0][0]])
        forward.append(spread)
        contributions.append(spread * 1e4)
    return {"signal": signal, "forward": forward, "contributions": contributions}


def build_vol_ratio_ts(
    panel: Panel, start: int, end: int, *, horizon: int = 1
) -> dict[str, list[Any]]:
    calendar = panel.calendar
    rets: list[float | None] = [None]
    for position in range(1, len(calendar)):
        a = panel.price("BTC/USDT", calendar[position - 1])
        b = panel.price("BTC/USDT", calendar[position])
        rets.append(b / a - 1.0 if a and b and a > 0 else None)
    clean = [value if value is not None else 0.0 for value in rets]
    means5, stds5 = rolling_mean_std(clean, 5)
    means20, stds20 = rolling_mean_std(clean, 20)
    signal: list[float | None] = []
    forward = _asset_forward(panel, "BTC/USDT", start, end, horizon)
    for position in range(start, end):
        short_std = stds5[position]
        long_std = stds20[position]
        if short_std is None or long_std is None or long_std == 0.0:
            signal.append(None)
        else:
            signal.append(short_std / long_std)
    _ = means5, means20
    contributions: list[float] = []
    for sig, fwd in zip(signal, forward, strict=True):
        contributions.append(0.0 if sig is None or fwd is None else -sign(sig - 1.0) * fwd * 1e4)
    return {"signal": signal, "forward": forward, "contributions": contributions}


def build_vol_shock(
    panel: Panel, start: int, end: int, *, reverse: bool, horizon: int = 1
) -> dict[str, list[Any]]:
    calendar = panel.calendar
    rets: list[float | None] = [None]
    for position in range(1, len(calendar)):
        a = panel.price("BTC/USDT", calendar[position - 1])
        b = panel.price("BTC/USDT", calendar[position])
        rets.append(b / a - 1.0 if a and b and a > 0 else None)
    clean = [value if value is not None else 0.0 for value in rets]
    _, stds = rolling_mean_std(clean, 20)
    signal: list[float | None] = []
    forward = _asset_forward(panel, "BTC/USDT", start, end, horizon)
    for position in range(start, end):
        shock_ret = rets[position]
        sigma = stds[position]
        if shock_ret is None or sigma is None or sigma == 0.0:
            signal.append(None)
        elif abs(shock_ret) > 2.0 * sigma:
            signal.append(shock_ret)
        else:
            signal.append(None)
    contributions: list[float] = []
    for sig, fwd in zip(signal, forward, strict=True):
        if sig is None or fwd is None:
            contributions.append(0.0)
        else:
            direction = (-1.0 if reverse else 1.0) * sign(sig)
            contributions.append(direction * fwd * 1e4)
    return {"signal": signal, "forward": forward, "contributions": contributions}


def build_session(
    intraday: Sequence[Sequence[float]],
    start: int,
    end: int,
    *,
    fade: bool,
    horizon: int = 1,
    hard_end: int | None = None,
) -> dict[str, list[Any]]:
    """Bar-of-day hypothesis over an explicit window.

    ``hard_end`` is the barrier for *realised* returns: the last decision of an
    earlier phase may not take its forward return from a later phase, so the
    holdout slice stays untouched even at the window boundary.
    """
    opens = [int(row[0]) for row in intraday]
    closes = [float(row[4]) for row in intraday]
    limit = len(closes) if hard_end is None else min(hard_end, len(closes))
    signal: list[float | None] = []
    forward: list[float | None] = []
    contributions: list[float] = []
    for position in range(start, end):
        if position == 0 or position + horizon >= limit:
            signal.append(None)
            forward.append(None)
            contributions.append(0.0)
            continue
        ret = closes[position] / closes[position - 1] - 1.0 if closes[position - 1] > 0 else None
        fwd = closes[position + horizon] / closes[position] - 1.0 if closes[position] > 0 else None
        hour = dt.datetime.fromtimestamp(opens[position] // 1000, dt.UTC).hour
        in_window = hour in ((0, 1, 2, 3) if not fade else (12, 13, 14, 15))
        signal.append(ret if in_window else None)
        forward.append(fwd)
        if ret is None or fwd is None or not in_window:
            contributions.append(0.0)
        else:
            direction = (-1.0 if fade else 1.0) * sign(ret)
            contributions.append(direction * fwd * 1e4)
    return {"signal": signal, "forward": forward, "contributions": contributions}


# --------------------------------------------------------------------------- #
# statistics over a hypothesis
# --------------------------------------------------------------------------- #


def _one_sided_p(t_stat: float) -> float:
    """One-sided p for H1: mean gross alpha > 0, by normal approximation."""
    if t_stat <= 0:
        return 1.0
    return max(0.0, min(1.0, 0.5 * math.erfc(t_stat / math.sqrt(2.0))))


def summarise(
    names: dict[str, Any], built: Mapping[str, list[Any]], *, hurdle_bps: float
) -> dict[str, Any]:
    paired = [
        (float(sig), float(fwd))
        for sig, fwd in zip(built["signal"], built["forward"], strict=True)
        if sig is not None and fwd is not None
    ]
    signal = [sig for sig, _ in paired]
    forward = [fwd for _, fwd in paired]
    contributions = [
        float(value)
        for value, sig in zip(built["contributions"], built["signal"], strict=True)
        if sig is not None
    ]

    # Recover the signed direction of each active decision (contribution = direction * forward).
    # A permutation null must break the signal<->return alignment, not permute the
    # contributions themselves (their mean is shift-invariant).
    active_direction: list[float] = []
    active_forward: list[float] = []
    for contribution, fwd, sig in zip(
        built["contributions"], built["forward"], built["signal"], strict=True
    ):
        if sig is None or fwd is None or fwd == 0.0:
            continue
        active_direction.append(-1.0 if contribution * fwd < 0 else 1.0)
        active_forward.append(float(fwd))

    n = len(contributions)
    gross = a1.mean(contributions)
    sigma = statistics.pstdev(contributions) if n > 1 else 0.0
    n_eff = a1.effective_sample_size(contributions) if n > 1 else float(n)
    se = sigma / math.sqrt(n_eff) if n_eff > 0 and sigma > 0 else float("inf")
    t_stat = gross / se if se not in (0.0, float("inf")) else 0.0
    p_raw = _one_sided_p(t_stat)
    ic = a1.spearman(signal, forward) if len(signal) >= 5 else 0.0
    power = a1.power_class(n_effective=n_eff, sigma_bps=sigma, hurdle_bps=hurdle_bps)
    return {
        "hypothesis_id": names["hypothesis_id"],
        "family_id": names["family_id"],
        "n": n,
        "n_effective": round(n_eff, 3),
        "gross_bps": round(gross, 6),
        "sigma_bps": round(sigma, 6),
        "ic": round(ic, 6),
        "t_stat": round(t_stat, 6),
        "p_raw": round(p_raw, 8),
        "net_bps": round(gross - a1.COST_BPS_V3, 6),
        "power_class": power["class"],
        "mde_bps": power["mde_bps"],
        "hurdle_bps": round(hurdle_bps, 6),
        "gross_above_hurdle": gross >= hurdle_bps,
        "contributions": contributions,
        "signal": signal,
        "forward": forward,
        "active_direction": active_direction,
        "active_forward": active_forward,
    }


def circular_shift(values: Sequence[float], shift: int) -> list[float]:
    if not values:
        return []
    shift %= len(values)
    return list(values[shift:]) + list(values[:shift])


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def build_hypotheses(
    panel: Panel,
    intraday: Any,
    start: int,
    end: int,
    *,
    session_start: int = 60,
    session_end: int | None = None,
    session_hard_end: int | None = None,
) -> dict[str, dict[str, list[Any]]]:
    session_end = len(intraday) - 2 if session_end is None else session_end
    return {
        "A1-H01": build_dispersion(panel, start, end, change=False),
        "A1-H02": build_dispersion(panel, start, end, change=True),
        "A1-H03": build_lead_lag(panel, start, end, lag_days=1),
        "A1-H04": build_lead_lag(panel, start, end, lag_days=3),
        "A1-H05": build_breadth(panel, start, end, change_days=None, horizon=3),
        "A1-H06": build_breadth(panel, start, end, change_days=5, horizon=1),
        "A1-H07": build_vol_ratio_xsec(panel, start, end, horizon=5),
        "A1-H08": build_vol_ratio_ts(panel, start, end, horizon=1),
        "A1-H09": build_vol_shock(panel, start, end, reverse=False, horizon=1),
        "A1-H10": build_vol_shock(panel, start, end, reverse=True, horizon=1),
        "A1-H11": build_session(
            intraday, session_start, session_end, fade=False, hard_end=session_hard_end
        ),
        "A1-H12": build_session(
            intraday, session_start, session_end, fade=True, hard_end=session_hard_end
        ),
    }


def _write_json(name: str, payload: Any) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / name).write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ALPHA-001 discovery driver")
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args(argv)

    if not args.skip_fetch:
        print("fetching daily universe ...")
        for symbol in UNIVERSE:
            rows = load_candles(symbol, "1d", DAILY_SINCE)
            print(f"  {symbol}: {len(rows)} daily bars")
    daily = {symbol: load_candles(symbol, "1d", DAILY_SINCE) for symbol in UNIVERSE}
    intraday = load_candles(INTRADAY_SYMBOL, "4h", INTRADAY_SINCE)

    hashes = {symbol: dataset_hash(rows) for symbol, rows in daily.items()}
    intraday_hash = dataset_hash(intraday)

    panel = build_panel(daily)
    n = len(panel.calendar)
    discovery_end = int(n * DISCOVERY_FRACTION)
    validation_end = int(n * (DISCOVERY_FRACTION + VALIDATION_FRACTION))
    # HOLDOUT = [validation_end, n) is never read.

    # The split is a *calendar* split, not a per-series index split: every timeframe
    # ends its discovery phase on the same date, so the 4h hypotheses cover exactly
    # the period the daily ones do and neither can reach past validation_end.
    intraday_opens = [int(row[0]) for row in intraday]
    intraday_discovery_end = _position_at_or_after(intraday_opens, panel.calendar[discovery_end])
    intraday_validation_end = _position_at_or_after(intraday_opens, panel.calendar[validation_end])

    built = build_hypotheses(
        panel,
        intraday,
        0,
        discovery_end,
        session_start=60,
        session_end=intraday_discovery_end,
        session_hard_end=intraday_validation_end,
    )

    # design sample: number of non-overlapping decisions in DISCOVERY
    design_n = max(1, discovery_end)
    hurdle = a1.min_gross_hurdle_bps(n_effective=design_n, sigma_trade_bps=DESIGN_SIGMA_BPS)
    hurdle_bps = hurdle["min_gross_alpha_hurdle_bps"]

    names = {item["hypothesis_id"]: item for item in a1.HYPOTHESES}
    summaries = {hid: summarise(names[hid], built[hid], hurdle_bps=hurdle_bps) for hid in built}

    pvalues = [summaries[hid]["p_raw"] for hid in sorted(summaries)]
    ids = sorted(summaries)
    bh = a1.benjamini_hochberg(pvalues, q=BH_Q)
    holm_pass = a1.holm(pvalues, alpha=HOLM_ALPHA)

    # best-of-N null.  Walking the real decision indices: each hypothesis enters the
    # null with its own observed gross and its own alignment-shift distribution.
    rng = random.Random(NULL_SEED)
    observed_best_id = max(ids, key=lambda hid: a1.mean(summaries[hid]["contributions"]))
    observed_best = a1.mean(summaries[observed_best_id]["contributions"])
    null_best: list[float] = []
    for _ in range(NULL_DRAWS):
        best = float("-inf")
        for hid in ids:
            direction = summaries[hid]["active_direction"]
            forward = summaries[hid]["active_forward"]
            if len(direction) < 20:
                continue
            shift = rng.randrange(1, len(direction))
            shifted_direction = circular_shift(direction, shift)
            best = max(
                best,
                a1.mean([d * f * 1e4 for d, f in zip(shifted_direction, forward, strict=True)]),
            )
        if best > float("-inf"):
            null_best.append(best)
    best_null = a1.best_of_n_null(observed_best, null_best)
    curse = a1.winners_curse_shrinkage(
        observed_best=observed_best, null_best_median=float(best_null.get("null_median", 0.0))
    )

    best_id = observed_best_id
    conc = a1.concentration(
        [value for value in summaries[best_id]["contributions"] if value != 0.0]
    )
    signs = a1.sign_concentration(
        [value for value in summaries[best_id]["contributions"] if value != 0.0]
    )
    stability = a1.stability_by_window(summaries[best_id]["contributions"], windows=4)

    # admission
    admitted: list[str] = []
    for hid in ids:
        item = summaries[hid]
        ok = (
            abs(item["ic"]) > 0.0
            and item["gross_above_hurdle"]
            and bh[ids.index(hid)]
            and item["power_class"] == "POWERED"
            and a1.concentration([v for v in item["contributions"] if v != 0.0])["classification"]
            == "ROBUST"
        )
        if ok:
            admitted.append(hid)

    validation: dict[str, Any] = {}
    for hid in admitted[:3]:
        spec = names[hid]
        if spec["timeframe"] == "4h":
            vbuilt = build_session(
                intraday,
                intraday_discovery_end,
                intraday_validation_end,
                fade=hid == "A1-H12",
                hard_end=intraday_validation_end,
            )
        elif hid == "A1-H01":
            vbuilt = build_dispersion(panel, discovery_end, validation_end, change=False)
        elif hid == "A1-H02":
            vbuilt = build_dispersion(panel, discovery_end, validation_end, change=True)
        elif hid == "A1-H03":
            vbuilt = build_lead_lag(panel, discovery_end, validation_end, lag_days=1)
        elif hid == "A1-H04":
            vbuilt = build_lead_lag(panel, discovery_end, validation_end, lag_days=3)
        elif hid == "A1-H05":
            vbuilt = build_breadth(
                panel, discovery_end, validation_end, change_days=None, horizon=3
            )
        elif hid == "A1-H06":
            vbuilt = build_breadth(panel, discovery_end, validation_end, change_days=5, horizon=1)
        elif hid == "A1-H07":
            vbuilt = build_vol_ratio_xsec(panel, discovery_end, validation_end, horizon=5)
        elif hid == "A1-H08":
            vbuilt = build_vol_ratio_ts(panel, discovery_end, validation_end, horizon=1)
        elif hid == "A1-H09":
            vbuilt = build_vol_shock(panel, discovery_end, validation_end, reverse=False)
        else:
            vbuilt = build_vol_shock(panel, discovery_end, validation_end, reverse=True)
        vsum = summarise(names[hid], vbuilt, hurdle_bps=hurdle_bps)
        reproduced = vsum["gross_bps"] > 0 and sign(vsum["gross_bps"]) == sign(
            summaries[hid]["gross_bps"]
        )
        classification = (
            "REPRODUCED"
            if reproduced and vsum["gross_bps"] >= hurdle_bps
            else ("UNDERPOWERED" if vsum["power_class"] == "UNDERPOWERED" else "NOT_REPRODUCED")
        )
        validation[hid] = {
            k: v for k, v in vsum.items() if k not in ("contributions", "signal", "forward")
        }
        validation[hid]["classification"] = classification

    registry_hash = a1.hypothesis_registry_hash()

    artifacts = {
        "campaign": "ALPHA-001",
        "holdout_read": False,
        "cost_bps": a1.COST_BPS_V3,
        "hurdle": hurdle,
        "hurdle_bps": hurdle_bps,
        "registry_hash": registry_hash,
        "hypothesis_count": len(a1.HYPOTHESES),
        "family_count": len(a1.FAMILIES),
        "universe": list(UNIVERSE),
        "panel": {"n_days": n, "discovery_end": discovery_end, "validation_end": validation_end},
        "dataset_hashes": {**hashes, "BTC/USDT:4h": intraday_hash},
        "null": {"draws": NULL_DRAWS, "seed": NULL_SEED, **best_null},
        "winners_curse": curse,
        "best_hypothesis": best_id,
        "concentration": conc,
        "sign_concentration": signs,
        "stability": stability,
        "multiple_testing": {
            "bh_q": BH_Q,
            "holm_alpha": HOLM_ALPHA,
            "rows": [
                {
                    "hypothesis_id": hid,
                    "p_raw": summaries[hid]["p_raw"],
                    "bh_pass": bh[index],
                    "holm_pass": holm_pass[index],
                }
                for index, hid in enumerate(ids)
            ],
        },
        "admitted": admitted,
        "validation": validation,
        "summaries": {
            hid: {
                k: v
                for k, v in summaries[hid].items()
                if k
                not in (
                    "signal",
                    "forward",
                    "contributions",
                    "active_direction",
                    "active_forward",
                )
            }
            for hid in ids
        },
        "series": {
            hid: {
                "signal": summaries[hid]["signal"],
                "forward": summaries[hid]["forward"],
                "contributions": summaries[hid]["contributions"],
                "active_direction": summaries[hid]["active_direction"],
                "active_forward": summaries[hid]["active_forward"],
            }
            for hid in ids
        },
        "generated_at": int(time.time()),
    }
    series: dict[str, Any] = artifacts.pop("series")
    _write_json("ALPHA001_ARTIFACTS.json", artifacts)
    _write_json("ALPHA001_SERIES.json", series)

    print(
        json.dumps(
            {
                "registry_hash": registry_hash,
                "hurdle_bps": hurdle_bps,
                "observed_best_bps": observed_best,
                "best_hypothesis": best_id,
                "p_null_best_ge_observed": best_null.get("p_null_best_ge_observed"),
                "admitted": admitted,
                "validation": {k: v["classification"] for k, v in validation.items()},
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
