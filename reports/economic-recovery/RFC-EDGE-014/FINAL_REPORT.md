# RFC-EDGE-014 — recuperación económica, auditoría del camino real de órdenes y benchmark externo

*Un solo cierre, a `2026-10-16T12:50:42Z`. Cifras leídas de los artefactos que este run escribió.*

## 1. Estado

| Eje | Estado |
| --- | --- |
| Camino real de órdenes | **TRADE_PATH_DIAGNOSED** |
| Economía | **ECONOMIC_INTEGRITY_RECONCILED** |
| Investigación | **RESEARCH_COMPLETED_NO_EDGE** |
| Continuidad / paper | **PAPER_BLOCKED_BY_GATE** |
| Benchmark externo | **PINES_VERIFICADOS, MOTOR NO EJECUTADO** |
| Verificación independiente | **VERIFICATION_PASS** — 12/12 checks, 30/30 sabotajes detectados |

`FALSE_SUCCESS = 0`, `promotion = NONE`, `order_sent = False`. No se declara rentabilidad, ni PAPER_READY, ni LIVE_READY.

## 2. PHASE

RFC-EDGE-014 `IMPLEMENTATION_AUTHORIZED_FOR_SAFE_RESEARCH_ONLY`. Los seis work packages se ejecutaron
en el orden de valor del encargo: primero el camino real y la contabilidad, después el laboratorio
externo y las hipótesis.

## 3. ACCEPTANCE

{"BLOQUEADO_DECLARADO": 1, "SATISFECHO": 23}

- **ACC-18** `BLOQUEADO_DECLARADO` — OOS class TEMPORAL_WITHIN_A_CONSUMED_CORPUS: no unread corpus remains in the tree


## 4. WP-14A — el camino real de órdenes

El ledger CAP-004 cubre `9.6986` días (no 30: la ventana es la que existe y
no se rellenó). En esa ventana el runtime **selló 4 decisiones**,
de las cuales **1** fue direccional, y **no envió ninguna orden**.

| Etapa | Recuento | Clase de evidencia |
| --- | ---: | --- |
| `MARKET_DATA` | 4 | `observed` |
| `SIGNAL` | 4 | `observed` |
| `PROPOSAL` | 1 | `observed` |
| `ROUTER` | UNKNOWN | `unknown` |
| `RISK` | UNKNOWN | `unknown` |
| `ORDER_INTENT` | 0 | `absent_ledger` |
| `PAPER_BROKER` | 0 | `absent_ledger` |
| `RECONCILIATION` | 4 | `observed` |

Una etapa sin ledger es `UNKNOWN`, no cero. Las causas de NO_TRADE reconstruidas:
`DATA_GAP`, `DISK_BUDGET_VETO`, `NO_SIGNAL`, `UNKNOWN`.
`ECONOMIC_INTEGRITY_RECONCILED` no altera esto.

## 5. WP-14B — la contradicción de costes, resuelta

El informe decía **85.9% de la barrera**; la factibilidad decía **32.5 bps de una barrera de 23.4439 (1.3863)**.
Ambos se reproducen desde el artefacto primario, y la diferencia es de **población**, no de aritmética:

- **85.92%** = comisión de admisión (20.0 bps) ÷ ida y vuelta de admisión (23.27783 bps) — misma población.
- **1.3863** = media de la comisión sobre las **cuatro** programaciones de venue (20, 20, 10, 80 bps → 32.5)
  ÷ la barrera media **solo de admisión** (23.4439 bps) — dos poblaciones distintas.

No hubo comisión duplicada ni identidad rota en la puerta: la identidad se rompió en la *frase*, al
renderizar. La afirmación correcta es **la comisión es el 85.9% del ida y vuelta de admisión**; el 1.3863
queda `INCONSISTENT_SUPERSEDED` sin editar el original (`primary_source_untouched = True`).

Y la segunda contradicción: **144.061/day no es 48.018/day**. Son métricas distintas — el selector cuenta
inicios solapados de 60 s condicionados a desequilibrio extremo; el techo del tape des-solapa antes de
contar. Solo el segundo mapea a operaciones distintas, y es el denominador del objetivo ACTIVE.

