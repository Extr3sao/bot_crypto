# TSK-200 - Motor de indicadores: Technical Specification (Command 03)

> Contratos de tipos, interfaces, errores, configuracion afectada
> y metricas observables del modulo indicators. Metodologia:
> `.ai/commands/03-specify.md`.

---

## 1. Layout de archivos

```
src/trading_bot/indicators/
  __init__.py               # docstring + re-exports publicos
  types.py                  # IndicatorOutput, InsufficientHistoryError, IndicatorParams
  protocols.py              # Indicator (Protocol, runtime_checkable)
  registry.py               # IndicatorRegistry
  cache.py                  # IndicatorCache + IndicatorCacheStats + RegistryFrozenError
  exceptions.py             # RegistryFrozenError, InsufficientHistoryError, ParamsHashError
  ema.py                    # EmaIndicator (1 indicador de referencia; los demas entran TSK-201..203)
tests/unit/indicators/
  __init__.py               # vacio
  test_types.py             # IndicatorOutput frozen+slots, InsufficientHistoryError
  test_protocols.py         # Indicator Protocol runtime_checkable
  test_registry.py          # IndicatorRegistry register/freeze/all/len
  test_cache.py             # IndicatorCache hit/miss/eviction/invalidate; threading test
  test_ema.py               # EmaIndicator end-to-end (1 indicator de referencia)
  test_cross_layer.py       # AST parse: indicators/ no importa capas vedadas
  test_params_hash.py       # params_hash invariancia al orden de keys + TypeError defensivo
docs/specs/TSK-200-indicators-interface/
  01-requirements.md        # este spec consume RF/RNF/CL
  02-bdd.md
  03-specify.md             # este archivo
  04-plan.md
  05-tasks.md
bdd/features/indicators.feature   # 17 escenarios nuevos
```

## 2. Tipos publicos (`src/trading_bot/indicators/types.py`)

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


# Tipo canonico para los parametros de un indicator.
# NO es structural: debe ser `Mapping[str, Any]`-compatible y serializable
# a JSON determinista. Incumplimiento -> TypeError defensivo en el
# `params_hash` builder (cubierto por CL-4).
IndicatorParams = Mapping[str, float | int | str | bool | None]


@dataclass(frozen=True, slots=True)
class IndicatorOutput:
    """Salida canonica de un indicator. Inmutable. Ver RNF-6.

    `values` es un `Mapping[str, float]` que permite multi-value
    outputs sin cambiar la firma del Protocol (e.g., MACD retorna
    `{"macd": 0.5, "signal": 0.4, "hist": 0.1}`). Cualquier valor
    no-finito (NaN/inf) raise ValueError en el constructor del
    dataclass (RF-2 + CL pine contract).

    `meta` es opcional: metadatos no-numericos como
    `{"period": 9, "source": "close"}` para observabilidad.
    """

    values: Mapping[str, float]
    meta: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for k, v in self.values.items():
            if not isinstance(v, (int, float)):
                raise TypeError(
                    f"IndicatorOutput.values[{k!r}] debe ser float; got {type(v).__name__}"
                )
            import math
            if isinstance(v, float) and not math.isfinite(v):
                raise ValueError(
                    f"IndicatorOutput.values[{k!r}] debe ser finito; got {v!r}"
                )


__all__ = ["IndicatorOutput", "IndicatorParams"]
```

> El constructor valida NaN/inf al construir el dataclass; `compute()`
> que retorne `IndicatorOutput` con valores no-finitos falla ANTES de
> salir del indicator (cubierto por RF-2 + escenario
> `values[k] no acepta NaN/inf`).

## 3. Protocolos (`src/trading_bot/indicators/protocols.py`)

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable
from trading_bot.market_data.types import OHLCV
from trading_bot.indicators.types import IndicatorOutput, IndicatorParams


@runtime_checkable
class Indicator(Protocol):
    """Contrato publico de un indicator (duck typing estructural).

    Toda implementacion debe:
    - Exponer `.name: str` (unico dentro del registry).
    - Exponer `.compute(ohlcv, params) -> IndicatorOutput`.

    El `RuntimeCheckable` permite isinstance check durante tests
    (cubierto por RF-11 via `test_protocols.py`) sin acoplar a una
    clase base concreta (elegido via ADR-0013-Fase2).
    """

    name: str

    def compute(
        self,
        ohlcv: list[OHLCV],
        params: IndicatorParams,
    ) -> IndicatorOutput:
        ...
```

