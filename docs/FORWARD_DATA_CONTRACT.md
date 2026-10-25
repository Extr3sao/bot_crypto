# FORWARD_DATA_CONTRACT — FORWARD-DATA-CONTRACT-V1

Fecha: 2026-09-28. Esquema: `forward-event-v1`. Colector: `FORWARD-WS-COLLECTOR-V1`.

> La versión machine-readable la genera el propio colector desde su código:
> `docs/FORWARD_DATA_CONTRACT.json` (`build_contract_document()`). Este documento
> la explica. Si ambos discreparan, el JSON generado es el correcto, porque no
> puede desviarse de lo que el colector escribe.

## 1. Regla base: RAW EVENTS > DERIVED FEATURES (§19)

Cada registro persistido contiene:

1. la **copia verbatim** del payload del exchange en `raw` (salvo `--drop-raw`);
2. **todas** las magnitudes numéricas como el **string decimal exacto** que envió
   el venue (`"83506.02000000"`), nunca convertidas a `float` en el camino a
   disco;
3. los campos derivados que el colector calcula (`network_delay_ms`,
   `processing_delay_ms`) **además** de sus entradas, jamás en su lugar.

Consecuencia verificable: cualquier feature futura se puede recomputar solo desde
el almacenamiento, y un `0` de profundidad sigue siendo exactamente cero (su
significado es "borra este nivel", no "no sé").

## 2. Campos del evento

Orden canónico, idéntico en todas las filas (lo fija `RawEvent.to_dict()`):

| Campo | Tipo | Significado |
| --- | --- | --- |
| `schema_version` | str | `forward-event-v1` |
| `contract_version` | str | `FORWARD-DATA-CONTRACT-V1` |
| `collector_version` | str | `FORWARD-WS-COLLECTOR-V1` |
| `source` | str | `binance` |
| `market` | str | `spot` \| `perp` — **nunca se mezclan** (§7) |
| `symbol` | str | p.ej. `BTCUSDT` (mayúsculas, validado) |
| `stream` | str | stream de origen, p.ej. `btcusdt@depth@100ms` |
| `event_type` | str | ver §3 |
| `transport` | str | `ws` \| `rest_poll` \| `rest_backfill` |
| `run_id` | str | identificador de la captura |
| `write_seq` | int | contador monótono de proceso asignado por el almacenamiento |
| `connection_id` | int \| null | identificador de la conexión WS |
| `exchange_event_id` | str \| null | id del venue (aggTrade id, update id, funding ts…) |
| `exchange_event_time` | int \| null | **reloj 1**: tiempo del evento, ms desde epoch |
| `receive_time` | int | **reloj 2**: cuando terminó de leerse el frame |
| `process_time` | int | **reloj 3**: cuando se ensambló el registro |
| `network_delay_ms` | int \| null | derivado: `receive_time - exchange_event_time` |
| `processing_delay_ms` | int | derivado: `process_time - receive_time` |
| `clock_skew_ms` | int | desviación registrada cuando hubo violación temporal |
| `sequence` | obj \| null | `{first, last, prev}` ids de secuencia del update |
| `price` | str \| null | precio (string decimal) |
| `quantity` | str \| null | cantidad (string decimal) |
| `aggressor_side` | str \| null | `buy` \| `sell` (quien agrede, no quien hace el mercado) |
| `trade_count` | int \| null | `l - f + 1` de un aggTrade |
| `bid`, `ask` | str \| null | mejor bid/ask |
| `bid_qty`, `ask_qty` | str \| null | tamaño en el mejor bid/ask |
| `bids`, `asks` | list \| null | `[[price, qty], ...]` verbatim (diff o snapshot) |
| `funding_rate` | str \| null | tasa de funding vigente |
| `next_funding_time` | int \| null | próxima liquidación de funding |
| `mark_price`, `index_price` | str \| null | mark e index del perpetuo |
| `open_interest` | str \| null | open interest |
| `open_interest_time` | int \| null | timestamp de OI provisto por el venue |
| `detail` | obj \| null | metadatos específicos del tipo de evento |
| `raw_reference` | str \| null | referencia al origen |
| `raw` | obj \| null | **payload verbatim del exchange** |

En un `agg_trade`, `detail.origin` etiqueta la procedencia de la fila:

| `detail.origin` | Significado |
| --- | --- |
| `ws` | llegó por el stream secuenciado en vivo |
| `agg_trade_backfill` | es el registro del propio venue, obtenido del índice público para cerrar un hueco. `transport` sigue siendo `ws` porque su id es lo que la hace detectable en el stream; la procedencia va en `origin`, no en una etiqueta que rompería la prohibición de presentar REST como alta frecuencia |