## 6. WP-14C — laboratorio externo

3 pines resueltos: **3/3**, clonados fuera del
árbol y sin instalar. La licencia se lee del **fichero de licencia en el commit pinneado**, nunca del README.

| id | repo | pin | resuelve | familia del fichero | regla |
| --- | --- | --- | :-: | --- | --- |
| `SRC-01` | freqtrade/freqtrade | `b33068949fc1` | True | GPL | NO_COPY |
| `SRC-02` | jesse-ai/jesse | `5e642997f962` | True | MIT | COPY_WITH_ATTRIBUTION |
| `SRC-03` | vnpy/vnpy_ctastrategy | `7a8768de9784` | True | MIT | COPY_WITH_ATTRIBUTION |

Dos defectos propios cerrados aquí: el `^{commit}` iba sin el caret (revisión inválida), y la detección de
familia marcaba GPL-3.0 como AGPL porque el cuerpo de la GPL-3.0 nombra la AGPL en la sección 13 — ahora se
lee solo el encabezado y freqtrade vuelve a GPL. Ningún motor se ejecutó, así que ninguna diferencia de
equity se cuantifica: `parity_plan` congelado, ejecución `BLOQUEADO_DECLARADO`.

## 7. WP-14D — hipótesis y resultados reales

Las tres hipótesis nombradas resultaron **duplicadas** de familias que ya existen; se rechazan por nombre,
no se renombran para aparentar novedad. La cuarta, buscada por ortogonalidad con el mismo instrumento,
se retiene.

| id | familia | estado | duplicada de |
| --- | --- | --- | --- |
| `E14-01` | REGIME_CONDITIONED_VOL_BREAKOUT | REJECTED | breakout_family, volatility_family |
| `E14-02` | LIQUID_SPOT_CROSS_SECTIONAL_ROTATION | REJECTED | cross_sectional, diversified_xsec, diversified_xsec_riskadj |
| `E14-03` | CONDITIONAL_EXTREME_MEAN_REVERSION | REJECTED | mean_reversion_family |
| `E14-04` | CROSS_ASSET_LEAD_LAG_TRANSMISSION | STRATEGY_CANDIDATE | — |

6 brazos **ejecutados de verdad** sobre OHLCV real, cobrando el ida y vuelta de admisión
(`22.9866` bps) por operación:

| brazo | operaciones | días | días a cero | bruto medio (bps) | neto medio (bps) |
| --- | ---: | ---: | ---: | ---: | ---: |
| `E14-04_LEAD_LAG::UNI->AAVEUSDT` | 534 | 2113 | 1690 | -0.787586 | -23.774186 |
| `E14-04_LEAD_LAG::UNI->CRVUSDT` | 739 | 2113 | 1553 | -2.818763 | -25.805363 |
| `E14-04_LEAD_LAG::UNI->KSMUSDT` | 508 | 2113 | 1713 | -5.444085 | -28.430685 |
| `E14-04_LEAD_LAG::UNI->SUSHIUSDT` | 508 | 2113 | 1705 | 2.860899 | -20.125701 |
| `NEUTRAL_MA_CROSS_1H::BTCUSDT` | 98 | 228 | 142 | 21.975396 | -1.011204 |
| `NEUTRAL_MA_CROSS_1H::ETHUSDT` | 107 | 228 | 134 | 16.494155 | -6.492445 |

**Ningún brazo es neto-positivo.** El cruce de medias neutro gana `21.975396` bps brutos
por operación en BTC y la barrera se los come: neto `-1.011204` bps. Es el mismo muro aritmético que
EDGE-09 midió, ahora reproducido de forma independiente en otro corpus y otro horizonte.

`oos_is_fresh = False`: ningún corpus del árbol sigue sin leerse, así que el corte es temporal dentro de un
corpus consumido y **no puede sustentar una promoción**. Veredicto: `INSUFFICIENT_SAMPLE_FOR_FRESH_OOS`.

