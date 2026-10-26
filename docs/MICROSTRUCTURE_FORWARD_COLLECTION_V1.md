# MICROSTRUCTURE_FORWARD_COLLECTION_V1 — captura forward read-only

Fecha: 2026-09-27. Colector: `scripts/microstructure_collector.py`
(`COLLECTOR_VERSION = FORWARD-COLLECTOR-V1`, `SCHEMA_VERSION = forward-record-v1`).
Informe de smoke: `reports/microstructure-v1/COLLECTION_SMOKE_REPORT.json`.

> **DISCOVERY PLANE ONLY.** Sin API key, sin secretos, sin cuenta, sin órdenes.
> No se conecta al trading decision path. No sustituye al libro histórico que no
> existe (§16): lo **captura hacia delante**.

## 1. Por qué existe

`bookTicker` y `depth` **no tienen endpoint histórico** (SRC-07, DS-03/04 =
`LIVE_ONLY`). OI/basis solo retienen 30 días (SRC-06). Fabricar un libro desde
OHLCV está prohibido (§16). Por tanto la única vía honesta para M-02 y para un
modelo de fill es **recoger datos forward**.

## 2. Streams capturados

| kind | endpoint | campos clave | exchange event ts | sequence id |
| --- | --- | --- | --- | --- |
| `bookTicker` | `/api/v3/ticker/bookTicker` | bid, ask, bid_qty, ask_qty, mid, spread_bps, crossed | ✗ (no existe) | — |
| `depth` | `/api/v3/depth?limit=N` | bids[], asks[], last_update_id | ✗ | `last_update_id` |
| `aggTrade` | `/api/v3/aggTrades?limit=100` | price, qty, is_buyer_maker, aggressor, agg_trade_id, first/last_trade_id | ✓ | `agg_trade_id` |
| `premiumIndex` | `/fapi/v1/premiumIndex` | mark, index, last_funding_rate, next_funding_time | ✓ | — |

## 3. Tres relojes por registro

```text
exchange_event_time   cuándo ocurrió en el exchange (null si no existe)
receive_time          cuándo lo observó el colector
process_time          cuándo se escribió la línea
```

Regla dura: `data_time <= observed_time`. Un registro sin
`exchange_event_time` **lo dice explícitamente** (`null`), no lo inventa.

## 4. Persistencia append-only y manifest

Cada poll escribe líneas JSONL (una por registro) sin reescribir nada. El
manifest derivado contiene:

```text
collector_version · schema_version · file · sha256 · bytes · records
by_kind · by_symbol
coverage (start/end receive_time, ISO, duration_s)
duplicates · out_of_order
gaps[]              (por kind+símbolo: n, worst_gap_ms, stale_periods)
sequence_gaps[]     (aggTrade: n_ids, holes, worst_step)
depth_sequence_regressions[]
records_with_exchange_event_time
```

El manifest es **derivable**: se puede reconstruir del JSONL, no es autoridad.

## 5. Detecciones de integridad

| detector | qué reporta |
| --- | --- |
| duplicados | registros con misma (kind, symbol, receive_time, id) |
| orden | `receive_time` regresivo |
| gaps | huecos > `STALE_AFTER_S = 15 s` por kind+símbolo |
| secuencia | saltos en `agg_trade_id` (`holes`, `worst_step`) |
| regresión de secuencia | `last_update_id` que decrece en `depth` |
| libro cruzado | `crossed = bid >= ask` marcado en el propio registro |

Fail-closed: un error de red se persiste como registro `{"kind": "error"}`; no
se silencia ni se repara.

## 6. Smoke collection — resultado real

Ejecutado el 2026-09-27 con `--smoke --duration 40` (BTCUSDT, ETHUSDT,
SOLUSDT, depth 20):

| métrica | valor |
| --- | --- |
| registros | 5,214 |
| `bookTicker` / `depth` / `aggTrade` / `premiumIndex` | 51 / 51 / 5,100 / 12 |
| duplicados | 0 |
| out-of-order | 0 |
| gaps > 15 s | 0 |
| cobertura | 46.185 s |
| registros con exchange event time | 5,112 |
| SHA-256 del JSONL | `d82023d84d31bf16…` |

### Limitación medida (declarada, no ocultada)

`sequence_gaps` detectó **1 hueco** en `aggTrade` de BTCUSDT con `worst_step =
19`. La causa es estructural: `GET /api/v3/aggTrades?limit=100` devuelve los 100
prints **más recientes**, así que en un burst de >100 prints entre dos polls, el
muestreo REST **se salta** prints. Consecuencia honesta:

* la captura REST a 1 s **no es gap-free** en BTC;
* una captura forward de calidad requiere el stream WS `@aggTrade` (y `@depth`
  con reconciliación diff) para no perder prints;
* ninguna métrica de fill debe construirse sobre REST polling sin declarar este
  límite.

`depth` no mostró regresiones de `last_update_id` (0/17 en cada símbolo), pero
los snapshots REST son **polls independientes**, no una secuencia diff: no hay
reconciliación de libro. Queda escrito en `known_limitation` del manifest.

## 7. Estado y siguiente paso

* El colector queda **preparado para ejecución continuada**; en esta fase solo
  se ejecutó un smoke corto (§63: no se declara ningún resultado de datos que
  todavía no existen).
* Para que M-02 (book imbalance) y el modelo de fill sean testeables hace falta
  una campaña de varios días, preferiblemente por WebSocket.
* **Ninguna** estrategia maker puede promocionarse hasta que ese dataset
  alimente `FillEvidence` (ver `EXECUTION_MODEL_V1.md`).