No todos los campos aplican a todos los eventos (§8 del encargo); los no
aplicables quedan en `null`. La ausencia **nunca** significa "se perdió": la
pérdida se representa con un registro de hueco (§6).

## 3. Tipos de evento

| `event_type` | Transporte | Lossless | Detección de pérdida |
| --- | --- | --- | --- |
| `agg_trade` | `ws` | sí | id de aggTrade estrictamente +1 por símbolo |
| `depth_diff` | `ws` | sí | cadena `U`/`u` (spot) o `pu` (USDⓈ-M) |
| `book_ticker` | `ws` | sí | id monótono (liveness); no contiguo por diseño del venue |
| `depth_snapshot` | `rest_backfill` | no | ancla de alineación, no aplica |
| `open_interest` | `rest_poll` | no | sondeo periódico; el venue **sí** da timestamp propio |
| `mark_price` | `rest_poll` | no | sondeo periódico; el basis deriva de aquí + spot |
| `funding` | `rest_poll` | no | magnitud periódica por naturaleza del venue |
| `book_checkpoint` | `ws` | no | estado derivado del libro, con su health |
| `heartbeat` | `ws` | no | telemetría del colector |
| `gap` | `ws` | no | **este registro es el registro de pérdida** |
| `violation` | `ws` | no | dato descartado o puesto en cuarentena |
| `lifecycle` | `ws` | no | conexión, desconexión, reinicio, cambio de estado |

Invariante comprobado en tiempo de construcción: un `agg_trade`, `depth_diff` o
`book_ticker` **con transporte distinto de `ws` lanza `ContractError`** (§5, §55).
Es decir, es imposible construir un dataset donde un sondeo REST se presente como
feed de alta frecuencia.

## 4. Los tres relojes (§9, §10)

```text
exchange_event_time   reloj del venue (ms). Puede faltar por diseño:
                      el bookTicker de spot NO publica tiempo de evento.
receive_time          cuando el frame terminó de leerse del socket.
process_time          cuando el registro se ensambló para persistir.
```

Invariantes:

1. `process_time >= receive_time` — si no, `ClockViolation` y el evento no se
   construye.
2. `exchange_event_time <= receive_time + tolerancia` (por defecto 500 ms). Una
   violación **no** se escribe en el stream principal: se escribe un registro
   `violation` con `kind=TEMPORAL_GUARANTEE`, se incrementa
   `clock_violations` y el colector pasa a `FAILED`. Un dataset con eventos
   futuros no puede sostener después un argumento
   `feature_available_time <= decision_time`.
3. `network_delay_ms` puede ser negativo y se conserva tal cual: un reloj del
   venue que retrocede es evidencia, no ruido a suavizar.

## 5. Semántica de secuencia (§13)

```text
spot_update_id
  snapshot con lastUpdateId = L
  descartar u <= L
  el update puente debe cumplir  U <= L+1 <= u
  después, cada update debe cumplir  U == (u anterior) + 1

futures_prev_id
  snapshot con lastUpdateId = L
  descartar u < L
  el update puente debe cumplir  U <= L+1 <= u
  después, cada update debe cumplir  pu == (u anterior)
```

El puente `U <= L+1 <= u` es la unión de las dos formas documentadas por el venue
y es necesaria y suficiente: un buffer que empieza estrictamente después del
snapshot es un hueco real y nunca se puentea.

Veredictos posibles de un diff, exhaustivos y mutuamente excluyentes:
`APPLIED`, `BUFFERED`, `DUPLICATE`, `OUT_OF_ORDER`, `GAP`, `MALFORMED`.

Todos los diffs se persisten **aunque el libro esté inválido**: son evidencia
cruda y no deben perderse por un fallo de estado derivado.

## 6. Registro de hueco (`GapRecord`)

| Campo | Significado |
| --- | --- |
| `gap_id` | identificador estable (`<run_id>:gap:<n>`) que permite seguir el hueco por su ciclo de vida |
| `market`, `symbol`, `event_type` | localización exacta |
| `start_ms`, `end_ms`, `duration_ms` | ventana afectada |
| `reason` | `WS_DISCONNECT`, `WS_CONNECT_FAILED`, `AGG_TRADE_ID_JUMP`, `DEPTH_SEQUENCE_BREAK`, `SNAPSHOT_CANNOT_BRIDGE_BUFFER`, `COLLECTOR_RESTART` |
| `recovered` | **el dato se recuperó** (backfill del índice público). Reconectar no es recuperar |
| `data_lost` | sigue faltando información y no es recuperable |
| `estimated_lost_events` | estimación cuando el venue da identificadores (p.ej. ids de aggTrade saltados); `null` cuando no es estimable, nunca inventada |
| `recovered_events` | cuántos eventos restauró realmente el backfill |
| `remaining_missing` | `estimated_lost_events - recovered_events` cuando el tamaño se pudo medir; `null` si no |
| `status` | `RECOVERED_COMPLETE` \| `RECOVERED_PARTIAL` \| `UNRECOVERABLE` |
| `detail` | explicación legible |

