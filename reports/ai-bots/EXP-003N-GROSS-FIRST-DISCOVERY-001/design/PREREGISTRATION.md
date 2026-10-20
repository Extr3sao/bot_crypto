# PREREGISTRATION — EXP-003N (gross-first strategy discovery)

- Experimento: `EXP-003N-GROSS-FIRST-DISCOVERY-001`
- Protocolo congelado en disco: **2026-10-20T18:38:16Z**, sobre el commit `9800925`
- Fuente de verdad legible por máquina: [`DESIGN.json`](DESIGN.json) (sello `AI_BOTS_003N_DESIGN_V1`)
- Inventario congelado: [`STRATEGY_UNIVERSE.json`](STRATEGY_UNIVERSE.json), [`STRATEGY_UNIVERSE.md`](STRATEGY_UNIVERSE.md)
- Generador: `scripts/exp_003n_preregister.py` (no lee ni un precio; solo hashea entradas y escribe el protocolo)

## 0. Aviso de procedencia — esto NO es una preregistración prospectiva

Hay que decirlo antes que nada, porque cambia cómo se puede leer todo lo que sigue:

- El protocolo se congeló en disco a las **18:38:16Z** y el screening se ejecutó a las
  **19:32:34Z**, de modo que la secuencia en el sistema de ficheros es *protocolo → números*.
- Pero este documento y `DESIGN.json` **entraron en Git después** de que existieran
  `analysis/SCREENING.json`, `analysis/VALIDATION.json` y `analysis/DECISION.json`.
  El commit que los publica lo dice en su mensaje.
- Consecuencia: el congelamiento está **anclado por contenido** (el verificador comprueba el
  SHA-256 de `DESIGN.json` contra el que quedó escrito en `SCREENING.json`) pero **no está
  anclado por tiempo en Git**. Cualquier afirmación del tipo «este umbral se fijó antes de
  conocer el resultado» se apoya en la traza local de ejecución, no en una firma de Git
  previa al análisis.
- Por tanto el análisis de este experimento es **retrospectivo con protocolo declarado**, no
  prospectivo. `RUN_REPORT.md`, `FINAL_REPORT.md` y `RUN_REPORT.json` lo repiten.

Lo que sí queda cerrado y comprobable a posteriori:

1. `DESIGN.json` no se puede regenerar con otro contenido: `scripts/exp_003n_preregister.py`
   se niega a sobrescribir un diseño existente, y `--check` recalcula los hashes de sus
   entradas (dataset, módulos de familia, configs, predecesor) y falla si algo derivó.
2. `SCREENING.json` guarda el `design_sha256` con el que se ejecutó; el verificador compara
   ese valor con el fichero publicado.
3. Ninguna partición, horizonte, coste ni puerta se ha tocado después del screening: el
   `--check` del preregister y la comprobación V3 del verificador lo detectarían como
   discrepancia de hash, no como una opinión.

## 1. Pregunta

> ¿Existe algún mecanismo **ya implementado en este repositorio** cuyo ingreso bruto por señal
> cubra su propio coste de ida y vuelta sobre barras válidas en su punto en el tiempo?

El experimento anterior (`EXP-003M`) cerró la puerta al único candidato que sobrevivió a
`EXP-003L`: incluso con el modelo de *fills* maker más generoso, `5m/mean_reversion` produce
como techo 0.2669 USDT por operación cerrada frente a un suelo de comisión de 0.75 USDT
(cobertura 0.356x). Ese veredicto no dice «el ejecutor estaba mal»: dice que el **bruto** no
paga una vuelta completa. Modelar mejor la ejecución no crea ingreso; solo puede capturar el
que ya existe. Por eso este experimento mide el bruto primero y no modela *fills* en absoluto.

## 2. Hipótesis evaluadas (y la nula)

Cada hipótesis se declara con su mecanismo económico y con la familia que la implementa hoy.
Ninguna se ha añadido al repositorio para este experimento; el inventario de la Fase 1
clasifica lo que ya existía.

