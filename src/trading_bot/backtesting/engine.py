"""Backtest engine (TSK-104 F1).

Replay loop determinista sobre ``OHLCVSourceProtocol`` que itera velas
en orden cronologico y simula fills para una ``StrategyProtocol``,
produciendo un ``BacktestResult``.

Principios per ``docs/backtesting-methodology.md``:

1. **Determinismo**: mismo input -> misma output. Sin ``random``,
   sin set iteration, sin ``datetime.now()``. El engine NO
   genera timestamps por su cuenta; usa los del candle.
2. **Comisiones y slippage**: ambos son flat-pct en F1; F2 introducira
   modelos mas finos (volume-weighted, fixed-fee, etc.).
3. **Walk-forward**: NO esta en F1 (deferred a F3 per ADR-0007).
4. **Métricas minimas**: F1 calcula solo 4 (total_trades, win_rate,
   profit_factor, final_equity); F2 anadira Sharpe, Sortino,
   max_drawdown, etc.

Limitaciones de F1 (documentadas para handoff a F2/F3):

- Fills inmediatos al close del candle (no realistic next-bar fill).
- Sin partial fills (qty exacto o rechazo).
- Sin multiple-position (una posicion abierta a la vez).
- Sin position sizing inteligente (qty viene de la estrategia).
- Sin soporte para ``Order.type == "limit"`` (F2 lo anadira).
"""

from __future__ import annotations

import datetime

from .types import (
    OHLCV,
    BacktestContext,
    BacktestResult,
    EquityPoint,
    Fill,
    OHLCVSourceProtocol,
    Order,
    StrategyProtocol,
    Trade,
)


