"""Universe scanner orchestrator (TSK-103.4/F4).

Pega los modulos F1 (tipos + protocolos), F2 (filtros + registry),
F3 (scoring cerrado) en un asyncio orchestrator que itera el universe
configurado, aplica filtros por par con short-circuit en el primer
fallo (TSK-103.4.4 explicito), construye ``MarketSnapshot`` y emite
los 5 structlog events de la spec section 10.

Anti-patrones (cubierto por test AST enforcement TSK-103.4.9):
- scaner.py NO importa ``execution``, ``strategies``, ``risk``,
  ``portfolio``, ``indicators``, ``paper``, ``observability``.
- Solo importa modulo internos del paquete ``trading_bot.scanner`` +
  ``trading_bot.config.*`` + ``trading_bot.market_data.types``.

Decisiones validadas por thinker (Q1..Q4):
- Q1: ``TradingMode.SHADOW_LIVE`` -> registry 'live' (semantica
  identica al live en market-data; la diferencia solo afecta
  execution, fuera del scanner).
- Q2: ATR bounds derivados de ``Settings.universe.filters`` +
  endurecimiento live aplicado en ``__init__`` (no extraer de
  registry attrs; respeta D1-A + freeze-immutability ADR-lock).
- Q3: Reentrancy guard con try/finally (limpieza garantizada en
  errores no capturados).
- Q4: Filter short-circuit en el primer fail; orden de registro
  asegura que las llamadas baratas (volume/spread) vengan ANTES de
  la costosa (ATR/fetch_recent) para maximizar el beneficio perf.

Gotchas de implementacion mitigados:
- Gotcha #1 (data duplication trap): ``_CachingSource`` memoiza
  per-symbol fetches dentro de un solo ``run()`` para evitar
  doble I/O cuando un filtro + scoring necesitan el mismo dato.
- Gotcha #2 (scan_iteration_id perdido): se pasa EXPLÍCITAMENTE como
  kwarg ``scan_iteration_id=scan_id`` en cada ``self._log.*(...)`` call.
  Esto pinea el campo en el log_dict incluso con
  ``structlog.testing.capture_logs()`` (que no captura contextvars
  sin un processor ``merge_contextvars`` adicional).

MEDIO + BAJO fixes del reviewer de handoff (septimo ciclo):
- ``_execute_iteration``: cada path (healthy / kill_switch / empty_universe)
  cae al MISMO single-emission point de ``scanner.iteration.completed``
  para cumplir spec section 10 (siempre emite ``duration_ms`` + 4
  counters, con tag ``early_exit`` para distinguir el abort reason).
- ``counters`` property: retorna fresh ``CounterSnapshot`` frozen
  dataclass en cada acceso. El caller lee atributos pero NO puede
  mutar (``scanner.counters.pairs_active = 999`` raises
  ``dataclasses.FrozenInstanceError``). Internamente sigue
  ``_CountersState`` mutable para que ``_process_pair`` haga
  ``+= 1`` sin levantar.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from uuid import uuid4

import structlog

from trading_bot.config.runtime import TradingMode
from trading_bot.config.settings import Settings
from trading_bot.config.universe import UniverseFilters
from trading_bot.market_data.types import OHLCV
from trading_bot.scanner.exceptions import ConfigurationError
from trading_bot.scanner.filters import (
    VALID_MODES,
    _compute_atr_pct,
)
from trading_bot.scanner.protocols import MarketDataSourceProtocol
from trading_bot.scanner.registry import FilterRegistry
from trading_bot.scanner.scoring import compute_rank_score
from trading_bot.scanner.types import FilterOutcome, MarketSnapshot

# ---------------------------------------------------------------------------
# Mode mapping (Q1 verdict)
# TradingMode tiene 5 valores (incluido SHADOW_LIVE); VALID_MODES en
# filters.py solo conoce 4. SHADOW_LIVE -> 'live' porque su dominio
# de filtrado es identico al LIVE; la diferencia entre LIVE y SHADOW_LIVE
# solo afecta execution, fuera del scanner.
# ---------------------------------------------------------------------------

_SCANNER_MODE_MAP: Final[dict[TradingMode, str]] = {
    TradingMode.RESEARCH: "research",
    TradingMode.BACKTEST: "backtest",
    TradingMode.PAPER: "paper",
    TradingMode.LIVE: "live",
    TradingMode.SHADOW_LIVE: "live",
}

# ---------------------------------------------------------------------------
# Live-endurecimiento numerico (Q2 verdict)
# Spec section 7.1: live endurece volume 10M / spread 20 bps / ATR max 5%.
# Aplicados en __init__ sobre los bounds de Settings, antes de
# construir ``FilterBounds`` (single source of truth).
# ---------------------------------------------------------------------------

LIVE_MIN_VOLUME_USDT: Final[float] = 10_000_000.0
LIVE_MAX_SPREAD_BPS: Final[float] = 20.0
LIVE_MAX_ATR_PERCENT: Final[float] = 5.0


# ---------------------------------------------------------------------------
# Per-mode score-normalization maxima (compute_rank_score input).
# Frozen dataclass: parte del API publico para que callers (F5)
# puedan sobreescribir via ``normalizers_per_mode`` del constructor.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScoreNormalizers:
    """Parametros de normalizacion para ``compute_rank_score`` (spec §6)."""

    spread_norm_max: float = 30.0
    volume_norm_max: float = 100_000_000.0
    atr_optimo: float = 2.0

    @classmethod
    def for_mode(cls, mode: str) -> ScoreNormalizers:
        """Per-mode defaults; live usa bounds mas estrechos.

        Override semantics: si el caller quiere un valor custom
        (incluso para ``"live"``), debe pasar
        ``normalizers_per_mode={mode: ScoreNormalizers(...)}`` a
        ``UniverseScanner.__init__``. Esta factory solo se invoca
        para modes no especificados; para "live" devuelve el canonical
        endurecimiento (el caller puede sobreescribirlo via
        ``normalizers_per_mode``).
        """
        if mode == "live":
            return cls(
                spread_norm_max=20.0,
                volume_norm_max=200_000_000.0,
                atr_optimo=2.0,
            )
        return cls()


# ---------------------------------------------------------------------------
# Per-mode filter bounds (Q2 verdict: single source of truth, derived
# de Settings + endurecimiento live aplicado localmente).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FilterBounds:
    """Per-mode filter thresholds; computed una sola vez en ``__init__``.

    Single source of truth: tanto los ``Filter`` construidos en
    ``build_filter_set_per_mode`` (mode_filters.py) como la logica
    de scoring (en ``_process_pair``) leen de estos valores. Esto
    evita el coupling name-based con attrs privados de AtrFilter
    que el thinker flagged como fragil en Q2.
    """

    min_24h_volume_usdt: float
    live_min_24h_volume_usdt: float | None
    max_spread_bps: float
    min_atr_percent: float
    max_atr_percent: float
    min_history: int

    @classmethod
    def from_settings(cls, settings: Settings, mode_str: str) -> FilterBounds:
        """Deriva bounds per-mode; endurecimiento live se aplica aqui."""
        f: UniverseFilters = settings.universe.filters
        if mode_str == "live":
            # Endurecimiento: el mas restrictivo entre Settings y spec §7.1.
            return cls(
                min_24h_volume_usdt=float(f.min_24h_volume_usdt),
                live_min_24h_volume_usdt=LIVE_MIN_VOLUME_USDT,
                max_spread_bps=min(LIVE_MAX_SPREAD_BPS, float(f.max_spread_bps)),
                min_atr_percent=float(f.min_atr_percent),
                max_atr_percent=min(LIVE_MAX_ATR_PERCENT, float(f.max_atr_percent)),
                min_history=100,
            )
        return cls(
            min_24h_volume_usdt=float(f.min_24h_volume_usdt),
            live_min_24h_volume_usdt=None,
            max_spread_bps=float(f.max_spread_bps),
            min_atr_percent=float(f.min_atr_percent),
            max_atr_percent=float(f.max_atr_percent),
            min_history=100,
        )


# ---------------------------------------------------------------------------
# Caching source (gotcha #1 mitigation).
# Wrappea ``MarketDataSourceProtocol`` memoizando per-symbol fetches
# dentro de UN solo ``run()``. Asi:
# - VolumeFilter.apply() hace fetch_24h_volume_usdt -> cached.
# - SpreadFilter.apply() hace fetch_spread_bps -> cached.
# - AtrFilter.apply() hace fetch_recent -> cached.
# - Score computation reusa los mismos valores sin re-fetch.
# Pine contract: el cache se descarta al finalizar ``run()`` (se
# construye fresh en cada iteracion del scheduler).
# ---------------------------------------------------------------------------


class _CachingSource:
    """Wraps ``MarketDataSourceProtocol`` + memoizes per-symbol fetches per run."""

    def __init__(self, source: MarketDataSourceProtocol) -> None:
        self._source = source
        self._recent_cache: dict[tuple[str, int], list[OHLCV]] = {}
        self._volume_cache: dict[str, float] = {}
        self._spread_cache: dict[str, float] = {}

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        key = (symbol, limit)
        if key not in self._recent_cache:
            self._recent_cache[key] = await self._source.fetch_recent(symbol, limit)
        return self._recent_cache[key]

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        if symbol not in self._volume_cache:
            self._volume_cache[symbol] = await self._source.fetch_24h_volume_usdt(symbol)
        return self._volume_cache[symbol]

    async def fetch_spread_bps(self, symbol: str) -> float:
        if symbol not in self._spread_cache:
            self._spread_cache[symbol] = await self._source.fetch_spread_bps(symbol)
        return self._spread_cache[symbol]


# ---------------------------------------------------------------------------
# Counters (spec section 10). Mutable interno (``_CountersState``) +
# read-only view publico (``CounterSnapshot``). El property ``counters``
# retorna SIEMPRE un ``CounterSnapshot`` frozen dataclass: el caller
# puede leer atributos pero NO puede mutar ``scanner.counters.X = Y``
# (raises ``FrozenInstanceError``).
# ---------------------------------------------------------------------------


class _CountersState:
    """Internal mutable counters (renamed from ``_Counters`` post-fix
    para preservar naming clarity: ``_CountersState`` = mutable state;
    ``CounterSnapshot`` = immutable snapshot)."""

    def __init__(self) -> None:
        self.pairs_processed: int = 0
        self.pairs_active: int = 0
        self.pairs_inactive: int = 0
        self.scanner_errors: int = 0

    def reset(self) -> None:
        self.pairs_processed = 0
        self.pairs_active = 0
        self.pairs_inactive = 0
        self.scanner_errors = 0


@dataclass(frozen=True, slots=True)
class CounterSnapshot:
    """Read-only view de los 4 contadores (spec section 10).

    Construido fresh en cada acceso a ``UniverseScanner.counters``.
    Pine contract:
    - Mismos nombre de atributos que ``_CountersState``
      (``pairs_processed``, ``pairs_active``, ``pairs_inactive``,
      ``scanner_errors``), por tanto los tests existentes siguen
      funcionando sin cambios.
    - Frozen: cualquier intento de ``snap.pairs_active = 999`` raise
      ``dataclasses.FrozenInstanceError`` (BAJO fix del reviewer).
    - El interno ``_CountersState`` sigue mutable para que
      ``self._counters.pairs_active += 1`` en ``_process_pair``
      NO levante.
    """

    pairs_processed: int
    pairs_active: int
    pairs_inactive: int
    scanner_errors: int


# ---------------------------------------------------------------------------
# Per-mode bundle: lo que __init__ resuelve una sola vez para cada
# mode-string del dict que recibe el caller. Es inmutable (frozen +
# slots); UniverseScanner los mantiene en ``self._bundles``.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ModeRegistryBundle:
    """Inmutable bundle per-mode. Derivado una sola vez en ``__init__``."""

    mode: str
    # ``registry`` ya esta frozen al entrar al bundle (ADR-lock).
    # Tipado como FilterRegistry directo (NO hay circular import:
    # registry.py solo importa de protocols.py).
    registry: FilterRegistry
    bounds: FilterBounds
    normalizers: ScoreNormalizers


# ---------------------------------------------------------------------------
# UniverseScanner
# ---------------------------------------------------------------------------


class UniverseScanner:
    """Orchestrator async (TSK-103.4/F4). NO reentrante.

    Constructor DI:
      - ``source``: ``MarketDataSourceProtocol`` (CCXTMarketDataSource en
        produccion; ``FakeMarketDataSource`` en tests).
      - ``registry_per_mode``: ``dict[str, FilterRegistry]`` con key ∈
        ``VALID_MODES``; cada registry se congela al instanciar.
      - ``settings``: ``Settings`` (typed config); controla universe.pairs
        + runtime.mode + risk.kill_switch_enabled.
      - ``normalizers_per_mode``: opcional; default usa ``ScoreNormalizers.for_mode``.
      - ``scan_iteration_id_factory``: opcional; default ``uuid4().hex``.

    Comportamiento (verificado por tests/unit/scanner/test_universe_scanner.py):
      - ``run()`` emite 5 structlog events en orden (started, optional
        paused/empty, pair.processed por par, completed final).
      - ``scanner.iteration.completed`` SIEMPRE se emite al final (incl.
        paths kill_switch / empty_universe, con ``early_exit`` tag) -
        fix MEDIO del reviewer de handoff.
      - Short-circuit en el primer filter fail (TSK-103.4.4).
      - Orden: pares de ``universe.pairs`` con ``enabled=True``.
      - Cache per run: ``_CachingSource`` evita doble I/O.
      - Reentrancy guard: ``RuntimeError`` si ``run()`` ya en curso.
      - Try/finally garantiza cleanup del flag aun en errores
        no capturados (Q3 latent risk mitigado).
      - ``counters`` property retorna fresh ``CounterSnapshot`` frozen
        dataclass por acceso (BAJO fix del reviewer).
    """

    def __init__(
        self,
        *,
        source: MarketDataSourceProtocol,
        registry_per_mode: dict[str, FilterRegistry],
        settings: Settings,
        normalizers_per_mode: dict[str, ScoreNormalizers] | None = None,
        scan_iteration_id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        # --- Validacion de DI ---
        if source is None:
            raise ConfigurationError("UniverseScanner requiere source; got None")
        if registry_per_mode is None or not registry_per_mode:
            raise ConfigurationError("UniverseScanner requiere registry_per_mode no-vacio")
        if settings is None:
            raise ConfigurationError("UniverseScanner requiere settings; got None")

        # --- Resolucion per-mode: freeze + bounds + normalizers ---
        bundles: dict[str, _ModeRegistryBundle] = {}
        for mode_key, reg in registry_per_mode.items():
            if mode_key not in VALID_MODES:
                raise ConfigurationError(
                    f"registry_per_mode key {mode_key!r} no esta en "
                    f"VALID_MODES={sorted(VALID_MODES)}"
                )
            # Verificacion de tipo sin importar (evita import circular en type hints).
            freeze = getattr(reg, "freeze", None)
            if not callable(freeze):
                raise ConfigurationError(
                    f"registry_per_mode[{mode_key!r}] no es un FilterRegistry "
                    f"(sin .freeze()): {type(reg).__name__}"
                )
            reg.freeze()  # ADR-lock: freeze() opt-in.

            normalizers = (normalizers_per_mode or {}).get(mode_key) or ScoreNormalizers.for_mode(
                mode_key
            )
            bundles[mode_key] = _ModeRegistryBundle(
                mode=mode_key,
                registry=reg,
                bounds=FilterBounds.from_settings(settings, mode_key),
                normalizers=normalizers,
            )

        self._bundles = bundles
        self._source = source
        self._settings = settings
        self._id_factory = scan_iteration_id_factory
        self._counters = _CountersState()
        self._log = structlog.get_logger("trading_bot.scanner")
        self._running = False  # reentrancy guard (Q3 verdict)

    @property
    def counters(self) -> CounterSnapshot:
        """Read-only counter snapshot (BAJO fix del reviewer).

        Retorna fresh ``CounterSnapshot`` frozen dataclass en cada
        acceso. Caller puede leer atributos (``scanner.counters.pairs_active``)
        pero NO mutarlos: ``scanner.counters.pairs_active = 999`` raises
        ``dataclasses.FrozenInstanceError``.

        Reads de los 4 contadores se copian desde el ``_CountersState``
        mutable interno. Esto preserva el contrato observability:
        ``pairs_processed``, ``pairs_active``, ``pairs_inactive``,
        ``scanner_errors`` son siempre reflejo del state post-run.
        """
        c = self._counters
        return CounterSnapshot(
            pairs_processed=c.pairs_processed,
            pairs_active=c.pairs_active,
            pairs_inactive=c.pairs_inactive,
            scanner_errors=c.scanner_errors,
        )

    def _scanner_mode_str(self) -> str:
        """Map ``TradingMode`` -> ``VALID_MODES`` string.

        Pine contract: si ``TradingMode`` gana un valor nuevo y no se
        actualiza ``_SCANNER_MODE_MAP``, el operador recibe un
        ``ConfigurationError`` con la lista de mapeos pineados que
        apunta a ``tasks/decisions.md`` (ADR firmada). Asi NO es un
        ``KeyError`` opaco escondido en un deep-stack trace:

        - ``RESEARCH``     -> ``"research"``
        - ``BACKTEST``     -> ``"backtest"``
        - ``PAPER``        -> ``"paper"``
        - ``LIVE``         -> ``"live"``
        - ``SHADOW_LIVE``  -> ``"live"``  (Q1 verdict: dominio identico)
        """
        try:
            return _SCANNER_MODE_MAP[self._settings.runtime.mode]
        except KeyError as exc:
            supported = ", ".join(f"{m.name} -> {v!r}" for m, v in _SCANNER_MODE_MAP.items())
            raise ConfigurationError(
                f"TradingMode {self._settings.runtime.mode!r} no esta mapeado en "
                f"_SCANNER_MODE_MAP; supported={supported}. "
                f"Anade el mapeo o firma una ADR en tasks/decisions.md antes de "
                f"agregar nuevos TradingMode en trading_bot.config.runtime."
            ) from exc

    def _bundle_for_current_mode(self) -> _ModeRegistryBundle:
        mode = self._scanner_mode_str()
        bundle = self._bundles.get(mode)
        if bundle is None:
            raise ConfigurationError(
                f"registry_per_mode no contiene key {mode!r}; "
                f"available: {sorted(self._bundles.keys())}"
            )
        return bundle

    # ------------------------------------------------------------------
    # Public entrypoint: run() con reentrancy guard
    # ------------------------------------------------------------------

    async def run(self) -> list[MarketSnapshot]:
        """Una iteracion completa del scanner.

        Raises:
            RuntimeError: si ``run()`` ya esta en curso (no reentrante).
        """
        if self._running:
            raise RuntimeError(
                "UniverseScanner.run() no es reentrante; ya hay una "
                "iteracion en curso. Espera a que termine antes de "
                "invocar de nuevo."
            )
        self._running = True
        try:
            return await self._run_impl()
        finally:
            # Q3 latent risk: cleanup garantizado incluso en
            # errores no capturados (e.g. bug interno que levanta
            # sin pasar por el catch de transient errors).
            self._running = False

    async def _run_impl(self) -> list[MarketSnapshot]:
        scan_id = self._id_factory()
        # Pine contract: scan_iteration_id se pasa EXPLÍCITAMENTE a cada
        # ``self._log.*(...)`` call como kwarg ``scan_iteration_id=scan_id``
        # (no via contextvars) para que el campo sea visible a
        # ``structlog.testing.capture_logs()`` sin requerir un
        # ``structlog.configure(..., processors=[..., merge_contextvars])``
        # adicional. Ver tests/unit/scanner/test_universe_scanner.py::
        # test_structlog_emits_5_event_kinds + test_pairs_processed_counts_per_pair_not_per_filter.
        self._counters.reset()
        return await self._execute_iteration(scan_id)

    async def _execute_iteration(self, scan_id: str) -> list[MarketSnapshot]:
        start = time.perf_counter()
        mode_str = self._scanner_mode_str()
        bundle = self._bundle_for_current_mode()

        # --- Step 1: iteration.started ---
        self._log.info("scanner.iteration.started", mode=mode_str, scan_iteration_id=scan_id)

        # MEDIO fix del reviewer: single ``iteration.completed`` emission
        # al final, funciona para los 3 paths:
        #   - healthy: process N pares, emit `iteration.completed(early_exit=None)`
        #   - kill switch: emit `iteration.completed(early_exit='kill_switch')`
        #   - empty universe: emit `iteration.completed(early_exit='empty_universe')`
        # El log consumer SIEMPRE ve `iteration.completed` con `duration_ms`
        # + los 4 counters, sin importar si fue early-abort (spec section 10).
        early_exit: str | None = None
        snapshots: list[MarketSnapshot] = []

        # --- Step 2: kill switch (RF-4 / CL-5) ---
        if self._settings.risk.kill_switch_enabled:
            self._log.info("scanner.paused.kill_switch", scan_iteration_id=scan_id)
            early_exit = "kill_switch"
        else:
            # --- Step 3: empty universe (CL-1) ---
            enabled_pairs = [p for p in self._settings.universe.pairs if p.enabled]
            if not enabled_pairs:
                self._log.warning("scanner.universe.empty", scan_iteration_id=scan_id)
                early_exit = "empty_universe"
            else:
                # --- Step 4: process each pair (RF-1) ---
                # Gotcha #1: wrap source con cache per-run. Se construye fresh
                # en cada run() para que el cache refleje solo esta iteracion.
                caching_source = _CachingSource(self._source)

                for pair in enabled_pairs:
                    try:
                        snap = await self._process_pair(
                            pair.symbol, bundle, caching_source, scan_id
                        )
                        snapshots.append(snap)
                    except Exception as exc:
                        # --- RF-5 / CL-3: transient error isolation ---
                        self._counters.scanner_errors += 1
                        self._log.error(
                            "scanner.pair.error",
                            symbol=pair.symbol,
                            error_type=type(exc).__name__,
                            error_msg=str(exc),
                            scan_iteration_id=scan_id,
                        )
                        continue

        # --- Step 5: iteration.completed (RF-6) — single emission ---
        duration_ms = int((time.perf_counter() - start) * 1000)
        # Round-9 + Round-10 fix: `all_failed` se computa una sola vez
        # y se emite SIEMPRE. Pine contract (round-10 tightening):
        #   - early_exit != None: all_failed=None (irrelevante en aborts)
        #   - early_exit is None AND pairs_active == 0:
        #     all_failed=True (CL-3 truth-table row 2: zero snapshots
        #     activos. Cubre BOTH all-transient-errors AND
        #     all-filter-rejected sin distinguirlos per Q1 del round-9;
        #     el discriminador exclusivo es ``pairs_active==0``, NO
        #     ``not snapshots and scanner_errors > 0`` como antes del
        #     round-10 tightening.)
        #   - otherwise: all_failed=False (healthy completion, 1+ snapshot activo).
        all_failed: bool | None
        if early_exit is not None:
            all_failed = None
        elif self._counters.pairs_active == 0:
            all_failed = True
        else:
            all_failed = False
        log_kwargs = dict(
            duration_ms=duration_ms,
            pairs_processed=self._counters.pairs_processed,
            pairs_active=self._counters.pairs_active,
            pairs_inactive=self._counters.pairs_inactive,
            scanner_errors=self._counters.scanner_errors,
            early_exit=early_exit,
            all_failed=all_failed,
            scan_iteration_id=scan_id,
        )
        if early_exit is not None:
            # MEDIO fix: kill_switch / empty_universe eran paths que
            # emitían `iteration.started` + su path-specific event pero
            # NO emitían `iteration.completed`. Ahora todos caen aqui,
            # log level WARNING porque la iteracion se aborto (= no healthy).
            self._log.warning("scanner.iteration.completed", **log_kwargs)
        elif all_failed:
            # Round-10 tightening: zero active snapshots (filter-fail-only
            # OR all-transient-errors, per `pairs_active == 0`) -> warn level
            # (still emit completed).
            self._log.warning("scanner.iteration.completed", **log_kwargs)
        else:
            self._log.info("scanner.iteration.completed", **log_kwargs)

        # RF-10: lista en orden de insercion (mismo orden que universe.pairs).
        return snapshots

    async def _process_pair(
        self,
        symbol: str,
        bundle: _ModeRegistryBundle,
        source: _CachingSource,
        scan_id: str,
    ) -> MarketSnapshot:
        """Aplica filters al par; short-circuit en el primer fail (Q4 verdict)."""
        # P0 fix: ``pairs_processed`` semantica per spec section 10
        # = count of pairs (no count of filter calls). Incrementa UNA
        # vez por par al entrar, sin importar cuantos filters se ejecuten.
        self._counters.pairs_processed += 1
        # Q4 latent risk: orden de los filtros del registry.
        # ``build_filter_set_per_mode`` (mode_filters.py) registra volume + spread
        # ANTES de atr porque son baratos (single async call); atr requiere
        # fetch_recent (red + math) y solo se evalua si los baratos pasan.
        for f in bundle.registry.all():
            outcome: FilterOutcome = await f.apply(symbol, source)
            if not outcome.passed:
                # Inactive snapshot con reason del primer fail.
                self._counters.pairs_inactive += 1
                self._log.info(
                    "scanner.pair.processed",
                    symbol=symbol,
                    active=False,
                    rejection_reason=outcome.reason,
                    scan_iteration_id=scan_id,
                )
                return MarketSnapshot(
                    symbol=symbol,
                    last_price=0.0,
                    volume_24h_usdt=0.0,
                    spread_bps=0.0,
                    atr_pct=None,
                    volatility_pct=None,
                    active=False,
                    rejection_reason=outcome.reason,
                    timestamp=_now_ms(),
                    rank_score=0.0,
                )

        # All filters passed: construir active snapshot + scoring.
        # Gotcha #1: reusa cache del _CachingSource para evitar double-fetch.
        self._counters.pairs_active += 1
        ohlcv = await source.fetch_recent(symbol, bundle.bounds.min_history)
        volume = await source.fetch_24h_volume_usdt(symbol)
        spread = await source.fetch_spread_bps(symbol)
        last_price = ohlcv[-1].close if ohlcv else 0.0
        # R5-LATENT: _compute_atr_pct = mean(TR) sobre TODAS las velas;
        # no es ATR-14 Wilder fijo. Pine contract preservado aqui.
        atr_pct = _compute_atr_pct(ohlcv) if len(ohlcv) >= 2 else None
        atr_in_range = (
            atr_pct is not None
            and bundle.bounds.min_atr_percent <= atr_pct <= bundle.bounds.max_atr_percent
        )
        score = compute_rank_score(
            spread_bps=spread,
            spread_norm_max=bundle.normalizers.spread_norm_max,
            volume_24h_usdt=volume,
            volume_norm_max=bundle.normalizers.volume_norm_max,
            atr_pct=atr_pct,
            atr_optimo=bundle.normalizers.atr_optimo,
            atr_en_rango=atr_in_range,
        )
        snap = MarketSnapshot(
            symbol=symbol,
            last_price=last_price,
            volume_24h_usdt=volume,
            spread_bps=spread,
            atr_pct=atr_pct,
            volatility_pct=None,  # extensible Fase 2 (ATR close-aware).
            active=True,
            rejection_reason=None,
            timestamp=_now_ms(),
            rank_score=score,
        )
        self._log.info(
            "scanner.pair.processed",
            symbol=symbol,
            active=True,
            rejection_reason=None,
            rank_score=score,
            scan_iteration_id=scan_id,
        )
        return snap


def _now_ms() -> int:
    """Millisegundos since epoch para MarketSnapshot.timestamp."""
    return int(time.time() * 1000)


__all__ = [
    "LIVE_MAX_ATR_PERCENT",
    "LIVE_MAX_SPREAD_BPS",
    "LIVE_MIN_VOLUME_USDT",
    "CounterSnapshot",
    "FilterBounds",
    "ScoreNormalizers",
    "UniverseScanner",
]