## 8. WP-14E — paper

`PAPER_BLOCKED_BY_GATE`. Motivos:
- `DISK_BUDGET` — 42 cycles refused a new decision slot with NO_NEW_DECISION_DISK_CRITICAL
- `PAPER_BROKER_NOT_RUNNING` — no paper fill ledger exists on the CAP-004 real-decision path

No se aflojó ninguna puerta, no se tocó el riesgo y no se renunció a ningún día forward. Todas las
mediciones offline se conservan.

## 9. TESTS

- `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe -m pytest tests/unit/research/test_edge14_economic_recovery.py -q` → exit `0` — 37 passed in 23.82s
- `C:\Users\GVLLFR0035\Downloads\bot freebuff\.venv\Scripts\python.exe scripts/edge14_verify.py` → exit `0` — sabotage: 30/30 detected

## 10. DEFECTS cerrados

1. `^{commit}` sin caret: la comprobación del pin fallaba con "Not a valid object name".
2. Familia de licencia leída del cuerpo entero: GPL-3.0 clasificada como AGPL por la referencia a la AGPL.
3. `load_ohlcv` entendía una sola forma de barra y devolvía **cero barras en silencio** con la otra (señal de "no hay operaciones"). Ahora acepta las dos y **falla** con una tercera.
4. Fórmula de frecuencia del verificador mal derivada (2479.9 vs 48.018) — el verificador se corrigió contra el primario.
5. Comprobación de `live_status` trataba un exit 1 registrado como sospecha de orden.
6. Caso de sabotaje S07 mal planteado (no detectaba la vela alta abierta).

## 11. BLOCKERS

- **Sin OOS fresco**: no queda corpus sin leer; la validación inferencial queda bloqueada hasta capturar datos nuevos.
- **Sin paridad de motores**: los pines se verificaron pero no se ejecutó ningún motor externo.
- **Paper bloqueado por puerta**: el guardián de disco rechaza slots y no hay broker paper en este camino.
- Ninguno de los tres requiere autorización: son límites de datos y de puerta, no de permiso.

## 12. EVIDENCE

- `BASELINE.json`
- `CANDIDATE_EXPERIMENTS.json`
- `CANDIDATE_REGISTRY.json`
- `CLONE_MANIFEST.json`
- `FREQUENCY_DEFINITIONS.json`
- `MARKET_COST_RECONCILIATION.json`
- `PAPER_GATE.json`
- `RUNTIME_AUTHORITY_MAP.json`
- `TRADE_PATH_DIAGNOSIS.json`
- `INDEPENDENT_VERIFICATION.json`, `ACCEPTANCE.json`, `GIT_STATE.json`

## 13. ARCHITECTURE_STATUS

La cadena de autoridad no cambió: Market Data → Signal → TradeProposal → Router → Risk determinista →
Paper Broker/Execution → Reconciliación → Evidencia. Ningún tercero entra al runtime; un motor externo es
fuente de hipótesis o benchmark, nunca ejecutor.

## 14. RFC_STATUS

`RESEARCH_COMPLETED_NO_EDGE` con la economía `ECONOMIC_INTEGRITY_RECONCILED`. Una salida negativa con
código, pruebas y experimentos ejecutados, causas y costes verificables, es la entrega válida.

## 15. NEXT_PHASE

Por impacto económico, no por número de RFCs:

1. **Capturar un OOS genuinamente fresco** (símbolos o ventana que ningún paquete haya tocado) y volver a
   medir el cruce neutro: es la única prueba que puede mover el veredicto.
2. **Ejecutar el benchmark de paridad** sobre ese OOS cuando exista, con la tolerancia ya congelada.
3. **Medir un modelo de fills maker**: sin él, ningún producto pasivo de este proyecto puede puntuarse.
4. Resolver el slot de decisión bloqueado por disco, porque sin slots no hay camino real que auditar.

Research only: ninguna orden, ninguna credencial, ningún capital.
