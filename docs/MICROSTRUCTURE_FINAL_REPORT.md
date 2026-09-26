# MICROSTRUCTURE_FINAL_REPORT — EXECUTION-COST & MICROSTRUCTURE-EDGE-V1

Fecha: 2026-09-26. HEAD base: `5b4051e`.

## 1. Veredicto

```text
FINAL STATUS: MICROSTRUCTURE_V1_NO_EDGE_FOUND
PAPER CANDIDATES: 0
FALSE_SUCCESS: 0
```

Calificación honesta: el no-edge aplica a las hipótesis **históricamente
testeables**. La dimensión order book (M-02) y el OI más allá de 30 días **no
son testeables hoy** y quedan explícitamente fuera del veredicto (§63): no se
declara resultado sobre datos que no existen.

## 2. Los dos hallazgos estructurales

### Hallazgo A — el coste es el doble de lo asumido (Phase A)

| item | valor |
| --- | --- |
| venue/producto | Binance **Spot** (VIP0 retail), runtime read-only |
| modelo previo | 12 bps RT (fee 5 bps/lado) |
| fee oficial real | **10 bps/lado** (20 bps RT) |
| spread observado | BTC 0.001, ETH 0.04, SOL 0.83 bps |
| **coste realista** | **~23.5 bps RT** |
| `COST_MODEL_STATUS` | **OPTIMISTIC** |
| required edge (×1.5) | **35.25 bps** |

Reevaluación de V3: techo OHLCV +8.91 bps < 12 (modelo viejo) << 23.5 (real)
-> `OHLCV_CURRENT_FAMILIES_NOT_EXECUTION_VIABLE`. No se reescribieron
resultados.

Maker no rescata: a VIP0 el maker Spot es **también 10 bps**. `MAKER EDGE GATE
= FAIL`.

### Hallazgo B — no aparece información nueva suficiente (Phase B)

Features testeables en histórico completo: order flow (klines taker), funding,
premium. Max gross tradeable **+2.36 bps** (`flow_imbalance_z`, h5). Todos los
demás ≤ 0 o negativo. Clasificación:

```text
COST_KILLED 3 | NO_GROSS_EDGE 5 | LIMITED_HISTORY 3 | EXECUTION_MODEL_REQUIRED 1
PAPER_CANDIDATE 0
```

## 3. Qué es testeable y qué no

| dimensión | estado | resultado |
| --- | --- | --- |
| order flow agregado (M-01) | DATA_SUFFICIENT | COST_KILLED (gross +2.36) |
| flow breakout (M-03) | DATA_SUFFICIENT | COST_KILLED (gross +0.94) |
| funding extremes (M-04) | DATA_SUFFICIENT | NO_GROSS_EDGE (OOS negativo) |
| premium/basis (M-05) | DATA_SUFFICIENT | NO_GROSS_EDGE |
| OI+price (M-06) | LIMITED_HISTORY (30d) | NO_GROSS_EDGE |
| funding+OI (M-07) | LIMITED_HISTORY (30d) | no testeable DEV/VAL |
| BTC lead/lag (M-08) | DATA_SUFFICIENT | NO_GROSS_EDGE (≈0) |
| **book imbalance (M-02)** | **LIVE_ONLY** | **EXECUTION_MODEL_REQUIRED** |

## 4. Integridad y disciplina

- PIT: `available_at <= decision_time` en toda alineación
  (`bisect_right` sobre available_at).
- Gaps de klines: 0. Duplicados/orden: limpios.
- 46 tests nuevos (cost model, features, integrity, adversarial fail-closed).
- `ruff` limpio; `mypy` 0 issues (263 ficheros); `pytest` 655 pasan
  (1 guard de dependency-closure que exige módulos git-tracked: se satisface
  al commitear).
- ZERO_COST nunca usado en admission.
- No se tocó el core runtime (§50): RiskManager/PaperBroker/Portfolio/
  StartupReconciler/StrategyRouter intactos.
- No se fabricó libro histórico desde OHLCV (§16).

## 5. Decisión sobre spot y derivados (§58-59)

```text
SPOT_INTRADAY_COST_BLOCKED      (taker intradía, retail VIP0, majors)
DERIVATIVES_NO_EVIDENCE         (direccional; carry market-neutral = línea aparte)
```

## 6. Próxima fase recomendada (§69 — exactamente una)

El hallazgo dominante es el **económico**, no el informativo: a este venue y
nivel de fee, ninguna señal intradía puede cubrir el coste. Por eso la fase
con mayor retorno esperado es comparar venue/producto de forma factual antes
de seguir buscando señales.

```text
NEXT RECOMMENDED PHASE: VENUE-AND-EXECUTION-RESEARCH-V1   (opción D)
```

Justificación: `SPOT_INTRADAY_COST_BLOCKED`. Alternativas descartadas para
este paso: `MICROSTRUCTURE-PAPER-INTEGRATION-V1` (no hay candidata),
`ALPHA-DISCOVERY-V4` (cazar más señales contra una barrera de 23.5 bps tiene
bajo retorno esperado sin resolver antes el venue).

Dato pendiente para una fase de datos: la dimensión order book sólo puede
avanzar con `MICROSTRUCTURE-FORWARD-COLLECTION-V1` (colector ya implementado,
read-only, DISCOVERY PLANE).

## 7. Entregables

Docs: `EXECUTION_COST_REALITY_AUDIT.md`, `COST_MODEL_V2.md`,
`MARKET_MICROSTRUCTURE_DATA_AUDIT.md`, `MICROSTRUCTURE_HYPOTHESES_V1.md`,
`MICROSTRUCTURE_EXPERIMENTS_V1.md`, `MICROSTRUCTURE_RESULTS_V1.md`,
`MICROSTRUCTURE_ADMISSION_V1.md`, `MICROSTRUCTURE_FINAL_REPORT.md`,
`source_registry.md`.
Machine-readable: `COST_MODEL_V2.json`, `MARKET_MICROSTRUCTURE_DATA_AUDIT.json`,
`MICROSTRUCTURE_RESULTS_V1.json`, `MICROSTRUCTURE_ADMISSION_V1.json`.
Código: `src/trading_bot/research/microstructure/*`,
`scripts/{fetch_microstructure_data,microstructure_experiments,microstructure_admission,microstructure_collector}.py`,
`tests/unit/microstructure/*`.

## 8. Regla final

El hallazgo de V3 fue `OHLCV EDGE <= EXECUTION COST`. La respuesta no fue
"más indicadores": fue auditar la economía real de ejecución y buscar
información nueva. Resultado: la economía real es **peor** de lo asumido
(23.5 vs 12 bps) y la información nueva testeable **no la cubre**. La decisión
correcta es `DO_NOT_ADOPT` y reorientar a venue/ejecución.
