# TSK-860 - Trade Intelligence Feedback Loop: Technical Specification (Command 03)

> Diseno tecnico propuesto para expediente, snapshots, feedback y
> aprendizaje controlado.

---

## 1. Modulos propuestos

| Modulo | Responsabilidad |
| --- | --- |
| `trading_bot.trade_journal.types` | Dataclasses/Pydantic models publicos. |
| `trading_bot.trade_journal.store` | Persistencia SQLite de casos, zonas, snapshots y outcomes. |
| `trading_bot.market_structure.detector` | Detectar soportes, resistencias, bloques, rangos y techos/suelos. |
| `trading_bot.trade_journal.thesis` | Construir `EntryThesis` desde senal, indicadores, estructura y riesgo. |
| `trading_bot.charting.snapshots` | Interfaz para TradingView/local renderer. |
| `trading_bot.feedback.evaluator` | Evaluar cierre, MFE/MAE/R y diagnostico. |
| `trading_bot.feedback.reports` | Exportar casos a JSON/CSV/Markdown. |

## 2. Contratos de datos

```python
@dataclass(frozen=True, slots=True)
class TechnicalZone:
    zone_id: str
    symbol: str
    timeframe: str
    kind: str  # support, resistance, order_block, accumulation, distribution, range_high, range_low
    low: float
    high: float
    strength: float
    detected_at: int
    source: str
    evidence: dict[str, float | str | bool]


@dataclass(frozen=True, slots=True)
class EntryThesis:
    trade_case_id: str
    signal_id: str
    symbol: str
    direction: str  # LONG, SHORT
    entry_price: float
    tp_price: float
    sl_price: float
    timeframe: str
    entry_reason: str
    criteria_met: tuple[str, ...]
    criteria_failed: tuple[str, ...]
    indicators: dict[str, float | str | bool]
    zones: tuple[TechnicalZone, ...]
    confidence_score: float
    created_at: int


@dataclass(frozen=True, slots=True)
class ChartSnapshot:
    snapshot_id: str
    trade_case_id: str
    provider: str  # tradingview, local_renderer
    path: str
    status: str  # ok, fallback, failed, deferred
    captured_at: int | None
    overlays: dict[str, object]


@dataclass(frozen=True, slots=True)
class TradeOutcome:
    trade_case_id: str
    position_id: str
    exit_reason: str
    pnl_net: float
    r_multiple: float
    mfe: float
    mae: float
    win_loss: str
    closed_at: int
    post_trade_diagnosis: tuple[str, ...]
```

## 3. Persistencia

Tablas propuestas:

| Tabla | Proposito |
| --- | --- |
| `trade_cases` | Cabecera del expediente y correlaciones. |
| `entry_theses` | Tesis estructurada de entrada. |
| `technical_zones` | Zonas detectadas por caso. |
| `chart_snapshots` | Imagenes, proveedor, estado y overlays. |
| `trade_outcomes` | Resultado final y diagnostico. |
| `feedback_recommendations` | Recomendaciones no aplicadas automaticamente. |

Reglas:

- SQLite WAL para concurrencia con runtime y frontend.
- IDs estables: `trade_case_id`, `snapshot_id`, `zone_id`.
- No guardar secretos, cookies ni tokens en ninguna tabla.
- Retencion configurable para imagenes pesadas.

## 4. Deteccion de estructura

Version inicial determinista:

- Soporte/resistencia: pivots de swing highs/lows con ventana configurable.
- Techo/suelo: max/min significativos dentro de lookback.
- Order block: ultima vela contraria antes de impulso con desplazamiento ATR.
- Acumulacion/distribucion: rango estrecho + volumen relativo elevado.
- Proximidad: distancia entre entrada y zona en bps y en ATR.

Cada detector devuelve `TechnicalZone` con `strength` en `[0, 1]` y
`evidence` trazable.

## 5. Imagen del grafico

Proveedor preferido:

- `TradingViewSnapshotProvider`, habilitado solo si
  `chart_snapshot.provider=tradingview`.
- Debe usar sesion local controlada o mecanismo autorizado por el usuario.
- Debe respetar timeout y no bloquear la orden.

Fallback:

- `LocalChartSnapshotProvider` usando OHLCV local y overlays equivalentes.
- Debe producir imagen aunque TradingView falle.

Overlays minimos:

- Entry horizontal.
- TP y SL.
- Zonas como rectangulos semitransparentes.
- Marcador de direccion LONG/SHORT.
- Texto compacto con `trade_case_id`, timeframe y fecha.

## 6. Feedback y aprendizaje

El evaluador post-cierre debe:

1. Cargar tesis + fills + OHLCV posterior a entrada.
2. Calcular MFE, MAE, R multiple y PnL neto.
3. Comprobar si el precio respeto o invalido zonas.
4. Etiquetar diagnostico con tags normalizados:
   - `support_respected`
   - `resistance_rejected`
   - `structure_invalidated`
   - `late_entry`
   - `tp_too_close`
   - `sl_too_tight`
   - `spread_cost_high`
   - `trend_against_entry`
   - `multi_timeframe_conflict`
5. Crear recomendacion si detecta patron repetido.

Las recomendaciones no modifican live trading sin ADR o aprobacion.

## 7. Configuracion

Nueva seccion sugerida:

```yaml
trade_journal:
  enabled: true
  storage_url: sqlite:///data/trade_journal.db
  snapshot_dir: data/chart_snapshots
  retention_days: 90

market_structure:
  enabled: true
  primary_timeframe: 1m
  confirmation_timeframes: [5m, 15m]
  swing_window: 5
  min_zone_strength: 0.55

chart_snapshot:
  enabled: true
  provider: tradingview
  fallback_provider: local_renderer
  max_wait_ms: 1500
  defer_if_slow: true

feedback:
  enabled: true
  min_cases_for_recommendation: 20
  auto_apply_recommendations: false
```

## 8. Arquitectura y fronteras

- `strategies` puede leer indicadores y estructura, pero no escribir
  outcomes.
- `risk` puede leer tesis y zonas para vetar/reducir riesgo.
- `execution` solo recibe `trade_case_id` y no decide tesis.
- `feedback` no envia ordenes.
- `charting` no conoce claves del exchange.
- `frontend` consume APIs, no lee SQLite directo.

## 9. Riesgos

| Riesgo | Severidad | Mitigacion |
| --- | --- | --- |
| Captura TradingView bloquea orden. | Alta | Timeout + defer + fallback. |
| Feedback sobreajusta reglas. | Alta | Recomendaciones manuales, no auto-live. |
| Se guardan secretos de sesion. | Critica | Tests + security review + rutas ignored. |
| Imagen no reproduce niveles exactos. | Media | Overlays generados desde mismos datos persistidos. |
| Diagnostico inventa causalidad. | Media | Tags probabilisticos y evidencia numerica. |

