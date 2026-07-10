"""Synthetic ``MarketDataSourceProtocol`` for demo, dry-run, and tests.

This module is the **production** home for the fake data source; the
tests under ``tests/unit/scanner/conftest.py`` and ``tests/bdd/conftest.py``
re-export the public helpers (``FakeMarketDataSource``,
``make_flat_ohlcv``, ``make_high_volatility_ohlcv``,
``build_demo_settings``, ``build_demo_fetcher``) so unit and BDD
suites keep working unchanged.

Why live in ``src/`` (not under ``tests/``):

- ``app.py`` needs the fake in ``scan --demo`` mode so the user can
  run the scanner end-to-end **without exchange credentials**. A CLI
  flag that imports from ``tests.*`` would break the cross-layer AST
  enforcement test (``tests/unit/scanner/test_cross_layer.py``) and
  also ship test code in production builds.
- Other entrypoints (Fase 1 ``--dry-run`` paper-mode startup, the
  dashboard preview in ``scripts/``) can reuse the same fake.

API:

- ``FakeMarketDataSource``: zero-magic ``MarketDataSourceProtocol`` impl
  with configurable per-symbol responses + a ``call_counts`` counter
  that lets tests pine dedup (gotcha #1 of TSK-103.4) without
  ``MagicMock`` per ADR-0011.
- ``make_flat_ohlcv``: deterministic synthetic OHLCV with
  ``high - low = 1`` (daily range of 1 unit) and configurable
  ``last_close`` — useful for "all filters pass" scenarios.
- ``make_high_volatility_ohlcv``: deterministic synthetic OHLCV that
  forces a daily range of ``daily_pct`` (e.g. 0.12 = 12%) so ATR
  out-of-range rejections can be exercised.
- ``build_demo_settings``: ``Settings`` constructed via
  ``Settings.model_construct`` (no disk, no cross-field validators)
  for the CLI ``scan --demo`` entrypoint.
- ``build_demo_fetcher``: composes a ``FakeMarketDataSource`` pre-seeded
  with 5 crypto pairs at realistic spreads/volumes so the demo
  prints a useful snapshot table on stdout.

Cross-layer contract: this module is in the ``market_data`` layer,
which the scanner consumes only via ``MarketDataSourceProtocol``
(``scanner/protocols.py``). The scanner never sees this concrete
class.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings
from trading_bot.market_data.types import OHLCV

# ===========================================================================
# 1. FakeMarketDataSource — MarketDataSourceProtocol impl
# ===========================================================================


@dataclass
class FakeMarketDataSource:
    """In-process ``MarketDataSourceProtocol`` with configurable responses.

    Pine contract:
    - Each call (for a symbol) increments ``call_counts[(method, symbol)]``.
    - ``fetch_recent(symbol, limit)`` returns the first ``limit`` rows of
      ``ohlcv_by_symbol[symbol]`` (or empty list if missing).
    - ``fetch_24h_volume_usdt(symbol)`` returns
      ``volume_by_symbol[symbol]`` (or 0.0 if missing).
    - ``fetch_spread_bps(symbol)`` returns
      ``spread_by_symbol[symbol]`` (or 0.0 if missing).

    Compatible with ``trading_bot.scanner.protocols.MarketDataSourceProtocol``
    (runtime_checkable). Use ``isinstance(x, MarketDataSourceProtocol)``
    to validate.

    Anti-pattern: do NOT extend with ``MagicMock`` patches; the
    dataclass + per-call counter is the contract that makes
    gotcha #1 dedup verifiable.
    """

    volume_by_symbol: dict[str, float] = field(default_factory=dict)
    spread_by_symbol: dict[str, float] = field(default_factory=dict)
    ohlcv_by_symbol: dict[str, list[OHLCV]] = field(default_factory=dict)
    call_counts: dict[tuple[str, str], int] = field(default_factory=dict)

    def _touch(self, method: str, symbol: str) -> None:
        key = (method, symbol)
        self.call_counts[key] = self.call_counts.get(key, 0) + 1

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        self._touch("fetch_recent", symbol)
        return list(self.ohlcv_by_symbol.get(symbol, [])[:limit])

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        self._touch("fetch_24h_volume_usdt", symbol)
        return float(self.volume_by_symbol.get(symbol, 0.0))

    async def fetch_spread_bps(self, symbol: str) -> float:
        self._touch("fetch_spread_bps", symbol)
        return float(self.spread_by_symbol.get(symbol, 0.0))


def assert_called_once_per_symbol(source: FakeMarketDataSource, method: str, symbol: str) -> None:
    """Pine contract del gotcha #1: 1 call per method per symbol per ``run()``."""
    calls = source.call_counts.get((method, symbol), 0)
    assert calls == 1, (
        f"Esperaba 1 call a {method}({symbol!r}) per run(); got {calls}. "
        f"Fallo de caching source (gotcha #1)."
    )


