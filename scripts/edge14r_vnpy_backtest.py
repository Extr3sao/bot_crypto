"""edge14r_vnpy_backtest — run the neutral rule through VeighNa's CTA backtester.

Runs with the *engine's* interpreter, from a scratch workspace, and writes one
JSON file holding the trades VeighNa actually produced.  Nothing here is copied
into the project: the strategy is a transcription of the parity rule into
VeighNa's vocabulary, written into the engine's own workspace.

VeighNa's CTA backtester crosses orders at the start of the NEXT bar using that
bar's open price (``new_bar`` sets ``self.bar`` and then crosses before
``on_bar``), which is the same fill timing the other engines are given.  That is
checked rather than assumed: the exported trades carry their own timestamps and
the comparison looks at them.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

STRATEGY_SOURCE = '''\
"""NEUTRAL_MA_CROSS_1H — the parity rule in VeighNa's vocabulary.

Long while ema(12) > ema(26) on the previous closed bar, flat otherwise. Orders
are sent marketable (just through the touch) so they cross at the next bar's
open, which is where this engine fills them and where the other engines fill
too. No fitted parameter and one exit path.
"""

from vnpy.trader.utility import ArrayManager
from vnpy_ctastrategy.backtesting import CtaTemplate


class NeutralMaCross(CtaTemplate):
    author = "WP-EDGE-14R"

    fast_window = 12
    slow_window = 26
    #: Notional the parity run trades, so the position size is a declared input
    #: rather than whatever the engine's default volume happens to be.
    notional = 10000.0
    touch = 0.01

    parameters = ["fast_window", "slow_window", "notional", "touch"]
    variables = ["pos"]

    def on_init(self):
        # The declared indicator is the SMA-seeded recursive EMA over the bar
        # series. ArrayManager.ema() is NOT that: it runs talib over a sliding
        # window, so the seed is re-taken from the window's own first bar every
        # time and the value it returns is a different number. The strategy
        # therefore keeps the close series itself and computes the declared
        # indicator on it (see ``ema_probe.json`` for the measured size of the
        # difference the convenience call would have introduced).
        self.am = ArrayManager(size=26)
        self.closes: list[float] = []
        self.ema_probe: list[dict[str, Any]] = []
        self.write_log("NeutralMaCross initialised")

    def _ema(self, period: int) -> float:
        closes = self.closes
        if len(closes) < period:
            return float("nan")
        k = 2.0 / (period + 1.0)
        value = sum(closes[:period]) / period
        for close in closes[period:]:
            value = close * k + value * (1.0 - k)
        return value

    def _volume(self, price: float) -> float:
        if price <= 0:
            return 0.0
        return round(self.notional / price, 6)

    def on_bar(self, bar):
        self.closes.append(float(bar.close_price))
        self.am.update_bar(bar)
        if len(self.closes) < self.slow_window:
            return

        fast = self._ema(self.fast_window)
        slow = self._ema(self.slow_window)
        if self.am.inited:
            window_fast = float(self.am.ema(self.fast_window, array=True)[-1])
            window_slow = float(self.am.ema(self.slow_window, array=True)[-1])
            self.ema_probe.append(
                {
                    "index": len(self.closes) - 1,
                    "declared_fast": fast,
                    "window_fast": window_fast,
                    "declared_slow": slow,
                    "window_slow": window_slow,
                }
            )

        if fast > slow and self.pos == 0:
            volume = self._volume(bar.close_price)
            if volume > 0:
                self.buy(bar.close_price * (1 + self.touch), volume)
        elif fast < slow and self.pos > 0:
            # Exit the whole book.  Re-deriving the volume from the notional would
            # ask to sell a size the position does not hold whenever the price
            # moved, and this engine rejects an oversized sell — which would leave
            # the position open forever and quietly end the run after one trade.
            self.sell(bar.close_price * (1 - self.touch), self.pos)
'''


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-14R VeighNa CTA backtest")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--fee-bps-per-side", type=float, default=10.0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    # The engine reads its database settings from vt_setting.json in the cwd.
    Path("vt_setting.json").write_text(
        json.dumps({"database.driver": "sqlite", "database.database": "edge14r_vnpy.db"}),
        encoding="utf-8",
    )
    strategies = Path("strategies")
    strategies.mkdir(exist_ok=True)
    sys.path.insert(0, str(strategies.resolve()))
    (strategies / "NeutralMaCross.py").write_text(STRATEGY_SOURCE, encoding="utf-8")

    from vnpy.trader.constant import Exchange, Interval  # type: ignore[import-not-found]
    from vnpy.trader.database import get_database  # type: ignore[import-not-found]
    from vnpy.trader.object import BarData  # type: ignore[import-not-found]
    from vnpy_ctastrategy.backtesting import (  # type: ignore[import-not-found]
        BacktestingEngine,
    )

    wanted = {s.strip().replace("/", ""): s.strip() for s in args.symbols.split(",") if s.strip()}
    rows: dict[str, list[BarData]] = {key: [] for key in wanted}
    for line in Path(args.bars).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = str(row["symbol"]).replace("/", "")
        if key not in rows:
            continue
        moment = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=UTC).replace(tzinfo=None)
        rows[key].append(
            BarData(
                symbol=key,
                # VeighNa 4.5 carries no crypto venue in its Exchange enum, so the
                # run declares its venue explicitly instead of borrowing a code
                # that means something else in this engine's vocabulary.
                exchange=Exchange.GLOBAL,
                datetime=moment,
                interval=Interval.HOUR,
                volume=float(row["volume"]),
                turnover=0.0,
                open_interest=0.0,
                open_price=float(row["open"]),
                high_price=float(row["high"]),
                low_price=float(row["low"]),
                close_price=float(row["close"]),
                gateway_name="EDGE14R",
            )
        )

    database = get_database()
    report: dict[str, Any] = {"engine": "vnpy_ctastrategy", "symbols": {}, "order_sent": False}

    for key, series in sorted(rows.items()):
        if not series:
            report["symbols"][key] = {"outcome": "NO_BARS"}
            continue
        # Already present from an earlier run in the same workspace is fine.
        with contextlib.suppress(Exception):
            database.save_bar_data(series)

        engine = BacktestingEngine()
        engine.set_parameters(
            vt_symbol=f"{key}.GLOBAL",
            interval=Interval.HOUR,
            start=series[0].datetime,
            end=series[-1].datetime + timedelta(hours=1),
            rate=args.fee_bps_per_side / 10_000.0,
            slippage=0.0,
            size=1.0,
            pricetick=0.01,
            capital=args.capital,
        )
        from NeutralMaCross import NeutralMaCross  # type: ignore[import-not-found]

        engine.output = lambda *_a, **_k: None
        engine.add_strategy(NeutralMaCross, {})
        engine.load_data()
        engine.run_backtesting()
        engine.calculate_result()
        stats = engine.calculate_statistics(output=False)
        trades = [
            {
                "trade_id": trade.tradeid,
                "order_id": trade.orderid,
                "symbol": trade.symbol,
                "exchange": trade.exchange.value,
                "direction": trade.direction.value,
                "offset": trade.offset.value,
                "price": float(trade.price),
                "volume": float(trade.volume),
                "datetime": trade.datetime.replace(tzinfo=UTC).isoformat(),
                "datetime_ms": int(trade.datetime.replace(tzinfo=UTC).timestamp() * 1000),
            }
            for trade in engine.trades.values()
        ]
        probe = getattr(engine.strategy, "ema_probe", [])
        probe_reading = {
            "bars_probed": len(probe),
            "max_abs_diff_fast": max(
                (abs(p["declared_fast"] - p["window_fast"]) for p in probe), default=None
            ),
            "max_abs_diff_slow": max(
                (abs(p["declared_slow"] - p["window_slow"]) for p in probe), default=None
            ),
            "reading": (
                "declared = SMA-seeded recursive EMA over the series; window = the "
                "same call over a sliding 26-bar window, re-seeded every bar. The gap "
                "is the indicator difference the convenience call would have made"
            ),
        }
        report["symbols"][key] = {
            "outcome": "EXECUTED",
            "bars": len(series),
            "trades": trades,
            "ema_indicator_probe": probe_reading,
            "statistics": {
                k: (float(v) if isinstance(v, (int, float)) else v)
                for k, v in (stats or {}).items()
            },
            "engine_daily_result_count": len(engine.daily_results),
        }

    Path(args.out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    for key, block in report["symbols"].items():
        probe = block.get("ema_indicator_probe") or {}
        print(
            f"[vnpy] {key}: {block.get('outcome')} trades="
            f"{len(block.get('trades') or [])} "
            f"pnl={block.get('statistics', {}).get('total_net_pnl')} "
            f"ema_window_gap_fast={probe.get('max_abs_diff_fast')} "
            f"ema_window_gap_slow={probe.get('max_abs_diff_slow')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
