# COST_MODEL_V2 (§7-8, §40, §57)

> Modelo de coste revisado tras la auditoría Phase A. **No sustituye** al
> modelo histórico: lo complementa. Los resultados antiguos no se reescriben.

Fichero máquina: `docs/COST_MODEL_V2.json`.
Implementación research: `src/trading_bot/research/microstructure/cost_model.py`.

## 1. Estructura de componentes (§8)

```
per_side = fee + slippage + market_impact + adverse_selection
round_trip = 2 * per_side + full_spread + funding_bps_per_day * holding_days
```

Para maker, además: `maker_fee/rebate`, `fill probability`, `partial fills`,
`queue uncertainty`, `adverse selection after fill`, `missed opportunity`.
**Nunca** se modela `LIMIT ORDER = FREE FILL`.

## 2. Escenarios pre-registrados

| Scenario | Fee/side | Spread | Slip/side | Impact/side | Adv.Sel/side | Funding | **RT cost** | Required (×1.5) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CURRENT_PROJECT_COST_MODEL | 5.0 | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 | **12.0** | 18.0 |
| REALISTIC_RETAIL_COST_MODEL | 10.0 | 1.0 | 1.0 | 0.25 | 0.0 | 0.0 | **23.5** | **35.25** |
| REALISTIC_RETAIL_BNB_COST_MODEL | 7.5 | 1.0 | 1.0 | 0.25 | 0.0 | 0.0 | **18.5** | 27.75 |
| REALISTIC_MAKER_COST_MODEL | 10.0 | 0.0 | 0.0 | 0.0 | 0.5 | 0.0 | **21.0** (theoretical) | 31.5 |
| STRESS_COST_MODEL | 10.0 | 2.0 | 3.0 | 1.0 | 0.0 | 0.0 | **30.0** | 45.0 |

Notas:
- `REALISTIC_RETAIL` es el **modelo de admission**. Es taker: los candidatos
  investigados entran a mercado/limit cruzándolo y **no hay fill model** que
  demuestre ejecución pasiva.
- `spread = 1.0` es **conservador**: el spread observado de majors fue
  BTC 0.0012, ETH 0.037, SOL 0.83 bps. Se usa 1 bp para absorber activos de
  spread amplio y regímenes de estrés.
- `REALISTIC_RETAIL_BNB` es un **escenario**, no el baseline: exige mantener
  BNB y pagar fees con BNB. No se asume como garantizado (§7).
- `REALISTIC_MAKER` es **THEORETICAL**: a VIP0 el maker fee Spot es *también*
  10 bps, así que pasivo no ahorra fee. `effective_maker_cost_bps(fill_prob)`
  sube el coste esperado al no completarse el fill.

## 3. COST_MODEL_STATUS

```text
OPTIMISTIC
```

El modelo previo (12 bps) subestima el fee real (20 bps round-trip) por 2x.

## 4. Break-even y margen (§10, §42)

Para el modelo de admission (23.5 bps):
- `MINIMUM_GROSS_EDGE_BPS = 23.5`
- `REQUIRED_EDGE_BPS = 23.5 × 1.5 = 35.25` (margen de seguridad para error de modelo)

`edge == cost` no es admisible. La señal debe ser **materialmente mayor** que
el coste esperado.

## 5. Cost stress (§40)

| escenario de stress | múltiplo | RT cost |
| --- | ---: | ---: |
| BASE_REALISTIC | 1.0x | 23.5 |
| 1.5X_COST | 1.5x | 35.25 |
| 2X_COST | 2.0x | 47.0 |

`ZERO_COST` **no** se usa para admission (solo diagnóstico de edge bruto).

## 6. Por qué maker no rescata (§12-13)

- Maker VIP0 Spot = 10 bps/lado = taker VIP0. Sin ahorro de fee.
- No existe histórico de libro → no hay fill probability, queue position ni
  adverse selection medibles (§16, §47).
- Conclusión: ninguna candidata OHLCV rechazada se reabre por costes.
  `MAKER EDGE GATE = FAIL`.
- Solo un `MICROSTRUCTURE-FORWARD-DATA-V1` (colector read-only) permitiría
  estimar un modelo de fill honesto en el futuro.

## 7. Relación con el modelo de producción

El `ExecutionCostModel` de producción **no se modifica** en esta fase (§50).
Este módulo es RESEARCH_ONLY y vive en
`trading_bot.research.microstructure.cost_model`. Si una fase posterior
decidiera alinear el runtime con el coste realista, requeriría RFC/ADR y
tests propios.
