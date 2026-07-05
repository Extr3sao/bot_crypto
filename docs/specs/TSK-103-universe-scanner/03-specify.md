# TSK-103 - Universe Scanner: Technical Specification (Command 03)

> Contratos de tipos, interfaces, errores, configuracion afectada
> y metricas observables del modulo scanner. Metodologia:
> `.ai/commands/03-specify.md`.

---

## 1. Layout de archivos

```
src/trading_bot/scanner/
  __init__.py               # docstring + re-exports publicos
  types.py                  # MarketSnapshot, PairScanResult, FilterOutcome
  protocols.py              # MarketDataSourceProtocol, Filter (Protocol)
  registry.py               # FilterRegistry
  filters.py                # VolumeFilter, SpreadFilter, AtrFilter
  scoring.py                # ranking: spread_norm, vol_norm, atr_in_range_norm
  scanner.py                # UniverseScanner (orquestador)
  exceptions.py             # KillSwitchActiveError, AllPairsFailedWarning
tests/unit/scanner/
  test_filters.py           # filtros individuales parametrizados
  test_registry.py          # registro y composicion
  test_scoring.py           # scoring y tie-break
  test_universe_scanner.py  # orquestador end-to-end con mock MarketDataSource
  test_cross_layer.py       # integridad: scanner no importa otras capas
docs/specs/TSK-103-universe-scanner/
  01-requirements.md        # este spec consume RF/RNF/CL
  02-bdd.md
  03-specify.md             # este archivo
  04-plan.md
  05-tasks.md
```

## 2. Tipos publicos (`src/trading_bot/scanner/types.py`)

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

# Catalogo cerrado de motivos por los que un par queda inactivo.
# Extender requiere ADR por la regla de "tipos canonicos por release".
# 1:1 con el ``Literal[...]`` pineado por tests en
# ``tests/unit/scanner/test_types.py::test_rejection_reason_literal_values``;
# cualquier extension aqui DEBE propagarse al .feature, a los tests, y si
# toca money-risk o invariants de negocio, a una ADR firmada en
# ``tasks/decisions.md``.
RejectionReason = Literal[
    "not_whitelisted",
    "volume_below_threshold",
    "volume_below_threshold_for_live_min_10M",
    "spread_above_threshold",
    "atr_out_of_range",
    "insufficient_history",
    "price_below_threshold",        # si se registra PriceFilter custom
]  # cierre del Literal: 7 valores, fenc-cerrados por test_rejection_reason_literal_values
</invoke>