| id | hipótesis | mecanismo económico | implementación medida |
| --- | --- | --- | --- |
| `H1` | La continuación de tendencia en `5m/1h/4h` supera el coste de ida y vuelta en majors. | Persistencia de flujo de órdenes y ajuste lento de precios tras un movimiento direccional. | `momentum`, `trend`, `ema_crossover` (lane A) |
| `H2` | La expansión de volatilidad y la ruptura de rango pagan el coste en algún horizonte. | Asimetría de colas: la ruptura de un rango comprimido atrae volumen direccional. | `breakout`, `volatility` (lane A), `vol_regime_breakout` (lane B) |
| `H3` | La reversión a la media en horizontes **distintos** de `5m` (nueva hipótesis, sin rehabilitar `5m/mean_reversion`) paga el coste. | Sobrerreacción a un shock de liquidez que se corrige en horas. | `mean_reversion@1h`, `mean_reversion@4h`, `mean_reversion_vol_liq`, `trend_pullback` (lane B) |
| `H0` | **Nula:** una señal de moneda al aire con la misma cadencia y la misma política de salida falla las puertas S1–S4. | Si `H0` pasase, las puertas estarían midiendo costes y no ventaja. | `S7_null_baseline` en el verificador |

Candidatos **excluidos por evidencia previa** (no se re-miden: gastar la muestra en un
mecanismo ya refutado es selección, no descubrimiento):

- `cand001`–`cand003`: `REJECTED_INITIAL_EXPERIMENT` con expectativa bruta por operación negativa.
- `cross_sectional_rotation`: `REJECT` en WP-EDGE-015 y degenerado con tres activos (una
  rotación top-k sobre BTC/ETH/SOL es una regla de tendencia de un activo con pasos extra).
- `maker_only_spread_capture`: `DEFER_NO_FILL_MODEL`; `EXP-003M` ya midió su lado de *fill*.

## 3. Baseline y configuración experimental

- **Baseline de comparación:** el propio suelo de costes. Toda celda se compara contra
  `20.0 bps` de ida y vuelta (VIP0 sin BNB) y contra `24.79 bps` / `27.31 bps` de coste
  completo (`BTCUSDT`/`ETHUSDT` tier 1, `SOLUSDT` major, stake 500 USDT). Un bruto que no
  cubre el suelo no se compara con nada más: está fuera.
- **Baseline estadístico:** `H0`, la señal de moneda al aire con la misma cadencia y salida.
- **Configuración:** las clases de familia del repositorio, sin reimplementar nada, sobre
  `config/runtime.yaml`, `config/risk.yaml` y `config/vision.yaml` congelados por SHA-256 en
  `DESIGN.json → invariants.config_sha256`.
- **Activos:** `BTCUSDT`, `ETHUSDT`, `SOLUSDT` (spot Binance, liquidez suficiente para 500
  USDT sin impacto material — el propio modelo de coste lo cuantifica).
- **Timeframes:** lane A `5m`, `1h`, `4h`; lane B `1h`, `4h` (las familias de WP-EDGE-015 se
  parametrizan en horas).
- **Horizontes de retorno bruto:** `1, 3, 6, 12, 24, 48` barras.
- **Política de salida (para la vista de operación cerrada):** entrada en la apertura de la
  barra siguiente a la de decisión, salida en la apertura 12 barras después o en el stop si se
  toca antes; `ATR(14) × 2.0`; sin objetivo; intrabar `stop_first`.

## 4. Datos, periodos y particiones

Dataset congelado de `EXP-003K` (Binance spot `/api/v3/klines`, velas de 1 minuto), regenerable
con `scripts/exp_003j_dataset.py --fetch`. La procedencia queda fijada por estos SHA-256, que
son los que `DESIGN.json` guarda y los que el verificador recalcula (V1):

| símbolo | fichero | bytes | SHA-256 |
| --- | --- | ---: | --- |
| `BTCUSDT` | `BTCUSDT.1m.jsonl.gz` | 1 474 761 | `7fbdfefa12785bb025d525994466b5a64d5c0668d6ff997f5f7566bc42d13814` |
| `ETHUSDT` | `ETHUSDT.1m.jsonl.gz` | 1 375 601 | `cf04dc37617a0998016fcd7edfb9b2a77c9aa5fa656bbb54422805a5964650a6` |
| `SOLUSDT` | `SOLUSDT.1m.jsonl.gz` | 1 077 312 | `33342aacc2ac75f897e2c9df2602a41d340c96ed08cd683dbd3871c3c7c60c32` |

