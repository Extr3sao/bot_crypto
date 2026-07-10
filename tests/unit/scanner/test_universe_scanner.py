"""Tests for TSK-103.4 F4 UniverseScanner (~20 sentinels).

Cubre los RF-1..RF-10 + CL-1..CL-7 del spec pack, los 9 sub-tickets
de 05-tasks.md, y los veredictos del thinker:

- Q1: SHADOW_LIVE -> registry 'live' (mode mapping).
- Q2: ATR bounds derived from Settings + live hardening in __init__
  (FilterBounds no extrae de registry attrs).
- Q3: try/finally en el reentrancy guard.
- Q4: filter short-circuit; orden volume -> spread -> atr.

Gotchas mitigadas verificadas:

- Gotcha #1: _CachingSource memoiza per-symbol fetches per run
  (un solo fetch_24h_volume_usdt para volume + scoring en el mismo pair).
- Gotcha #2: scan_iteration_id se bind-ea via contextvars; los logs
  lo llevan automaticamente sin pasarlo en cada llamada.

FakeMarketDataSource:

- Implementa MarketDataSourceProtocol en test (sin MagicMock per
  ADR-0011: pine contract favorece dataclasses inline).
- Cada test construye el source con respuestas configurables (vols
  por symbol, spreads por symbol, OHLCV sinteticos).
- Counter per-call que pine contract de dedup: si un mismo metodo se
  llama 2 veces para el mismo symbol (sin cache) -> assertion failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import structlog

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings
from trading_bot.market_data.types import OHLCV
from trading_bot.scanner.exceptions import ConfigurationError
from trading_bot.scanner.mode_filters import build_filter_set_per_mode
from trading_bot.scanner.registry import FilterRegistry
from trading_bot.scanner.scanner import (
    LIVE_MAX_ATR_PERCENT,
    LIVE_MAX_SPREAD_BPS,
    LIVE_MIN_VOLUME_USDT,
    CounterSnapshot,
    FilterBounds,
    ScoreNormalizers,
    UniverseScanner,
)

# ---------------------------------------------------------------------------
# FakeMarketDataSource (sin MagicMock per ADR-0011)
# ---------------------------------------------------------------------------


@dataclass
class FakeMarketDataSource:
    """In-test MarketDataSourceProtocol con respuestas configurables.

    Pine contract:
    - Cada call (para un symbol) se cuenta en ``call_counts``.
    - Tests usan ``assert_called_once_per_symbol`` para verificar
      dedup (gotcha #1) sin MagicMock.
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
    """Pine contract: en un run() normal, cada metodo per-symbol se llama 1 vez (gotcha #1)."""
    calls = source.call_counts.get((method, symbol), 0)
    assert calls == 1, (
        f"Esperaba 1 call a {method}({symbol!r}) per run(); got {calls}. "
        f"Fallo de caching source (gotcha #1)."
    )


# ---------------------------------------------------------------------------
# Minimal Settings builder (sin tocar disco)
# ---------------------------------------------------------------------------


def _build_settings(
    *,
    pairs: list[tuple[str, bool]],
    min_volume_usdt: int = 5_000_000,
    max_spread_bps: int = 30,
    min_atr_percent: float = 0.05,
    max_atr_percent: float = 8.0,
    mode: str = "paper",
    kill_switch_enabled: bool = True,
    live_trading_enabled: bool = False,
    i_understand_the_risks: bool = False,
) -> Settings:
    """Settings construido via model_construct (sin tocar disco). Bypassea
    validadores cross-field; tests son responsables de inyectar estado
    coherente."""
    # Pydantic v2 model_construct: pre-validated object construction.
    # IMPORTANTE: requiere instancias de los sub-models, no dicts.
    from trading_bot.config.exchange import (
        Exchange,
        ExchangeEndpoints,
        ExchangeRetries,
        ExchangeTimeouts,
    )
    from trading_bot.config.indicators import (
        IndicatorsConfig,
        IndicatorsGlobal,
    )
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
        TradingMode,
    )
    from trading_bot.config.strategies import (
        StrategiesConfig,
        StrategiesGlobal,
    )
    from trading_bot.config.universe import PairSpec, Universe, UniverseFilters

    pair_specs = [PairSpec.model_construct(symbol=s, enabled=en) for s, en in pairs]
    universe = Universe.model_construct(
        name="test",
        description="test",
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
        live_trading_enabled=False,  # source of truth is runtime.py
    )

    strategies_cfg = StrategiesConfig.model_construct(
        strategies={},
        global_=StrategiesGlobal.model_construct(),
    )

    indicators_cfg = IndicatorsConfig.model_construct(
        indicators={},
        global_=IndicatorsGlobal.model_construct(),
    )

    runtime = Runtime.model_construct(
        mode=TradingMode(mode),
        live_trading_enabled=live_trading_enabled,
        require_manual_confirmation_for_live=True,
        i_understand_the_risks=i_understand_the_risks,
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


# Helpers generadores de OHLCV sinteticos


def _flat_ohlcv(symbol: str, n: int, *, last_close: float) -> list[OHLCV]:
    """Genera n velas con high-low=1 (daily_range=1) y last_close configurable."""
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


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------


def test_init_minimal_args_ok() -> None:
    settings = _build_settings(pairs=[("BTC/USDT", True)])
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource()
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    assert scanner.counters.pairs_processed == 0
    assert scanner.counters.scanner_errors == 0


def test_init_raises_configuration_error_if_source_none() -> None:
    settings = _build_settings(pairs=[("BTC/USDT", True)])
    registries = build_filter_set_per_mode(settings)
    with pytest.raises(ConfigurationError, match="source"):
        UniverseScanner(
            source=None,  # type: ignore[arg-type]
            registry_per_mode=registries,
            settings=settings,
        )


def test_init_raises_configuration_error_if_registry_per_mode_empty() -> None:
    settings = _build_settings(pairs=[("BTC/USDT", True)])
    source = FakeMarketDataSource()
    with pytest.raises(ConfigurationError, match="registry_per_mode"):
        UniverseScanner(
            source=source,  # type: ignore[arg-type]
            registry_per_mode={},
            settings=settings,
        )


def test_init_raises_configuration_error_if_settings_none() -> None:
    settings = _build_settings(pairs=[("BTC/USDT", True)])
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource()
    with pytest.raises(ConfigurationError, match="settings"):
        UniverseScanner(
            source=source,  # type: ignore[arg-type]
            registry_per_mode=registries,
            settings=None,  # type: ignore[arg-type]
        )


def test_init_raises_configuration_error_if_invalid_mode_key() -> None:
    settings = _build_settings(pairs=[("BTC/USDT", True)])
    registries = build_filter_set_per_mode(settings)
    registries["bogus_mode"] = FilterRegistry()  # not in VALID_MODES
    source = FakeMarketDataSource()
    with pytest.raises(ConfigurationError, match="bogus_mode"):
        UniverseScanner(
            source=source,  # type: ignore[arg-type]
            registry_per_mode=registries,
            settings=settings,
        )


def test_init_freezes_all_registries() -> None:
    """ADR-lock: registries se freezen al init (Q3/Q4 testimony)."""
    settings = _build_settings(pairs=[("BTC/USDT", True)])
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource()
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    for mode_reg in scanner._bundles.values():  # type: ignore[attr-defined]
        reg = mode_reg.registry  # type: ignore[attr-defined]
        assert reg.is_frozen, f"Registry para mode {mode_reg.mode!r} no fue freezeado"


# ---------------------------------------------------------------------------
# run() orchestration tests (RF-1..RF-10 + CL-1..CL-7 + Q1..Q4 + gotchas)
# ---------------------------------------------------------------------------


def test_run_empty_universe_returns_empty_list() -> None:
    """CL-1: todos los pares disabled -> []."""
    settings = _build_settings(
        pairs=[("BTC/USDT", False), ("ETH/USDT", False)],
        kill_switch_enabled=False,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource()
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    snapshots = asyncio.run(scanner.run())
    assert snapshots == []


def test_run_kill_switch_aborts_and_logs_paused() -> None:
    """RF-4: kill_switch=True -> [] + log scanner.paused.kill_switch."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=True,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource()
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    with structlog.testing.capture_logs() as cap:
        import asyncio

        snapshots = asyncio.run(scanner.run())
    assert snapshots == []
    assert any(e["event"] == "scanner.paused.kill_switch" for e in cap)


def test_run_full_universe_preserves_pair_order() -> None:
    """RF-10: lista en orden de insercion (universe.pairs), no sort por rank."""
    settings = _build_settings(
        pairs=[("A/USDT", True), ("B/USDT", True), ("C/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"A/USDT": 100.0, "B/USDT": 100.0, "C/USDT": 100.0},
        spread_by_symbol={"A/USDT": 1.0, "B/USDT": 1.0, "C/USDT": 1.0},
        ohlcv_by_symbol={
            "A/USDT": _flat_ohlcv("A/USDT", 100, last_close=100.0),
            "B/USDT": _flat_ohlcv("B/USDT", 100, last_close=100.0),
            "C/USDT": _flat_ohlcv("C/USDT", 100, last_close=100.0),
        },
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    snapshots = asyncio.run(scanner.run())
    symbols = [s.symbol for s in snapshots]
    assert symbols == ["A/USDT", "B/USDT", "C/USDT"], (
        f"Orden perdido: esperaba input-order, got {symbols}"
    )


def test_filter_composition_first_failure_short_circuits() -> None:
    """Q4: volume fail corto-circuita el resto (atr NO se calcula)."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=10_000_000,  # BTC/USDT volume=100 no lo pasa
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 100.0},  # far below threshold
        spread_by_symbol={"BTC/USDT": 0.0},
        ohlcv_by_symbol={
            "BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0),
        },
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    snapshots = asyncio.run(scanner.run())
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap.active is False
    assert snap.rejection_reason is not None
    assert "volume" in snap.rejection_reason
    # ATR NO debe haberse fetcheado (short-circuit).
    assert ("fetch_recent", "BTC/USDT") not in source.call_counts, (
        "ATR fetch_recent fue llamado a pesar de volume fail (Q4 violation)"
    )


def test_transient_error_increments_scanner_errors() -> None:
    """RF-5: excepcion transitoria no aborta; scanner_errors+=1."""

    class FailingSource(FakeMarketDataSource):
        async def fetch_24h_volume_usdt(self, symbol: str) -> float:
            raise RuntimeError("simulated network error")

    settings = _build_settings(
        pairs=[("BTC/USDT", True), ("ETH/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )
    registries = build_filter_set_per_mode(settings)
    source = FailingSource(
        spread_by_symbol={"BTC/USDT": 1.0, "ETH/USDT": 1.0},
        ohlcv_by_symbol={
            "BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0),
            "ETH/USDT": _flat_ohlcv("ETH/USDT", 100, last_close=100.0),
        },
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    snapshots = asyncio.run(scanner.run())
    assert snapshots == []
    assert scanner.counters.scanner_errors == 2
    assert scanner.counters.pairs_active == 0


def test_structlog_emits_5_event_kinds() -> None:
    """RF-6: 5 structlog events (started, pair.processed x N, completed)."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True), ("ETH/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 100.0, "ETH/USDT": 200.0},
        spread_by_symbol={"BTC/USDT": 1.0, "ETH/USDT": 1.0},
        ohlcv_by_symbol={
            "BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0),
            "ETH/USDT": _flat_ohlcv("ETH/USDT", 100, last_close=100.0),
        },
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    with structlog.testing.capture_logs() as cap:
        asyncio.run(scanner.run())
    events = {entry["event"] for entry in cap}
    assert "scanner.iteration.started" in events
    assert "scanner.iteration.completed" in events
    assert "scanner.pair.processed" in events
    # scan_iteration_id was bound (gotcha #2) — verify contextvars propagation.
    for entry in cap:
        assert "scan_iteration_id" in entry, (
            f"Log {entry['event']!r} no lleva scan_iteration_id (gotcha #2 violation)"
        )


def test_mode_paper_passes_normal_volume() -> None:
    """RF-7 (paper): volume=10M USDT pasa filter (threshold=5M default)."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        mode="paper",
        kill_switch_enabled=False,
        min_volume_usdt=5_000_000,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 10_000_000.0},
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    snapshots = asyncio.run(scanner.run())
    assert snapshots[0].active is True
    assert snapshots[0].rejection_reason is None


def test_mode_live_endures_volume_to_10M() -> None:
    """RF-7 (live): volume=7M USDT -> INACTIVE con motivo '..._live_min_10M'."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        mode="live",
        kill_switch_enabled=False,
        live_trading_enabled=False,  # evitamos que runtime._check_live_gates se queje
        i_understand_the_risks=False,
        min_volume_usdt=5_000_000,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 7_000_000.0},  # << LIVE_MIN_VOLUME_USDT (10M)
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    snapshots = asyncio.run(scanner.run())
    assert snapshots[0].active is False
    assert snapshots[0].rejection_reason == "volume_below_threshold_for_live_min_10M"


def test_mode_shadow_live_maps_to_live_thresholds() -> None:
    """Q1: SHADOW_LIVE -> registry 'live' (mismo endurecimiento)."""
    settings_shadow = _build_settings(
        pairs=[("BTC/USDT", True)],
        mode="shadow_live",
        kill_switch_enabled=False,
        min_volume_usdt=5_000_000,
    )
    settings_live = _build_settings(
        pairs=[("BTC/USDT", True)],
        mode="live",
        kill_switch_enabled=False,
        min_volume_usdt=5_000_000,
    )
    src_kwargs = dict(
        volume_by_symbol={"BTC/USDT": 7_000_000.0},
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    import asyncio

    snap_shadow = asyncio.run(
        UniverseScanner(
            source=FakeMarketDataSource(**src_kwargs),  # type: ignore[arg-type]
            registry_per_mode=build_filter_set_per_mode(settings_shadow),
            settings=settings_shadow,
        ).run()
    )
    snap_live = asyncio.run(
        UniverseScanner(
            source=FakeMarketDataSource(**src_kwargs),  # type: ignore[arg-type]
            registry_per_mode=build_filter_set_per_mode(settings_live),
            settings=settings_live,
        ).run()
    )
    assert snap_shadow[0].rejection_reason == snap_live[0].rejection_reason
    assert snap_shadow[0].rejection_reason == "volume_below_threshold_for_live_min_10M"


def test_counters_reset_each_run() -> None:
    """Counters NO se acumulan entre runs (idempotencia per-iteration)."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 100.0},
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    asyncio.run(scanner.run())
    first_count = scanner.counters.pairs_active
    asyncio.run(scanner.run())
    second_count = scanner.counters.pairs_active
    assert first_count == second_count, (
        f"Counters se acumularon entre runs: 1st={first_count}, 2nd={second_count}"
    )


def test_run_is_not_reentrant() -> None:
    """Q3: ``run()`` rechaza invocations concurrentes con ``RuntimeError``."""
    import asyncio

    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )
    registries = build_filter_set_per_mode(settings)

    # Source slow para que la primera run() siga viva cuando la 2da intenta.
    class SlowSource(FakeMarketDataSource):
        async def fetch_24h_volume_usdt(self, symbol: str) -> float:
            await asyncio.sleep(0.05)
            return 100.0

    source = SlowSource(
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )

    async def _two_runs() -> None:
        await asyncio.gather(scanner.run(), scanner.run())

    with pytest.raises(RuntimeError, match="reentrante"):
        asyncio.run(_two_runs())
    # Y el flag se limpio tras el error (try/finally verification).
    assert scanner._running is False  # type: ignore[attr-defined]


def test_active_snapshot_has_all_10_fields() -> None:
    """RF-2: snapshot tiene los 10 campos pineados por spec section 2."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 100.0},
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    snapshots = asyncio.run(scanner.run())
    snap = snapshots[0]
    assert hasattr(snap, "symbol")
    assert hasattr(snap, "last_price")
    assert hasattr(snap, "volume_24h_usdt")
    assert hasattr(snap, "spread_bps")
    assert hasattr(snap, "atr_pct")
    assert hasattr(snap, "volatility_pct")
    assert hasattr(snap, "active")
    assert hasattr(snap, "rejection_reason")
    assert hasattr(snap, "timestamp")
    assert hasattr(snap, "rank_score")


def test_inactive_snapshot_has_zero_score() -> None:
    """RF-3 + CL-2: inactive snapshot -> rank_score=0.0 (regression guard)."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=10_000_000,  # volume=100 fails
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 100.0},
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    snapshots = asyncio.run(scanner.run())
    snap = snapshots[0]
    assert snap.active is False
    assert snap.rejection_reason is not None
    assert snap.rank_score == 0.0


def test_caching_source_avoids_double_fetch() -> None:
    """Gotcha #1: una sola llamada per symbol per fetch_* per run()."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 100.0},
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    asyncio.run(scanner.run())
    # Cada metodo per-symbol debe haberse llamado exactamente 1 vez.
    assert_called_once_per_symbol(source, "fetch_24h_volume_usdt", "BTC/USDT")
    assert_called_once_per_symbol(source, "fetch_spread_bps", "BTC/USDT")
    assert_called_once_per_symbol(source, "fetch_recent", "BTC/USDT")


def test_filter_bounds_live_hardening() -> None:
    """Q2 verdict: FilterBounds.from_settings aplica endurecimiento live localmente."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        mode="live",
        min_volume_usdt=5_000_000,
        max_spread_bps=30,
        max_atr_percent=8.0,
    )
    paper_bounds = FilterBounds.from_settings(settings, "paper")
    live_bounds = FilterBounds.from_settings(settings, "live")
    # Paper: volume = 5M, no live_min_usdt, spread = 30, ATR max = 8.
    assert paper_bounds.min_24h_volume_usdt == 5_000_000
    assert paper_bounds.live_min_24h_volume_usdt is None
    assert paper_bounds.max_spread_bps == 30
    assert paper_bounds.max_atr_percent == 8.0
    # Live: endurece spread & ATR; live_min = LIVE_MIN_VOLUME_USDT (10M).
    assert live_bounds.min_24h_volume_usdt == 5_000_000  # min_usdt del YAML (paper default)
    assert live_bounds.live_min_24h_volume_usdt == LIVE_MIN_VOLUME_USDT
    assert live_bounds.max_spread_bps == LIVE_MAX_SPREAD_BPS  # 20 << 30
    assert live_bounds.max_atr_percent == LIVE_MAX_ATR_PERCENT  # 5 << 8


def test_filter_bounds_hardening_defensive_when_yaml_is_more_permissive() -> None:
    """Si YAML pone live_permisivo (e.g. spread=100) y spec dice 20, gana el spec."""
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        mode="live",
        min_volume_usdt=5_000_000,
        max_spread_bps=100,  # MUY permisivo en YAML
        max_atr_percent=20.0,  # Mismo
    )
    live_bounds = FilterBounds.from_settings(settings, "live")
    assert live_bounds.max_spread_bps == LIVE_MAX_SPREAD_BPS  # 20, no 100
    assert live_bounds.max_atr_percent == LIVE_MAX_ATR_PERCENT  # 5, no 20


