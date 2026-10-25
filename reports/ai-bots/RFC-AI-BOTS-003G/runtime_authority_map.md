# Runtime authority map — RFC-TAP-AI-BOTS-003G

Una sola autoridad por invariante. Si dos piezas pudieran decidir lo mismo, se nombra la que
manda y la otra se declara derivada. Los hashes son los que la sesión graba en
`SESSION_START.json → runtime_sha256` y el verificador vuelve a calcular.

## 1. Quién manda en cada pregunta

| Pregunta | Autoridad | Derivado / consumidor | Prueba |
| --- | --- | --- | --- |
| ¿Qué minuto existe y cuándo se recibió? | `market_data/minute_collector.py` (`MinuteBar`, `MinuteStore`) | `vision/quotes.py` (feed), `vision/prospective.py` | `tests/unit/market_data/test_minute_collector.py` |
| ¿Está cerrada la vela? | `MinuteBar.__post_init__` (reloj del exchange) | `formación` filtrada en `_parse_page` | `test_a_forming_minute_is_never_stored` |
| ¿Hay hueco? ¿Se puede cruzar? | `MinuteCollector._fill_forward` + `gaps()` | `MinuteBarQuoteFeed.prove_coverage` para el carril | `test_a_gap_is_detected_and_filled_before_the_later_minute_is_stored` |
| ¿Está fresca la serie? | `MinuteCollector.health_at` (`OK/GAP/STALE/CLOCK_SKEW/BLOCKED`) | `ProspectiveSession` (bloquea el ciclo) | `test_a_stale_feed_is_not_tradeable`, `test_a_clock_skew_blocks…` |
| ¿Qué instante puede decidir? | `vision/clock.py` (`information_ms`) | `VisionLane._decide` | `tests/unit/vision/test_causal_clock.py` |
| ¿Puede una vela de warm-up decidir? | `VisionLane.decision_from_ms` | `ProspectiveSession` lo fija al inicio | `test_decisions_begin_when_the_session_begins…` |
| ¿A qué precio se rellena? | `vision/execution.py` (`Quote`, `schedule`, `QuoteRange`) + `subbar_entries` | `VisionLane._execute` | `tests/unit/vision/test_causal_execution.py`, `test_subbar_execution.py` |
| ¿Qué parte de la vela de entrada ve el stop? | `VisionLane._entry_bar_range` | `PaperBroker.check_positions_ohlc` | `test_open_phase_causality.py`, verificador 003G |
| ¿Se aprueba riesgo? | `risk/manager.py` (sin cambios) | `VisionLane._decide` | suites `tests/unit/risk` |
| ¿Cómo se ejecuta y cuesta? | `paper/broker.py` (sin cambios) | ledger `FILL`/`CLOSE` | `tests/unit/paper` |
| ¿Queda traza inalterable? | `vision/ledger.py` (cadena sha256, escritor único) | `STREAM.jsonl`, un ledger por ciclo | `test_ledgers_are_chained`, verificador |
| ¿Qué código corrió? | `prospective.runtime_hashes` | `SESSION_START.json` | verificador `tested_runtime_equals_used_runtime` |
| ¿Puede haber LIVE? | `ProspectiveConfig` + `run()` (sin cliente de órdenes) | verificador estático | `test_live_mode_is_refused…`, `no_live_order_route_in_runtime` |

## 2. Fronteras que NO se cruzan

- **`config/risk.yaml`**: se lee (`load_settings`) y se copia al ledger `RUN`; nunca se escribe.
  Hash registrado en `RUN_META.json`.
- **`risk/manager.py` y `paper/broker.py`**: no se modifican en 003G. El hash que la sesión
  graba debe coincidir con el fichero del árbol; si alguien los cambia, el verificador falla.
- **Proveedor de modelo**: `paper-script` es un guion determinista. `REAL_MODEL_CALLED=false`.
  No hay credencial en disco ni en el entorno de la sesión.
- **Ruta de orden**: no existe. El verificador busca `/api/v3/order`, `create_order(`,
  `place_order(`, `submit_order(` en los once ficheros del runtime y falla si aparecen.

## 3. Cadena de autoridad de una operación

```text
Binance /api/v3/klines                 (origen: open, o/h/l/c/v)
        │  server_time_ms, received_at_ms
        ▼
MinuteCollector  ── valida cerrada, orden, duplicado, gap ──► MinuteStore (JSONL + sha256)
        │  cola contigua
        ▼
aggregate_complete (sólo grupos con sus 5 minutos)  ──► Barras de 5 m
        │
        ▼
VisionLane(decision_from_ms, quote_feed, subbar_entries=True)
        │  clock.information_ms = close + data_delay
        ▼
RiskManager.check_signal  ──►  PaperBroker.fill  ──►  ledger (DECISION→…→CLOSE)
        │
        ▼
STREAM.jsonl (CYCLE: data_time, decision_time, hashes) ──► verificador independiente
```

## 4. Autoridad de la medición

| Cifra publicada | Se recalcula desde | Quién la recalcula |
| --- | --- | --- |
| `series_sha256` por ciclo | minutos crudos del ciclo | `scripts/ai_bots_003g_verify.py` |
| `fills`, `closed_trades`, `net` | ledger del último ciclo | idem |
| precio de relleno | apertura de 1 m en `quote_ts_ms` | idem |
| rango post-relleno | minutos estrictamente posteriores | idem |
| `data_time <= decision_time` | fila `CYCLE` | idem |
| identidad de costes | fila `CLOSE` | idem |
| runtime | hashes de los 11 ficheros | idem |

Ninguna cifra del informe se copia de un run anterior. El comparador CURRENT/PROPOSED
reconstruye la serie y **aborta** si su hash no coincide con el publicado.