## 4. Registry (`src/trading_bot/indicators/registry.py`)

```python
from collections import OrderedDict
from trading_bot.indicators.protocols import Indicator
from trading_bot.indicators.exceptions import RegistryFrozenError


class IndicatorRegistry:
    """Registro ordenado, freeze-friendly (mirror de FilterRegistry de F2).

    - `register(name, indicator)`: anyade uno nuevo. Duplicado -> ValueError.
    - `freeze()`: cierra el registro. `register()` post-freeze -> RegistryFrozenError.
    - `all()`: devuelve la lista de indicadores en orden de insercion.
    - `get(name)`: devuelve el indicator registrado bajo `name`.
    - `__contains__`, `__len__`: operadores estandar.

    NOTA: a diferencia de FilterRegistry de F2 (que NO tiene `freeze()`
    porque F4 evaluara registries per-mode sin re-registro), el
    `IndicatorRegistry` **SI** tiene `freeze()` para pinear el
    contrato de Fase 2: el catalogo de indicators se carga al
    arranque de `trading_bot.app` desde `IndicatorsConfig` y NO se
    espera mutacion runtime. Cualquier extension requiere un
    restart (cubierto por RF-12 + ADR-0013).
    """

    def __init__(self) -> None:
        self._indicators: OrderedDict[str, Indicator] = OrderedDict()
        self._frozen: bool = False

    def register(self, name: str, indicator: Indicator) -> None:
        if self._frozen:
            raise RegistryFrozenError(
                f"IndicatorRegistry esta frozen; cannot register {name!r}"
            )
        if name in self._indicators:
            raise ValueError(
                f"name {name!r} ya registrado en IndicatorRegistry"
            )
        if not isinstance(indicator, Indicator):
            raise TypeError(
                f"indicator debe satisfacer Indicator Protocol; got {type(indicator).__name__}"
            )
        self._indicators[name] = indicator

    def freeze(self) -> None:
        # Idempotente: freeze() dos veces = silencioso OK (CL-7).
        self._frozen = True

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def all(self) -> list[Indicator]:
        return list(self._indicators.values())

    def get(self, name: str) -> Indicator:
        if name not in self._indicators:
            raise KeyError(f"Indicator {name!r} no registrado")
        return self._indicators[name]

    def __contains__(self, name: str) -> bool:
        return name in self._indicators

    def __len__(self) -> int:
        return len(self._indicators)
```

## 5. Cache (`src/trading_bot/indicators/cache.py`)