def test_pairs_processed_counts_per_pair_not_per_filter() -> None:
    """Regression guard (P0 #1 del reviewer round-1).

    Pine contract (spec section 10): ``pairs_processed`` cuenta pares,
    NO filter calls. Con 1 par que pasa 3 filtros, debe ser 1, NO 3.
    Si este test falla es probable que el fix per-pair se haya
    revertido y el counter se incremente dentro del for-loop de
    ``_process_pair``.
    """
    # Q9 (cheap fix per reviewer round-5): forzar 'all filters pass'
    # via min_atr_percent=0.0, max_atr_percent=10.0 para independizar
    # el test del R5-LATENT unit ambiguity (_compute_atr_pct formula).
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
        min_atr_percent=0.0,
        max_atr_percent=10.0,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 1_000_000.0},
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    # Q12 (cheap fix per reviewer round-5): wrap en capture_logs para
    # verificar que ``scanner.pair.processed`` se emite con
    # ``scan_iteration_id`` (gotcha #2 lock).
    import asyncio

    with structlog.testing.capture_logs() as cap:
        asyncio.run(scanner.run())
    # 1 par procesado, 3 filtros corrido. Counter debe ser 1, NO 3.
    assert scanner.counters.pairs_processed == 1, (
        f"pairs_processed Pinea spec section 10 (count of pairs); "
        f"got {scanner.counters.pairs_processed}. Probable inflation "
        "por increment dentro del for-loop de _process_pair."
    )
    # Q5 (cheap add per reviewer round-5): prueba que exactamente un
    # filter-evaluation cycle (active XOR inactive) recorrio.
    assert (scanner.counters.pairs_active + scanner.counters.pairs_inactive) == 1, (
        f"Esperaba exactamente 1 filter-evaluation cycle (active+inactive); "
        f"got active={scanner.counters.pairs_active}, "
        f"inactive={scanner.counters.pairs_inactive}"
    )
    # Q12: pair.processed se emite con scan_iteration_id (gotcha #2).
    pair_events = [e for e in cap if e["event"] == "scanner.pair.processed"]
    assert len(pair_events) == 1, (
        f"Esperaba 1 'scanner.pair.processed' event; got {len(pair_events)}"
    )
    assert "scan_iteration_id" in pair_events[0], (
        f"scanner.pair.processed debe llevar scan_iteration_id (gotcha #2); got {pair_events[0]}"
    )


