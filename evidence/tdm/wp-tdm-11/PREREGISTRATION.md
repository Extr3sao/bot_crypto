# WP-TDM-11B — PREREGISTRATION

**Hipótesis:** `TDM11-H1` · **RFC:** RFC-TDM-011 · **Estado:** `PREREGISTERED` / `AWAITING_NEW_DATA`
**Commit fijado:** `e67194e79a42aef2a2ded3aca21ac4a0ea3689c5`
**Congelado:** 2026-10-25T11:52Z (ver `prereg_freeze.json` para SHA-256 y marca temporal)
**Números de potencia:** `prereg.json` (script `scripts/tdm11_prereg.py`)

> Este documento se congela **antes** de abrir cualquier barra posterior a
> `2026-10-24T16:00:00Z`. Ninguna barra confirmatoria ha sido leída en el momento de la firma.

---

## 1. Hipótesis

**H0:** la expectativa neta de la regla es `≤ 0 bps` por operación tras costes aplicables.
**H1:** la expectativa neta es `> 0 bps` por operación, con intervalo unilateral al 95 % que excluya el cero.

**Unidad:** bps netos por operación sobre notional normalizado. El coste se aplica **una sola vez** como
constante round-trip restada del edge bruto; no se infiere PnL de cartera (no hay sizing en este WP).

**Umbral económico prefijado:** `net_bps_per_trade > 0` con `cost = 23,7906 bps`
(`BINANCE_SPOT_STANDARD_TAKER`, 1 000 USD, 30 min). No se rebaja el coste para aprobar.

---

## 2. Combinación primaria — una sola, congelada

| Elemento | Valor |
| --- | --- |
| Familia | `momentum` (`MomentumFamily`, params del repo: MACD 12/26/9, momentum 10 barras, umbral 0,5 %) |
| Timeframe | **5m** (barra de 5 min; horizonte exacto, sin colapso de barras) |
| Dirección | **SHORT** únicamente |
| Filtro de régimen | `regime_trend == "down"` en la barra de decisión |
| Activos | BTC/USDT, ETH/USDT, SOL/USDT (spot Binance, klines públicas) |
| Entrada | **open de la barra `i+1`** tras decidir en el cierre de la barra `i` |
| Salida | close de la barra `i+1+6` (**30 min**) |
| Posición | una a la vez, secuencial, sin piramidación, sin stops ni take-profits |
| Ventana de decisión | `[2026-06-25T00:00Z, 2026-09-25T00:00Z)` para potencia; confirmatoria aún no abierta |

### 2.1 Por qué esta combinación (y qué sesgo arrastra)

La idea **nace de mirar HOLD** (ventana de veredicto de TDM-08/10, ya expuesta). Este documento **no**
pretende que la selección sea ciega: la declara.

Criterio de elección, fijado antes de calcular la potencia: entre las cubetas `trend=down` con
**edge bruto positivo y `n ≥ 40`** en el HOLD, elegir la de **mayor n**, con independencia del edge.
Resultado: `momentum@5m` (n=74 en la tabla publicada; 57 SHORT puros; bruto +12,72 bps solo-SHORT).

Alternativas descartadas y por qué:

| Alternativa | Descartada por |
| --- | --- |
| `ema_crossover@1h` down (bruto +23,05, n=29 SHORT) | la celda completa está **falsificada** por TDM-10 (cota superior +2,30 bps con 832 ops); tomar una rebanada del 3,8 % de una celda refutada es selección post-hoc pura |
| `breakout@1h` down | 7 operaciones en la cubeta; además @1h el hold "30 min" colapsa a 60 min (defecto D-07) |
| `volatility@5m` down | 4 operaciones, **1** de ellas corta |
| `trend@15m` down | n=42 pero bruto +10,44 < el de momentum y un solo activo domina la muestra |
| `breakout@30m` high_vol | cubeta de **volatilidad**, no de tendencia; no responde a la hipótesis bajista |

