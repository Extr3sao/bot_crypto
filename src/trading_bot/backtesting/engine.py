"""Backtest engine (TSK-104 F1 + F2).

Replay loop determinista sobre ``OHLCVSourceProtocol`` que itera velas
en orden cronologico y simula fills para una ``StrategyProtocol``,
produciendo un ``BacktestResult``.

Principios per ``docs/backtesting-methodology.md``:

1. **Determinismo**: mismo input -> misma output. Sin ``random``,
   sin set iteration, sin ``datetime.now()``. El engine NO
   genera timestamps por su cuenta; usa los del candle.
2. **Comisiones y slippage**:
   - F1: flat-pct (engine acepta ``float`` y lo envuelve en
     ``FlatPctCommission`` / ``FlatBpsSlippage``).
   - F2: pluggable via ``CommissionModel`` / ``SlippageModel``
     protocols. El engine acepta explicitamente un modelo o un float
     (backward-compat: float se auto-wrappea).
3. **Walk-forward**: NO esta en F1/F2 (deferred to F3 per ADR-0007).
4. **Métricas**:
   - F1: 4 baseline (total_trades, win_rate, profit_factor, final_equity).
   - F2: + 7 advanced (max_drawdown, cagr, calmar_ratio, sharpe_ratio,
     sortino_ratio, avg_trade_pnl, expectancy). Ver ``types.Metrics``.

Limitaciones documentadas para handoff a F2/F3:

- Fills inmediatos al close del candle (no realistic next-bar fill).
- Sin partial fills (qty exacto o rechazo).
- Sin multiple-position (una posicion abierta a la vez).
- Sin position sizing inteligente (qty viene de la estrategia).
- Sin soporte para ``Order.type == "limit"`` (F2 lo anadira).
- Slippage siempre round-trip-neutral (F2 mantiene la misma propiedad;
  side-asymmetric models vendran en F3+).
"""

from __future__ import annotations

import copy
import datetime
import math
import statistics
from collections.abc import Callable
from typing import cast, overload

from .commissions import CommissionModel, FlatPctCommission
from .slippage import FlatBpsSlippage, SlippageModel
from .types import (
    OHLCV,
    BacktestContext,
    BacktestResult,
    EquityPoint,
    Fill,
    Metrics,
    OHLCVSourceProtocol,
    Order,
    StrategyProtocol,
    Trade,
)

# Periods-per-year para annualizacion de Sharpe/Sortino. Pineado a
# los timeframes soportados por el engine. Si el timeframe no esta en
# el mapa, se usa 365 (daily) como default conservador.
_PERIODS_PER_YEAR: dict[str, int] = {
    "1m": 525_600,  # 365 * 24 * 60
    "5m": 105_120,
    "15m": 35_040,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
    "1w": 52,
}