def test_scanner_mode_str_raises_configuration_error_for_unknown_mode() -> None:
    """Regression guard (P2 #5 del reviewer round-2): map miss -> error explicito.

    Monkeypatch ``_SCANNER_MODE_MAP`` para simular un ``TradingMode``
    nuevo sin actualizar el mapping. El scanner debe levantar
    ``ConfigurationError`` con mention a ``tasks/decisions.md``,
    NO un ``KeyError`` opaco.
    """
    import trading_bot.scanner.scanner as scanner_mod

    # Force el caso: shim del map que solo conoce 2 modos en lugar de 5.
    sentinel_map = {
        TradingMode.RESEARCH: "research",
        TradingMode.PAPER: "paper",
    }
    original_map = scanner_mod._SCANNER_MODE_MAP
    scanner_mod._SCANNER_MODE_MAP = sentinel_map  # type: ignore[assignment]
    try:
        settings = _build_settings(
            pairs=[("BTC/USDT", True)],
            mode="live",  # NO esta en sentinel_map
            kill_switch_enabled=False,
        )
        registries = build_filter_set_per_mode(settings)
        source = FakeMarketDataSource()
        scanner = UniverseScanner(
            source=source,  # type: ignore[arg-type]
            registry_per_mode=registries,
            settings=settings,
        )
        import asyncio

        with pytest.raises(ConfigurationError, match=r"tasks/decisions.md"):
            asyncio.run(scanner.run())
    finally:
        scanner_mod._SCANNER_MODE_MAP = original_map  # type: ignore[assignment]