# ===========================================================================
# 2. Synthetic OHLCV generators
# ===========================================================================


def make_flat_ohlcv(symbol: str, n: int, *, last_close: float) -> list[OHLCV]:
    """Genera ``n`` velas con ``high - low = 1`` y ``last_close`` configurable.

    Daily range = 1 unit. Pineado por ``test_universe_scanner.py`` para
    escenarios "all filters pass" donde el ATR% debe caer dentro del
    rango (spread 1 / close 100 = 1%).
    """
    return [
        OHLCV(
            symbol=symbol,
            timestamp=1_700_000_000_000 + i * 60_000,
            open=last_close,
            high=last_close + 0.5,
            low=last_close - 0.5,
            close=last_close,
            volume=100.0,
        )
        for i in range(n)
    ]


def make_high_volatility_ohlcv(
    symbol: str, n: int, *, close: float, daily_pct: float
) -> list[OHLCV]:
    """Genera ``n`` velas con daily-range = ``daily_pct`` del close.

    Util para forzar que ``_compute_atr_pct`` retorne ~daily_pct * 100
    (R5-LATENT: el helper calcula mean(TR) sobre TODAS las velas, NO
    ATR-14 Wilder fijo; un daily-range constante de 12% produce
    atr_pct cercano a 12%).

    Si daily_pct=0.12 y max_atr_percent=8.0 -> el par sera
    rechazado con motivo ``atr_out_of_range``.
    """
    half = close * daily_pct / 2.0
    return [
        OHLCV(
            symbol=symbol,
            timestamp=1_700_000_000_000 + i * 60_000,
            open=close,
            high=close + half,
            low=close - half,
            close=close,
            volume=100.0,
        )
        for i in range(n)
    ]


# ===========================================================================
# 3. Demo settings — Settings via model_construct (no disk, no validators)
# ===========================================================================


def build_demo_settings(
    *,
    pairs: list[tuple[str, bool]] | None = None,
    min_volume_usdt: int = 5_000_000,
    max_spread_bps: int = 30,
    min_atr_percent: float = 0.05,
    max_atr_percent: float = 8.0,
    mode: str = "paper",
    kill_switch_enabled: bool = True,
) -> Settings:
    """``Settings`` para el CLI ``scan --demo``.

    Bypassea validadores cross-field via ``model_construct`` (test
    idiom; en produccion ``load_settings()`` aplicaria los
    validadores). Pine contract: el caller es responsable de inyectar
    estado coherente. Por defecto 5 pares USDT en mode=paper con
    kill_switch apagado.
    """
    if pairs is None:
        pairs = [
            ("BTC/USDT", True),
            ("ETH/USDT", True),
            ("SOL/USDT", True),
            ("AVAX/USDT", True),
            ("MATIC/USDT", True),
        ]

    # Lazy imports para evitar side-effects en collection-time.
    from trading_bot.config.exchange import (
        Exchange,
        ExchangeEndpoints,
        ExchangeRetries,
        ExchangeTimeouts,
    )
    from trading_bot.config.indicators import IndicatorsConfig, IndicatorsGlobal
    from trading_bot.config.risk import DefensiveBlocks, Risk
    from trading_bot.config.runtime import (
        FeatureFlags,
        LoggingBlock,
        Metrics,
        Paths,
        Reports,
        Runtime,
        Scheduler,
        SchedulerActiveHours,
        Storage,
    )
    from trading_bot.config.strategies import StrategiesConfig, StrategiesGlobal
    from trading_bot.config.universe import PairSpec, Universe, UniverseFilters

    pair_specs = [PairSpec.model_construct(symbol=s, enabled=en) for s, en in pairs]
    universe = Universe.model_construct(
        name="demo",
        description="demo universe for --demo CLI mode",
        base_currency="USDT",
        enabled=True,
        pairs=pair_specs,
        timeframes=["5m"],
        filters=UniverseFilters.model_construct(
            min_24h_volume_usdt=min_volume_usdt,
            max_spread_bps=max_spread_bps,
            max_atr_percent=max_atr_percent,
            min_atr_percent=min_atr_percent,
        ),
    )
    exchange = Exchange.model_construct(
        id="binance",
        sandbox=True,
        endpoints=ExchangeEndpoints.model_construct(),
        timeouts=ExchangeTimeouts.model_construct(),
        retries=ExchangeRetries.model_construct(),
    )
    risk = Risk.model_construct(
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0,
        max_weekly_loss_pct=7.0,
        max_daily_drawdown_pct=5.0,
        max_total_drawdown_pct=15.0,
        max_open_positions=5,
        max_trades_per_day=100,
        max_consecutive_losses=3,
        consecutive_loss_cooldown_minutes=60,
        max_asset_exposure_pct=20.0,
        max_total_exposure_pct=80.0,
        min_order_notional_usdt=10.0,
        max_order_notional_usdt=1000.0,
        default_stop_loss_pct=0.5,
        default_take_profit_pct=1.0,
        blocks=DefensiveBlocks.model_construct(),
        kill_switch_enabled=kill_switch_enabled,
        live_trading_enabled=False,
    )
    strategies_cfg = StrategiesConfig.model_construct(
        strategies={},
        global_=StrategiesGlobal.model_construct(
            required_progression=[
                "disabled",
                "research",
                "paper",
                "live_candidate",
                "live",
            ],
            require_min_trades_for_promotion=30,
        ),
    )
    indicators_cfg = IndicatorsConfig.model_construct(
        indicators={},
        global_=IndicatorsGlobal.model_construct(require_min_candles=100),
    )
    runtime = Runtime.model_construct(
        mode=TradingMode(mode),
        live_trading_enabled=False,
        require_manual_confirmation_for_live=True,
        i_understand_the_risks=False,
        scheduler=Scheduler.model_construct(
            timezone="UTC",
            active_hours=SchedulerActiveHours.model_construct(),
        ),
        storage=Storage.model_construct(),
        logging=LoggingBlock.model_construct(),
        reports=Reports.model_construct(),
        metrics=Metrics.model_construct(),
        paths=Paths.model_construct(),
        features=FeatureFlags.model_construct(),
    )
    return Settings.model_construct(
        universe=universe,
        exchange=exchange,
        risk=risk,
        strategies=strategies_cfg,
        indicators=indicators_cfg,
        runtime=runtime,
    )


