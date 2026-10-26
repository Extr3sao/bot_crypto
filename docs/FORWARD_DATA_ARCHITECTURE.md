# FORWARD_DATA_ARCHITECTURE — MICROSTRUCTURE-FORWARD-COLLECTION-V1

Fecha: 2026-09-28. HEAD base de la fase: `faf3992`
(`SHADOW_DECISION_RUNTIME_VERIFIED`, `MICROSTRUCTURE_NO_EDGE_FOUND`, 891 tests,
verifier 15/15).

> Este documento describe **infraestructura de datos**, no estrategia. No hay
> aquí ninguna afirmación de edge, rentabilidad ni readiness para operar.

## 1. Por qué existe esta fase

Las dos hipótesis que sobrevivieron a la auditoría histórica no se pueden testear
porque **los datos no existen**:

```text
M-03 order book imbalance   -> ORDER_BOOK = FORWARD_ONLY (ningún proveedor sirve histórico)
M-07 open interest x precio -> OPEN_INTEREST = LIMITED_HISTORY (~31 días, termina 2026-08-26)
liquidations                -> GET fapi/v1/allForceOrders = HTTP 404 = UNUSABLE_VIA_THIS_ENDPOINT
```

La respuesta de la fase anterior fue correcta: **no sintetizar historia**. La
respuesta de esta fase es **capturar forward con calidad demostrable**.

```text
REAL FORWARD COLLECTION
  -> DATA QUALITY
  -> TIME ALIGNMENT
  -> GAP DETECTION
  -> REPLAY
  -> DATASET BUILD
  -> (fase posterior) EXPERIMENTOS M-03 / M-07
```

## 2. Plano de autoridad

```text
             PUBLIC MARKET DATA
                    |
        +-----------+-----------+
        |                       |
  PAPER RUNTIME            FORWARD COLLECTOR
  (TRADING PLANE)          (DISCOVERY PLANE)
        |                       |
  decisiones              eventos crudos
  risk checks             dataset forward
  traces / outcomes            |
                               v
                            RESEARCH
```

* El colector vive en `src/trading_bot/research/forward/` (DISCOVERY PLANE).
* **No importa ningún módulo del trading runtime**: lo verifica un test que
  parsea los imports con `ast` y falla si aparece `trading_bot.risk`,
  `trading_bot.paper`, `trading_bot.execution`, `trading_bot.autonomous`,
  `trading_bot.portfolio`, `trading_bot.strategies`, `trading_bot.scanner`,
  `trading_bot.backtesting`, `trading_bot.feedback` o
  `trading_bot.market_structure`.
* No comparte estado mutable: escribe ficheros append-only bajo
  `reports/microstructure-forward/` y nada más.
* Solo endpoints **públicos de market data**; sin claves, sin cuenta, sin órdenes.
  También lo verifica un test (los endpoints son constantes comprobadas).

## 3. Componentes

| Módulo | Responsabilidad |
| --- | --- |
| `contract.py` | Contrato de evento crudo: tres relojes, mercado explícito, strings decimales exactos, invariantes temporales fail-closed |
| `orderbook.py` | Snapshot + diffs con integridad de secuencia dura; estado del libro; features de checkpoint |
| `storage.py` | Rotación determinista, fingerprints, manifest, estado de resume, tolerancia a escritura parcial |
| `collector.py` | Proceso WebSocket-first: ingest, reconciliación, health, heartbeat, reconexión, resume |
| `replay.py` | Reconstrucción offline determinista y verificación contra el manifest |
| `aggregation.py` | RAW -> 1m -> 5m/15m/30m solo con buckets completos, con `available_at_ms` |
| `reporting.py` | Informes de calidad, libro, recursos, diario y contrato machine-readable |
| `resources.py` | Medición portable de CPU, RAM, disco y red |

Entrypoints: `scripts/forward_collector.py` para **capturar** (`--mode run`) y
`scripts/forward_report.py` para las vistas **read-side** (`--mode report|replay|daily`).

La separación es deliberada. `scripts/forward_collector.py` es una de las cinco rutas
de escritura que la fase certifica como idénticas al commit que produjo la captura
oficial (§24): añadir ahí un flag de reporting haría que el punto de entrada de la
captura certificada dejara de ser el del árbol final, y ninguna re-ejecución de una
hora ya cerrada puede restaurar esa igualdad. Por eso el reporting vive en su propio
ejecutable, que además soporta `--offline` (sockets sustituidos por excepciones) para
que un replay sin red sea un hecho del proceso y no una afirmación del informe.

