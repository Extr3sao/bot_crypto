# source_registry.md — fuentes oficiales (§6, §51)

> Registro de fuentes usadas para fijar hechos de exchange (fees, reglas
> maker/taker, APIs de market data, funding, basis, premium, order book,
> rate limits, disponibilidad histórica). Cada claim que depende de una
> característica del exchange se apoya aquí.
>
> Fecha de consulta: **2026-09-26** (reloj local `Sat Sep 26 RDT 2026`).
> Nada de este registro se modifica tras ver resultados: los claims se fijan
> antes de ejecutar los experimentos.

## Fuentes

### SRC-01 — Binance Spot trading fee schedule
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-01 |
| URL | https://www.binance.com/en/fee/trading |
| SOURCE_TYPE | official exchange fee page |
| DATE | consultada 2026-09-26 |
| PRODUCT | Binance Spot |
| CLAIM | Regular User (VIP0, 30d volume < 1,000,000 USD, 0 BNB balance): **maker 0.100% / taker 0.100%** (10 bps por lado). Con pago de fee en BNB (25% descuento): **0.075% / 0.075%** (7.5 bps). VIP1 (≥ 1,000,000 USD, ≥ 5 BNB): maker 0.090% / taker 0.100%. |
| EVIDENCE | Snippet indexado de la página oficial: `Regular User · < 1,000,000 USD · ≥ 0 BNB · 0.100% / 0.100% · 0.07500% / 0.07500%`; `VIP 1 · ≥ 1,000,000 USD · ≥ 5 BNB · 0.090% / 0.100%`. |
| RELIABILITY | HIGH (fuente oficial) |
| DECISION | El fee taker de baseline para el proyecto debe ser **10 bps/lado**, no 5 bps. El modelo de 5 bps/lado es OPTIMISTIC. |

### SRC-02 — Binance USDⓈ-M Futures fee schedule
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-02 |
| URL | https://www.binance.com/en/fee/futureFee |
| SOURCE_TYPE | official exchange fee page |
| DATE | consultada 2026-09-26 |
| PRODUCT | Binance USDⓈ-M Perpetual Futures |
| CLAIM | Tarifas USDⓈ-M estándar: maker ~0.02%, taker ~0.05% (VIP0, según programa vigente); promociones temporales pueden llevar maker a 0 en pares concretos. |
| EVIDENCE | Snippet oficial: *"Binance regular and VIP 1 to 9 users will be able to enjoy 0 maker fee and up to 50% discounts on taker fees … during the Promotion"*; snippets de 2026 citando taker regular 0.0400%–0.0500%. |
| RELIABILITY | MEDIUM (promociones cambian; el runtime **excluye** derivados) |
| DECISION | Derivados quedan fuera del runtime (`excluded_markets`). Solo se usan sus datos públicos como *información*, no como producto ejecutable. |

### SRC-03 — Binance Spot klines schema (taker flow fields)
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-03 |
| URL | https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market (y `binance-spot-api-docs/rest-api.md`) |
| SOURCE_TYPE | official API docs |
| DATE | consultada 2026-09-26 |
| PRODUCT | Binance Spot REST `/api/v3/klines` |
| CLAIM | Cada kline incluye 12 columnas: openTime, O,H,L,C, volume, closeTime, quoteVolume, **number of trades**, **taker buy base asset volume**, **taker buy quote asset volume**, ignore. Es decir, el flujo agresor buy/sell agregado por intervalo está disponible en el histórico completo. |
| EVIDENCE | Docs oficiales listan "Taker buy base asset volume" como campo del kline; verificado empíricamente (12 columnas, col 9 = taker buy base). |
| RELIABILITY | HIGH |
| DECISION | M-01/M-03 testeables sobre histórico completo vía flows de klines (agregado, no tick). |

### SRC-04 — Binance public historical data (data.binance.vision)
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-04 |
| URL | https://data.binance.vision/ |
| SOURCE_TYPE | official bulk data repository |
| DATE | consultada 2026-09-26 |
| PRODUCT | Binance Spot & USDⓈ-M Futures |
| CLAIM | Zips mensuales/diarios de klines y aggTrades con histórico completo, descargables sin credenciales. Verificado: `data/spot/monthly/klines/BTCUSDT/5m/BTCUSDT-5m-2026-08.zip` -> 200. |
| EVIDENCE | Descarga directa HTTP 200; CSV con 12 columnas idénticas a REST klines. |
| RELIABILITY | HIGH |
| DECISION | Fuente para bulk histórico de OHLCV+flow y (si se requiere) aggTrades tick-level. |

