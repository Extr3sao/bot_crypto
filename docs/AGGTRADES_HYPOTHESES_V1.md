# AGGTRADES_HYPOTHESES_V1 — pre-registro (§PHASE 5)

> **Estado: PRE-REGISTRADO el 2026-09-27, ANTES de ejecutar cualquier
> experimento de aggTrades.** Los datasets, features, umbrales, horizontes,
> reglas de señal y criterios quedan fijados aquí. Nada se re-optimiza después
> de ver resultados. Si una hipótesis falla, se clasifica y se detiene; no se
> ajusta el umbral para rescatarla.

## 0. Por qué aggTrades y no más klines

La fase anterior concluyó `MICROSTRUCTURE_V1_NO_EDGE_FOUND` y dejó explícito un
hueco: **la columna `aggTrades` (tick real) estaba disponible en histórico
completo y no se explotó**; solo se usó el flujo agresor *agregado por kline*
(4 campos por barra de 5m). Ese agregado destruye precisamente la información
que define a la microestructura: secuencia de prints, tamaño de trade,
burstiness y flujo por agresor a resolución de tick.

Esta fase ataca ese hueco con datos **reales** descargados de
`data.binance.vision` (SRC-04), sin fabricar nada.

## 1. Fuente de datos y procedencia

| item | valor |
| --- | --- |
| fuente | `https://data.binance.vision/data/spot/daily/aggTrades/<SYM>/<SYM>-aggTrades-<YYYY-MM-DD>.zip` |
| SOURCE_ID | SRC-04 (bulk oficial Binance) |
| producto | Binance Spot |
| símbolos | BTCUSDT, ETHUSDT, SOLUSDT |
| esquema del zip | CSV sin cabecera: `aggTradeId, price, qty, firstTradeId, lastTradeId, timestamp, isBuyerMaker, isBestMatch` |
| claves de la verdad PIT | `timestamp` (ms, hora del evento en el exchange) y `isBuyerMaker` (agresor) |
| credenciales | ninguna (público, read-only) |

`isBuyerMaker == true` ⇒ el **agresor fue el vendedor** (un market sell golpeó
un bid). `false` ⇒ agresor comprador. De ahí se firma el flujo.

### 1.1 Muestra pre-registrada

No se descarga el histórico completo (volumen y disco: ~360–560 MB/mes por
activo). Se fija **antes de mirar resultados** una muestra de días:

```text
día 12 y día 24 de cada mes, 2026-03 .. 2026-09
= 14 días x 3 activos = 42 archivos diarios
```

Reparto por split (idéntico al de V3, §38):

| split | ventanas | días |
| --- | --- | --- |
| DEV | 2026-03..2026-06 | 03-12, 03-24, 04-12, 04-24, 05-12, 05-24, 06-12, 06-24 |
| VAL | 2026-07..2026-08 | 07-12, 07-24, 08-12, 08-24 |
| OOS | 2026-09 | 09-12, 09-24 |

Un día calendario puede faltar en el repositorio oficial; si falta, se
**registra el hueco** y no se sustituye por otro día (sustituirlo sería elegir
el día después de ver datos).

Limitación declarada de la muestra: 14 días no son 7 meses. La muestra es
**discontinua** y se documenta como tal; cualquier conclusión es sobre esta
muestra, no sobre el período completo.

## 2. Agregación y PIT

Los ticks se agregan a **barras de 1 minuto** UTC y de ahí a **barras de 5
minutos** alineadas a `:00, :05, ...` (el reloj de decisión del runtime).

* `event_time(bar) = open time` de la barra.
* `available_at(bar) = close time + 1 ms` (una barra solo es utilizable en la
  decisión siguiente). Regla dura: `available_at <= decision_time`.
* Los agregados de una barra usan **solo** ticks con
  `timestamp < close_time(bar)`. No hay look-ahead por agregación (§18).

## 3. Features pre-registradas (máximo 8)

| ID | feature | definición | ventana |
| --- | --- | --- | --- |
| F1 | `signed_flow_imbalance` | `(buy_vol - sell_vol) / (buy_vol + sell_vol)` | 1 barra |
| F2 | `trade_imbalance` | `(buy_count - sell_count) / n_trades` | 1 barra |
| F3 | `large_trade_imbalance` | `(large_buy_vol - large_sell_vol) / (large_buy_vol + large_sell_vol)`; `large` = print con notional `>= 50,000 USD` (umbral **fijo**, no ajustado por día ni por activo) | 1 barra |
| F4 | `trade_intensity_z` | z-score rolling de `n_trades` | 20 barras |
| F5 | `interarrival_accel` | `min_interarrival_ms(bar) / rolling_median(min_interarrival_ms)` (<1 = prints acelerando) | 20 barras |
| F6 | `abs_flow_z` | z-score rolling de `abs(signed_flow_imbalance)` | 20 barras |
| F7 | `vwap_dislocation_bps` | `(last_price / vwap(bar) - 1) * 10_000` | 1 barra |
| F8 | `cross_flow_btc` | `signed_flow_imbalance` de BTC en la barra `t-1`, aplicado a ETH/SOL | 1 barra |