## 4. WebSocket first (§5)

La captura principal es WebSocket porque **solo un stream secuenciado permite
demostrar ausencia de pérdidas**. El colector REST anterior midió exactamente el
fallo contrario (`forward_1790595680.jsonl`: 1 hueco de secuencia de aggTrade en
BTCUSDT y 1 periodo de `premiumIndex` obsoleto de ~15,3 s). Una encuesta REST es
una sucesión de muestras independientes: no existe un identificador que pruebe
que no falta nada entre dos sondeos.

Suscribe, por mercado (spot y USDⓈ-M) y símbolo, en una única conexión combinada:

```text
<symbol>@aggTrade        secuenciado por 'a' (id estrictamente +1)
<symbol>@depth@100ms     secuenciado por 'U'/'u' y (USDⓈ-M) 'pu'
<symbol>@bookTicker      id monótono, liveness
```

REST queda para lo que solo REST puede dar: snapshot inicial de libro, y series
periódicas (open interest, mark/index, funding). Nada de alta frecuencia.

**Hallazgo medido de esta fase:** en este entorno `fstream.binance.com` sirve
`depth` y `bookTicker` pero **entrega cero mensajes** en `@aggTrade` y
`@markPrice@1s` (comprobado con sondas independientes de 30 s y 20 s). El
colector sigue suscribiéndose y registra el veredicto `NO_DATA` en el manifest:
no sustituye el stream ausente por sondeo REST disfrazado de lossless.

## 5. Almacenamiento (§20-§23, §43)

```text
reports/microstructure-forward/
  segments/<source>/<market>/<symbol>/<event_type>/<UTC date>/<HHMMSS>.jsonl.gz
  manifest/<run_id>.json
  state/<run_id>.json
  aggregation/<run_id>.json
  heartbeats (como stream _GLOBAL)
  collector.stdout.log / collector.stderr.log
```

Decisiones:

* **La ruta es función pura de su ventana.** El nombre del fichero es el inicio
  del bucket de rotación en UTC, así que dado un evento se sabe dónde debe vivir
  y dada una ruta se sabe qué ventana cubre. La rotación ocurre *en el momento de
  escribir* cuando el bucket cambia (no solo por temporizador), precisamente para
  que esa propiedad sea cierta y no aproximada.
* **Append-only, línea completa JSON.** Un crash solo puede dejar una línea
  parcial al final; los lectores la reportan como `partial_tail` en lugar de
  ignorarla. Un miembro gzip truncado se trata igual: los miembros completos
  anteriores siguen siendo legibles.
* **Compresión gzip (nivel 6) por defecto.** No es un adorno: el JSON comprime
  ~13x medido, y un dataset que no puede correr durante días no es un dataset
  forward (§37). El ratio medido en la captura oficial está en
  `docs/FORWARD_DATA_RESOURCE_REPORT.json` (`footprint.compression_ratio`),
  medido descomprimiendo los ficheros, no autocitado por el escritor.
* **La ruta de análisis hace *streaming* (§34).** Una hora forward de un stream
  activo es un único segmento de ~10^6 filas. Materializar el run costaba
  ~7.5 KB por fila (medido: 1.38M filas → 9.8 GB), es decir ~59 GB para una hora
  completa: el pipeline no podía analizar su propia salida. `ForwardReplay.iter_rows()`
  fusiona los segmentos por `write_seq` con memoria constante (una fila residente
  por segmento; medido: 1.70M filas → +47 MB), y la agregación acepta una fuente
  re-ejecutable en lugar de una lista. Esa propiedad es la que permite que el
  pipeline corra durante días (§37), y un test la fija: el resultado por
  streaming debe ser idéntico al materializado.
* **Rotación horaria** por defecto (`--rotation-seconds`), determinista.
* **Retención (§43):** esta fase no borra raw. La política portable recomendada
  para operación continua es: *raw comprimido* 7-14 días, *agregados* (1m y
  superiores) indefinido, *manifests y fingerprints* indefinido (son pequeños y
  son la prueba de auditoría).

## 6. Integridad de secuencia (§12, §13)

```text
REST SNAPSHOT
   -> buffer WS diffs
   -> alinear secuencia
   -> aplicar diffs
   -> LIVE BOOK
```

El puente snapshot/diff se acepta solo si `U <= lastUpdateId + 1 <= u` (que
cubre tanto la forma documentada por spot como la de USDⓈ-M). Después:

* spot: cada update debe cumplir `U == (u anterior) + 1`;
* USDⓈ-M: cada update debe cumplir `pu == (u anterior)`, que es una comprobación
  estrictamente más fuerte que la adyacencia aritmética.

Si la cadena se rompe: `INVALID`, se descarta el libro, se lanza un resnapshot y
se registra el hueco. **Nunca se parchea, interpola ni continúa en silencio.**

## 7. Estado del libro (§14)

```text
HEALTHY      libro vivo y sin updates fuera de la ventana de staleness
RECOVERING   hay snapshot pero aún no se ha puenteado el primer diff
STALE        libro vivo pero sin updates durante más de stale_after_ms
INVALID      la cadena de secuencia se rompió (o el libro se cruzó)
```

Una feature de libro solo puede generarse desde `HEALTHY`. Los checkpoints se
persisten **siempre** con su estado, para que el fallo sea visible, pero cada uno
lleva `feature_usable = (health == HEALTHY)` y el informe cuenta la proporción
usable.

## 8. Fallo de red y reconexión (§25, §26)

```text
desconexión detectada (CLOSED/ERROR, o sin frames durante read_timeout)
   -> comienza el hueco
   -> reconexión con backoff (1,2,5,10,20,30 s)
   -> reconciliación (resnapshot)
   -> hueco documentado
```

El manifest registra por cada desconexión: motivo, duración, si la conexión
llegó a establecerse y el resultado de la reconciliación.

**Semántica de `recovered` (estricta):** `recovered` significa *el dato se
recuperó*, no *la conexión volvió*. Reconectar no es recuperar. Una ventana de
longitud cero (el venue cierra el socket justo tras el handshake) se registra con
`data_lost=False`; cualquier hueco reconstruido por backfill se registra con
`recovered=True` y `recovered_events=n`. Un hueco con pérdida real es
`data_lost=True` y **no permite declarar continuidad** (§27).

Se detectan dos formas distintas de hueco en el stream de trades, y ambas se
tratan con el mismo ciclo de vida:

```text
WS_DISCONNECT          el socket se cayó: se desconoce el rango exacto al inicio
AGG_TRADE_ID_JUMP      dos trades vivos consecutivos con ids no adyacentes: el
                       rango perdido es exactamente [prev+1, agg_id-1]
```

## 8-bis. Backfill de trades y ciclo de vida del hueco (§2, §5, §26)

El índice público de aggregate trades (`/api/v3/aggTrades` y
`/fapi/v1/aggTrades` con `fromId`) es la única fuente que puede **cerrar** un
hueco de trades en lugar de solo declararlo: los ids de `fromId` en adelante son
exactamente los trades que el corte se llevó, y siguen siendo el registro del
propio venue (no una reconstrucción sintética).

```text
GAP_DETECTED        el hueco se persiste ANTES de intentar nada
   -> RECOVERY_ATTEMPTED   se recorre el índice público desde prev+1
   -> RECOVERED_COMPLETE   el rango se cerró entero
   -> RECOVERED_PARTIAL    se recuperó una parte; el resto queda como pérdida
   -> UNRECOVERABLE        el índice no responde, o el hueco supera el presupuesto de páginas
```

Cada hueco lleva `gap_id`, `reason`, `start_ms`, `end_ms`, `estimated_lost_events`,
`recovered_events`, `remaining_missing` y `status`, y escribe **dos** eventos
`gap` en el dataset (fase `GAP_DETECTED` y fase `RECOVERY_RESOLVED`) para que la
recuperación sea auditable y no una afirmación.

Reglas que hacen esto seguro:

* **El hueco se registra primero.** Si el proceso muere durante la recuperación,
  el dataset conserva la prueba del hueco.
* **El backfill no se re-entra.** Un hueco visto *dentro* de una página de
  backfill no programa otra recuperación (ya estamos recorriendo ese mismo
  índice); se registra y se cuenta en `backfill_deferred`.
* **Presupuesto acotado:** 5 páginas de 1000 filas (`BACKFILL_MAX_PAGES`). Si el
  hueco es mayor, queda `RECOVERED_PARTIAL` con `remaining_missing` explícito.
* **Etiquetado por fila:** una fila recuperada conserva `transport=ws` (su id es
  lo que la hace detectable en el stream secuenciado) y añade
  `detail.origin="agg_trade_backfill"`. Presentar un registro REST como WS está
  prohibido a nivel de contrato: `RawEvent` rechaza `transport != ws` para
tipos lossless.
* **Latencia honesta:** las filas recuperadas se excluyen de los percentiles de
  latencia (su retardo es la anchura del corte, no la latencia de la red) y se
  cuentan aparte en `loss.backfilled_events`.

