"""Scanner universe multi-activo.

Fase objetivo: 3 (mover a Fase 1 con TSK-103 dentro de sprint-002).
Ticket: ``TSK-103`` (per ``tasks/sprint-002.md`` Pri 5 y
``tasks/backlog.md``).

Responsabilidades (TSK-103.4, ticket posterior):
- Iterar los pares USDT configurados en ``config/assets.yaml``.
- Aplicar filtros de volumen 24h, spread y ATR/volatilidad.
- Producir ``MarketSnapshot`` para el motor de estrategias (Fase 4).
- Manejar errores transitorios sin abortar el loop.

Reglas (pinea contra ``docs/architecture.md`` §11 + §14):
- Cero dependencias cross-layer: el scanner NO importa
  ``exchange.*``, ``execution.*``, ``strategies.*``, ``risk.*``,
  ``portfolio.*``, ``indicators.*``. Cobertura via test AST
  enforcement (TSK-103.4.9).
- Tipos frozen + slots (RNF-6); ver ``types.py``.
- ``__init__.py`` solo docstring + re-exports; cero side-effects.

Subpaquetes:
- ``types``: ``MarketSnapshot``, ``FilterOutcome``, ``RejectionReason``.
- ``protocols``: ``MarketDataSourceProtocol`` (runtime_checkable),
  ``Filter`` (Protocol estructural).
- ``exceptions``: ``ScannerError``, ``KillSwitchActiveError``,
  ``ConfigurationError``.
- ``registry``: ``FilterRegistry`` (TSK-103.2).
- ``filters``: ``VolumeFilter`` / ``SpreadFilter`` / ``AtrFilter``
  + ``VALID_MODES`` (TSK-103.2).
- ``scoring``: ``compute_rank_score`` (formula cerrada ADR-locked) +
  coefs ``SPREAD_WEIGHT`` / ``VOLUME_WEIGHT`` / ``ATR_WEIGHT`` (TSK-103.3).
- ``mode_filters``: ``build_filter_set_per_mode`` (helper que construye
  4 ``FilterRegistry`` paralelos consumiendo ``FilterBounds`` como
  single source of truth; post-P1 fix).
- ``scanner``: ``UniverseScanner`` orquestador async + ``FilterBounds``
  + ``ScoreNormalizers`` + ``_CachingSource`` + constantes live
  ``LIVE_MIN_VOLUME_USDT`` / ``LIVE_MAX_SPREAD_BPS`` / ``LIVE_MAX_ATR_PERCENT``
  para hardening (TSK-103.4).

Estado del paquete:
- TSK-103.1 (F1, mergeado): tipos + protocolos + excepciones cerrados.
- TSK-103.2 (F2, mergeado): ``FilterRegistry`` + 3 filtros default.
- TSK-103.3 (F3, mergeado): ``compute_rank_score`` + property tests.
- TSK-103.4 (F4, implementado en local, pendiente review round-2 post
  P0/P1 fixes del code-reviewer-minimax-m3):
  ``UniverseScanner`` orquestador + ``build_filter_set_per_mode`` (single
  source of truth via ``FilterBounds``) + cross-layer enforcement via
  AST. 21 sentinels + 3 cross-layer + 6 builder.
  Decisiones del thinker aplicadas + veredictos del reviewer
  turn-1 corregidos (pairs_processed semantics + FilterRegistry typing +
  FilterBounds consolidation).
- TSK-103.5 (F5, en cola): wiring con Settings + 17 escenarios BDD +
  ADR-0013 + 6 quality gates. Bloqueante para merge depender de F4.
"""

from trading_bot.scanner.exceptions import (
    ConfigurationError,
    KillSwitchActiveError,
    ScannerError,
)
from trading_bot.scanner.filters import (
    AtrFilter,
    SpreadFilter,
    VALID_MODES,
    VolumeFilter,
    _compute_atr_pct,
)
from trading_bot.scanner.mode_filters import build_filter_set_per_mode
from trading_bot.scanner.scanner import (
    CounterSnapshot,
    LIVE_MAX_ATR_PERCENT,
    LIVE_MAX_SPREAD_BPS,
    LIVE_MIN_VOLUME_USDT,
    FilterBounds,
    ScoreNormalizers,
    UniverseScanner,
)
from trading_bot.scanner.scoring import (
    ATR_WEIGHT,
    SPREAD_WEIGHT,
    VOLUME_WEIGHT,
    compute_rank_score,
)
from trading_bot.scanner.protocols import (
    Filter,
    MarketDataSourceProtocol,
)
from trading_bot.scanner.registry import FilterRegistry
from trading_bot.scanner.types import (
    FilterOutcome,
    MarketSnapshot,
    RejectionReason,
)

__all__ = [
    "ATR_WEIGHT",
    "AtrFilter",
    "ConfigurationError",
    "CounterSnapshot",
    "Filter",
    "FilterBounds",
    "FilterOutcome",
    "FilterRegistry",
    "KillSwitchActiveError",
    "LIVE_MAX_ATR_PERCENT",
    "LIVE_MAX_SPREAD_BPS",
    "LIVE_MIN_VOLUME_USDT",
    "MarketDataSourceProtocol",
    "MarketSnapshot",
    "RejectionReason",
    "SPREAD_WEIGHT",
    "ScannerError",
    "ScoreNormalizers",
    "SpreadFilter",
    "UniverseScanner",
    "VALID_MODES",
    "VOLUME_WEIGHT",
    "VolumeFilter",
    "_compute_atr_pct",
    "build_filter_set_per_mode",
    "compute_rank_score",
]