def test_iteration_completed_emitted_on_kill_switch() -> None:
    """MEDIO fix del reviewer (handoff round): kill_switch path SI emite
    ``scanner.iteration.completed`` con ``early_exit='kill_switch'``.

    Pine contract (spec section 10): la iteracion SIEMPRE cierra con
    ``scanner.iteration.completed`` levando ``duration_ms`` y los 4
    contadores, incluso si la iteracion termino anticipadamente por
    kill_switch / empty_universe / all_failed.

    Antes del fix MEDIO: kill_switch branch retornaba ``[]`` sin emitir
    ``scanner.iteration.completed``, dejando dashboards sin telemetria
    de cierre.
    """
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=True,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource()
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    with structlog.testing.capture_logs() as cap:
        snapshots = asyncio.run(scanner.run())
    assert snapshots == []
    completed_events = [e for e in cap if e["event"] == "scanner.iteration.completed"]
    assert len(completed_events) == 1, (
        f"Kill_switch path DEBE emitir scanner.iteration.completed (MEDIO fix); "
        f"got {len(completed_events)} events"
    )
    evt = completed_events[0]
    assert evt.get("early_exit") == "kill_switch", (
        f"early_exit tag debe ser 'kill_switch'; got {evt.get('early_exit')!r}"
    )
    # Y los 4 counters + duration_ms pineados por spec section 10 + Q6 del
    # round-9 fix asegura que `all_failed` se emite SIEMPRE (None en este branch).
    for key in (
        "duration_ms",
        "pairs_processed",
        "pairs_active",
        "pairs_inactive",
        "scanner_errors",
        "all_failed",
    ):
        assert key in evt, f"iteration.completed debe llevar {key!r} (spec §10)"
    assert evt.get("all_failed") is None, (
        f"all_failed es irrelevante en kill_switch path; got {evt.get('all_failed')!r}"
    )
    # Y el path-specific event continua emitiendo (paused aired before completed).
    assert any(e["event"] == "scanner.paused.kill_switch" for e in cap)