Racional por feature:

* **F1/F2** — hipótesis clásica de *order flow imbalance* M-01: desequilibrio
  agresor persistente. Es el análogo tick-level del feature que en V3 dio el
  mejor gross edge (+2.36 bps).
* **F3** — separa *tamaño* de *dirección*: el desequilibrio de clips grandes
  suele informar más que el conteo bruto.
* **F4/F5/F6** — burstiness y aceleración de llegada: la microestructura
  distingue "mucho volumen por pocos trades" de "explosión de prints".
* **F7** — presión intrabar: cerrar por encima del VWAP de la barra indica
  agresor comprador que no fue absorbido.
* **F8** — lead/lag M-08 a resolución de tick, PIT estricto.

## 4. Horizontes y label

Label único: **forward return en bps** `close[t+h]/close[t] - 1`, con
`h ∈ {1, 5, 15, 30, 60}` barras de 5m. Cada hipótesis tiene **un horizonte
primario pre-registrado**; los demás se reportan como contexto y **no** se usan
para promocionar.

| ID | hipótesis | horizonte primario |
| --- | --- | --- |
| A-01 | F1 `signed_flow_imbalance` (dirección determinada en DEV) | 5 barras (25 min) |
| A-02 | F3 `large_trade_imbalance` (dirección en DEV) | 5 barras |
| A-03 | F1 + breakout: `ret_mom_bps > 0` **y** `F1 > +0.3` -> long (simétrico short) | 5 barras |
| A-04 | F5 `interarrival_accel < 0.5` (burst) -> reversión | 5 barras |
| A-05 | F7 `vwap_dislocation_bps` extremo (`|x| > 20 bps`) -> reversión | 5 barras |
| A-06 | F8 `cross_flow_btc` -> ETH/SOL siguiente barra | 1 barra |

**Regla de dirección (idéntica a V3):** el signo empírico se determina en DEV
y se **congela**; se aplica el mismo signo en VAL y OOS. No se invierte la
dirección por split.

## 5. Filtros secuenciales pre-registrados

```text
Filter 0  INFO CONTENT  — monotonicidad de forward return por quintil de feature
                          en DEV (signo estable en >= 4/5 quintiles)
Filter 1  GROSS EDGE    — expectancy bruta por trade > 0 en DEV
Filter 2  COST SURVIVAL — gross - COST_MODEL_V3(BINANCE_SPOT_STANDARD_TAKER) > 0
Filter 3  SPLITS        — DEV > 0, VAL > 0, OOS > 0
Filter 4  COST STRESS   — sobrevive 1.25x y 1.5x
Filter 5  ADMISSION     — §41 + margen material
```

Early stop (§53): si Filter 1 falla, la línea se cierra como `NO_GROSS_EDGE`.

## 6. Coste de admission pre-registrado

`COST_MODEL_V3`, escenario **`BINANCE_SPOT_STANDARD_TAKER`** (taker VIP0, sin
descuentos asumidos), intención de referencia `size = 1,000 USD`,
`liquidity_regime = normal`, horizonte 25 min. El escenario maker **no** es
admission (§13) porque no existe `FillEvidence`.

Se reporta además el coste bajo `MEXC_SPOT_TAKER` como **escenario de venue
alternativo**, solo informativo, para medir cuánto del bloqueo es fee y cuánto
es ausencia de señal. No se promociona una candidata por un venue no
integrado.

## 7. Criterios de admission (§41)

Para ser `PAPER_CANDIDATE` con el coste de admission:

1. net expectancy OOS > 0 **después** de coste realista;
2. `PF_OOS > 1.0`;
3. `n_total >= 100` y `n_OOS >= 30`;
4. DEV > 0, VAL > 0, OOS > 0;
5. sobrevive `1.25x` y `1.5x` con margen (`net > 0.25 * coste`);
6. estabilidad por activo: no puede venir de un único activo;
7. sin violaciones PIT;
8. muestra declarada suficiente para la afirmación hecha.

Estados permitidos (§PHASE 6): `NO_GROSS_EDGE`, `COST_KILLED`, `UNSTABLE`,
`INSUFFICIENT_DATA`, `EXECUTION_MODEL_REQUIRED`, `RESEARCH_CANDIDATE`,
`PAPER_CANDIDATE`.

## 8. Qué NO se hará

* No grids de parámetros, no ML, no búsqueda de features.
* No usar OOS para elegir dirección, umbral ni feature.
* No presentar gross edge como net edge.
* No cambiar el label por horizonte porque un resultado sea negativo.
* No tocar el core runtime (§50).
* No declarar nada sobre datos forward que aún no existen (§63).

## 9. Errata

Solo correcciones de **metodología**, fechadas, nunca de umbrales tras
resultados.
