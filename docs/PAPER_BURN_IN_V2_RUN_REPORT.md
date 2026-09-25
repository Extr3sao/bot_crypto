# PAPER-BURN-IN-V2 — RUN REPORT (INTERIM @ 5.08h)

> Estado: RUN EN CURSO (loop v3 autónomo, nohup, deadline propio 12h ≈ 03:09).
> Este reporte es INTERIM. El cierre formal exige regenerar tras el stop del loop.
> RUNTIME_COMMIT: d0f2d76 · FINAL_HEAD: 955aab7 · RUNTIME_CODE_EQUIVALENT=TRUE
> (delta d0f2d76→955aab7: solo docs).

## Runtime

- WALL_CLOCK_SPAN: 5.081h · DOWNTIME: 0 (cero gaps >10min) · ACTUAL_RUNTIME: 5.081h
- CYCLES: 3648 intentados / 3648 completados · HEALTHY 100% · FAILED 0%
- MTM: 3648/3648 MTM_OK (100%), precios PIT-snapshot, missing_prices siempre vacío
- RESTARTS: 75 reconciliation=RECOVERED · 0 MISMATCH · 0 FATAL
- DUPLICATE_ECONOMIC_EXECUTIONS: 0

## Bar-close gate (§8-9)

- Evaluaciones: 548 · Gate-skips: 10394 → **reducción 94.99%** (churn eliminado upstream)
- 95.83% de ciclos con skip; re-evaluación solo por vela nueva o cambio de estado
- Decision clock verificado: poll ~5.5s + evaluación solo cuando cambia
  (bar_ts, state_version) — no re-cómputo continuo de la misma vela
- UNIQUE ECONOMIC DECISIONS PRESERVED (A/B en docs/BAR_CLOSE_GATE_VALIDATION.md)

## Risk (§14) — raw vs unique

- RAW VETOES: 337 · UNIQUE VETO EVENTS: 142 (ratio churn 2.37×)
- Top rules (raw): Max open positions (3)=282 · Daily loss limit (1.0%)=36 ·
  Consecutive loss cooldown (3)=19
- Daily loss limit se activó en el run: Risk protegiendo capital, sin relajación

## Ejecución (§15) — semántica separada

- EXECUTION_REQUESTS (metric orders_created): 23 · FILLS durables: 22 ·
  broker_rejected_no_fill: 35 (same-side skips)
- DEF-204 confirmado: `orders_created` mezcla requests con fills; renombrado
  conceptual a EXECUTION_REQUESTS en RUN_SUMMARY.json sin cambio económico
- 0 duplicaciones económicas; la idempotencia suprimió 50 intents duplicados

## Economía (§11) — INSUFFICIENT_SAMPLE

- Equity: 10000 → 9994.81 realized · MTM final 9993.69 · peak 9999.96
- MAX DD: 8.16 abs / 0.082% (serie MTM completa)
- Cierres: 18 (8W/10L, win rate 44.4%) · avg win +3.51 · avg loss −54.81
- Payoff 0.064 · expectancy −28.89 · profit factor 0.051 — OBSERVED, no edge
- Asimetría estructural: TP 0.75% vs SL ~3.3% → la muestra pequeña con payoff
  <<1 domina el PnL negativo. PnL por asset: BTC −495.43 (5 trades) ·
  SOL −21.62 (7) · ETH −2.98 (6)
- strategy_id en todos los cierres: ema_crossover ✓

## Frecuencia (§13)

- unique signals/h: 87.6 (pre-colapso) · fills/h: 4.33 · cierres/h: 3.54

## Recursos (§20)

- events.jsonl: 8.64 MB (3648 ciclos) · state.json: 6.7 KB (estable) ·
- seg logs: 37.8 MB en 75 ficheros — crecimiento lineal, sin anomalías;
  candidates para rotación en V3 (P3)

## Defectos

- DEF-201 (P1 tooling, colisión launchers): RESUELTO — v3 con flock+freshness,
  LAUNCHER_SINGLETON=PASS desde 15:09, 0 colisiones en 75 restarts
- DEF-202/203 (P3): documentados en DEFECTS.md
- DEF-204 (P2→V3): churn same-side por vela nueva; observación pura en V2
- Runtime P0/P1 abiertos: **0**