```python
from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndicatorCacheStats:
    """Snapshot inmutable de counters del cache (mirror de CounterSnapshot F2)."""
    hits: int
    misses: int
    evictions: int
    size: int


def compute_params_hash(params: Mapping[str, Any]) -> int:
    """Hash determinista de params (RNF-5).

    Usa `json.dumps(..., sort_keys=True, default=str)` para invariance
    al orden de keys. Valores no-JSON-serializables (e.g., callable)
    raise TypeError defensivo (CL-4).
    """
    try:
        canonical = json.dumps(dict(params), sort_keys=True, default=str)
    except TypeError as exc:
        raise TypeError(
            f"params_hash: params no JSON-serializable: {exc}"
        ) from exc
    return hash(canonical)


class IndicatorCache:
    """LRU cache para resultados de `compute()`, keyed por
    `(name, params_hash, last_candle_ts)`.

    - Hit iff las 3 componentes matchean (RF-5).
    - `invalidate_on_new_candle(ts)` purga entries con mismo
      `(name, params_hash)` y `ts < new_ts` (RF-6).
    - `max_entries` (default 256) limita LRU eviction (RNF-3).
    - `threading.Lock` per-instance protege read/write (RNF-4).
    """

    def __init__(self, max_entries: int = 256) -> None:
        self._cache: OrderedDict[tuple[str, int, int], IndicatorOutput] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

        # Counters mutables internos; accesibles via `stats()` (frozen snapshot).
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get_or_compute(
        self,
        name: str,
        params: IndicatorParams,
        last_candle_ts: int,
        compute_fn: Callable[[], IndicatorOutput],
    ) -> IndicatorOutput:
        params_hash_value = compute_params_hash(params)
        key = (name, params_hash_value, last_candle_ts)
        with self._lock:
            if key in self._cache:
                self._hits += 1
                # LRU: mover al final (mas reciente).
                self._cache.move_to_end(key)
                return self._cache[key]
            self._misses += 1
        # Compute FUERA del lock para no bloquear reads (CL-8).
        result = compute_fn()
        with self._lock:
            if key in self._cache:
                # Race: otro thread gano entre `miss` y `compute`.
                # Mantenemos el resultado anaderlo para no desperdiciar.
                # Selector: stick con el entry que ya esta.
                self._cache.move_to_end(key)
                return self._cache[key]
            self._cache[key] = result
            if len(self._cache) > self._max:
                self._cache.popitem(last=False)  # FIFO eviction (oldest).
                self._evictions += 1
            return result

    def invalidate_on_new_candle(self, new_ts: int) -> int:
        """Purga entries con `ts < new_ts` (RF-6). Retorna count purgados."""
        purged = 0
        with self._lock:
            keys_to_purge = [k for k in list(self._cache.keys()) if k[2] < new_ts]
            for k in keys_to_purge:
                del self._cache[k]
                purged += 1
        return purged

    def stats(self) -> IndicatorCacheStats:
        with self._lock:
            return IndicatorCacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                size=len(self._cache),
            )

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
```

> **NOTA threading (RNF-4 + CL-8)**: el lock protege el `OrderedDict`
> + los counters. El `compute_fn()` se invoca FUERA del lock para no
> serializar computations lentas; el race condition post-compute se
> resuelve con un re-check + `move_to_end` (stick con el entry que ya
> esta si gano otro thread, evitando overwrites).

## 6. Indicator de referencia (`src/trading_bot/indicators/ema.py`)

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmaIndicator:
    """Indicator EMA de referencia (TSK-200 incluye solo este; el resto entra TSK-201..203).

    Implementacion pura Python (NO numpy por ADR-0012; el calculo
    EMA es trivial sin numpy y mantiene la dep count plana).

    Formula: EMA_t = (close_t - EMA_{t-1}) * k + EMA_{t-1}
    donde k = 2 / (period + 1), EMA_0 = close[0].

    El indicador arranca con close[0] (semilla) y suaviza el resto.
    Output: `IndicatorOutput(values={"ema": float}, meta={"period": int})`.
    """

    name: str = "ema"

    def compute(
        self,
        ohlcv: list[OHLCV],
        params: IndicatorParams,
    ) -> IndicatorOutput:
        if not isinstance(params, Mapping):
            raise TypeError("params debe ser Mapping[str, Any]")
        period = int(params.get("period", 9))  # default 9 per FAST/SLOW en config
        if not ohlcv:
            raise InsufficientHistoryError(required=2, got=0)
        if len(ohlcv) < max(period, 2):
            raise InsufficientHistoryError(required=period, got=len(ohlcv))
        k = 2.0 / (period + 1)
        ema = float(ohlcv[0].close)  # semilla
        for candle in ohlcv[1:]:
            ema = (float(candle.close) - ema) * k + ema
        return IndicatorOutput(
            values={"ema": ema},
            meta={"period": str(period)},
        )
```

## 7. Errores custom (`src/trading_bot/indicators/exceptions.py`)

```python
class IndicatorError(Exception):
    """Base para todos los errores especificos del motor de indicators."""


class RegistryFrozenError(IndicatorError):
    """Levantado cuando `register()` se llama despues de `freeze()`.

    El catalogo de indicators se considera inmutable post-arranque;
    cualquier modificacion runtime requiere restart del process.
    """


