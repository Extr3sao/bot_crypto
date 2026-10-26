# MULTI_STRATEGY_FINAL_REPORT — ENABLEMENT-V1

> HEAD antes: 7b2c02d · HEAD final: ver git log · FALSE_SUCCESS: 0

## 1. Gate 0 — estado de PAPER-BURN-IN-V2

El run V2 SIGUE EJECUTÁNDOSE (loop v3 autónomo, deadline propio ~03:09,
span ~8.5h al cierre de esta fase). No se interrumpió: su certificación
12h vale más que acelerar el enablement. Escalón certificado hasta ahora:
**V2_6H_STABLE+** (100% HEALTHY, 78+ restarts RECOVERED, 0 duplicaciones).
DEF-205 post-fix: 0 exits a precio 0 desde el fix (validación en curso;
completa tras el reset diario UTC que libera el lockout).
El enablement runtime (map/router/portfolio) NO se tocó: el burn-in debe
correr sobre el código que empezó a certificar.

## 2. Causa demostrada del bloqueo multi-strategy (§6)

Triple + defecto de wiring (MULTI_STRATEGY_ROUTING_AUDIT.md):
1. Router single-select (retorna 1 best, nunca N elegibles)
2. Map-order + `regimes: []` universal de ema_crossover
3. `build_portfolio(max_per_correlation_group=1)` colapsa N señales a 1/asset
4. **DEF-206**: `_default_indicators` no provee las claves de las otras 5
   familias → generate()=[] siempre (muerte silenciosa por inanición)

## 3. Parity (§13-14)

El motor de evaluación USA las clases productivas + su propio precompute +
semántica del adapter (quirk SHORT incluido) + exits PaperBroker.
ema_crossover: 2 motores independientes convergen (PF 0.57 / 0.50, mismo
veredicto). TEST_TARGET == RUNTIME_TARGET demostrado.

## 4. Baselines y admission (§15-25)

Criterios pre-registrados ANTES de resultados (c1ffbaa), aplicación
mecánica (scripts/build_admission_matrix.py):

| Family | Trades | PF BASE | PF DEV | PF OOS | PF 2X | Admission |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| momentum | 2436 | 0.65 | 0.66 | 0.63 | 0.47 | REJECT |
| breakout | 2276 | 0.66 | 0.71 | 0.67 | 0.48 | REJECT |
| trend | 1288 | 0.72 | 0.71 | 0.94 | 0.56 | REJECT |
| mean_reversion | 2861 | 0.67 | 0.69 | 0.70 | 0.47 | REJECT |
| volatility | 519 | 0.62 | 0.65 | 0.60 | 0.46 | REJECT |
| ema_crossover | 1561* | 0.50 | — | 0.47 | <0.5 | REJECT (previo) |

*parity engine; el baseline dedicado (1723, PF 0.57) coincide en veredicto.

## 5. Resultado (§41)

**MULTI_STRATEGY_RESEARCH_BLOCKED** — 0 candidatas. No se falsifica el
DoD: no hay ≥2 familias validadas, y activar perdedoras degradaría el
baseline determinista que es el CONTROL de toda medición futura.

## 6. Smokes y conflict policy (§30-34)

No aplicables sin candidatas: ningún STRATEGY-PAPER-SMOKE se ejecuta
(no hay qué humear) y la política de conflictos queda especificada
(NO_TRADE_CONFLICT como default seguro) para cuando existan ≥2 admitidas.

## 7. Siguiente fase recomendada (§47-A)

**STRATEGY-DISCOVERY-V3**: nuevas hipótesis cuya expectación BRUTA supere
los costes estructurales (el diagnóstico transversal: TP 0.75% + 5bps/lado
devoran señales 5m; trend casi breakeven en OOS 0.94 es la pista más
fuerte). Los defects de wiring (DEF-206, router, portfolio) se cierran en
el enablement SOLO cuando haya ≥1 estrategia con edge que justifique el
pipeline.

## 8. Evidencia

- docs/MULTI_STRATEGY_ROUTING_AUDIT.md · STRATEGY_ADMISSION_CRITERIA.md
- docs/STRATEGY_ADMISSION_MATRIX.md + .json · STRATEGY_RUNTIME_INVENTORY.md
- reports/strategy-baseline/MULTI_FAMILY_RESULTS_*.json (6 ficheros)
- scripts/multi_family_backtest.py · scripts/build_admission_matrix.py
