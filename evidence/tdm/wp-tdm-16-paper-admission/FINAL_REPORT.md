# WP-TDM-016 — PAPER admission: informe final

> Rama `feat/tdm-016-paper-admission` · árbol `d35721ad13f4` · base `c9623fd31d37`.
> Generado por `scripts/tdm16_report.py` desde los artefactos; ningún número se escribe a mano.

## Veredicto

**`ECONOMIC_BLOCKED`.** 0/24 estrategias admitidas para PAPER. Ninguna orden PAPER con datos reales, ninguna orden LIVE.

La razón no es una opinión ni una estimación: el mejor gross medido es **8.912 bps/trade** (`volatility@30m`), la línea de coste medida más barata son **12.177 bps RT** y la línea maker de futuros **asumida** son **9.250 bps RT**. Aun con llenado perfecto y cero slippage, la resta es negativa.

## Los tres paquetes

| WP | Qué se hizo | Resultado | Evidencia |
| --- | --- | --- | --- |
| 016A | Auditoría de las 24 estrategias: regla de admisión recalculada, criterios c1..c8, procedencia sha256, cota aritmética por celda | 24 auditadas, 0 discrepancias con la regla, 0 checks fallidos | `ADMISSION_AUDIT.json/.md` |
| 016B | Ciclo completo orden → fill → PnL → reconciliación, en tests de integración aislados etiquetados TEST_ONLY | 3/3 tests, 0 checks fallidos | `PAPER_CYCLE_EVIDENCE.json` |
| 016C | Decisión de admisión + siguiente experimento pre-registrado | `ECONOMIC_BLOCKED`, umbral 4.912 bps | `ECONOMIC_DECISION.json`, `NEXT_EXPERIMENT.md` |

## Lo que 016B demuestra, y lo que no

Demuestra mecánica, con las clases reales del runtime (`PaperCycleEngine`, `RiskManager`, `PaperBroker`, `PaperStateStore`, `StartupReconcilerV4`): una orden aprobada por riesgo produce **un** fill, cierra **una** vez, el PnL es neto de las dos comisiones, la equity cumple `inicial + Σ pnl`, el libro se restaura tras un reinicio con el mismo estado, y **el mismo intento repetido tras el reinicio no coloca una segunda orden**.

No demuestra rentabilidad. Los precios son fixtures deterministas y el artefacto está etiquetado `TEST_ONLY` en cada traza. Un PnL positivo en un fixture no dice nada del mercado, y no se presenta como si lo dijera.

## Números de la auditoría

- estrategias con gross > 0: **7**; con gross ≤ 0: **17**
- entradas con muestra no publicada en el ledger: **18** (hueco de procedencia, no de datos: el explorer recupera los trades)
- celdas que cruzan la línea medida: **0**
- celdas que cruzan la maker asumida: **0**
- divergencias ledger↔explorer: **3** inmateriales (≤0.026 bps, sin cambio de signo ni de lado de la línea de coste)

## Tests

`547` tests en las suites alcanzables (paper, risk, autonomous, integration y el módulo nuevo): **0 fallos**, **0 errores**. El cambio es aditivo: `git diff` contra el commit padre no modifica ningún fichero versionado.

## Verificación independiente

`VERIFY.json`: **29/29** checks, **0** `false_success` sobre 12 mutaciones (gross inflado, ledger promovido, celda eliminada, línea de coste rebajada, umbral desplazado, test fallido, PnL alterado, veredicto invertido, población inflada, aviso de divergencia borrado, informe desviado, check oculto). Estado: **VERIFIED**.

## Bloqueos

- **ECONOMIC_BLOCKED** — volatility@30m earns 8.912 bps gross. Fees are 4.000 bps RT (known). The maker line therefore breaks even only if measured execution cost stays below 4.912 bps; the model currently assumes 5.250 bps for it, which is why the line reads 9.250 bps and kills the cell. _Se cierra cuando_: EXP-MAKER-LINE-001 measures a maker execution cost below 4.912 bps and the pre-registered criteria c1..c9 pass on the resulting numbers.
- **PAPER_ORDER_BLOCKED** — the admission ledger admits 0 of 24, so the PAPER_ORDER layer reports BLOCKED _Se cierra cuando_: the authorised pipeline admits a strategy from measured evidence.
- **AI_BLOCKED** — unchanged from WP-TDM-015-OPS: no analyst provider key is configured _Se cierra cuando_: a key is stored outside the repo (--store-secret) and the analyst retries.

## Siguiente paso hacia producción

`EXP-MAKER-LINE-001` (`evidence/tdm/wp-tdm-16-paper-admission/NEXT_EXPERIMENT.md`). Una pregunta, un umbral: **coste de ejecución maker medido < 4.912 bps** para `volatility@30m` a 200 USD en USDⓈ-M profundo. Predicción declarada antes de ver datos: **H0**. Y un criterio de muerte: si el coste medido llega o supera el umbral, la lane OHLCV intradía se cierra definitivamente.

Si pasa, el artefacto alimenta `build_strategy_admission.py`, la admisión se decide con los criterios vigentes y **entonces** se abre PAPER con datos reales durante 72 h. Ni los criterios ni el ledger se tocan en este WP.

## Límites declarados

- no strategy has demonstrated a positive net edge: the verdict is ECONOMIC_BLOCKED, not a validation
- the WP-016B cycle uses deterministic fixtures labelled TEST_ONLY; it proves mechanics, not returns
- the maker execution cost remains assumed (5.25 bps); measuring it is the next experiment, not this one
- the pre-registered c6 (drawdown) and c8 (window dominance) are still null in every audited cell
- the 72 h PAPER run with real market data was not attempted, because admission is empty

