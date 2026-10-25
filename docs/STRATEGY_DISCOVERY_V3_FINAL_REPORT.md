# STRATEGY-DISCOVERY-V3 — FINAL REPORT (§49)

Fecha: 2026-09-26 · HEAD base: `a910f8d` · Cierre: `31dd261` + commits de resultados.

## 1. RUNTIME STATUS — SANO (sin cambios)

El motor de ejecución paper sigue maduro: V2 cerrado formalmente por
deadline del loop con recovery real de una suspensión de 8.4h del host
(133 restarts RECOVERED, 0 MISMATCH/FATAL, 0 duplicaciones económicas,
99.98% HEALTHY en 6004 ciclos). DEF-205 sin recurrencia post-fix.
El fallo de las estrategias NO es un fallo del runtime.

## 2. STRATEGY STATUS — 6 FAMILIAS AUDITADAS + 5 HIPÓTESIS NUEVAS: 0 ADMISIBLES

- 6 familias runtime (5m) con diagnóstico fino: **mean_reversion tiene
  edge bruto REAL** (+236.92$ / +1.49 bps por trade a coste cero, PF
  1.057) — la única. Las otras 5 son NO_GROSS_EDGE (gross negativo sin
  costes). Ninguna sobrevive a los 12 bps round-trip → 6/6 REJECT
  confirmado, ahora con taxonomía exacta (1 COST_KILLED + 5 NO_EDGE).
- 5 hipótesis nuevas pre-registradas (D-01..D-05): REJECT (ver §4).
- Exit research (D-06): gate no activado — ni siquiera el edge real de
  mean_reversion produce MFE≫realizado, y la asimetría de momentum
  (+6.5 bps) sigue bajo la barrera. El problema es de SEÑAL vs COSTES,
  no de exits.
- Detalle completo: STRATEGY_DISCOVERY_V3_RESULTS.md/.json +
  STRATEGY_DISCOVERY_V3_ADMISSION.md/.json.

## 3. PAPER V2 STATUS — CERRADO (V2_12H_WALL_REACHED)

Escalón real: **9.29h de runtime** (17.69h wall − 8.40h suspensión del
host). El objetivo nominal de 12h se alcanzó en wall-clock, no en runtime
efectivo; no se certifica V2_12H_STABLE. Economics as-run −524.55$
(dominado por el trade DEF-205 a precio 0); ex-DEF-205: −24.05$ en 18
trades (PF 0.54) — consistente con estrategia sin edge y runtime sano.

## 4. DISCOVERY STATUS — STRATEGY_DISCOVERY_V3_NO_EDGE_FOUND

Resultado válido según §1/§45/§46: conjunto razonable de hipótesis
explorado (24 experimentos registrados), 0 candidatas. Nada se activa.
DO_NOT_ADOPT para todas las líneas evaluadas.

Hallazgos estructurales (más valiosos que cualquier backtest individual):

1. **Barrera de costes**: 12 bps round-trip BASE. El gross edge por trade
   de CUALQUIER mecanismo probado (6 familias × 4 TFs, 3 candidatas
   nuevas, 12 celdas de régimen) tiene techo +8.9 bps — insuficiente.
   La única señal con edge bruto confirmado (mean_reversion@5m,
   +1.49 bps) queda 8× bajo la barrera.
   **Consecuencia cuantificada**: con costes ≤ 3 bps RT (maker/rebate),
   mean_reversion@5m y las celdas 15m/30m de trend/mean_rev/volatility
   pasarían de muertas a viables-como-hipótesis. El factor limitante del
   sistema HOY es el coste de ejecución, no la ausencia total de señal.
2. **El horizonte no salva solo**: subir de 5m a 15m/30m convierte el
   gross de trend/mean_reversion en positivo (+1.3 a +8.9 bps) pero NO
   escala hasta la barrera; en 1h vuelve a ser negativo. La mejora
   signal/noise existe pero es pequeña.
3. **Sin reversión explotable**: la reversión post-excursión extrema
   (D-02) y el momentum relativo (D-04) no existen en BTC/ETH/SOL en
   2026-03..09 con estas definiciones.
4. **Régimen inestable**: ninguna celda (familia×TF×régimen-vol) mantiene
   el signo de su expectancy entre DEV y VAL (11/12 cambian de signo).
5. **MFE≈MAE transversal**: salvo momentum (+6.5 bps de asimetría, aún
   bajo la barrera), las señales no producen excursión favorable
   dominante → el problema es de SEÑAL+COSTES, no de exits. Cualquier
   ingeniería de TP/SL sobre estas señales es pintar sobre ruido.

## 5. Decisión y siguiente fase recomendada (§46)

El cuello de botella sigue siendo SEÑAL, ahora con diagnóstico fino: la
clase de señales técnicas de corto horizonte sobre cripto majors, con
costes minoristas (12 bps RT), no muestra edge bruto suficiente. Líneas
futuras con potencial real (fuera del alcance de V3):

- **Costes más bajos**:_maker/rebate o fees < 2 bps RT cambian la barrera
  de 12 → ~3 bps y las celdas 15m/30m de trend/mean_rev (gross +2 a +9
  bps) pasan a ser viables COMO HIPÓTESIS (requeriría venue/API nuevo y
  pre-registro fresh).
- **Datos nuevos**: order flow/funding/basis/depth (no OHLCV) como
  features de mecanismo real; el universe OHLCV-5m está agotado.
- **Horizontes de días**: swing multi-day sobre majors con menos trades
  y moves > 12 bps por diseño; requiere ventanas de datos más largas.
- **Re-especificación D-03** con spec alcanzable, pre-registrada en fase
  nueva (la compresión estricta actual no ocurre nunca).

No se recomienda otra campaña de indicadores OHLCV intradía sin uno de
estos cambios estructurales.

## 6. Evidencia

- docs/STRATEGY_DISCOVERY_V3.md (pre-registro, ANTES de resultados)
- docs/STRATEGY_DISCOVERY_V3_EXPERIMENTS.md (registro, fingerprint)
- docs/STRATEGY_DISCOVERY_V3_RESULTS.md/.json · _ADMISSION.md/.json
- reports/strategy-baseline/: COST_BARRIER.json, TIMEFRAME_AUDIT.json,
  DISCOVERY_CANDIDATES.json, REGIME_ANALYSIS.json, MULTI_FAMILY_RESULTS_*.json,
  TRADES_*.csv, diag_*.log
- scripts/: multi_family_backtest.py, multi_tf_backtest.py,
  resample_baseline_data.py, cost_barrier.py, discovery_candidates.py,
  regime_analysis.py