Cada hueco escribe **dos** eventos `gap` en el dataset, con el mismo `gap_id`:
fase `GAP_DETECTED` (antes de intentar nada) y fase `RECOVERY_RESOLVED`. Así la
recuperación es auditable, y un hueco sin fase de resolución es un hueco cuyo
proceso murió durante la reparación — visible, no silencioso.

`CONTINUOUS_DATA` se declara **si y solo si** no existe ningún hueco con
`data_lost = true` y no hubo violaciones temporales ni resnapshots fallidos
(§27). Es una igualdad, no una opinión, y el verificador independiente la
comprueba.

## 7. Fingerprint de partición (`SegmentFingerprint`)

`path`, `row_count`, `first_event_time`, `last_event_time`,
`first_receive_time`, `last_receive_time`, `sha256`, `bytes`,
`schema_version`, `sealed`, `partial_tail`.

`sealed=false` significa que el fichero aún puede crecer; el replay y el informe
de calidad exigen que todo esté sellado al cierre de una captura. `partial_tail`
marca una escritura truncada.

## 8. Derivaciones que se conservan con sus entradas (§18)

| Derivado | Entradas raw que se persisten |
| --- | --- |
| `spread_bps` (checkpoint) | `bid`, `ask`, `bids`/`asks` del libro reconstruido |
| `mid`, `microprice`, `depth_imbalance`, `*_depth_notional` | niveles `bids`/`asks` y sus cantidades |
| `basis_bps` | `mark_price`, `index_price` (perp) y el `bookTicker` de spot |
| `network_delay_ms` | `exchange_event_time`, `receive_time` |
| `taker_imbalance` (bucket 1m) | `price`, `quantity`, `aggressor_side` de cada aggTrade |

Nunca se guarda solo la feature derivada.

## 9. Agregación (§33, §34, §35)

RAW -> 1m con:

```text
buy_volume, sell_volume, buy_notional, sell_notional,
vwap, taker_imbalance, trade_count,
open_interest_last, open_interest_mean, open_interest_samples,
funding_rate_last, mark_price_last, index_price_last, basis_bps_last
```

y, para el libro: `spread_bps_mean/min/max`, `depth_imbalance_mean`,
`usable_ratio` (proporción de checkpoints `HEALTHY`), último `mid`,
`microprice`, profundidad nocional por lado.

Reglas:

* un bucket es `complete` solo si toda su ventana cerrada cae dentro de la
  ventana de captura **y** ningún hueco con pérdida lo solapa;
* `available_at_ms = close_time_ms` siempre (nunca el open);
* `1m -> 5m -> 15m -> 30m` solo desde hijos **completos y alineados**; si falta
  un hijo, el bucket padre no existe.

Un bucket incompleto se emite igualmente, marcado `complete=false`, para que el
hueco sea visible en lugar de desaparecer del dataset.

## 10. Compatibilidad

* El orden y el nombre de los campos son el contrato. Añadir un campo exige
  subir `schema_version`.
* `parse_event()` falla cerrado ante un `event_type`, `market` o `transport`
  desconocido: un segmento corrupto no puede reinterpretarse en silencio.
* Los ficheros son `.jsonl.gz` (gzip, nivel 6 por defecto). Un lector debe
  aceptar además `.jsonl` plano, porque `--no-compress` existe.
* **Identidad lógica de un aggTrade:** `(market, symbol, aggregate_trade_id)`.
  El dataset no contiene dos filas con la misma identidad: una fila reenviada
  (porque el backfill ya la restauró) se cuenta como duplicado detectado y no se
  escribe.
* **Orden lógico:** el orden en fichero es el orden de proceso (`write_seq`), no
  el orden de mercado. Un consumidor que necesite orden de mercado debe ordenar
  por `exchange_event_time` y, dentro del stream de trades, por id.
* **Un root, un run:** un root de dataset pertenece a un run; escribir un run
  nuevo sobre segmentos que ya tienen filas falla cerrado salvo `--resume`
  declarado del mismo run.