## 8-ter. Identidad y deduplicación (§3, §11)

La identidad lógica de un aggTrade es `(market, symbol, aggregate_trade_id)`.
Una ventana deslizante acotada por stream (`RECENT_ID_WINDOW = 4096`) recuerda
los ids ya escritos, así que **una fila nunca se escribe dos veces**: si el
stream vivo reenvía un id que el backfill ya restauró, se cuenta como duplicado
detectado y se descarta. El fichero resultante no contiene filas duplicadas, y
la calidad declara `duplicate_rows_on_disk = 0` como propiedad comprobable.

El orden lógico del dataset **no depende del orden físico de escritura** (§4):
una fila recuperada puede llegar después de filas con ids mayores, y ningún
consumidor debe asumir orden de fichero. La agregación indexa por ventana
(`exchange_event_time` truncado a bucket) y ordena al emitir, y el stream de
trades se puede reordenar por id. No se reescribe masivamente nada ya persistido.

## 8-quater. Un root, un run (§12, §23)

La ruta de un segmento es función pura de su ventana, así que **dos runs
distintos escribiendo en el mismo root se fusionarían en el mismo fichero y en
el mismo fingerprint**. Para que eso no pueda pasar en silencio, `SegmentWriter`
se niega a abrir un segmento que ya contiene filas salvo que el arranque sea un
`--resume` declarado del mismo run. Un `--resume` sí añade al mismo segmento, y
el fingerprint se recalcula leyendo el fichero completo, de modo que un segmento
reanudado nunca parece más corto de lo que es.

## 9. Resume (§24)

`state/<run_id>.json` se guarda periódicamente con el último `receive_time`, los
últimos ids de aggTrade por símbolo, la secuencia de `gap_id` y los contadores.
Un arranque con `--resume --run-id <id>` reabre los mismos segmentos (append),
registra la ventana de parada como hueco `COLLECTOR_RESTART` con
`data_lost=True`, y **programa la recuperación del stream de trades** desde el
último id conocido (`fromId = ultimo_id + 1`) en cuanto existe sesión HTTP, para
que lo primero que haga una captura reanudada sea reparar su propio corte. Sin
duplicados descontrolados, sin huecos silenciosos, sin estado de secuencia
perdido: el estado se re-deriva del snapshot.

## 10. PIT y anti-lookahead (§10, §35)

* Tres relojes separados y persistidos: `exchange_event_time`, `receive_time`,
  `process_time`. Los derivados (`network_delay_ms`, `processing_delay_ms`) se
  añaden **junto a** ellos, nunca en su lugar.
* `process_time >= receive_time` es invariante y lanza excepción.
* `exchange_event_time <= receive_time + tolerancia` (500 ms) se comprueba por
  evento; una violación **pone el evento en cuarentena** en el stream de
  violaciones y marca el colector `FAILED`, en lugar de envenenar el dataset.
* Cada bucket agregado expone `available_at_ms = close_time_ms`. Un bucket
  `10:00-10:05` solo está disponible desde `10:05:00`, y nunca se agrega hacia
  arriba si está incompleto.

## 11. Replay (§31, §32)

`replay_microstructure_dataset(root, run_id)` reconstruye el dataset **desde
disco, sin red**:

* ordena las filas por `write_seq` (el contador de proceso asignado por el
  almacenamiento), no por reloj: los timestamps empatan, el orden de proceso no;
* reconstruye el libro con el mismo camino de código (mismo `BookSyncer`) y
  compara **cada** checkpoint persistido campo a campo;
* re-deriva la cadena de ids de aggTrade y las series de OI/funding/premium;
* recalcula la agregación raw -> 1m -> 5m/15m/30m y la compara con el digest
  registrado en `aggregation/<run_id>.json`;
* recalcula cada fingerprint desde los bytes en disco y lo compara con el
  manifest;
* hace una **segunda pasada completa** y exige que el digest y los conteos
  coincidan (`deterministic=true`).

El verificador independiente vuelve a reconstruir el libro con una **segunda
implementación escrita aparte** y ejecuta el replay con los sockets deshabilitados.

## 12. Health global, heartbeat y recursos (§28, §29, §42)

Cada `--heartbeat-seconds` se escribe un heartbeat compacto (estado, conexiones,
eventos/s, edad del último evento, contadores por stream, huecos, reconexiones,
bytes en disco, memoria, CPU) al stream global, y alimenta el informe de recursos.