# Normalizacion de los posibles source.
# True -> par optimo para strategies; False -> motivo en rejection_reason.
@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Salida canonica del scanner. Inmutable. Ver RNF-6."""
    symbol: str
    last_price: float
    volume_24h_usdt: float
    spread_bps: float
    atr_pct: Optional[float]            # None si insufficient_history.
    volatility_pct: Optional[float]    # Idem.
    active: bool
    rejection_reason: Optional[RejectionReason]  # None si active=True.
    timestamp: int                                 # ms since epoch.
    rank_score: float                              # ∈ [0, 1]. 0.0 si active=False.

# Resultado intermedio de un filtro individual. El scanner compone N.
@dataclass(frozen=True, slots=True)
class FilterOutcome:
    passed: bool
    reason: Optional[RejectionReason] = None      # populated solo si passed=False.
```

`__all__ = ["MarketSnapshot", "FilterOutcome", "RejectionReason"]`.

## 3. Protocolos (`src/trading_bot/scanner/protocols.py`)

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable
from trading_bot.market_data.types import OHLCV
from trading_bot.scanner.types import MarketSnapshot, FilterOutcome

@runtime_checkable
class MarketDataSourceProtocol(Protocol):
    """Abstraccion sobre OHLCVFetcher + OHLCVStore (Decision D2).

    Permite al scanner ser unit-testeable sin testnet CCXT: en
    tests inyectamos un FakeMarketDataSource con velas sinteticas.

    Implementacion canonica de produccion:
    ``CCXTMarketDataSource`` (wrapper sobre ``OHLCVFetcher`` +
    ``OHLCVStore``), declarado en este mismo paquete.
    """

    async def fetch_recent(self, symbol: str, limit: int = 100) -> list[OHLCV]:
        ...

    async def fetch_24h_volume_usdt(self, symbol: str) -> float:
        ...

    async def fetch_spread_bps(self, symbol: str) -> float:
        ...


class Filter(Protocol):
    """Filtro abstracto. Una implementacion decide activo/inactivo."""

    name: str

    async def apply(
        self, symbol: str, source: MarketDataSourceProtocol
    ) -> FilterOutcome:
        ...
```

## 4. Registry (`src/trading_bot/scanner/registry.py`)

```python
from collections import OrderedDict
from trading_bot.scanner.protocols import Filter

class FilterRegistry:
    """Registro ordenado de filtros (Decision D4).

    El orden de insercion define el orden de composicion. Cualquier
    nuevo filtro se anade con ``registry.register(name, callable)``
    sin tocar ``UniverseScanner``.
    """

    def __init__(self) -> None:
        self._filters: "OrderedDict[str, Filter]" = OrderedDict()

    def register(self, name: str, f: Filter) -> None:
        if name in self._filters:
            raise ValueError(f"Filter {name!r} ya registrado")
        self._filters[name] = f

    def all(self) -> list[Filter]:
        return list(self._filters.values())

    def __contains__(self, name: str) -> bool:
        return name in self._filters

    def __len__(self) -> int:
        return len(self._filters)
```

## 5. Filtros default (`src/trading_bot/scanner/filters.py`)

Cada filtro implementa `Filter`; encapsula **una sola** decision y
devuelve `FilterOutcome`. NO conoce al `UniverseScanner`.

- `VolumeFilter(min_usdt: float, live_min_usdt: float | None = None)`
  -> rechaza si `volume_24h_usdt < threshold` (modo live endurece).
- `SpreadFilter(max_bps: float)`
  -> rechaza si `spread_bps > max_bps`.
- `AtrFilter(min_pct: float, max_pct: float, min_history: int = 100)`
  -> rechaza si N velas insuficientes (`insufficient_history`) o
     `atr_pct ∉ [min_pct, max_pct]`.

Opcionales (futuro, no en scope TSK-103): `PriceFilter`,
`VolatilityFilter`, `OrderBookImbalanceFilter`.

### 5.1 Riesgos latentes (post-F3, a resolver en F4 o ADR futura)

> **TODO(R1-HIGH) — `VolumeFilter.mode` baked at construction (Decision D1-A)**
> `VolumeFilter` fija ``mode`` en el constructor; F4 (TSK-103.4
> `UniverseScanner`) debe construir **registries per-mode** (uno por
> cada `paper` / `live`) para alternar el endurcimiento del threshold
> sin re-construir filtros individuales en runtime. El
> `FilterRegistry` actual en `registry.py` es mode-agnostic; F4 decide
> si el orquestador mantiene `self._registries: dict[mode, FilterRegistry]`
> o inyecta filtros rebuilt segun `runtime.mode`. Revisitar antes de
> promover a Fase 9 (`live_candidate`).

> **TODO(R5-LATENT) — ATR = media(TR) sobre todas las velas, no ATR-14 fijo**
> `_compute_atr_pct` calcula ATR como media aritmetica de True Ranges
> sobre TODAS las velas que recibe (``mean(TR_1..TR_N)``), NO como
> ATR-Wilder de ventana fija (e.g. ATR-14). Si se quiere ATR-14
> estricto hay que (a) aceptar ``window: int`` opcional en el helper,
> (b) decidir si las N velas vienen ya recortadas de
> `MarketDataSourceProtocol.fetch_recent` o se hace in-place,
> (c) emitir ADR para cambiar la firma publica del helper. Tests
> pinean el ratio ``daily_range=1 sobre last_close=100 => ATR%=2.0``
> (ver `tests/unit/scanner/test_filters.py::test_compute_atr_pct_*`).
> Cualquier inversion del contrato requiere ADR firmada en
> `tasks/decisions.md` antes de modificar tests existentes.

## 6. Scoring (`src/trading_bot/scanner/scoring.py`)

```python
def compute_rank_score(
    spread_bps: float,
    spread_norm_max: float,
    volume_24h_usdt: float,
    volume_norm_max: float,
    atr_pct: float | None,
    atr_optimo: float,
    atr_en_rango: bool,
) -> float:
    """RF-10. Retorna ∈ [0, 1]. Si ``atr_pct`` es None -> 0.0."""
    spread_norm = min(max(spread_bps / spread_norm_max, 0.0), 1.0)
    vol_norm = min(max(volume_24h_usdt / volume_norm_max, 0.0), 1.0)
    atr_term = 1.0 if atr_en_rango and atr_pct is not None else 0.0
    return 0.5 * (1.0 - spread_norm) + 0.3 * vol_norm + 0.2 * atr_term
```

Coeficientes fijos por diseno; cualquier cambio requiere ADR.

## 7. Scanner (`src/trading_bot/scanner/scanner.py`)

```python
class UniverseScanner:
    """Orquestador async (Decision D2). NO importa ccxt/exchange directo."""

    def __init__(
        self,
        *,
        source: MarketDataSourceProtocol,
        registry: FilterRegistry,
        settings: "Settings",                 # de trading_bot.config.settings
        scan_iteration_id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None: ...

    async def run(self) -> list[MarketSnapshot]:
        """Devuelve un snapshot por par enabled, en orden de insercion."""
```

### 7.1 Comportamiento por modo (RF-7)

| `runtime.mode` | Efecto                                                                  |
| -------------- | ----------------------------------------------------------------------- |
| `research`     | Filtros default; loguea todo.                                           |
| `backtest`     | Usa `MarketDataSourceProtocol` con `clock_fn` inyectable (determinista). |
| `paper`        | Filtros default; contadores activos.                                     |
| `live`         | `VolumeFilter.live_min_usdt` endurece a 10M; spread max 20 bps; ATR max 5%. |

## 8. Errores custom (`src/trading_bot/scanner/exceptions.py`)

```python
class ScannerError(Exception):
    """Base para todos los errores especificos del scanner."""

class KillSwitchActiveError(ScannerError):
    """Se eleva desde ``UniverseScanner.run`` cuando el kill_switch
    esta activo. La iteracion devuelve ``[]`` en lugar de elevar este
    error para evitar crash del scheduler; error solo para tests."""

class ConfigurationError(ScannerError):
    """Configuration invalida (e.g. universe sin pares habilitados)."""
```

`AllPairsFailedWarning` se emite como `structlog.warning` (no error)
cuando los 25 pares fallaron por excepciones transitorias (CL-3).

## 9. Configuracion afectada (`config/assets.yaml` + `config/settings.py`)

- `universe.filters.min_24h_volume_usdt`: ya existe en
  `assets.yaml`. `UniverseVolumeFilter` lo lee.
- `universe.filters.max_spread_bps`: ya existe.
- `universe.filters.min_atr_percent`, `max_atr_percent`: ya existen.
- `risk.kill_switch_enabled`: ya existe (`True` por defecto). El
  scanner lo lee en cada `run()` para soportar cambio en runtime.
- `runtime.mode`: ya existe. Define el endurecimiento en live.
- `runtime.scheduler.primary_timeframe`: ya existe en `runtime.yaml`.

**Cero YAML nuevos**. Toda la policy del scanner viene de Settings ya
cargados.

## 10. Metricas observables

- **Logs estructurados** (`structlog` JSON, ADR-0004):
  - `scanner.iteration.started { scan_iteration_id }`.
  - `scanner.iteration.completed { scan_iteration_id, duration_ms,
    pairs_processed, pairs_active, pairs_inactive, scanner_errors,
    early_exit, all_failed }` (MEDIO + round-9 Q6 fix). `early_exit`
    y `all_failed` son ejes ortogonales:
    - `early_exit: Optional[str]`. Valores: `None` (la iteracion
      NO fue abortada por kill_switch / empty_universe; puede haber
      terminado healthy o all_FAILED en CL-3) | `"kill_switch"`
      (operator-initiated pause, RF-4) | `"empty_universe"`
      (sin pares enabled, CL-1).
    - `all_failed: Optional[bool]` SIEMPRE presente. `True` -> la
      iteracion proceso N pares Y NO produjo ningun snapshot activo
      (cubre filter failures Y transient errors per CL-3 sin
      distinguirlos; ver `test_iteration_completed_emits_all_failed_*`).
      `False` -> 1+ snapshot activo emitido. `None` -> aborto temprano
      (kill_switch / empty_universe); field irrelevante en ese branch.
    Truth-table:
    | `early_exit`     | `all_failed` | meaning                              |
    | ---------------- | ------------ | ------------------------------------ |
    | `None`           | `False`      | healthy completion (1+ snapshot)     |
    | `None`           | `True`       | complete pero fallida (CL-3)         |
    | `"kill_switch"`  | `None`       | operator-initiated pause (RF-4)      |
    | `"empty_universe"` | `None`     | sin pares enabled (CL-1)             |
    Single-emission point: `iteration.completed` cierra la iteracion
    siempre. En paths abort, el path-specific event aired ANTES del
    cierre (`started` -> `paused.kill_switch` ->
    `iteration.completed(early_exit='kill_switch')`).
  - `scanner.pair.processed { scan_iteration_id, symbol, active,
    rejection_reason }`.
  - `scanner.paused.kill_switch { scan_iteration_id }`.
  - `scanner.universe.empty { scan_iteration_id }`.
- **Counters atomicos** en `UniverseScanner._CountersState`
  (dataclass mutable interno, NO parte del API publico). El property
  publico `UniverseScanner.counters` retorna fresh
  `CounterSnapshot(pairs_processed, pairs_active, pairs_inactive,
  scanner_errors)` frozen dataclass por acceso (BAJO fix: snapshots
  inmutables; cualquier intento de `snap.pairs_active = 999` raises
  `dataclasses.FrozenInstanceError`).
- **Metricas Prometheus**: NO en TSK-103 (ADR-0003/0004 reserva para
  Fase 8). Se deja TODO en `src/trading_bot/scanner/scanner.py`
  con comentario explicito.

## 11. Dependencias nuevas

- **Cero deps runtime nuevas**. La libreria standard (`asyncio`,
  `dataclasses`, `collections.OrderedDict`, `uuid`) cubre todo.
- **Tests**: `pytest`, `pytest-asyncio`, `hypothesis`. Todos ya
  listados en `[dependency-groups].dev` del `pyproject.toml`
  (TSK-008).
- **Justificacion**: ADR-0005 (sqlite3 directo), ADR-0006 (CCXT). El
  scanner no introduce libreria externa para no reabrir Fase 1.

## 12. Anti-patrones evitados

- `__init__.py` solo docstring + re-exports (no side-effects).
- `scanner.py` no importa `execution`, `strategies`, `risk`,
  `portfolio`, `paper`, `observability` (cubierto por test
  `test_cross_layer.py` que parsea imports).
- Snapshots son frozen + slotted (RNF-6).
- I/O y calculo separados (`source.fetch_*` async vs filtros
  sincronos sobre resultados cacheados in-place).

## 13. Siguiente fase (handoff a `04-plan.md`)

El plan incremental distribuye la implementacion en 5 tickets
(TSK-103.1..103.5) ordenados por: tipos -> filtros -> scoring ->
orquestador -> instrumentacion/tests.