### SRC-05 — Binance USDⓈ-M funding rate history
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-05 |
| URL | https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data |
| SOURCE_TYPE | official API docs |
| DATE | consultada 2026-09-26 |
| PRODUCT | USDⓈ-M `/fapi/v1/fundingRate`, `/fapi/v1/premiumIndexKlines` |
| CLAIM | El histórico de funding y el premium index están disponibles sin la restricción de 30 días (a diferencia de OI/basis). Verificado: 624 pagos de funding desde 2026-03-01 para BTC/ETH/SOL. |
| EVIDENCE | Descarga directa; primer `fundingTime` = 2026-03-01 00:00; `premiumIndexKlines` 59,905 barras 5m desde 2026-03-01. |
| RELIABILITY | HIGH |
| DECISION | M-04 (funding) y M-05 (premium) testeables sobre histórico completo. |

### SRC-06 — Binance USDⓈ-M open interest / basis / long-short retention
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-06 |
| URL | https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data |
| SOURCE_TYPE | official API docs |
| DATE | consultada 2026-09-26 |
| PRODUCT | `/futures/data/openInterestHist`, `/futures/data/basis`, long/short ratio |
| CLAIM | **"Only the data of the latest 30 days is available."** Verificado empíricamente: OI devuelve 200 para `endTime` = now-30d y HTTP 400 para now-60d. Basis retiene ~30d y su paginación por `endTime` es inestable (devuelve la ventana más reciente repetida). |
| EVIDENCE | Doc oficial (frase textual) + prueba: `endTime=now-30d` -> 200; `endTime=now-60d` -> 400. |
| RELIABILITY | HIGH |
| DECISION | M-06/M-07 quedan **LIMITED_HISTORY** (30d): no cubren DEV/VAL -> no pueden pasar Filter 3. Basis redundante con premium index. |

### SRC-07 — Binance Spot order book (depth / bookTicker)
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-07 |
| URL | https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market |
| SOURCE_TYPE | official API docs |
| DATE | consultada 2026-09-26 |
| PRODUCT | Spot `/api/v3/depth`, `/api/v3/ticker/bookTicker`, WS `@depth`, `@bookTicker` |
| CLAIM | Solo snapshots/streams en vivo. **No existe endpoint REST de histórico de order book ni de bookTicker.** Verificado: `/api/v3/depth` y `/ticker/bookTicker` devuelven el estado actual. |
| EVIDENCE | Respuestas live 200 (sin parámetro temporal más allá de `limit`); no hay endpoint histórico en la API. |
| RELIABILITY | HIGH |
| DECISION | M-02 (book imbalance) = **LIVE_ONLY** -> requiere `MICROSTRUCTURE-FORWARD-DATA-V1`. **No se fabrica libro desde OHLCV (§16).** |

### SRC-08 — Binance Spot defined rate limits
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-08 |
| URL | https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market |
| SOURCE_TYPE | official API docs |
| DATE | consultada 2026-09-26 |
| PRODUCT | Spot REST weights |
| CLAIM | `/api/v3/klines` weight depende de `limit` (limit 1000 = weight 2); límite 6000 weight/min por IP. Colector a 250 ms/req está muy por debajo. |
| EVIDENCE | Docs oficiales de weights; config del proyecto usa `rate_limit_ms: 250`. |
| RELIABILITY | HIGH |
| DECISION | Colector read-only respeta rate limit; sin credenciales. |

### SRC-09 — Bybit spot trading fee schedule
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-09 |
| URL | https://www.bybit.com/en/help-center/article/Trading-Fee-Structure |
| SOURCE_TYPE | official exchange help center |
| DATE | consultada 2026-09-27 |
| PRODUCT | Bybit Spot (crypto-crypto) |
| CLAIM | VIP0: **maker 0.1000% / taker 0.1000%** (10 bps/lado); VIP1 taker 0.0800%. Perp: maker 0.02% / taker 0.055%. |
| EVIDENCE | Tabla oficial "VIP 0 · 0.1000% · 0.1000%"; página de fee-rate con perp maker 0.0400% / taker 0.1000% (promoción). |
| RELIABILITY | HIGH |
| DECISION | En VENUE_EXECUTION_MATRIX_V1: mismo fee spot que Binance a VIP0; RESEARCH_CANDIDATE, no adoptado. |