def test_iteration_completed_emitted_on_empty_universe() -> None:
    """MEDIO fix: empty universe path SI emite
    ``scanner.iteration.completed`` con ``early_exit='empty_universe'``.

    Verifica que el path empty universe (todos los pares disabled) cae
    al mismo single-emission point con tag correspondiente.
    """
    settings = _build_settings(
        pairs=[("BTC/USDT", False), ("ETH/USDT", False)],
        kill_switch_enabled=False,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource()
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    with structlog.testing.capture_logs() as cap:
        snapshots = asyncio.run(scanner.run())
    assert snapshots == []
    completed_events = [e for e in cap if e["event"] == "scanner.iteration.completed"]
    assert len(completed_events) == 1, (
        f"Empty universe path DEBE emitir scanner.iteration.completed (MEDIO fix); "
        f"got {len(completed_events)} events"
    )
    evt = completed_events[0]
    assert evt.get("early_exit") == "empty_universe", (
        f"early_exit tag debe ser 'empty_universe'; got {evt.get('early_exit')!r}"
    )
    # Y los 4 counters + duration_ms pineados por spec section 10 + Q6 del
    # round-9 fix asegura que `all_failed` se emite SIEMPRE (None en este branch).
    for key in (
        "duration_ms",
        "pairs_processed",
        "pairs_active",
        "pairs_inactive",
        "scanner_errors",
        "all_failed",
    ):
        assert key in evt, f"iteration.completed debe llevar {key!r} (spec §10)"
    assert evt.get("all_failed") is None, (
        f"all_failed es irrelevante en empty_universe path; got {evt.get('all_failed')!r}"
    )
    # Y el path-specific event continua emitiendo.
    assert any(e["event"] == "scanner.universe.empty" for e in cap)


def test_counters_property_returns_frozen_snapshot() -> None:
    """BAJO fix del reviewer (handoff round): ``scanner.counters`` retorna
    ``CounterSnapshot`` frozen dataclass.

    Caller puede leer atributos (``scanner.counters.pairs_active``)
    pero NO puede mutarlos: ``scanner.counters.pairs_active = 999``
    raises ``dataclasses.FrozenInstanceError``. Esto bloquea el escape
    de adulterar instrumentacion en runtime.
    """
    import dataclasses

    settings = _build_settings(pairs=[("BTC/USDT", True)])
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource()
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )

    snap = scanner.counters
    assert isinstance(snap, CounterSnapshot), (
        f"counters property debe retornar CounterSnapshot; got {type(snap).__name__}"
    )
    # Reads funcionan (4 attrs).
    assert snap.pairs_processed == 0
    assert snap.pairs_active == 0
    assert snap.pairs_inactive == 0
    assert snap.scanner_errors == 0
    # Mutation raises FrozenInstanceError (BAJO fix verification).
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.pairs_active = 999  # type: ignore[misc]


