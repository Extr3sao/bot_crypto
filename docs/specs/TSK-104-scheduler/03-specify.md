# TSK-104 - OHLCV Scheduler: Technical Specification (Command 03)

> Contratos de tipos, interfaces, errores, configuracion afectada
> y metricas observables del modulo scheduler. Metodologia:
> `.ai/commands/03-specify.md`. Es la **unica** fuente autorizada de
> diseno tecnico para `src/trading_bot/scheduler/`.

---

## 1. Layout de archivos

```
src/trading_bot/scheduler/
  __init__.py                 # docstring + re-exports publicos
  types.py                    # SchedulerResult, PullOutcome, CacheHitDecision
  protocols.py                # OHLCVSourceProtocol, ConnectorFactory, PullMetricsSink
  cache.py                    # CacheHitPredicate (RF-4) — pure function
  filters.py                  # KillSwitchGuard, ActiveHoursFilter (RF-2, RF-3)
  scheduler.py                # OHLCVScheduler (orquestador async)
  exceptions.py               # SchedulerError, KillSwitchActiveError,
                              #   EmptyUniverseWarning, RetryExhaustedError
tests/unit/scheduler/
  test_types.py               # dataclasses frozen, slots, invariante
  test_cache.py               # CacheHitPredicate parametrizado (RF-4)
  test_filters.py             # KillSwitch + ActiveHours parametrizados
  test_scheduler.py           # end-to-end con FakeOHLCVSource + FakeConnectorFactory
  test_cross_layer.py         # integridad: scheduler no importa otras capas
docs/specs/TSK-104-scheduler/
  01-requirements.md          # este spec consume RF/RNF/CL
  02-bdd.md
  03-specify.md               # este archivo
  04-plan.md
  05-tasks.md
```

**No nuevos sub-paquetes.** El scheduler es una sola unidad cohesiva
de ~300-400 LoC; dividir prematuramente en `cache/`, `retry/`, etc.
romperia la locality sin beneficio.

## 2. Tipos publicos (`src/trading_bot/scheduler/types.py`)

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal
from uuid import UUID

# Catalogo cerrado de motivos por los que un par es omitido del batch.
# Extender requiere ADR firmada en tasks/decisions.md (regla canonica,
# mismo criterio que ``scanner.types.RejectionReason``).
SkipReason = Literal[
    "active_hours_out_of_window",     # RF-2: current_time ∉ ventana activa
    "cache_hit",                       # RF-4: vela fresca en OHLCVStore
    "empty_universe",                  # CL-1: universe.pairs vacio
]

# Catalogo cerrado de motivos por los que un pull fallo. Distingue
# errores transitorios (con reintento) de errores permanentes (kill
# switch, configuration).
PullFailureReason = Literal[
    "rate_limit_exhausted",           # CL-9: HTTP 429 + 3 retries agotados
    "network_timeout",                # CL-2: OHLCVFetcherTimeoutError
    "exchange_unavailable",           # ccxt.ExchangeNotAvailable
    "ddos_protection",                # ccxt.DDoSProtection
    "validation_error",               # vela NaN o high<low tras retries
    "configuration_error",            # e.g. connector no inicializado
]

# Estado de la cache local ANTES de la decision de pull. Pineado por
# test para que el caller pueda distinguir "tenia vela fresca" de
# "vela corrupta pero dentro de ventana" (CL-8).
class CacheState(Enum):
    FRESH = "fresh"          # RF-4 predicado True -> skip
    STALE = "stale"          # RF-4 predicado False -> pull
    EMPTY = "empty"          # no hay vela para este simbolo
    CORRUPT = "corrupt"      # vela presente pero invalida (NaN, high<low)


@dataclass(frozen=True, slots=True)
class CacheHitDecision:
    """Decision del CacheHitPredicate sobre un par (RF-4)."""
    state: CacheState
    last_candle_ts: int | None       # ms since epoch, None si EMPTY
    current_ts: int                   # ms since epoch
    primary_timeframe_ms: int         # e.g. 5*60*1000 para 5m
    freshness_window_ms: int          # e.g. 5*60*1000 para 5m
    should_pull: bool
    reason: str                       # explicacion textual para logs