### SRC-10 — OKX spot trading fee schedule
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-10 |
| URL | https://www.okx.com/en-us/fees |
| SOURCE_TYPE | official exchange fee page |
| DATE | consultada 2026-09-27 |
| PRODUCT | OKX Spot |
| CLAIM | Tier base (Lv1, < 500 OKB): **maker 0.08% / taker 0.10%** (8 / 10 bps). Perp 0.02% / 0.05%. |
| EVIDENCE | FAQ oficial "Trader A (Maker fee: 0.08%; Taker fee: 0.1%)"; página de fees por tiers. |
| RELIABILITY | HIGH |
| DECISION | Maker 8 bps → ejecución pasiva ahorra 2 bps frente a Binance. RESEARCH_CANDIDATE, no adoptado. |

### SRC-11 — MEXC spot trading fee schedule
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-11 |
| URL | https://www.mexc.com/support/article/mexc-0-fee-spot-trading-faq-264764306934491136 |
| SOURCE_TYPE | official exchange support article |
| DATE | consultada 2026-09-27 |
| PRODUCT | MEXC Spot |
| CLAIM | Spot estándar: **maker 0% / taker 0.05%** (0 / 5 bps). Programa 0-fee: "All Spot trading pairs on MEXC are eligible for 0% maker and 0% taker fees". |
| EVIDENCE | FAQ oficial 0-fee spot; schedule publicado 0%/0.05% confirmado por múltiples páginas de comparación, pero el **fee que decide el modelo (5 bps taker) viene del artículo oficial**. |
| RELIABILITY | HIGH para 0%/0.05%; el programa 0%/0% se marca POSSIBLE (campaña, puede excluir pares/regiones) |
| DECISION | Único spot investigado que baja el fee taker a la mitad. Se reporta 0%/0.05% como base y el programa 0-fee como POSSIBLE, nunca CONFIRMED. RESEARCH_CANDIDATE. |

### SRC-12 — Kraken Pro spot fee schedule
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-12 |
| URL | https://www.kraken.com/features/fee-schedule |
| SOURCE_TYPE | official exchange fee page |
| DATE | consultada 2026-09-27 |
| PRODUCT | Kraken Pro Spot |
| CLAIM | Tier inicial (< 10,000 USD 30d): **maker ~0.25% / taker ~0.40%** (25 / 40 bps). Cambio de tiers desde 2026-07-09 basado en volumen spot **o** activos en plataforma. |
| EVIDENCE | Página oficial de fee schedule por tiers; soporte oficial con la nota de cambio de tiers de julio 2026. |
| RELIABILITY | MEDIUM (el tier exacto depende de AoP; se usa el más conservador) |
| DECISION | Acceso regulatorio (US/EU) pero fee prohibitivo para intradía. RESEARCH_CANDIDATE, no adoptado. |

### SRC-13 — Binance bulk aggTrades CSV timestamp unit
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-13 |
| URL | https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-09-24.zip |
| SOURCE_TYPE | official bulk data repository (verificación empírica directa) |
| DATE | verificada 2026-09-27 |
| PRODUCT | Binance Spot daily aggTrades |
| CLAIM | La columna `timestamp` del CSV viene en **MICROSEGUNDOS**, no en milisegundos. Esquema de 8 columnas sin cabecera: `aggTradeId, price, qty, firstTradeId, lastTradeId, timestamp, isBuyerMaker, isBestMatch`. |
| EVIDENCE | Valor observado en los 42 archivos: p. ej. `1783814400000000` = 2026-07-12T00:00:00Z en µs (en ms sería `1783814400000`). Asumir ms produce **62,000 buckets/día** en lugar de 1,440 (agrupación por print). Verificado también que ningún archivo mezcla unidades. |
| RELIABILITY | HIGH (medido directamente sobre el dato) |
| DECISION | El fetcher detecta la unidad (`_to_ms`, umbral 1e14), la registra en el manifest (`source_timestamp_unit`) y **falla en cerrado** ante unidades mezcladas. Defecto `DEFECT-AG-01`, corregido, con test de regresión. |

