# PAPER_BURN_IN_V2_ECONOMICS — auditoría económica (§8, §11)

> TRADE_ASYMMETRY.json (per-trade) y RUN_SUMMARY.json (agregado) en el
> directorio del run; snapshot a 6h regenerable al cierre.

## Snapshot @ 6.0h de ejecución real continua

- Ciclos: 4148/4148 HEALTHY · MTM_OK 4148/4148 · restarts 69+ RECOVERED
- Equity: 10000 → 9475.45 realized · MTM 9474.69 · peak 9999.96
- MAX DD MTM: 5.33% (dominado por DEF-205)
- Cierres: 19 (8W/11L) · expectancy −27.61 · PF 0.051 · payoff 0.070

## Auditoría per-trade (§8) — planned vs observed

Contrato real detectado: **SL = 1.5×ATR (adaptativo, típicamente 1-3.5%),
TP = 0.75% fijo** → planned RR observado 0.23-2.32 (mediana ≈ 0.8),
no 0.225 uniforme.

- 9 stops: slippage medio más allá del stop ≈ −11.1% del R planificado
  (gap through del stop intra-vela; normal en 5m crypto, categorizado
  E: artifact de fill realista, no bug)
- 7 TPs: avg +0.85R (el TP fijo 0.75% captura menos que el riesgo medio)
- 1 UNMATCHED (DEF-205): el trade con snapshot perdido

## DEF-205 — la pérdida que no fue trading

Un snapshot inactivo (`last_price=0.0`) cerró la posición BTC a precio 0:
−500.50 (−100% del notional) en 2.4min, vs stop real en 83826 (≈ −86.6).
Sin DEF-205: **net ≈ −19.85 en 18 trades** — mal (PF ≈ 0.32), pero 25×
menos severo. Cascada: daily_pnl −500 triplicó el límite (−1%) →
50 vetos Daily loss limit + 53 cooldown el resto del día.

**Fix aplicado (commit 51957e4)**: guard fail-closed precio≤0 en
`check_positions` + tests de regresión (zero/negative skip, reconcile
con snapshot muerto). El fix entra en runtime en el próximo restart del
loop (≤40 ciclos) y se valida en vivo.

## Alineación con el histórico

Ex-DEF-205 el paper muestra lo mismo que el backtest (1723 trades,
PF 0.57, OOS 0.41): la estrategia pierde por estructura (gross negativo,
72% de trades mueren en stop con TP 0.75%), no por bug de accounting.
El contable está sano; la estrategia no.

## INSUFFICIENT_SAMPLE — con contexto

19 cierres no certifican nada por sí solos. Por eso el veredicto se apoya
en el histórico ANALYZABLE (1723 trades, todas las ventanas/regímenes
negativos), del cual el paper es una muestra consistente.