@dataclass(frozen=True, slots=True)
class PullOutcome:
    """Resultado del pull de un par individual (per-pair)."""
    symbol: str
    attempted: bool                   # True si se intento fetch (no cache hit)
    succeeded: bool                   # True si llego al OHLCVStore
    failure_reason: PullFailureReason | None  # None si succeeded
    duration_ms: int
    retries_used: int                 # 0..max_retries


@dataclass(frozen=True, slots=True)
class SchedulerResult:
    """Salida canonica de ``OHLCVScheduler.run_once()``.

    Pine contract (01-requirements.md §2.3 + invariante post-filter):
    - 6 campos frozen + slots.
    - Invariante: ``pulls_attempted == pulls_succeeded + pulls_failed + cache_hits``.
    - Invariante cubre el subconjunto que pasa filtros ``active_hours``
      y ``kill_switch``. Pares filtrados pre-batch NO aparecen en
      contadores.
    - Ver tests/unit/scheduler/test_types.py::test_scheduler_result_invariante.
    """
    pulls_attempted: int
    pulls_succeeded: int
    pulls_failed: int
    cache_hits: int
    duration_ms: int
    scheduler_iteration_id: UUID
```

`__all__ = ["CacheHitDecision", "CacheState", "PullFailureReason",
"PullOutcome", "SchedulerResult", "SkipReason"]`.

### 2.1 Risgo latente (R1) — Extensibilidad del Literal

> **TODO(R1) — Extension de `SkipReason` o `PullFailureReason` requiere ADR.**
> Mismo criterio que ``scanner.types.RejectionReason``: el Literal
> pinea el contrato publico. Tests pinean ``Literal[...]`` exhaustivo
> (``test_skip_reason_literal_values`` + ``test_pull_failure_reason_literal_values``).
> Anadir un valor requiere (a) actualizar el Literal, (b) actualizar
> los tests pineantes, (c) firmar ADR en ``tasks/decisions.md`` si
> toca money-risk invariants.

## 3. Protocolos (`src/trading_bot/scheduler/protocols.py`)

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from trading_bot.config.runtime import TradingMode
from trading_bot.market_data.exchange_connector import ExchangeConnector
from trading_bot.market_data.types import OHLCV
from trading_bot.scheduler.types import (
    CacheHitDecision,
    PullFailureReason,
    PullOutcome,
)


@runtime_checkable
class OHLCVSourceProtocol(Protocol):
    """    Abstraccion sobre OHLCVFetcher (decision documentada en §3).

    El scheduler no importa ``market_data.exchange_connector`` ni
    ``storage.ohlcv_store`` directamente; solo este Protocol.
    Implementacion canonica: ``LiveOHLCVSource`` (envuelve
    ``OHLCVFetcher``). Tests usan ``FakeOHLCVSource`` con velas
    sinteticas + clock inyectable.

    Async: ``fetch_one`` es una coroutine que se invoca via ``await``
    en el ``OHLCVScheduler.run_once()``.
    """

    async def fetch_one(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[OHLCV]:
        """Pull + validate + cache; devuelve velas leidas del store.

        Raises:
            Exception: cualquier excepcion transitoria (timeout, 429,
                network) propaga al scheduler que decide retry. NO
                retorna lista vacia en error: el scheduler necesita
                distinguir success de failure.
        """
        ...

    async def get_last_candle_ts(self, symbol: str) -> int | None:
        """Devuelve el timestamp de la ultima vela en OHLCVStore, o None.

        Usado por CacheHitPredicate (RF-4) para evaluar la ventana
        de freshness. None si OHLCVStore no tiene velas para el par.
        """
        ...


# Factory para construir el ExchangeConnector correcto segun modo.
# Pine contract: el scheduler NO instancia ``CCXTExchangeConnector``
# directamente; siempre delega a ``ConnectorFactory`` para que el
# caller (production wiring) pueda sustituir por ``FakeConnector``
# en tests.
ConnectorFactory = Callable[[TradingMode], ExchangeConnector]


@runtime_checkable
class PullMetricsSink(Protocol):
    """Sink para emitir metricas (structlog + counters).

    Default: ``StructlogSink`` (envuelve structlog + CounterSnapshot
    interno). Tests usan ``InMemorySink`` que captura eventos para
    aserciones deterministas.

    NO es ``runtime_checkable`` en el sentido de ``isinstance``; los
    Protocols con metodos async no son ``runtime_checkable`` por
    defecto en Python 3.11. Mypy strict cubre la validacion
    compile-time.
    """

    async def on_pull_completed(self, outcome: PullOutcome) -> None:
        ...

    async def on_pull_skipped(
        self, symbol: str, decision: CacheHitDecision
    ) -> None:
        ...

    async def on_pull_failed(
        self, symbol: str, reason: PullFailureReason, attempts: int
    ) -> None:
        ...

    async def on_iteration_completed(
        self, result: SchedulerResult, early_exit: str | None
    ) -> None:
        ...
```