### SRC-14 — Binance Spot public WebSocket market streams
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-14 |
| URL | `wss://stream.binance.com:9443/stream?streams=<a>/<b>/...` |
| SOURCE_TYPE | public market data WebSocket (verificación empírica directa en esta fase) |
| DATE | usada 2026-09-28 (captura `MICROSTRUCTURE-FORWARD-COLLECTION-V1`) |
| PRODUCT | Binance Spot |
| CLAIM | Los streams `<symbol>@aggTrade`, `<symbol>@depth@100ms` y `<symbol>@bookTicker` están **operativos y secuenciados**: `aggTrade` trae el id `a` (estrictamente +1), `depthUpdate` trae `U`/`u` (y **no** trae `pu`, que es exclusivo de USDⓈ-M), y `bookTicker` de spot **no publica ningún timestamp de evento** (solo `u`). |
| EVIDENCE | Captura oficial de esta fase (63.06 min, 3 símbolos, conexión combinada): la cadena de ids de `aggTrade` es **contigua y sin duplicados** — 5,481,951 filas replayadas, 15,969 filas restauradas del índice público, 0 violaciones, `resolved_hi == live_head` (ver `docs/FORWARD_DATA_REPLAY_VALIDATION.md`). El entorno sí cerró el socket de spot 6 veces en la hora (18 gaps `WS_DISCONNECT`, uno por símbolo y episodio): los huecos de `aggTrade` se cerraron **todos** desde el índice público (`RECOVERED_COMPLETE`, 195–1,947 trades por episodio), y los de `depth`/`bookTicker` no costaron datos porque el libro descarta su estado y resnapshotea. Ejemplo de `depthUpdate` de spot: `{"e":"depthUpdate","E":…,"s":"BTCUSDT","U":100770669108,"u":100770669183,…}` (sin `pu`). |
| RELIABILITY | HIGH (medido directamente sobre el stream) |
| DECISION | El colector forward usa WS como transporte principal y declara `bookTicker` de spot sin event time **explícitamente** (`detail.event_time_available=false`), en lugar de inventarlo. |

### SRC-15 — Binance USDⓈ-M public WebSocket market streams (disponibilidad parcial)
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-15 |
| URL | `wss://fstream.binance.com/stream?streams=<a>/<b>/...` |
| SOURCE_TYPE | public market data WebSocket (verificación empírica directa en esta fase) |
| DATE | usada 2026-09-28 |
| PRODUCT | Binance USDⓈ-M Perpetual Futures |
| CLAIM | En este entorno `depth@100ms` y `bookTicker` **sí** entregan datos (y `depthUpdate` incluye `pu`, permitiendo la cadena de secuencia más fuerte), pero `@aggTrade` y `@markPrice@1s` **entregan CERO mensajes**. Además la conexión es inestable: el servidor la cierra periódicamente. |
| EVIDENCE | Sondas independientes: `@aggTrade` en URL simple durante 30 s -> 0 mensajes; `@markPrice@1s` durante 8 s -> 0 mensajes; conexión combinada de 20 s -> solo `depth` (195) y `bookTicker` (13,201). En la captura real de la fase, el 100% de las desconexiones registradas ocurrieron en `perp` (motivo `websocket CLOSED`), 0 en `spot`. |
| RELIABILITY | HIGH para la observación (medida); la causa es ambiental, no del exchange |
| DECISION | El colector **se suscribe igualmente** a `perp@aggTrade` y registra el veredicto `NO_DATA` en `provider_stream_status`. **No** sustituye el stream ausente por sondeo REST presentado como lossless (§5, §55): el flujo de trades del perpetuo queda declarado como no capturado. |

