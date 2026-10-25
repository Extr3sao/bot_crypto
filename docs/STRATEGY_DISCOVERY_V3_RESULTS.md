# STRATEGY-DISCOVERY-V3 — resultados (§18-§22)

> Todos los resultados provienen del engine de parity (clases runtime) o de
> los runners de candidatas con mecánica idéntica, sobre el dataset
> fingerprint `e44a7ab1933362096dfd6f5fd36fb560` (W1-W7, 2026-03..2026-09-24,
> BTC/ETH/SOL). ZERO_COST es diagnóstico, nunca admission (§17).
> Costes BASE: 12 bps round-trip (fees 10 + slippage 2). 2X_COST: 24 bps.
> STRESSED_SLIPPAGE: 32 bps.

## 1. Resumen ejecutivo de hipótesis

| Hipótesis | Mecanismo | Resultado | Clasificación (§19) |
|---|---|---|---|
| D-01 horizonte 15m/30m/1h | menos ruido/turnover por decisión | gross positivo aparece (trend/mean_rev 15m-30m) pero techo +8.9 bps < 12 bps barrera | COST_KILLED |
| D-02 reversión vol-z (15m) | reversión tras excursión 2σ·ATR | gross −11.51$ en 31 trades (ZERO_COST) | NO_GROSS_EDGE |
| D-03 squeeze breakout (30m) | compresión→expansión confirmada | 0 señales en 187k barras 5m→30m | INTESTABLE (spec demasiado estricta; no se re-ajusta, §23) |
| D-04 momentum relativo (1h) | cross-sectional leader | gross −12.12$ en 191 trades (ZERO_COST, PF 0.95) | NO_GROSS_EDGE |
| D-05 régimen PIT (12 celdas) | condicionar familia×TF×regimen vol | 0/12 celdas pasan gate (DEV>12bps ∧ VAL>0) | REGIME_FRAGILE |
| D-06 exit research | gate: señal viva con MFE≫realizado | GATE NO ACTIVADO: MFE≈MAE en todas las celdas | NO_GATE (no aplicable) |

**Familias runtime a 5m (diagnóstico de rechazos, ZERO_COST)**: sorpresa
principal — mean_reversion SÍ tiene edge bruto real (+236.92$ en 3190
trades, PF 1.057 = +1.49 bps/trade) pero queda 8× bajo la barrera de 12
bps → COST_KILLED. Las otras 5 familias tienen gross negativo incluso a
coste cero (NO_GROSS_EDGE). §42 queda respondido: trend NO tenía señal
que los costes destruyeran (−106.17$ a coste cero). Detalle en §3.

## 2. Transaction-cost barrier (§5) — COST_BARRIER.json

Movimiento mediano necesario para cubrir el round-trip BASE (12 bps):

| TF | BTC | ETH | SOL |
|---|---|---|---|
| 5m | 1.8 barras (~9 min) | 1.4 | 1.1 |
| 15m | 1.3 (~33 min) | 1.0 | 0.8 |
| 30m | 0.9 (~45 min) | 0.7 | 0.6 |
| 1h | 0.6 (~36 min) | 0.5 | 0.4 |

Lectura: la barrera NO es alcanzable por horizonte corto — cualquier señal
con expectancy bruta < 12 bps/trade muere. El TP fijo 0.75% (75 bps) exige
WR·payoff > 0.16 neto de la estructura; con MFE≈MAE observado la señal no
aporta dirección que lo garantice. Pregunto §6: subir el TF NO resuelve
porque el edge bruto disponible (ver §4) no escala con el horizonte.

## 3. Diagnóstico 5m por familia (ZERO_COST; lección de los rechazos, §4/§19)

| familia | trades | gross $ | bps/trade | MFE% | MAE% | PF | WR% | clasificación (§19) |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| mean_reversion | 3190 | **+236.92** | +1.49 | 0.466 | 0.474 | 1.057 | 51.2 | **COST_KILLED** (edge real, 8x bajo la barrera) |
| breakout | 2426 | −10.19 | −0.11 | 0.536 | 0.483 | 0.997 | 40.6 | NO_GROSS_EDGE (breakeven exacto) |
| trend | 1291 | −106.17 | −1.65 | 0.716 | 0.723 | 0.962 | 56.0 | NO_GROSS_EDGE |
| volatility | 520 | −123.12 | −4.73 | 0.566 | 0.584 | 0.870 | 43.7 | NO_GROSS_EDGE |
| momentum | 2526 | −237.89 | −1.88 | 0.565 | 0.500 | 0.941 | 40.5 | NO_GROSS_EDGE (MFE>MAE +6.5 bps insuficiente) |
| ema_crossover | 1725 | −393.37 | −4.56 | 0.406 | 0.357 | 0.805 | 29.0 | NO_GROSS_EDGE (el peor) |

Respuesta a §4 (por qué fallaron las 6):
- **COST_KILLED (1/6)**: mean_reversion ES la única con señal bruta real
  (+1.49 bps/trade a coste cero) — pero 8× por debajo de los 12 bps de
  coste round-trip. Con costes de maker (~2-3 bps RT) sería viable COMO
  HIPÓTESIS (ver FINAL_REPORT §5).