class BacktestEngine:
    """Replay engine determinista.

    Pine contract:
    - El constructor solo valida tipos (Pydantic-style); no abre
      conexiones ni hace I/O.
    - ``run()`` itera ``source.iter_candles`` en orden, llama
      ``strategy.on_candle(ctx, candle)`` y procesa la orden
      resultante.
    - Si la fuente levanta una excepcion, el engine la re-eleva
      (fail-fast, no traga errores).
    - Si la estrategia levanta una excepcion, el engine la re-eleva.
    """

    def __init__(
        self,
        source: OHLCVSourceProtocol,
        strategy: StrategyProtocol,
        commission: float = 0.001,  # 0.1% (Binance spot taker tipico)
        slippage_bps: float = 5.0,  # 5 bps = 0.05%
        initial_capital: float = 10_000.0,
    ) -> None:
        self.source = source
        self.strategy = strategy
        self.commission = commission
        self.slippage_bps = slippage_bps
        self.initial_capital = initial_capital

    def run(
        self,
        symbol: str,
        start: datetime.datetime,
        end: datetime.datetime,
        timeframe: str = "1m",
    ) -> BacktestResult:
        """Ejecuta el backtest y retorna un ``BacktestResult``.

        ``start`` y ``end`` son ``datetime`` (se convierten a epoch ms
        para el source). El engine NO genera timestamps; el de la
        vela es la unica fuente de tiempo.
        """
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        equity = self.initial_capital
        peak_equity = equity
        position_qty = 0.0
        position_avg_price = 0.0

        equity_curve: list[EquityPoint] = []
        trades: list[Trade] = []

        pending_entry_fill: Fill | None = None
        bars_held = 0

        for candle in self.source.iter_candles(symbol, start_ms, end_ms):
            # Update mark-to-market equity with the candle's close.
            floating_pnl = 0.0
            if position_qty > 0.0 and pending_entry_fill is not None:
                floating_pnl = (candle.close - pending_entry_fill.fill_price) * position_qty
            mtm_equity = equity + floating_pnl
            if mtm_equity > peak_equity:
                peak_equity = mtm_equity
            drawdown_pct = (peak_equity - mtm_equity) / peak_equity if peak_equity > 0 else 0.0
            equity_curve.append(
                EquityPoint(
                    timestamp=candle.timestamp,
                    equity=mtm_equity,
                    drawdown_pct=drawdown_pct,
                )
            )

            # Build context and ask strategy for an order.
            ctx = BacktestContext(
                symbol=symbol,
                current_time=candle.timestamp,
                current_price=candle.close,
                equity=equity,
                position_qty=position_qty,
                position_avg_price=position_avg_price,
            )
            order = self.strategy.on_candle(ctx, candle)

            if position_qty > 0.0:
                bars_held += 1

            if order is not None:
                if order.side == "buy" and position_qty == 0.0:
                    pending_entry_fill, equity, position_qty, position_avg_price = (
                        self._execute_buy(order, candle, equity)
                    )
                    bars_held = 0
                elif order.side == "sell" and position_qty > 0.0:
                    trade, equity, position_qty, position_avg_price, pending_entry_fill = (
                        self._execute_sell(
                            order,
                            candle,
                            equity,
                            position_qty,
                            position_avg_price,
                            pending_entry_fill,
                            bars_held,
                        )
                    )
                    if trade is not None:
                        trades.append(trade)
                    bars_held = 0

        metrics = self._compute_metrics(trades, equity)
        return BacktestResult(
            strategy_name=self.strategy.name,
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            initial_capital=self.initial_capital,
            final_equity=equity,
            trades=trades,
            equity_curve=equity_curve,
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    # Internal helpers (deterministic, no side-effects)
    # ------------------------------------------------------------------

    def _execute_buy(
        self,
        order: Order,
        candle: OHLCV,
        equity: float,
    ) -> tuple[Fill, float, float, float]:
        """Simula un buy fill al close + slippage + commission.

        F1: slippage es siempre a favor del market (precio sube en
        buy, baja en sell). F2 introducira modelos mas realistas
        (volume-weighted, random walk, etc.).
        """
        slippage = candle.close * (self.slippage_bps / 10_000.0)
        fill_price = candle.close + slippage
        cost = fill_price * order.qty
        comm = cost * self.commission

        fill = Fill(
            order_id=order.id,
            symbol=order.symbol,
            side="buy",
            qty_filled=order.qty,
            fill_price=fill_price,
            commission=comm,
            slippage=slippage,
            timestamp=candle.timestamp,
        )
        new_equity = equity - comm
        new_position_qty = order.qty
        new_avg_price = fill_price
        return fill, new_equity, new_position_qty, new_avg_price

    def _execute_sell(
        self,
        order: Order,
        candle: OHLCV,
        equity: float,
        position_qty: float,
        position_avg_price: float,
        pending_entry_fill: Fill | None,
        bars_held: int,
    ) -> tuple[Trade | None, float, float, float, Fill | None]:
        """Simula un sell fill al close + slippage + commission.

        Construye un ``Trade`` si hay un ``pending_entry_fill``; sin
        entrada previa, el sell se ignora (no se trata de un short).
        """
        slippage = candle.close * (self.slippage_bps / 10_000.0)
        fill_price = candle.close - slippage
        revenue = fill_price * order.qty
        comm = revenue * self.commission

        fill = Fill(
            order_id=order.id,
            symbol=order.symbol,
            side="sell",
            qty_filled=order.qty,
            fill_price=fill_price,
            commission=comm,
            slippage=slippage,
            timestamp=candle.timestamp,
        )

        if pending_entry_fill is None:
            # No entry to close; treat as a no-op (no shorting in F1).
            return None, equity, position_qty, position_avg_price, pending_entry_fill

        entry_cost = pending_entry_fill.fill_price * pending_entry_fill.qty_filled
        exit_revenue = fill_price * order.qty
        # Pine contract: buy_comm ya se desconto en _execute_buy.
        pnl = exit_revenue - entry_cost - comm
        # pnl_pct se calcula contra el costo total (entry + commission).
        invested = entry_cost + pending_entry_fill.commission
        pnl_pct = pnl / invested if invested > 0 else 0.0

        trade = Trade(
            entry_fill=pending_entry_fill,
            exit_fill=fill,
            pnl=pnl,
            pnl_pct=pnl_pct,
            bars_held=bars_held,
        )
        new_equity = equity + pnl
        return trade, new_equity, 0.0, 0.0, None

    def _compute_metrics(
        self,
        trades: list[Trade],
        final_equity: float,
    ) -> dict[str, float]:
        """Calcula metricas baseline (F1 = 4; F2 anadira mas)."""
        total = len(trades)
        if total == 0:
            return {
                "total_trades": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "final_equity": final_equity,
            }

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        win_rate = len(wins) / total
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return {
            "total_trades": float(total),
            "win_rate": float(win_rate),
            "profit_factor": float(profit_factor),
            "final_equity": float(final_equity),
        }


__all__ = ["BacktestEngine"]