### SRC-16 — Binance public aggregate-trade index (REST, read-only)
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-16 |
| URL | `GET https://api.binance.com/api/v3/aggTrades?symbol=&fromId=&limit=` y `GET https://fapi.binance.com/fapi/v1/aggTrades?…` |
| SOURCE_TYPE | public market data REST (read-only, sin claves) |
| DATE | usada 2026-09-28 (reparación de huecos de la captura forward) |
| PRODUCT | Binance Spot y USDⓈ-M |
| CLAIM | El índice de aggregate trades es **direccionable por id**: `fromId = ultimo_id_visto + 1` devuelve exactamente los trades que un corte de WebSocket se llevó, en orden ascendente de `a`, y `limit` acota la página (1000). Por tanto un hueco de trades es **recuperable**, a diferencia de un hueco de diffs de libro. |
| EVIDENCE | Uso real en la captura oficial: cada `WS_DISCONNECT` y cada `AGG_TRADE_ID_JUMP` del stream de trades dispara un recorrido del índice; los eventos restaurados se escriben con `detail.origin=agg_trade_backfill` y el hueco pasa a `RECOVERED_COMPLETE`/`RECOVERED_PARTIAL` con `recovered_events` y `remaining_missing`. Comprobado por tests adversariales (paginación, fallo HTTP, presupuesto de páginas agotado, reentrada prohibida). |
| RELIABILITY | HIGH (ids verificables + identidad `(market, symbol, id)` sin duplicados en disco) |
| DECISION | Se usa **solo** para cerrar huecos de trades ya detectados, nunca como fuente primaria (`transport` de la fila sigue siendo `ws`; la procedencia va en `detail.origin`). El presupuesto de páginas acota el coste y clasifica el hueco como parcial cuando no alcanza. |

### SRC-17 — Binance public klines (REST, validación cruzada)
| campo | valor |
| --- | --- |
| SOURCE_ID | SRC-17 |
| URL | `GET https://api.binance.com/api/v3/klines?symbol=&interval=1m&startTime=&endTime=` |
| SOURCE_TYPE | public market data REST (read-only) |
| DATE | usada 2026-09-28 |
| PRODUCT | Binance Spot |
| CLAIM | Sirve como **control externo** del volumen capturado: el volumen de una vela 1m debe coincidir con la suma de `quantity` de los aggTrades capturados en ese mismo minuto. Es un endpoint sin relación con el camino WebSocket del colector, así que un acuerdo no se puede explicar por un error compartido. |
| EVIDENCE | `scripts/forward_kline_crosscheck.py` sobre la captura oficial; artefacto `docs/FORWARD_DATA_KLINE_CROSSCHECK.json` (buckets comparados, ratio por bucket, excluidos por solapar pérdida declarada). El verificador independiente **recalcula** la aritmética de los ratios desde los pares almacenados. |
| RELIABILITY | MEDIUM-HIGH (dato de terceros, mismo venue; se usa como control, no como fuente del dataset) |
| DECISION | Validación de calidad de datos de una muestra reproducible, **nunca** medición de edge. Los buckets que solapan un hueco con pérdida se excluyen y se cuentan. |

### SRC-18 — Matriz de capacidad observada por stream (captura oficial `forward-1790610007-9d07f3df`)

> Vocabulario exigido por la fase: **AVAILABLE** / **UNAVAILABLE_IN_CURRENT_ENVIRONMENT** /
> **ALTERNATIVE_SOURCE_AVAILABLE**. La clasificación sale del propio manifest
> (`provider_stream_status`), que se escribe a partir de lo que llegó, no de lo que se esperaba.
> Una capacidad ausente se declara; **no** se sustituye por otra cosa presentada como si fuera el
> mismo stream.