**Sesgo declarado:** es la mejor cubeta observada *ex post* entre ~144 cortes; su edge in-sample está por
debajo del coste incluso en la ventana donde se eligió (net −11,07 bps). Se elige como hipótesis **débil y
falsable**, no como candidata. La evidencia del HOLD es un máximo de ruido, y así se trata.

**Advertencia de gobernanza (G0-6):** la premisa del RFC ("5 de 6 mejores cubetas son SHORT en bajista") se
recomputó y resulta **3 de 6**; el artefacto publicado ni siquiera contiene la dirección. La hipótesis no
hereda evidencia previa verificada.

---

## 3. Contrato de datos y control de fuga

1. **Exposición total:** DEV (2026-06-25→2026-09-25), HOLD (2026-09-25→2026-10-24T15:50Z), todos los cortes
   de TDM-08/10 y el análisis de régimen de este WP se declaran `EXPOSED_FOR_SELECTION`.
2. **Muestra confirmatoria:** barras con `open_time >= 2026-10-24T16:00:00Z` (primer límite de barra
   posterior al instante de sellado del HOLD, `2026-10-24T15:57:44Z`). Ninguna barra anterior entra.
   `CONFIRMATORY_START_MS = 1792857600000`.
3. **Verificación obligatoria antes de evaluar:** hashes, huecos, duplicados, monotonía, UTC, frescura y
   ausencia de solapamiento con `[.., 2026-10-24T16:00Z)`. Un fallo ⇒ `DATA_INTEGRITY_FAILURE`, no veredicto.
4. **Acceso ciego:** durante el desarrollo solo se permiten recuentos y salud de datos (número de barras,
   timestamps, esquema). Ninguna estadística de precios de la ventana confirmatoria antes del análisis
   preregistrado. Un acceso prematuro se registra como contaminación y exige otra muestra.
5. **Sin datos nuevos suficientes** ⇒ `AWAITING_NEW_DATA`; no se sustituye por más backtests del HOLD.

**Punto de corte de régimen (PIT):** `regime_trend(i)` usa exclusivamente barras `≤ i`:
z-score de tendencia sobre 200 barras de log-retornos (`down` si `z < −1,5`), ventana trailing, sin
reconstrucción retrospectiva. `data_time <= decision_time` en todas las barras; entra en `i+1`.

---

## 4. Coste y ejecución

| Concepto | Valor | Clase |
| --- | --- | --- |
| Fee entrada + salida (taker) | 10,0 + 10,0 bps | KNOWN (VIP0, pago en quote) |
| Spread | 1,0 bps (medio spread × 2 patas taker) | **ESTIMATED** (no observado) |
| Slippage | 2,6325 bps | ESTIMATED |
| Impacto | 0,1581 bps | ESTIMATED |
| **Total primario** | **23,7906 bps** | ESTIMATED |
| Borrow / funding del corto | **AUSENTE del modelo** | — |

Escenarios **secundarios, descriptivos, prefijados** (nunca sustituyen al primario): `41,25 bps` (maker
ambas patas con fill p=0,5) y `18,7906 bps` (BNB taker). El `9,25 bps` citado por TDM-10 **no es un
escenario del repo** (G0-5 H-01) y no se usa aquí.

**Regla estadística anti-doble-conteo:** se compara el IC del edge **bruto** contra el coste, o el IC de
`bruto − coste` contra cero. Nunca ambas restas a la vez.

**Lema de independencia del coste (prefijado):** si la cota superior del IC95 del edge **bruto** es `< 0`,
H1 queda refutada para **todo** coste no negativo, incluido el borrow no modelado. Este lema permite emitir
veredicto sin certificar el coste del lado corto, y se aplicará tal cual.

---

## 5. Estadística e incertidumbre

- **Primaria:** media de `net_bps` por operación; IC unilateral 95 % por **bootstrap de bloques**
  (bloques de 1 día de operaciones, 10 000 réplicas, semilla `20261025`). El bootstrap IID se reporta solo
  como sensibilidad, nunca como prueba.