`__all__ = ["ConnectorFactory", "OHLCVSourceProtocol",
"PullMetricsSink"]`.

## 4. CacheHitPredicate (`src/trading_bot/scheduler/cache.py`)

Pure function (no I/O, no state). Pine contract (RF-4): skip si
`last_candle_ts >= current_ts - primary_timeframe AND current_ts -
last_candle_ts < freshness_window_min`.

```python
from __future__ import annotations

from trading_bot.scheduler.types import CacheHitDecision, CacheState


def evaluate_cache_hit(
    *,
    last_candle_ts: int | None,
    current_ts: int,
    primary_timeframe_ms: int,
    freshness_window_ms: int,
) -> CacheHitDecision:
    """RF-4: decide si el par necesita pull o cache hit.

    Pine contract:
    - EMPTY (last_candle_ts is None) -> should_pull=True, state=EMPTY.
    - Periodo previo (last_candle_ts < current_ts - primary_timeframe)
      -> should_pull=True, state=STALE. Caso: 5m TF, vela 10min atras.
    - Periodo actual + fresh (current_ts - last_candle_ts < freshness)
      -> should_pull=False, state=FRESH. Caso: 5m TF, vela 4min atras.
    - Boundary: current_ts - last_candle_ts == freshness_window_ms
      -> should_pull=True (strict <, no <=). Boundary miss es
      intencional para no under-pull en el limite.

    Nota: la corrupcion (NaN, high<low) la detecta el OHLCVFetcher
    en pull, NO este predicado. Aqui solo decidimos si PULL O SKIP;
    la calidad de los datos se valida downstream (CL-8).

    Returns:
        CacheHitDecision frozen dataclass.
    """
    if last_candle_ts is None:
        return CacheHitDecision(
            state=CacheState.EMPTY,
            last_candle_ts=None,
            current_ts=current_ts,
            primary_timeframe_ms=primary_timeframe_ms,
            freshness_window_ms=freshness_window_ms,
            should_pull=True,
            reason="no prior candle in OHLCVStore",
        )
    age_ms = current_ts - last_candle_ts
    is_current_period = last_candle_ts >= (current_ts - primary_timeframe_ms)
    is_fresh = age_ms < freshness_window_ms
    if is_current_period and is_fresh:
        return CacheHitDecision(
            state=CacheState.FRESH,
            last_candle_ts=last_candle_ts,
            current_ts=current_ts,
            primary_timeframe_ms=primary_timeframe_ms,
            freshness_window_ms=freshness_window_ms,
            should_pull=False,
            reason=f"last candle {age_ms}ms old within {freshness_window_ms}ms window",
        )
    return CacheHitDecision(
        state=CacheState.STALE,
        last_candle_ts=last_candle_ts,
        current_ts=current_ts,
        primary_timeframe_ms=primary_timeframe_ms,
        freshness_window_ms=freshness_window_ms,
        should_pull=True,
        reason=(
            f"last candle {age_ms}ms old (current_period={is_current_period}, "
            f"fresh={is_fresh})"
        ),
    )
```

## 5. Filtros pre-batch (`src/trading_bot/scheduler/filters.py`)

Dos guards pre-batch. NO son ``Filter`` (no implementan protocolo
async); son pure functions que devuelven ``ShouldContinue | Skip``.

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from trading_bot.config.settings import Settings

PreBatchDecision = Literal["continue", "skip_kill_switch", "skip_empty_universe"]