| stream | fuente | clasificación | evidencia en la captura |
| --- | --- | --- | --- |
| `spot@aggTrade` | WS | **AVAILABLE** | 124,232 filas, cadena de ids verificada (+36 huecos cerrados por índice REST) |
| `spot@depth@100ms` | WS | **AVAILABLE** | 92,649 diffs, `U`/`u` secuenciados |
| `spot@bookTicker` | WS | **AVAILABLE** (sin `event_time` publicado) | 1,659,064 filas; `detail.event_time_available=false` |
| `perp@depth@100ms` (incl. `pu`) | WS | **AVAILABLE** pero **inestable** | 66,570 diffs; 81 desconexiones del socket de `perp` |
| `perp@bookTicker` | WS | **AVAILABLE** pero **inestable** | 3,535,889 filas |
| `perp@aggTrade` | WS | **UNAVAILABLE_IN_CURRENT_ENVIRONMENT** | veredicto `NO_DATA`, 0 eventos en 63.06 min pese a estar suscrito |
| `perp@markPrice@1s` | WS | **UNAVAILABLE_IN_CURRENT_ENVIRONMENT** | veredicto `NO_DATA`, 0 eventos (el `mark_price` capturado viene de `rest_poll`) |
| `perp` funding / OI / premium | REST poll | **ALTERNATIVE_SOURCE_AVAILABLE** (usada) | `/fapi/v1/fundingRate`, `/fapi/v1/openInterest`, `/fapi/v1/premiumIndex` cada 60 s: 58 muestras por símbolo |
| `perp@markPrice` vía `rest_poll` | REST poll | **ALTERNATIVE_SOURCE_AVAILABLE** (usada) | 58 muestras por símbolo, etiquetadas `rest_poll`, nunca `ws` |
| snapshot de libro | REST | **ALTERNATIVE_SOURCE_AVAILABLE** (usado y necesario) | 254 snapshots `rest_backfill` (los diffs por sí solos no pueden construir un libro) |
| índice de aggTrades para reparar huecos | REST | **ALTERNATIVE_SOURCE_AVAILABLE** (usada) | 15,969 filas `detail.origin=agg_trade_backfill`, 36 huecos `RECOVERED_COMPLETE` |
| `perp/agg_trade` como fuente del flujo agresor del perpetuo | — | **UNAVAILABLE_IN_CURRENT_ENVIRONMENT** | declarado `NO_DATA`; **no** se rellena con sondeo REST ni con klines (sería otro stream, no este) |

**Consecuencia declarada:** la matriz de datos prevista (spot + perp, 3 activos) queda **completa en spot**
(aggTrade, libro, bookTicker) e **incompleta en el flujo de trades del perpetuo**. Esto limita cualquier
investigación que necesite el flujo agresor del perpetuo, y **no** invalida la captura de spot, que es
íntegra y está validada contra las klines del propio venue (SRC-17).

## Claims -> Decision (resumen §51)

| CLAIM | SOURCE | EVIDENCE | DECISION |
| --- | --- | --- | --- |
| Spot VIP0 fee = 10 bps/lado | SRC-01 | página oficial | modelo 5 bps = OPTIMISTIC |
| Derivados fuera del runtime | config + SRC-02 | `excluded_markets` | solo datos, no producto |
| Flujo agresor en klines | SRC-03/04 | 12 columnas, col 9/10 | M-01/M-03 testeables |
| Funding/premium histórico completo | SRC-05 | 624 funding, 59,905 premium | M-04/M-05 testeables |
| OI/basis solo 30d | SRC-06 | 400 en now-60d | M-06/M-07 LIMITED_HISTORY |
| Order book sin histórico | SRC-07 | sin endpoint | M-02 LIVE_ONLY, forward required |
| Bybit Spot VIP0 = 10/10 bps | SRC-09 | tabla oficial | RESEARCH_CANDIDATE, no adoptado |
| OKX Spot Lv1 = 8/10 bps | SRC-10 | FAQ oficial | maker ahorra 2 bps; no adoptado |
| MEXC Spot = 0/5 bps | SRC-11 | artículo oficial | único spot con fee a la mitad; POSSIBLE, no CONFIRMED |
| Kraken Pro tier base = 25/40 bps | SRC-12 | fee schedule oficial | prohibitivo intradía; no adoptado |
| aggTrades CSV en microsegundos | SRC-13 | 42 archivos medidos | detección de unidad + fail-closed (DEFECT-AG-01) |
| Binance Spot VIP0 maker == taker (10/10) | SRC-01 | página oficial | "hacerse maker" no ahorra fee; MAKER EDGE GATE = FAIL |
| Spot WS aggTrade/depth/bookTicker operativos y secuenciados | SRC-14 | captura real 2026-09-28 | WS-first es viable; bookTicker spot sin event time (documentado) |
| USDⓈ-M WS aggTrade/markPrice entregan 0 mensajes aquí | SRC-15 | sondas + captura real | stream declarado `NO_DATA`; NO se sustituye por REST |
| El índice de aggTrades es direccionable por id | SRC-16 | uso real + tests | los huecos de trades se reparan y se marcan; los de libro solo se declaran |
| Las klines públicas reproducen el volumen capturado | SRC-17 | cross-check de la captura oficial | validación de calidad de datos, no de edge |
| Matriz de capacidad por stream | SRC-18 | `provider_stream_status` de la captura oficial | perp aggTrade/markPrice `UNAVAILABLE_IN_CURRENT_ENVIRONMENT`; spot completo; no se sustituye nada |