def test_iteration_completed_emits_all_failed_false_on_healthy_path() -> None:
    """Q6 fix del reviewer round-9: `all_failed` se emite SIEMPRE post-fix.

    Verifica el field-emission contract del round-9 review:
    - Healthy completion (1+ snapshot activo) -> `all_failed=False`.
    - El field debe estar presente en el log_kwargs (no ausente).
    - ``early_exit=None`` en healthy (Truth-table row 1).
    """
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
        min_atr_percent=0.0,
        max_atr_percent=10.0,
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 1_000_000.0},
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    with structlog.testing.capture_logs() as cap:
        asyncio.run(scanner.run())
    completed = [e for e in cap if e["event"] == "scanner.iteration.completed"]
    assert len(completed) == 1
    assert "all_failed" in completed[0], (
        f"all_failed debe estar SIEMPRE presente post-Q6 round-9 fix; "
        f"keys={list(completed[0].keys())}"
    )
    assert completed[0].get("all_failed") is False, (
        f"healthy completion debe emitir all_failed=False; got {completed[0].get('all_failed')!r}"
    )
    # Y early_exit=None en healthy (Truth-table row 1).
    assert completed[0].get("early_exit") is None, (
        f"healthy must emite early_exit=None; got {completed[0].get('early_exit')!r}"
    )


