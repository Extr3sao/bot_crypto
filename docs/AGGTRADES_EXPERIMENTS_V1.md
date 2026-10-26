# AGGTRADES_EXPERIMENTS_V1 — registro de experimentos y procedencia de datos

Fecha: 2026-09-27. Pre-registro: `docs/AGGTRADES_HYPOTHESES_V1.md` (escrito ANTES).
Ejecutor: `scripts/aggtrades_experiments.py`. Fetcher: `scripts/fetch_aggtrades_microstructure.py`.

## 1. Dataset y fingerprints

| item | valor |
| --- | --- |
| fuente | `data.binance.vision/data/spot/daily/aggTrades` (SRC-04) |
| archivos | **42** (14 días × BTC/ETH/SOL) |
| filas por minuto | **60,480** (= 42 × 1,440) |
| días por split | DEV 24 archivos / 8 días · VAL 12 / 4 días · OOS 6 / 2 días |
| días ausentes (404) | 0 |
| unidad temporal detectada | **`microseconds`** (en los 42 archivos) |
| bytes de zip fuente | 31,000,777 |
| manifest | `reports/microstructure-v1/aggtrades/MANIFEST_AGGTRADES.json` |

Muestra **discontinua** y pre-registrada (día 12 y 24 de cada mes, 2026-03..09).
Reproducible: cada `AGG_*.json` lleva su `source_url`, `source_zip_sha256` y
`derived_sha256`, de modo que el agregado es reconstruible desde el byte
original. Los datasets grandes siguen gitignored; **manifests, hashes,
parámetros y procedencia quedan versionados**.

## 2. Hallazgo de schema (defecto encontrado y corregido)

`DEFECT-AG-01` — El CSV de aggTrades de Binance emite `timestamp` en
**microsegundos**, no en milisegundos. La primera ejecución del fetcher asumió
ms y produjo **62k filas/día** en vez de 1,440 (un bucket por print, ~100 MB por
archivo, 2.2 GB de basura). Detectado, borrado y corregido con detección de
unidad (`_to_ms`, umbral 1e14) y **fail-closed ante unidades mezcladas**.

Impacto en resultados: **ninguno** — los archivos corruptos se descartaron antes
de cualquier experimento. Cubierto por el test
`test_wrong_unit_would_fragment_buckets` (regresión explícita).

`DEFECT-AG-02` (declarado, no corregido, por disciplina de pre-registro) — El
feature pre-registrado `F5_interarrival_accel` se define en **milisegundos**,
pero tras la conversión µs→ms el **97.7 % de los minutos** tiene
`min_interarrival_ms == 0` (se midió: 19,693 / 20,160 minutos en BTC). El
feature queda degenerado y A-04 no produce señales. Cambiar la unidad a µs
**después** de ver el resultado sería re-optimización post-hoc, así que **no se
hizo**: A-04 se clasifica `INSUFFICIENT_DATA` con la causa medida, y la
resolución µs queda como requisito de la próxima pre-registración.

## 3. Construcción de barras y PIT

* Ticks → barras de 1 minuto UTC → barras de 5 minutos alineadas a `:00, :05…`.
* `event_time(bar) = open_time`; `available_at = open_time + 300,001 ms`.
* Un tick pertenece al bucket de **su propio** timestamp de exchange.
* Los 288 barras/día se construyen desde los 1,440 minutos; una barra
  incompleta se **descarta** (no se agrega parcialmente).
* `last_price` de la barra = último print del 5º minuto.

**Disciplina de ventana:** la muestra es discontinua, así que **toda** ventana
rolling (20 barras) se calcula **dentro de un mismo día**. Ningún estadístico
cruza un límite de día. Esto elimina de raíz la fuga más común.

## 4. Features ejecutadas (8, pre-registradas)

| ID | feature | ventana | nota |
| --- | --- | --- | --- |
| F1 | `signed_flow_imbalance` | 1 | núcleo de M-01 a resolución de tick |
| F2 | `trade_imbalance` | 1 | |
| F3 | `large_trade_imbalance` | 1 | umbral fijo: notional ≥ 50,000 USD |
| F4 | `trade_intensity_z` | 20 | |
| F5 | `interarrival_accel` | 20 | **degenerado a ms** (DEFECT-AG-02) |
| F6 | `abs_flow_z` | 20 | |
| F7 | `vwap_dislocation_bps` | 1 | |
| F8 | `cross_flow_btc` | 1 | PIT: barra `t-1` de BTC |

## 5. Registry de experimentos

| experiment_id | hypothesis | feature | horizonte | dirección | n |
| --- | --- | --- | ---: | --- | ---: |
| A-01 | M-01 tick-level | F1 | 5 barras (25 min) | congelada de DEV | 4,420 |
| A-02 | M-01 (clips grandes) | F3 | 5 | congelada de DEV | 5,943 |
| A-03 | M-03 flow+breakout | F1 + `ret_mom` | 5 | congelada de DEV | 2,563 |
| A-04 | burst → reversión | F5 | 5 | pre-registrada | **0** |
| A-05 | presión intrabar → reversión | F7 | 5 | pre-registrada | 279 |
| A-06 | M-08 lead/lag | F8 | 1 barra (5 min) | congelada de DEV | 12,012 |

## 6. Coste aplicado

`COST_MODEL_V3` con `BINANCE_SPOT_STANDARD_TAKER`, `size = 1,000 USD`,
liquidez `normal`, 25 min → **23.791 bps** round-trip. Escenario de contexto
MEXC → **17.791 bps** (solo informativo, no admission).

`ZERO_COST` no se usa. Ningún resultado bruto se presenta como neto.

## 7. Filtros y estados (§PHASE 6)

```text
Filter 0 info content   -> AGGTRADES_INFO_CONTENT.json
Filter 1 gross > 0 (DEV)
Filter 2 net > 0 (coste V3)
Filter 3 DEV > 0, VAL > 0, OOS > 0
Filter 4 estrés 1.25x / 1.5x
```

Estados: `NO_GROSS_EDGE`, `COST_KILLED`, `UNSTABLE`, `INSUFFICIENT_DATA`,
`EXECUTION_MODEL_REQUIRED`, `RESEARCH_CANDIDATE`, `PAPER_CANDIDATE`.

Early stop aplicado: ninguna línea llegó a OOS-financiado por haber pasado
Filter 1+2 ya que ninguna supera Filter 2.

## 8. Verificación

`scripts/research_verification.py` re-ejecuta este pipeline y compara salidas
byte a byte, re-verifica los 42 hashes de procedencia, comprueba
`net == gross − cost` y que ningún candidato salta los filtros.
Resultado: **Fase 7 VERIFIED, 0 fallos**.