Manifiesto del dataset: `06339ca29a2334fb95d4c3773c7ef8b6f27b524c274dbd37c1e708704cf654ba`.

| partición | inicio (UTC) | fin (UTC) | uso |
| --- | --- | --- | --- |
| `RESEARCH` | dataset completo hasta `2026-08-06T00:00:00Z` | — | soporte de señal y calibración de descriptores |
| `IS` | `2026-06-21T00:00:00Z` | `2026-07-11T00:00:00Z` | **selección** del horizonte (S1, S4) |
| `VAL` | `2026-07-11T00:00:00Z` | `2026-07-26T00:00:00Z` | replicación y puerta económica (S2, S3) — no se eligió nada aquí |
| `TEST` | `2026-07-26T00:00:00Z` | `2026-08-06T00:00:00Z` | reservado para no mirarlo al decidir |
| `HOLDOUT` | `2026-08-06T00:00:00Z` | `2026-08-20T00:00:00Z` | **CERRADO** — ni una barra, señal, operación o estadístico lo toca |

El holdout no se usa en este experimento en ninguna forma: el runner corta en
`holdout_start_ms` y el verificador rechaza cualquier fila posterior (V4 y el control
`holdout_injection`).

## 5. Métricas

**Primaria:** ingreso bruto medio por señal en bps (retorno firmado desde la apertura de la
barra siguiente a la de decisión hasta la apertura `h` barras después), por celda
`(familia, timeframe, símbolo, horizonte)`, neto de coste completo en `VAL`, con su intervalo
bootstrap.

**Secundarias:**

- bruto por **operación cerrada** (lane A con la política de salida; lane B por construcción),
- frecuencia: señales por día,
- acierto, profit factor y distribución de resultados,
- neto por señal y por operación cerrada tras coste completo,
- sensibilidad a coste (0x, 1x, 2x) y a tamaño de posición,
- estabilidad temporal por bloque y por régimen,
- corrección por comparaciones múltiples (Benjamini-Hochberg, `q = 0.10`).

**Estadística:** bootstrap de bloques móviles sobre señales ordenadas en el tiempo, bloque de
5 días, 10 000 remuestras, `alpha = 0.05`, semilla `20261020`, unidad = bps por señal.

## 6. Costes

- Comisión spot VIP0: **10.0 bps por lado** → suelo comparable de ida y vuelta **20.0 bps**
  (15.0 bps con descuento BNB).
- Coste completo por símbolo, dos patas, stake 500 USDT, con `cost_for` de
  `trading_bot.research.economic_recovery.alpha15` (el mismo modelo que `EXP-003L` y
  `EXP-003M`): comisión + medio spread + slippage + impacto.
- **La puerta es el coste completo; el suelo de comisión es el mínimo con el que se compara
  para descartar.** Una celda que solo cubre el suelo de comisión no pasa S3.

## 7. Puertas, criterios de aceptación y de parada

| puerta | criterio | si falla |
| --- | --- | --- |
| `S0` muestra | ≥ 50 señales en `RESEARCH`, ≥ 20 en `IS`, ≥ 15 en `VAL` | `INSUFFICIENT_EVIDENCE`, nunca `PASS` |
| `S1` existencia | en `IS`, media del retorno firmado > 0 en algún horizonte **y** cota inferior bootstrap 95 % > 0 | `REJECT` |
| `S2` replicación | el mismo horizonte tiene media > 0 en `VAL` | `REJECT` |
| `S3` economía | media bruta en `VAL` − coste completo de ida y vuelta > 0 **y** bruto ≥ suelo de comisión | `REJECT` |
| `S4` múltiples | la celda sobrevive Benjamini-Hochberg `q = 0.10` dentro de la familia de test de su etapa | `REJECT` |
| `S5` holdout | ninguna fila, señal, operación o estadístico cubre `2026-08-06 → 2026-08-20` | experimento inválido |
| `S6` gobernanza | `config/runtime.yaml` sigue en paper con `live_trading_enabled: false`, cero órdenes live, ningún límite de riesgo tocado | experimento inválido |
| `S7` baseline nulo | la señal de moneda al aire con la misma cadencia y salida falla `S1`–`S4` | las puertas están mal calibradas |