@dataclass(frozen=True, slots=True)
class ActiveHoursWindow:
    start_hour: int   # 0..23, default 0
    end_hour: int     # 0..23, default 23


def check_kill_switch(settings: Settings) -> PreBatchDecision:
    """RF-3: pre-batch guard.

    Si ``settings.risk.kill_switch_enabled`` es True, devuelve
    ``skip_kill_switch`` ANTES de cualquier I/O. Pine contract: el
    log ``scheduler.paused.kill_switch`` se emite UNA vez por
    iteracion abortada (single emission point en
    ``_execute_iteration``).
    """
    if settings.risk.kill_switch_enabled:
        return "skip_kill_switch"
    return "continue"


def check_active_hours(
    settings: Settings, now: datetime
) -> PreBatchDecision:
    """RF-2: pre-batch guard.

    Por par, NO por iteracion: la exclusion se hace DENTRO del
    loop ``for pair in enabled_pairs``. Devuelve ``continue`` o
    ``skip_active_hours`` (este ultimo es per-par, no aborta la
    iteracion). El pre-batch global NO aborta; cada par se evalua
    individualmente.

    Default window 0-23 = siempre include. Pine contract: el log
    ``scheduler.pull.skipped.active_hours`` se emite por par omitido.
    """
    # Implementacion real en scheduler.py; esta firma es la
    # decision logic pura (testable sin I/O).
    window = ActiveHoursWindow(
        start_hour=settings.runtime.scheduler.active_hours_start,
        end_hour=settings.runtime.scheduler.active_hours_end,
    )
    hour = now.hour
    if window.start_hour <= window.end_hour:
        in_window = window.start_hour <= hour < window.end_hour
    else:
        # Wrap-around (e.g. 22..6): include if hour >= start OR hour < end.
        in_window = hour >= window.start_hour or hour < window.end_hour
    return "continue" if in_window else "skip_active_hours"