Estados globales derivados (nunca declarados a mano):

* `HEALTHY`
* `DEGRADED` — reconexión en curso o recién completada, algún libro no saludable,
  huecos presentes, resnapshots fallidos
* `FAILED` — ningún stream lossless fluyendo, violación de invariante temporal,
  escritura fallida, un mercado caído más de `MARKET_DOWN_FAILED_S` (60 s), un
  libro que nunca llegó a `HEALTHY` en `BOOK_NEVER_HEALTHY_FAILED_S` (300 s), o
  `BOOK_IRRECOVERABLE_FAILURES` (5) reconciliaciones fallidas

La frontera no es "¿está todo sano ahora mismo?" sino **"¿es recuperable?"**
(§29): una desconexión que se está recuperando es `DEGRADED`, y solo una
condición de la que el colector no puede salir es `FAILED`. Un estado `FAILED`
por un corte de red transitorio habría sido una clasificación falsa y se corrigió
como defecto DEF-FWD-3.

Los cambios de estado se registran como eventos `lifecycle` y quedan en
`degradation_events` del manifest.

## 13. Operación continua 24/7

```bash
uv run python scripts/forward_collector.py --duration 3600 \
    --out reports/microstructure-forward
uv run python scripts/forward_collector.py --resume --run-id <run_id>   # tras un corte
uv run python scripts/forward_report.py --mode report --offline         # artefactos
uv run python scripts/forward_report.py --mode replay --offline --write-docs
uv run python scripts/forward_report.py --mode daily                    # informe diario

# validaciones de la fase (todas read-only y offline salvo la de klines)
uv run python scripts/forward_kline_crosscheck.py                        # volumen capturado vs klines públicas
uv run python scripts/forward_paper_coexistence.py --label with_collector
uv run python scripts/forward_paper_coexistence.py --label without_collector
uv run python scripts/forward_paper_coexistence.py --assemble            # artefacto de coexistencia
uv run python scripts/research_verification.py                           # verificador independiente
```

Banderas operativas relevantes:

| Bandera | Efecto |
| --- | --- |
| `--streams` | selección explícita de streams (queda registrada en el manifest) |
| `--max-total-bytes` | válvula de seguridad: parada ordenada antes de llenar el volumen |
| `--drop-raw` | omite la copia verbatim del payload (RAW FIRST está ON por defecto) |
| `--depth-limit`, `--depth-n` | profundidad del snapshot REST y niveles usados en las features de checkpoint |
| `--heartbeat-seconds`, `--checkpoint-seconds` | cadencia de heartbeat y de checkpoints de libro |
| `--oi-interval-seconds`, `--premium-interval-seconds` | cadencia de los sondeos REST de OI/funding/mark |
| `--symbols`, `--markets` | universo pequeño mientras se valida calidad (§6) |

Parada ordenada: al alcanzar `--duration`, al recibir `SIGINT`/`SIGTERM`, o al
cruzar `--max-total-bytes`, el colector sella *todos* los segmentos abiertos
(escribiendo el trailer gzip, así que el último fichero no queda truncado),
escribe el manifest con fingerprints y guarda el estado de resume. El guard de
disco comprueba el tamaño **antes** de cada escritura y se detiene por su cuenta,
no confiando en que el sistema de ficheros avise.

Señales: `SIGINT`/`SIGTERM` no matan el proceso; activan una parada ordenada que
sella todos los segmentos, escribe el manifest y los fingerprints.

## 14. Qué NO hace esta fase (§38, §47)

* No evalúa edge. Un smoke de minutos valida el pipeline, no una hipótesis.
* No declara `PAPER_CANDIDATE`, `PROFITABLE` ni `LIVE_READY`.
* No presenta sondeo REST como feed de trades.
* No declara `CONTINUOUS_DATA` cuando existe un hueco con pérdida real.
* No llama "histórico" a lo que es forward.
* No fabrica historia de libro inexistente.

## 15. Readiness declarable al cerrar la fase

```text
M-03 (order book imbalance)
    requiere: muestras forward de libro + secuencia válida + observaciones suficientes
M-07 (open interest x precio)
    requiere: suficiente historia de OI para DEV / VAL / OOS
```

Los veredictos posibles son `READY_FOR_RESEARCH`, `COLLECTING`, `NOT_READY`. Al
cierre de esta fase ambos están en `COLLECTING`: la infraestructura funciona y la
muestra todavía no alcanza. Los números concretos están en
`FORWARD_DATA_QUALITY_REPORT.json`.
