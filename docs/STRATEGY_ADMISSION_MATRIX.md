# STRATEGY_ADMISSION_MATRIX — aplicación mecánica de criterios pre-registrados

> Criterios: docs/STRATEGY_ADMISSION_CRITERIA.md (comprometidos en `c1ffbaa`
> ANTES de ejecutar los baselines). Aplicación mecánica sin ajustes post-hoc.
> Machine-readable: STRATEGY_ADMISSION_MATRIX.json.
> Motor de evaluación: las clases runtime reales por familia (parity por
> construcción, §13-14) sobre 7 ventanas × 3 activos, 5m.

## Matriz de admission

| Family | Trades | Net BASE | PF BASE | PF DEV | PF OOS | PF 2X | Admission |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ema_crossover | 1561* | −1266.16 | 0.50 | — | 0.47 | <0.5 | **REJECT** |
| momentum | 2436 | −1679.33 | 0.65 | 0.66 | 0.63 | 0.47 | **REJECT** |
| breakout | 2276 | −1427.46 | 0.66 | 0.71 | 0.67 | 0.48 | **REJECT** |
| trend | 1288 | −876.83 | 0.72 | 0.71 | 0.94 | 0.56 | **REJECT** |
| mean_reversion | 2861 | −1514.34 | 0.67 | 0.69 | 0.70 | 0.47 | **REJECT** |
| volatility | 519 | −428.79 | 0.62 | 0.65 | 0.60 | 0.46 | **REJECT** |

*ema_crossover con el motor de parity (runtime classes + adapter semantics
incl. el quirk del SHORT con stop 1%); su baseline dedicado (1723 trades,
PF 0.57) y este run independiente convergen en el mismo veredicto.

## Lecturas clave

- **0/6 familias superan admission** — criterio c2 (net>0) y c3 (PF>1)
  fallan en todas; c4 (OOS positivo) también. c7 (2X_COST>0.9) falla en todas.
- **trend es la menos mala** (PF 0.72; OOS 0.94 casi breakeven) — señal de
  dirección correcta con costes/TP que la ahogan; queda como pista de
  research (exit asimétrico distinto), NO como candidata.
- El patrón transversal (todas ~0.6-0.7, todas mejoran en DEV y se
  deterioran con costes) apunta a la **hipótesis del coste estructural**:
  con TP 0.75% y fees 5bps+lado, el spread de costes devora el edge bruto
  de señales 5m.

## Consecuencia (§41, §47-A)

`MULTI_STRATEGY_RESEARCH_BLOCKED` — no se activa ninguna estrategia en
paper. Es el resultado honesto: meter 5 estrategias perdedoras en el
registry empeoraría el baseline, no lo mejoraría. La fase siguiente
recomendada es **STRATEGY-DISCOVERY-V3** (nuevas hipótesis con expectación
bruta > costes antes de tocar el runtime).

Los defectos de wiring (DEF-206 inanición de indicadores; router
single-select; correlation-group=1) quedan documentados y se cierran en la
siguiente fase de enablement SOLO cuando exista ≥1 estrategia con edge
demostrado que justifique el pipeline multi-strategy.