def _periods_per_year(timeframe: str) -> int:
    """Mapea timeframe string a periods-per-year para annualizacion."""
    return _PERIODS_PER_YEAR.get(timeframe, 365)


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
    - ``commission`` y ``slippage_bps`` aceptan ``float`` (backward
      compat con F1) o un ``CommissionModel`` / ``SlippageModel``
      explicito. Si se pasa float, se envuelve en
      ``FlatPctCommission(rate=...)`` / ``FlatBpsSlippage(bps=...)``.
    """

    def __init__(
        self,
        source: OHLCVSourceProtocol,
        strategy: StrategyProtocol,
        commission: float | CommissionModel = 0.001,
        slippage_bps: float | SlippageModel = 5.0,
        initial_capital: float = 10_000.0,
        strategy_factory: Callable[[], StrategyProtocol] | None = None,
    ) -> None:
        if initial_capital <= 0.0:
            raise ValueError(f"initial_capital must be > 0, got {initial_capital}")
        self.source = source
        self.strategy = strategy
        self.strategy_factory = strategy_factory
        # Backward compat: float -> FlatPctCommission; explicit model -> as-is.
        self.commission_model: CommissionModel = (
            commission
            if isinstance(commission, CommissionModel)
            else FlatPctCommission(rate=commission)
        )
        # Backward compat: float -> FlatBpsSlippage; explicit model -> as-is.
        self.slippage_model: SlippageModel = (
            slippage_bps
            if isinstance(slippage_bps, SlippageModel)
            else FlatBpsSlippage(bps=slippage_bps)
        )
        self.initial_capital = initial_capital

    @overload
    def run(
        self,
        symbol: str,
        start: datetime.datetime,
        end: datetime.datetime,
        timeframe: str = "1m",
    ) -> BacktestResult:
        ...

    @overload
    def run(
        self,
        symbol: list[str],
        start: datetime.datetime,
        end: datetime.datetime,
        timeframe: str = "1m",
    ) -> list[BacktestResult]:
        ...

    def run(
        self,
        symbol: str | list[str],
        start: datetime.datetime,
        end: datetime.datetime,
        timeframe: str = "1m",
    ) -> BacktestResult | list[BacktestResult]:
        """Ejecuta el backtest y retorna un ``BacktestResult``.

        ``start`` y ``end`` son ``datetime`` (se convierten a epoch ms
        para el source). El engine NO genera timestamps; el de la
        vela es la unica fuente de tiempo.

        F3a extension:
        - ``symbol`` puede ser ``str`` (backward compat) o ``Sequence[str]``.
        - En modo multi-symbol, cada symbol se ejecuta con una estrategia
          aislada para evitar state leakage entre runs.
        """
        if isinstance(symbol, str):
            return self._run_single(symbol, start, end, timeframe, self.strategy)

        results: list[BacktestResult] = []
        for one_symbol in symbol:
            strategy = self._make_strategy_instance()
            results.append(self._run_single(one_symbol, start, end, timeframe, strategy))
        return results

    def _run_single(
        self,
        symbol: str,
        start: datetime.datetime,
        end: datetime.datetime,
        timeframe: str,
        strategy: StrategyProtocol,
    ) -> BacktestResult:
        """Internal single-symbol execution path."""
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
            order = strategy.on_candle(ctx, candle)

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

        metrics = self._compute_metrics(trades, equity, equity_curve, start, end, timeframe)
        return BacktestResult(
            strategy_name=strategy.name,
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

    def _make_strategy_instance(self) -> StrategyProtocol:
        """Create a fresh strategy instance for multi-symbol runs.

        Preference order:
        1. explicit ``strategy_factory`` from the caller
        2. ``deepcopy(self.strategy)`` for deterministic state isolation
        """
        if self.strategy_factory is not None:
            return self.strategy_factory()
        try:
            cloned = copy.deepcopy(self.strategy)
        except Exception as exc:  # pragma: no cover - defensive branch
            raise TypeError(
                "Multi-symbol backtests require a cloneable strategy or "
                "an explicit strategy_factory."
            ) from exc
        return cloned

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

        Pine contract: usa ``self.slippage_model.calculate(...)`` y
        ``self.commission_model.calculate(...)`` (F2); preserva la
        firma y el orden de desempaquetado de F1 para backward compat.
        """
        slippage = self.slippage_model.calculate(
            price=candle.close,
            qty=order.qty,
            side=order.side,
            volume=candle.volume,
        )
        fill_price = candle.close + slippage
        cost = fill_price * order.qty
        comm = self.commission_model.calculate(
            notional=cost,
            qty=order.qty,
            price=fill_price,
        )

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

        Pine contract: el buy_commission (``pending_entry_fill.commission``)
        ya se desconto en ``_execute_buy``, asi que la formula de pnl
        no lo vuelve a restar. Solo resta el sell_comm (calculado aqui).
        """
        slippage = self.slippage_model.calculate(
            price=candle.close,
            qty=order.qty,
            side=order.side,
            volume=candle.volume,
        )
        fill_price = candle.close - slippage
        revenue = fill_price * order.qty
        comm = self.commission_model.calculate(
            notional=revenue,
            qty=order.qty,
            price=fill_price,
        )

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
            # No entry to close; treat as a no-op (no shorting in F1/F2).
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
        equity_curve: list[EquityPoint],
        start: datetime.datetime,
        end: datetime.datetime,
        timeframe: str,
    ) -> Metrics:
        """Calcula el set completo de metricas (F1 + F2).

        F1 baseline (4): ``total_trades``, ``win_rate``,
        ``profit_factor``, ``final_equity``.

        F2 advanced (7): ``max_drawdown``, ``cagr``, ``calmar_ratio``,
        ``sharpe_ratio``, ``sortino_ratio``, ``avg_trade_pnl``,
        ``expectancy``.

        Units (CRITICAL for downstream consumers):
        - ``expectancy``, ``avg_trade_pnl``, ``profit_factor``, ``final_equity``:
          ABSOLUTE monetary units (quote currency, e.g. USDT).
          ``expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)``
          is the industry-standard formula (Van K. Tharp) and returns
          CUANTO dinero se gana/perdio por trade en promedio, NO un
          porcentaje. Para compararlo entre portfolios de distintos
          tamanos, dividir por ``initial_capital``.
        - ``win_rate``, ``max_drawdown``, ``cagr``, ``sharpe_ratio``,
          ``sortino_ratio``, ``calmar_ratio``: DIMENSIONLESS ratios
          (0..1 para rates/drawdown, anualizados para los demas).

        Pine contract:
        - cagr/max_drawdown/calmar_ratio se computan ANTES del
          shortcut de trades==0 porque dependen de equity_curve +
          initial_capital, no de trades.
        - Sin trades: ``win_rate=0.0``, ``profit_factor=0.0``,
          ``sharpe=0.0``, ``sortino=0.0``, ``avg_trade_pnl=0.0``,
          ``expectancy=0.0``; cagr/max_drawdown/calmar = reales.
        - Solo ganancias (no losses): ``profit_factor=float('inf')``,
          ``sortino=0.0`` (downside_std=0, denominador indefinido).
        - Solo perdidas: ``profit_factor=0.0`` (gross_profit=0).
        - ``stdev`` con ``n<2``: retorna ``0.0`` (no raise).
        - ``max_drawdown`` se toma de ``equity_curve`` (ya calculado
          en el loop) usando ``max(p.drawdown_pct)``.
        - ``CAGR`` clampea el denominador de years a ``1e-5`` para
          evitar explosiones en intraday.
        """
        # EQUITY-CURVE-BASED metrics: computed ALWAYS (do not depend on trades).
        max_drawdown = max((p.drawdown_pct for p in equity_curve), default=0.0)
        years = max((end - start).total_seconds() / 31_536_000.0, 1e-5)
        cagr = (
            (final_equity / self.initial_capital) ** (1.0 / years) - 1.0
            if self.initial_capital > 0
            else 0.0
        )
        # Calmar: calmar = CAGR / |max_drawdown|, infinito si drawdown ~ 0.
        calmar_ratio = (
            cagr / abs(max_drawdown) if max_drawdown > 1e-6 else float("inf") if cagr > 0 else 0.0
        )

        # TRADE-BASED metrics: zero trades -> shortcut to zero for these 6 keys.
        total = len(trades)
        if total == 0:
            empty: Metrics = {
                "total_trades": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "final_equity": float(final_equity),
                "max_drawdown": float(max_drawdown),
                "cagr": float(cagr),
                "calmar_ratio": float(calmar_ratio),
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "avg_trade_pnl": 0.0,
                "expectancy": 0.0,
            }
            return empty

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        win_rate = len(wins) / total
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Returns = lista de pnl_pct por trade. Para Sharpe/Sortino se
        # annualizan usando periods_per_year mapeado desde el timeframe.
        # Pine contract: si len(rets) < 2, stdev raise StatisticsError;
        # se gatea explicitamente.
        rets = [t.pnl_pct for t in trades]
        ppy = _periods_per_year(timeframe)
        sharpe_ratio = self._compute_sharpe(rets, ppy)
        sortino_ratio = self._compute_sortino(rets, ppy)

        avg_trade_pnl = sum(t.pnl for t in trades) / total
        avg_win = (gross_profit / len(wins)) if wins else 0.0
        avg_loss = (gross_loss / len(losses)) if losses else 0.0
        # Expectancy = (win_rate * avg_win) - (loss_rate * avg_loss).
        expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss)

        return cast(
            Metrics,
            {
                "total_trades": float(total),
                "win_rate": float(win_rate),
                "profit_factor": float(profit_factor),
                "final_equity": float(final_equity),
                "max_drawdown": float(max_drawdown),
                "cagr": float(cagr),
                "calmar_ratio": float(calmar_ratio),
                "sharpe_ratio": float(sharpe_ratio),
                "sortino_ratio": float(sortino_ratio),
                "avg_trade_pnl": float(avg_trade_pnl),
                "expectancy": float(expectancy),
            },
        )

    @staticmethod
    def _compute_sharpe(rets: list[float], periods_per_year: int) -> float:
        """Sharpe anualizado: ``mean(rets) / stdev(rets) * sqrt(ppy)``.

        Pine contract:
        - ``len(rets) < 2``: retorna ``0.0`` (stdev indefinido).
        - ``stdev == 0``: retorna ``0.0`` (denominador cero).
        """
        if len(rets) < 2:
            return 0.0
        mean_ret = statistics.mean(rets)
        std_ret = statistics.stdev(rets)
        if std_ret < 1e-12:
            return 0.0
        return (mean_ret / std_ret) * math.sqrt(periods_per_year)

    @staticmethod
    def _compute_sortino(rets: list[float], periods_per_year: int) -> float:
        """Sortino anualizado: ``mean(rets) / downside_stdev * sqrt(ppy)``.

        Pine contract:
        - ``len(rets) < 2``: retorna ``0.0``.
        - ``len(downside) < 2`` (pocas perdidas para calcular stdev):
          retorna ``0.0``. Esto evita el caso "perfect strategy"
          (todas ganancias) que daria ``inf``.
        - ``downside_stdev == 0``: retorna ``0.0``.
        """
        if len(rets) < 2:
            return 0.0
        mean_ret = statistics.mean(rets)
        downside = [r for r in rets if r < 0]
        if len(downside) < 2:
            return 0.0
        downside_std = statistics.stdev(downside)
        if downside_std < 1e-12:
            return 0.0
        return (mean_ret / downside_std) * math.sqrt(periods_per_year)


__all__ = ["BacktestEngine"]