```

## 6. OHLCVScheduler (`src/trading_bot/scheduler/scheduler.py`)

Orquestador async. NO reentrante. Cero imports de `execution`,
`strategies`, `risk`, `portfolio` (cubierto por test AST).

```python
class OHLCVScheduler:
    """Orquestador async del OHLCVScheduler (TSK-104).

    Constructor DI:
      - ``settings``: ``Settings`` (typed config).
      - ``source_factory``: ``Callable[[TradingMode], OHLCVSourceProtocol]``
        (envuelve ``OHLCVFetcher`` en produccion; ``FakeOHLCVSource``
        en tests).
      - ``connector_factory``: ``ConnectorFactory`` (envuelve
        ``CCXTExchangeConnector`` en produccion; ``FakeConnector``
        en tests). Solo se invoca para modos ``live``/``paper``;
        ``backtest``/``research`` usan source synthetic (no
        connector). Ver RF-7 + RF-7b.
      - ``metrics_sink``: ``PullMetricsSink`` (default:
        ``StructlogSink``).
      - ``scheduler_iteration_id_factory``: default
        ``uuid4()`` (UUID, no str).
      - ``clock_fn``: default ``time.time`` (inyectable para
        determinismo en tests con freezegun).

    Comportamiento (verificado por tests/unit/scheduler/test_scheduler.py):
      - ``run()`` async: loop ``while not cancelled: await
        run_once(); await asyncio.sleep(interval_seconds)``.
        ``CancelledError`` propaga al caller sin ser tragado (RNF-4).
      - ``run_once()`` async: 1 iteracion completa, retorna
        ``SchedulerResult``. Es el unit de testeo.
      - Kill-switch check pre-batch (RF-3) -> early_exit="kill_switch".
      - Empty universe pre-batch (CL-1) -> early_exit="empty_universe".
      - Per-par: active_hours (RF-2) -> skip; cache hit (RF-4) ->
        skip; pull + retry con jitter (CL-9) -> success o fail.
      - Reentrancy guard: ``RuntimeError`` si ``run_once()`` ya en
        curso (mismo patron que ``UniverseScanner.run``).
      - Single emission point: ``iteration.completed`` se emite
        SIEMPRE, con tag ``early_exit`` para distinguir abort paths
        (mismo patron que scanner TSK-103 spec section 10).
      - Mode-flip (RF-7) via ``connector_reinjector`` method:
        ``self._connector = self._connector_factory(new_mode)``.
        El connector anterior se cierra via ``close()`` si existe.
        Esto resuelve el problema de que ``sandbox`` se setea en
        ``CCXTExchangeConnector.__init__`` (TSK-101) y no es
        mutable in-place.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        source_factory: Callable[[TradingMode], OHLCVSourceProtocol],
        connector_factory: ConnectorFactory | None = None,
        metrics_sink: PullMetricsSink | None = None,
        scheduler_iteration_id_factory: Callable[[], UUID] = lambda: uuid4(),
        clock_fn: Callable[[], float] = time.time,
    ) -> None: ...

    async def run(self) -> None:
        """Loop continuo hasta CancelledError (RNF-4).

        ``CancelledError`` se propaga al caller sin ser tragado.
        El ``finally`` cierra el connector via ``self._close()``.
        """

    async def run_once(self) -> SchedulerResult:
        """Una iteracion completa; retorna ``SchedulerResult``.

        Raises:
            RuntimeError: si ya hay un ``run_once()`` en curso.
        """

    def connector_reinjector(self, new_mode: TradingMode) -> None:
        """RF-7: re-injecta el connector cuando runtime.mode cambia.

        Cierra el connector actual (si existe) y construye uno nuevo
        via ``self._connector_factory(new_mode)``. NO muta el flag
        ``sandbox`` in-place (CCXTExchangeConnector lo setea en
        ``__init__`` antes de ``load_markets``, ver TSK-101).

        Pine contract: este metodo es el UNICO punto de cambio de
        connector en runtime. Cualquier intento de mutar
        ``self._connector`` directamente esta vetado por code review.
        """
```

### 6.1 Comportamiento por modo (RF-7, RF-7b)

| `runtime.mode` | ``source_factory`` retorna                          | ``connector_factory`` se invoca? |
| -------------- | --------------------------------------------------- | ------------------------------- |
| `research`     | ``DeterministicOHLCVSource`` (synthetic, in-memory)  | NO                              |
| `backtest`     | ``DeterministicOHLCVSource`` (synthetic, fixture)    | NO                              |
| `paper`        | ``LiveOHLCVSource`` con sandbox=True                | SI (sandbox=True)               |
| `live`         | ``LiveOHLCVSource`` con sandbox=False               | SI (sandbox=False)              |
| `shadow_live`[^1] | ``LiveOHLCVSource`` con sandbox=False             | SI (sandbox=False)              |

NOTA: ``DeterministicOHLCVSource`` y ``LiveOHLCVSource`` son nombres
de abstraccion de PRODUCCION propuestos. NO existen aun en el codigo;
se crearan durante `04-plan.md` / implementacion. La implementacion
de tests usara `FakeOHLCVSource` (test scaffolding en
`market_data/fake.py`, mismo patron que TSK-103), pero el scheduler
**NO importa** ese modulo (cubierto por test AST, §11).

Pine contract: el scheduler NO conoce el detalle del connector; solo
delega a ``connector_factory``. Tests inyectan ``FakeConnector``
que retorna velas sinteticas + asserts sobre ``sandbox`` flag.

### 6.2 Concurrencia (decision de diseno D-TSK104-2)

Pulls se ejecutan **secuencialmente** dentro de una iteracion. Razon:

1. Rate limit (CL-9): burst de N requests simultaneos dispara 429.
   ccxt con ``enableRateLimit=True`` ya pacea ANTES del POST; con
   concurrencia, el burst excede el rate y los retries se disparan.
2. Determinismo: tests asumen orden de procesamiento == orden de
   ``universe.pairs``. Concurrencia requiere ``asyncio.gather`` +
   ``return_exceptions=True`` + ordering explicito (frágil).
3. Latency budget: 25 pares sandbox a 200ms = 5s. El RNF-1
   (P95 <= 6s) se cumple secuencialmente. Si un dia se necesita
   concurrencia, anadir ``asyncio.gather`` con
   ``semaphore=N``; cambio requiere ADR firmada.

## 7. Errores custom (`src/trading_bot/scheduler/exceptions.py`)

```python
class SchedulerError(Exception):
    """Base para todos los errores especificos del scheduler."""


class KillSwitchActiveError(SchedulerError):
    """Se eleva desde ``OHLCVScheduler.run_once`` cuando el
    kill_switch esta activo. La iteracion devuelve
    ``SchedulerResult(pulls_attempted=0)`` en lugar de elevar este
    error para evitar crash del caller. Error solo para tests que
    validan el guard explicito."""


class EmptyUniverseWarning(UserWarning):
    """Warning cuando ``universe.pairs`` esta vacio.

    NO se eleva: el scheduler loguea ``scheduler.universe.empty``
    y retorna ``SchedulerResult(pulls_attempted=0)``. Esta clase
    existe para que tests puedan ``pytest.warns(EmptyUniverseWarning)``
    si lo necesitan, pero la implementacion actual usa structlog
    en lugar de ``warnings.warn``."""


class RetryExhaustedError(SchedulerError):
    """Se eleva desde ``OHLCVScheduler._fetch_with_retry`` tras
    agotar los retries. La excepcion incluye el ``last_exception``
    (chain via ``raise ... from``) y el ``attempts`` count.

    Caller (``_process_one_pair``) captura, incrementa
    ``pulls_failed``, emite log ``scheduler.pull.failed`` motivo
    ``rate_limit_exhausted`` (o el que corresponda), y continua con
    el siguiente par. El error NO aborta el batch.
    """
```

`__all__ = ["EmptyUniverseWarning", "KillSwitchActiveError",
"RetryExhaustedError", "SchedulerError"]`.

## 8. Configuracion afectada (`config/runtime.yaml` + `config/settings.py`)

YAML nuevo (sub-bloque ``runtime.scheduler``):

```yaml
# config/runtime.yaml
runtime:
  mode: paper
  scheduler:
    # RF-2: ventana activa para pulls (default 0-23 = todo el dia)
    active_hours_start: 0    # hora inclusiva [0..23]
    active_hours_end: 23     # hora exclusiva [1..24]
    # RF-4: ventana de freshness para cache hit
    freshness_window_minutes: 5   # 5 para sandbox, 1 para live
    # RF-4: timeframe primario (e.g. "5m", "1h"). Usado por
    # evaluate_cache_hit() para distinguir "vela del periodo actual"
    # de "vela del periodo previo" (ver §4 boundary).
    primary_timeframe: "5m"
    # RNF-1: latency P95 target
    p95_latency_budget_ms: 6000
    # CL-9: retry policy
    max_retries: 3
    retry_after_max_seconds: 60
    jitter_percent: 25
    # Loop interval (seconds) entre run_once() calls dentro de run()
    interval_seconds: 60
```

Cero cambios en `assets.yaml`, `exchange.yaml`, `risk.yaml`,
`strategies.yaml`, `indicators.yaml`. Todo se anade bajo
``runtime.scheduler`` en `runtime.yaml`.

`Settings` (Pydantic): el submodelo `RuntimeSettings` gana un campo
`scheduler: SchedulerSettings` (frozen, slots). Backward compat:
`Settings` ya cargados sin `scheduler` default a los valores del YAML.

## 9. Metricas observables

- **Logs estructurados** (`structlog` JSON, ADR-0004):
  - `scheduler.iteration.started { scheduler_iteration_id, mode,
    pairs_in_universe }`.
  - `scheduler.paused.kill_switch { scheduler_iteration_id }`
    (RF-3, una vez por iteracion abortada).
  - `scheduler.universe.empty { scheduler_iteration_id }`
    (CL-1, una vez por iteracion con universe vacio).
  - `scheduler.pull.completed { scheduler_iteration_id, symbol,
    duration_ms, attempts }` (RF-6).
  - `scheduler.pull.skipped { scheduler_iteration_id, symbol,
    reason, age_ms }` (RF-4 cache hit + RF-2 active_hours, con
    ``reason`` discriminante).
  - `scheduler.pull.failed { scheduler_iteration_id, symbol,
    failure_reason, attempts, last_error_type }` (CL-9 + RF-5).
  - `scheduler.iteration.completed { scheduler_iteration_id,
    duration_ms, pulls_attempted, pulls_succeeded, pulls_failed,
    cache_hits, early_exit }` (single emission point, igual
    patron que scanner).
- **Counters atomicos** en `OHLCVScheduler._SchedulerCounters`
  (mutable interno, NO parte del API publico). El property
  publico `scheduler.last_result` retorna el ultimo
  `SchedulerResult` frozen dataclass (no se acumulan; cada
  iteracion sobreescribe).
- **Metricas Prometheus**: NO en TSK-104 (ADR-0003/0004 reserva
  para Fase 8). Se deja TODO en `scheduler.py` con comentario
  explicito.

### 9.1 Anti-doble-emission

Pine contract: `scheduler.iteration.completed` se emite UNA vez
por `run_once()`, con `early_exit` tag discriminante:

| `early_exit`           | `pulls_attempted` | logs emitidos                                       |
| ---------------------- | ----------------- | --------------------------------------------------- |
| `None`                 | 0..N              | started + per-pair + completed                      |
| `"kill_switch"`        | 0                 | started + paused.kill_switch + completed            |
| `"empty_universe"`     | 0                 | started + universe.empty + completed                |

[^1]: `shadow_live` se trata identico a `live` en el scheduler
  (sandbox=False, market data real). La diferencia entre `live` y
  `shadow_live` solo afecta `execution` (shadow NO envia ordenes
  reales), fuera del scheduler. Mismo patron que
  `UniverseScanner._SCANNER_MODE_MAP` (TSK-103 spec section 7.1).

NOTA: el mode-flip mid-iteration via `connector_reinjector(new_mode)`
NO aborta la iteracion actual: la iteracion en curso termina con el
connector viejo, y la SIGUIENTE `run_once()` usa el nuevo. No existe
un early_exit `"connector_injected"`; la rotacion de connector es
asincrona al ciclo de pull.

## 10. Dependencias nuevas

- **Cero deps runtime nuevas**. La libreria standard (`asyncio`,
  `dataclasses`, `enum`, `uuid`, `time`, `datetime`) cubre todo.
- **Tests**: `pytest`, `pytest-asyncio`, `hypothesis`,
  `freezegun`. Todos ya listados en `[dependency-groups].dev`
  del `pyproject.toml` (TSK-008).
- **Justificacion**: el scheduler es una capa de orquestacion
  pura sobre `OHLCVFetcher` (TSK-102) y `OHLCVStore` (TSK-102).
  No introduce libreria externa para no reabrir Fase 1.

## 11. Anti-patrones evitados

- `__init__.py` solo docstring + re-exports (no side-effects).
- `scheduler.py` no importa `execution`, `strategies`, `risk`,
  `portfolio`, `paper`, `observability` (cubierto por test
  `test_cross_layer.py` que parsea AST — mismo patron que
  TSK-103).
- SchedulerResult + PullOutcome + CacheHitDecision son frozen +
  slotted (RNF-6 + inmutabilidad contractual).
- CacheHitPredicate es pure function (no I/O, no state). Tests
  deterministas con `freezegun` para el `clock_fn`.
- Kill-switch check ANTES del cache hit check (orden importa:
  si kill switch esta activo, ni siquiera leemos OHLCVStore).
- Active hours check es PER-PAR, no pre-batch global (RF-2
  explicito: cada par evalua individualmente).
- Mode-flip SOLO via `connector_reinjector(new_mode)` method
  (vetado en code review: `self._connector = ...` directo).
- Pulls secuenciales, no concurrentes (D-TSK104-2; decision
  documentada; cambiar requiere ADR).

## 12. Siguiente fase (handoff a `04-plan.md`)

El plan incremental distribuye la implementacion en 4 tickets
(TSK-104.1..104.4) ordenados por: tipos/protocolos -> cache +
filtros -> orquestador -> instrumentacion/tests. Ver
`docs/specs/TSK-104-scheduler/04-plan.md`.

El alcance NO incluye:
- WebSocket / streaming (pull-based; tick <= minuto).
- Backfill historico (TSK-102 OHLCVStore ya cubre).
- Multi-exchange simultaneo (ADR-0006 fija Binance+CCXT unico).
- Multi-timeframe scheduling (un solo `primary_timeframe` por
  proceso).
