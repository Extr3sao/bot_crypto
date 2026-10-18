"""Replay connector — a recorded exchange, for offline verification only.

RFC-TAP-MARKET-005 must prove that an incremental read returns the same closed
bars as a full refetch **without** spending the network on every test run.  This
adapter serves a captured fixture with the same semantics as the real endpoint:

* ``limit`` returns the *most recent* N bars (never the oldest N);
* bars are open-time ordered and include the bar that is still forming at
  ``now_ms``;
* a bar that does not exist yet is absent, not synthesised.

It implements the read half of ``ExchangeConnector`` and refuses every write
half loudly.  It is never selected by the runtime: only the offline CLI passes
``--fixture``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from trading_bot.market_data.exchange_connector import ExchangeConnector
from trading_bot.market_data.types import OHLCV, Balance, MarketRules, OrderResult, OrderType, Side

__all__ = ["ReplayConnector", "load_fixture", "save_fixture"]


def load_fixture(path: Path | str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "series" not in payload:
        raise ValueError(f"{path}: fixture needs a 'series' object")
    return payload


def save_fixture(path: Path | str, payload: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return target


class ReplayConnector(ExchangeConnector):
    """Read-only connector over a captured fixture."""

    def __init__(
        self,
        series: dict[str, dict[str, Sequence[Sequence[float]]]],
        *,
        now_ms: Callable[[], int],
        fail_on_call: int | None = None,
        error: str = "ExchangeNotAvailable: simulated provider failure",
    ) -> None:
        self._series = series
        self._now_ms = now_ms
        self._fail_on_call = fail_on_call
        self._error = error
        self.calls: list[dict[str, Any]] = []

    # ------------------------------------------------------------------- reads
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        call_index = len(self.calls) + 1
        now = int(self._now_ms())
        rows = self._series.get(symbol, {}).get(timeframe)
        if self._fail_on_call is not None and call_index == self._fail_on_call:
            self.calls.append(
                {
                    "call": call_index,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "limit": limit,
                    "returned": 0,
                    "error": self._error,
                }
            )
            raise RuntimeError(self._error)
        if rows is None:
            self.calls.append(
                {
                    "call": call_index,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "limit": limit,
                    "returned": 0,
                    "error": "unknown_series",
                }
            )
            raise KeyError(f"no fixture series for {symbol} {timeframe}")
        visible = [row for row in rows if int(row[0]) <= now]
        selected = visible[-limit:] if limit > 0 else []
        parsed = [
            OHLCV(
                symbol=symbol,
                timestamp=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in selected
        ]
        self.calls.append(
            {
                "call": call_index,
                "symbol": symbol,
                "timeframe": timeframe,
                "limit": limit,
                "returned": len(parsed),
                "first_open_ms": int(parsed[0].timestamp) if parsed else None,
                "last_open_ms": int(parsed[-1].timestamp) if parsed else None,
                "error": None,
            }
        )
        return parsed

    def load_markets(self) -> None:
        return None

    @property
    def sandbox_enabled(self) -> bool:
        return False

    # ------------------------------------------------------- forbidden writes
    def fetch_balance(self) -> list[Balance]:
        raise NotImplementedError("ReplayConnector is read-only: no balances")

    def create_order(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        amount: float,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> OrderResult:
        raise NotImplementedError("ReplayConnector is read-only: no orders")

    def cancel_order(self, order_id: str, symbol: str) -> None:
        raise NotImplementedError("ReplayConnector is read-only: no orders")

    def fetch_24h_volume_usdt(self, symbol: str) -> float:
        raise NotImplementedError("ReplayConnector does not model tickers")

    def fetch_spread_bps(self, symbol: str) -> float:
        raise NotImplementedError("ReplayConnector does not model the book")

    def fetch_market_rules(self, symbol: str) -> MarketRules:
        raise NotImplementedError("ReplayConnector does not model market rules")