| veredicto | regla |
| --- | --- |
| `ADVANCE_TO_VALIDATION` | `S1`, `S2`, `S3`, `S4` se cumplen y la vista de operación cerrada en `VAL` es neta positiva tras coste completo |
| `EXPERIMENT` | `S1` se cumple y `S2`/`S3` no: la señal lleva información que esta muestra no convierte en dinero |
| `INSUFFICIENT_EVIDENCE` | falla `S0`, o la medición depende de una entrada que el experimento no puede verificar |
| `REJECT` | falla `S1`, o `S1` se cumple pero `S3` muestra que el bruto no cubre ni el suelo de comisión |
| `NO_VIABLE_CANDIDATES` | ninguna celda llega a `ADVANCE_TO_VALIDATION` |

**Criterio de parada del experimento:** se detiene el barrido cuando todas las celdas
congeladas tienen veredicto. No hay búsqueda iterativa de parámetros: si ninguna celda avanza,
el resultado es `NO_VIABLE_CANDIDATES` y se publican las hipótesis refutadas con su déficit
medido. **No se optimiza para obtener un `PASS`.**

## 8. Controles contra look-ahead, leakage y overfitting

- **Punto en el tiempo:** cada familia se llama con una ventana que termina en la barra de
  decisión; el retorno se mide desde la apertura de la barra **siguiente**, nunca desde el
  cierre de la de decisión.
- **Sin contaminación de partición:** el horizonte se elige en `IS`; `VAL` es un bloque que no
  participó en la elección; `TEST` no se mira al decidir.
- **Holdout cerrado** por código, no por disciplina: el runner corta y el verificador rechaza.
- **Corrección por múltiples comparaciones** obligatoria (`S4`), con el conjunto de test
  declarado por etapa; el control `multiple_testing_inoperative` demuestra que sin corrección
  pasarían 84 celdas frente a 1 con `q = 0.10`.
- **Baseline nulo** (`S7`) para separar «costes medidos» de «ventaja medida».
- **Control de coste:** `cost_omitted` demuestra que 6 celdas pasarían una puerta de coste cero
  y fallan la real; `cost_below_floor` comprueba que el coste mínimo de ida y vuelta
  (24.79 bps) no está por debajo del suelo (20.0 bps).
- **Sin selección por el mejor backtest:** la unidad de decisión es la celda congelada, no el
  máximo de una superficie explorada; no hay barrido de parámetros en este experimento.
- **Trazabilidad de entradas:** hashes de dataset, módulos de familia y configs en
  `DESIGN.json`; el verificador falla si alguno deriva (V1, V2, V3).

## 9. Verificación independiente

- `BUILDER != VERIFIER`: `scripts/exp_003n_verify.py` no comparte código con
  `exp_003n_preregister.py`, `exp_003n_screen.py`, `exp_003n_validate.py` ni
  `exp_003n_report.py`; recalcula desde las barras crudas.
- Comprueba 12 cosas (V1–V12) y ejecuta 10 controles negativos; `FALSE_SUCCESS = 0` significa
  que ningún veredicto puede sobrevivir si su propio número lo contradice.
- Regla de precedencia aplicada:
  `REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > ASSUMPTION`.
  Este experimento vive en el escalón de *execution evidence* offline: no hay ejecución real
  de órdenes, y por eso **no puede** declarar rentabilidad demostrada ni promoción a paper.

## 10. Gobernanza

```
LIVE_TRADING=DISABLED
TRADES_AUTHORIZED=0
PAPER_PROMOTION=NOT_AUTHORIZED
OOS_HOLDOUT=CLOSED
RISK_LIMITS_CHANGED=0
BUILDER_IS_NOT_VERIFIER=1
```