# ===========================================================================
# 4. Pre-seeded demo fetcher for `python -m trading_bot.app scan --demo`
# ===========================================================================


def build_demo_fetcher(
    settings: Settings,
) -> FakeMarketDataSource:
    """Construye un ``FakeMarketDataSource`` pre-poblado para el CLI demo.

    Comportamiento por par (5 USDT pairs por defecto):

    - ``BTC/USDT``: volume 50M, spread 5 bps, OHLCV flat 100 velas.
      -> ACTIVE.
    - ``ETH/USDT``: volume 30M, spread 8 bps, OHLCV flat 100 velas.
      -> ACTIVE.
    - ``SOL/USDT``: volume 8M (paper pasa el threshold 5M), spread 12 bps.
      -> ACTIVE.
    - ``AVAX/USDT``: volume 1M (rechaza VolumeFilter). -> INACTIVE.
    - ``MATIC/USDT``: volume 20M, spread 50 bps (rechaza SpreadFilter).
      -> INACTIVE.

    Esto produce 3 activos + 2 inactivos en una sola iteracion,
    suficiente para demostrar el output tabular del CLI sin
    abrumar al usuario con logs.
    """
    source = FakeMarketDataSource()
    # Acepta cualquier settings (lee pares desde settings.universe.pairs).
    for pair in settings.universe.pairs:
        if not pair.enabled:
            continue
        sym = pair.symbol
        if sym == "BTC/USDT":
            source.volume_by_symbol[sym] = 50_000_000.0
            source.spread_by_symbol[sym] = 5.0
            source.ohlcv_by_symbol[sym] = make_flat_ohlcv(sym, 100, last_close=100.0)
        elif sym == "ETH/USDT":
            source.volume_by_symbol[sym] = 30_000_000.0
            source.spread_by_symbol[sym] = 8.0
            source.ohlcv_by_symbol[sym] = make_flat_ohlcv(sym, 100, last_close=100.0)
        elif sym == "SOL/USDT":
            source.volume_by_symbol[sym] = 8_000_000.0
            source.spread_by_symbol[sym] = 12.0
            source.ohlcv_by_symbol[sym] = make_flat_ohlcv(sym, 100, last_close=50.0)
        elif sym == "AVAX/USDT":
            # Volume bajo -> VolumeFilter rechaza.
            source.volume_by_symbol[sym] = 1_000_000.0
            source.spread_by_symbol[sym] = 5.0
            source.ohlcv_by_symbol[sym] = make_flat_ohlcv(sym, 100, last_close=20.0)
        elif sym == "MATIC/USDT":
            # Spread alto -> SpreadFilter rechaza.
            source.volume_by_symbol[sym] = 20_000_000.0
            source.spread_by_symbol[sym] = 50.0
            source.ohlcv_by_symbol[sym] = make_flat_ohlcv(sym, 100, last_close=1.0)
        else:
            # Default razonable: activo pero con volumen bajo para que
            # el usuario vea al menos 1 motivo de rechazo si lo activa.
            source.volume_by_symbol[sym] = 10_000_000.0
            source.spread_by_symbol[sym] = 10.0
            source.ohlcv_by_symbol[sym] = make_flat_ohlcv(sym, 100, last_close=1.0)
    return source


__all__ = [
    "FakeMarketDataSource",
    "assert_called_once_per_symbol",
    "build_demo_fetcher",
    "build_demo_settings",
    "make_flat_ohlcv",
    "make_high_volatility_ohlcv",
]