def test_iteration_completed_emits_all_failed_true_on_cl3_path() -> None:
    """Q1 + Q6 fix del reviewer round-9: CL-3 path emite `all_failed=True`.

    Cubre filter failures + transient errors: ambos paths caen en
    `not snapshots and scanner_errors > 0`. ``all_failed=True`` NO
    distingue entre failures + transient errors per Q1 word-ing fix.
    """

    class FailingSource(FakeMarketDataSource):
        async def fetch_24h_volume_usdt(self, symbol: str) -> float:
            raise RuntimeError("simulated transient error")

    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=1_000,
    )
    registries = build_filter_set_per_mode(settings)
    source = FailingSource(
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    with structlog.testing.capture_logs() as cap:
        snapshots = asyncio.run(scanner.run())
    assert snapshots == []
    assert scanner.counters.scanner_errors == 1
    completed = [e for e in cap if e["event"] == "scanner.iteration.completed"]
    assert len(completed) == 1
    assert completed[0].get("all_failed") is True, (
        f"CL-3 path (transient errors block all snapshots) -> all_failed=True; "
        f"got {completed[0].get('all_failed')!r}"
    )
    assert completed[0].get("early_exit") is None, (
        f"CL-3 is NOT an early exit; got {completed[0].get('early_exit')!r}"
    )


def test_iteration_completed_emits_all_failed_true_on_filter_reject_only_path() -> None:
    """Round-10 fix: filter-reject-only path tambien emite ``all_failed=True``.

    Sin transient errors (``scanner_errors=0``) pero con TODOS los pares
    filter-rejected (``pairs_inactive=N``, ``pairs_active=0``), el field
    ``all_failed`` debe ser ``True`` per CL-3 truth-table row 2.

    Pine contract (round-10 tightening): el discriminador exclusivo para
    ``all_failed=True`` es ``pairs_active == 0``, NO
    ``not snapshots and scanner_errors > 0``. Antes del tightening, un
    universo donde todos los pares son filter-rejected se reportaba como
    `all_failed=False` (porque ``snapshots`` no era vacio, aunque todos
    eran inactivos). El round-10 fix corrige eso.
    """
    settings = _build_settings(
        pairs=[("BTC/USDT", True)],
        kill_switch_enabled=False,
        min_volume_usdt=10_000_000,  # VolumeFilter rechaza BTC/USDT con volume=0
    )
    registries = build_filter_set_per_mode(settings)
    source = FakeMarketDataSource(
        volume_by_symbol={"BTC/USDT": 0.0},  # far below 10M threshold
        spread_by_symbol={"BTC/USDT": 1.0},
        ohlcv_by_symbol={"BTC/USDT": _flat_ohlcv("BTC/USDT", 100, last_close=100.0)},
    )
    scanner = UniverseScanner(
        source=source,  # type: ignore[arg-type]
        registry_per_mode=registries,
        settings=settings,
    )
    import asyncio

    with structlog.testing.capture_logs() as cap:
        snapshots = asyncio.run(scanner.run())
    # El outer loop appendea el inactive snapshot al list:
    # `snapshots` tiene 1 entrada (active=False).
    assert len(snapshots) == 1
    assert snapshots[0].active is False
    # Counters: solo se proceso 1 par (filter fail antes de scoring).
    assert scanner.counters.pairs_processed == 1
    assert scanner.counters.pairs_active == 0  # clave: pairs_active==0 es el discriminador
    assert scanner.counters.pairs_inactive == 1
    assert scanner.counters.scanner_errors == 0  # no transient errors happened
    completed = [e for e in cap if e["event"] == "scanner.iteration.completed"]
    assert len(completed) == 1
    assert completed[0].get("all_failed") is True, (
        f"Pure filter-reject path debe emitir all_failed=True per round-10 "
        f"semantic tightening (pairs_active==0); "
        f"got {completed[0].get('all_failed')!r}"
    )
    assert completed[0].get("early_exit") is None


def test_score_normalizers_for_mode_live_tighter() -> None:
    """Live usa spread_norm_max=20 (Spreaad cap Live) y volume_norm_max=200M."""
    paper = ScoreNormalizers.for_mode("paper")
    live = ScoreNormalizers.for_mode("live")
    assert paper.spread_norm_max == 30.0
    assert live.spread_norm_max == 20.0
    assert live.volume_norm_max == 200_000_000.0