- **Multiplicidad:** una sola hipótesis primaria. Los comparadores del §6 son **descriptivos** y no se
  testean inferencialmente; si alguno se testeara, entraría en Holm y este documento quedaría enmendado
  sin efecto retroactivo. No hay familia de tests secundaria.
- **Potencia (calculada solo con DEV, antes de abrir la ventana confirmatoria):**

| Cantidad | Valor |
| --- | --- |
| sd del edge bruto (DEV, misma regla) | **56,50 bps** |
| inflación por bloques | 1,0049 |
| operaciones/día en régimen bajista | **1,284** |
| **n mínimo (MDE = coste 23,79 bps, α=0,05, potencia 0,80)** | **36 operaciones** |
| ventana mínima equivalente | **28 días** con régimen bajista presente |
| n para resolver un efecto de 15 bps | 89 |
| n para resolver el efecto observado en DEV (12,58 bps) | 127 |
| efecto detectable con n=1 000 | 4,46 bps |

  Fórmula: `n = ((z₀.₉₅ + z₀.₈₀)·sd_bloque / efecto)²`. El mínimo **no se renegociará** tras ver datos.

- **Potencia insuficiente** (`n < 36`) ⇒ `INCONCLUSIVE` con `INSUFFICIENT_SAMPLE`; prohibido agrupar con
  ventanas expuestas para llegar al mínimo.

---

## 6. Comparadores prefijados

| ID | Regla | Uso |
| --- | --- | --- |
| `C0` | No operar (`net = 0`) | umbral económico |
| `C1` | Misma regla SHORT **sin** filtro de régimen | diagnóstico |
| `C2` | Misma regla **ambas direcciones** con filtro bajista | diagnóstico |

---

## 7. Contrato de decisión

| Resultado | Condición exacta |
| --- | --- |
| `RESEARCH_CANDIDATE` | integridad y causalidad PASS · ventana confirmatoria válida y no contaminada · coste verificado **incluido borrow del corto** · `n ≥ 36` · cota inferior IC95 de `net_bps` > 0 · robustez temporal sin hallazgos invalidantes |
| `NO_GO_ALPHA` | evaluación válida que descarta el umbral: cota superior IC95 de `net_bps` < 0, **o** cota superior del edge bruto < 0 (lema §4), **o** `n ≥ 36` con media neta ≤ 0 |
| `INCONCLUSIVE` | `n < 36` · IC cruza cero con potencia suficiente · coste no verificado sin lema aplicable · integridad/contaminación · verificador no independiente |

`RESEARCH_CANDIDATE` **no** autoriza PAPER/LIVE. `NO_GO_ALPHA` rechaza **esta regla y este universo**, no
todo SHORT ni la plataforma.

---

## 8. Qué falsificaría la hipótesis

1. Media neta ≤ 0 con `n ≥ 36` en la ventana confirmatoria.
2. Cota superior del IC95 del edge bruto < 0 en cualquier ventana causal válida (lema §4).
3. Ausencia del efecto en 2 de los 3 activos.
4. Degradación monotónica: que el signo dependa del escenario de coste más barato.

## 9. Inmutabilidad

Este archivo se firma con SHA-256 en `prereg_freeze.json` (timestamp UTC) **antes** del primer acceso a
la ventana confirmatoria. Cualquier cambio posterior es una **enmienda** registrada, sin efecto retroactivo.

**Divulgación:** los números de potencia del §5 se calcularon con DEV, que también produjo la media DEV
(−12,58 bps) visible en `prereg.json`. La media DEV **no** se usó para elegir la regla (la elección usó
solo HOLD), pero se declara que era visible al firmar; el análisis retrospectivo del §10 de
`ROBUSTNESS_REPORT.md` se ejecutó **después** de esta firma y verifica el hash antes de correr.