class InsufficientHistoryError(IndicatorError):
    """Levantado cuando `len(ohlcv) < required` para el indicator dado.

    Args:
        required: numero minimo de velas necesarias para el calculo.
        got: numero de velas realmente disponibles.
    """

    def __init__(self, required: int, got: int) -> None:
        self.required = required
        self.got = got
        super().__init__(
            f"insufficient_history: required {required} velas, got {got}"
        )


class ParamsHashError(IndicatorError):
    """Levantado cuando `params` no es JSON-serializable.

    Wrappea el TypeError de `json.dumps` para mantener jerarquia
    propia del motor.
    """
```

`__all__ = ["IndicatorError", "RegistryFrozenError",
"InsufficientHistoryError", "ParamsHashError"]`

## 8. Configuracion afectada (`config/indicators.yaml` + `src/trading_bot/config/indicators.py`)

- `indicators.indicators:<name>`: ya existe. El `IndicatorRegistry`
  consume directamente `IndicatorsConfig.indicators` (catalog).
  Cada entry declara `type`, `enabled`, `params`.
- `indicators.global.require_min_candles`: ya existe (default 100).
  El orchestrator (Fase 4) enforza este umbral para `runtime.mode=live`.
- `indicators.global.cache_results`: ya existe (default `true`).
  Honrado por el orchestrator al instanciar el cache.
- `indicators.global.invalidate_on_new_candle`: ya existe
  (default `true`). Honrado por el orchestrator al invocar
  `IndicatorCache.invalidate_on_new_candle` despues de cada scan.

**Importacion en el motor**: el `EmaIndicator` se materializa desde
`IndicatorsConfig.indicators["ema_*"]` en el app entrypoint; el resto
de los indicadores (TSK-201..203) siguen el mismo patron.

## 9. Metricas observables

- **Logs estructurados** (`structlog` JSON, ADR-0004):
  - `indicator.compute.completed { name, params_hash, duration_ms,
    cache_hit }`.
  - `indicator.cache.invalidated { purged_count, new_ts }`.
  - `indicator.cache.ts_decreasing { attempted_ts, last_ts }`
    (CL-5).
  - `indicator.insufficient_history { name, required, got }`
    (CL-1/CL-2).
- **Counters atomicos** accesibles via
  `IndicatorCache.stats() -> IndicatorCacheStats` (frozen dataclass
  snapshot, mirror de `CounterSnapshot` F2).
- **Metricas Prometheus**: NO en TSK-200 (ADR-0003/0004 reserva
  para Fase 8). Dejado como TODO en `cache.py`.

## 10. Dependencias nuevas

- **Cero deps runtime nuevas**. La libreria standard (`dataclasses`,
  `collections.OrderedDict`, `threading`, `json`, `hashlib` indirecto
  via `hash()`) cubre todo. `math.isfinite` es stdlib.
- **Tests**: `pytest`, `pytest-asyncio`, `hypothesis`. Todos ya
  listados en `[dependency-groups].dev` del `pyproject.toml`
  (TSK-008). Sin nuevas dependencias.
- **Justificacion**: ADR-0005 (sqlite3), ADR-0006 (CCXT). El motor
  no introduce libreria externa para no reabrir Fase 1 y mantener
  `numpy<2.1` lockeado per ADR-0012.

## 11. Anti-patrones evitados

- `__init__.py` solo docstring + re-exports (no side-effects).
- `indicators/` NO importa `strategies`, `execution`, `risk`,
  `portfolio`, `exchange`, `scanner` cruzado (cubierto por test
  `test_cross_layer.py` que parsea imports via AST).
- `IndicatorOutput` es frozen+slotted + valida NaN/inf (RNF-6 + RF-2).
- `IndicatorCache` no expone mutacion directa; stats via snapshot
  frozen.
- Sin estados globales mutables (RNF-1 determinismo): el cache es
  per-instance; orchestrator lo comparte via DI.

## 12. Siguiente fase (handoff a `04-plan.md`)

El plan incremental distribuye la implementacion en F1..F5 ordenados
por reversibilidad y verifica-antes-de-avanzar.