- **NO_GROSS_EDGE (5/6)**: trend, breakout, volatility, momentum,
  ema_crossover no tienen expectancy bruta positiva ni siquiera sin
  costes. §42 queda respondido: trend NO tenía señal que los costes
  destruyeran.
- **MFE/MAE (§20)**: momentum muestra la única asimetría MFE>MAE
  relevante a 5m (+6.5 bps) — capturarla al 100% seguiría bajo la
  barrera, así que el gate de exit-research (D-06) NO se abre en ningún
  caso. El problema transversal es de SEÑAL, no de exits.

## 4. Timeframe audit (D-01) — TIMEFRAME_AUDIT.json

ZERO_COST gross bps por trade (gross$/(trades·500$)·1e4):

| familia | 15m | 30m | 1h |
|---|---|---|---|
| ema_crossover | −1.12 | −0.73 | −0.96 |
| momentum | −3.97 | −2.61 | −2.33 |
| breakout | −1.82 | −1.79 | −0.22 |
| trend | +1.28 | +2.21 | −1.25 |
| mean_reversion | +2.71 | +5.47 | −2.23 |
| volatility | −7.06 | +8.91 | +6.28 |

- El edge bruto NO escala monótonamente con el horizonte: pico en 15m-30m
  para trend/mean_rev, retorno a negativo en 1h.
- Techo observado: +8.91 bps (volatility@30m) < 12 bps barrera BASE.
- OOS n por celda 17-388; frequency (§7): 96-3233 trades/semana-dataset →
  ninguna celda está en 1 trade/month.
- RESPUESTA §6/§43: el aumento del horizonte reduce turnover y mejora el
  PF bruto de 2 familias, pero NO suficiente para sobrevivir costes. 5m
  deja de ser el único TF auditado; ninguno se activa.

## 5. Candidatas D-02..D-04 — DISCOVERY_CANDIDATES.json

- D-02_vol_z_rev (15m): 31 trades totales (BASE) — población mínima;
  gross −13.16$, ZERO_COST −11.51$. La reversión tras |z|≥2 no existe en
  este universo/horizonte (cripto majors continúan, no revierten).
- D-03_squeeze_breakout (30m): 0 señales. La especificación (compresión
  estricta + cierre fuera de rango 12 barras) no ocurre en el dataset.
  Intestable; re-especificar sería mover los palos tras ver resultados.
- D-04_rel_momo (1h): 186-191 trades; ZERO_COST gross −12.12 (PF 0.95),
  BASE net −121.73. El liderazgo relativo 24h no predice continuidad.
- D-04 nota de diseño: z_rel>1.0 fue pre-registrado; sin grid para
  "salvar" la hipótesis.

## 6. Régimen condicional (D-05) — REGIME_ANALYSIS.json

Gate pre-registrado: ZERO gross>12 bps en DEV (n≥30) ∧ ZERO gross>0 en VAL.

| celda | DEV bps (n) | VAL gross$ (n) | OOS bps (n) | gate |
|---|---|---|---|---|
| trend_15m HIGH | −4.08 (3049) | +481.91 (977) | +3.22 (548) | ✗ |
| trend_15m LOW | −6.70 (1211) | −164.51 (296) | −9.06 (136) | ✗ |
| trend_30m HIGH | −9.60 (2402) | +590.76 (955) | +1.50 (522) | ✗ |
| trend_30m LOW | +0.54 (1598) | −80.14 (266) | −25.39 (119) | ✗ |
| mean_rev_15m HIGH | +6.14 (2033) | −94.37 (796) | +3.87 (452) | ✗ |
| mean_rev_15m LOW | −9.05 (1774) | +26.71 (885) | +0.45 (294) | ✗ |
| mean_rev_30m HIGH | +7.89 (1118) | +227.56 (614) | −1.09 (326) | ✗ |
| mean_rev_30m LOW | +4.07 (1064) | −120.51 (413) | −19.88 (134) | ✗ |
| volatility_15m HIGH | −20.27 (234) | +5.70 (144) | −25.17 (84) | ✗ |
| volatility_15m LOW | −13.06 (383) | −108.38 (176) | +17.99 (80) | ✗ |
| volatility_30m HIGH | +7.44 (205) | −58.84 (108) | −5.79 (88) | ✗ |
| volatility_30m LOW | +25.49 (224) | −107.82 (100) | +17.27 (48) | ✗ |

Patrón dominante: DEV y VAL no comparten signo en ninguna celda → la
dependencia de régimen es inestable entre años/ventanas (REGIME_FRAGILE).
La celda con mejor DEV (volatility_30m LOW +25.5 bps) falla VAL por −107$.

## 7. Filtros secuenciales (§22) — estado final

- FILTER 1 (gross): D-02, D-04 REJECT; 4/6 familias 5m REJECT (gross<0);
  3 celdas D-01 con gross>0 pero <12 bps → FILTER 2.
- FILTER 2 (cost survival): D-01 REJECT (techo 8.9 bps < 12 bps).
- FILTER 3-6: sin supervivientes, no alcanzados por ninguna candidata.

## 8. Frecuencia (§7/§44)

Trades/día por candidata (dataset 210 días): D-02 ≈ 0.15, D-04 ≈ 0.9,
celdas D-01 0.5-15. Ninguna en extremos patológicos; irrelevante al no
existir edge neto.
