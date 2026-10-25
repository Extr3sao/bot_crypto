# WP-TDM-11A — GOVERNANCE RECONCILIATION

**Work package:** WP-TDM-11A (read-only baseline) · **RFC:** RFC-TDM-011
**Worktree:** `C:\Users\GVLLFR0035\Downloads\ff-wt-tdm11` (detached)
**HEAD:** `e67194e79a42aef2a2ded3aca21ac4a0ea3689c5`
**Generado:** 2026-10-25T11:47Z · **Script:** `scripts/tdm11_g0.py`
**Evidencia:** `evidence/tdm/wp-tdm-11/g0.json`, `regime_direction.csv`, `logs/g0.log`

Autoridad aplicada: REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > ASSUMPTION.
Todo lo de este documento se midió en esta sesión; nada se copió de un informe previo sin recomputarlo.

---

## 1. Aislamiento (G0-1) — **PASS**

| Comprobación | Resultado |
| --- | --- |
| Worktree creado desde commit fijo | `git worktree add --detach … e67194e7` |
| HEAD del worktree | `e67194e7…` (= commit fijado) |
| Árbol con archivos trackeados modificados | **0** |
| Checkout compartido | mismo HEAD, **17** archivos trackeados ya modificados, **no tocados** |
| Huella del estado del checkout compartido | `porcelain_sha256 43462dbeb0e82137…` (solo lectura) |
| Entorno | Python 3.11.15 · Windows 10.0.26200 · numpy 2.0.2 |

El worktree no contiene `src/` alterado: los 17 archivos modificados del checkout compartido **no** se
copian aquí, de modo que todo lo que ejecuta este WP corre sobre el árbol prístino del commit fijado.
Los datos sellados se copiaron a `data/tdm08` y `data/tdm10` del worktree (archivos nuevos, hashes
reverificados en G0-3).

> Método de aislamiento: `git worktree`, no una copia del directorio. El checkout compartido se
> inspeccionó con `git status` y `git rev-parse` **sin escribir** en él.

---

## 2. Artefactos WP-TDM-10 (G0-2) — **PASS**

7/7 entregables no autorreferenciales recomputados contra `RUN_REPORT.json`:

| Archivo | SHA-256 (prefijo) | Bytes |
| --- | --- | --- |
| `EXPERIMENT_SPEC.md` | `8964d314a817…` | 11 612 |
| `DATASET_AND_COST_BASELINE.md` | `79e8cc72a2ff…` | 8 764 |
| `ALPHA_ECONOMIC_MATRIX.csv` | `8210646c1743…` | 121 487 |
| `ROBUSTNESS_REPORT.md` | `d09f929ce563…` | 14 668 |
| `INDEPENDENT_VERIFICATION.md` | `01e6143a7add…` | 8 672 |
| `RUN_REPORT.md` | `77819f163464…` | 10 296 |
| `FINAL_REPORT.md` | `fb7f6349753f…` | 12 193 |

Discrepancias: **0**. `RUN_REPORT.json` no se autohashea (correcto: un archivo no puede contener su
propio digest).

## 3. Integridad de datasets (G0-3) — **PASS**

24 archivos (12 DEV + 12 HOLD), hashes contra manifiesto: **24/24**. Sobre las barras crudas:

| Comprobación | Resultado |
| --- | --- |
| Timestamps duplicados | **0** |
| Barras faltantes (huecos vs. ventana esperada) | **0** |
| Series monótonas | 24/24 |
| Fin de DEV | `2026-09-24T23:55:00Z` |
| Inicio de HOLD | `2026-09-25T00:00:00Z` |
| Solapamiento DEV∩HOLD | **0 ms** |
| Fin de HOLD (última barra expuesta) | `2026-10-24T15:50:00Z` |

El corte DEV/HOLD cae en el límite de barra (5 min entre 23:55 y 00:00), no hay barra compartida ni
hueco real.

---

## 4. Especificación congelada y divergencia de estados (G0-4) — **PASS**

`EXPERIMENT_SPEC.md` sigue en `8964d314a817…`, idéntica al sello. La divergencia declarada por WP-TDM-10
se mantiene registrada y **no se ha corregido**:

| Fuente | Valor |
| --- | --- |
| Regla agregada §8 de la spec | `INCONCLUSIVE` |
| Criterio de salida del WP | `NO_GO_ALPHA` |
| Registro | `RUN_REPORT.json → verdict_detail.spec_aggregate_rule` |

Ambas lecturas excluyen `GO_RESEARCH`; la divergencia es de nomenclatura, no de economía. **No** se
modificó la spec: `A1` de la verificación de TDM-10 depende de su hash.

---

## 5. Auditoría de costes (G0-5) — **PASS con dos hallazgos**

Recomputado con el modelo del repo (`COST_MODEL_V3`, `default_model()`), tamaño 1 000 USD, horizonte
30 min, liquidez `normal`, volatilidad 0, spread por defecto:

`VENUE_SPECS` tiene **10** escenarios. Todos evaluados a 1 000 USD y 30 min:

| Escenario | Producto | bps | Clase |
| --- | --- | --- | --- |
| `BINANCE_USDM_PERP_MAKER` (p=0,5) | USDⓈ-M Perpetual | **9,2500** | ASSUMED |
| `BINANCE_USDM_PERP_TAKER` | USDⓈ-M Perpetual | 13,7906 | ESTIMATED |
| `MEXC_SPOT_TAKER` | Spot | 17,7906 | ESTIMATED |
| `BINANCE_SPOT_BNB_TAKER` | Spot | 18,7906 | ESTIMATED |
| `BINANCE_SPOT_STANDARD_TAKER` (**primario**), `BYBIT_SPOT_TAKER`, `OKX_SPOT_TAKER` | Spot | **23,7906** | ESTIMATED |
| `BINANCE_SPOT_BNB_MAKER` (p=0,5) | Spot | 31,2500 | ASSUMED |
| `BINANCE_SPOT_STANDARD_MAKER` (p=0,5) | Spot | 41,2500 | ASSUMED |
| `KRAKENPRO_SPOT_TAKER` | Spot | 83,7906 | ESTIMATED |

Desglose del primario: fee 10,0 + 10,0 · spread 1,0 · slippage 2,6325 · impacto 0,1581 = **23,7906**
(Δ +0,0006 bps frente al 23,79 publicado → reproducción exacta a 4 decimales).

**H-01 — retractado: el 9,25 bps sí está modelado.** `BINANCE_USDM_PERP_MAKER` = maker 2,0 ×2 +
adverse selection 1,0 + missed fill 0,25 + inflación 1/p 4,0 = **9,25**. Mi primera lectura de la tabla de
escenarios quedó truncada por un `UnicodeEncodeError` de consola (el tier contiene `Ⓢ`) y escribí que el
escenario no existía; la comprobación `V8` del verificador lo detectó y este documento queda corregido.
TDM-10 estaba en lo correcto. **El error fue mío y está en `RUN_REPORT.json → errors E4`.**

**H-02 — el coste del lado corto sigue sin verificar, por otra razón.** Existe un producto que admite
cortos (USDM Perpetual), así que el caso no es "imposible de costear". Pero:

* el escenario **primario** del preregistro es Spot, y un Spot **no admite posición corta**;
* en perp, `funding_carry` **no se emite** por defecto (`funding_rate_bps_per_interval = 0` aunque
  `funding_source_id = SRC-05`), de modo que un hold de 30 min que cruce un pago de funding no lo paga;
* el 9,25 asume **p = 0,5** de fill pasivo, con pérdida por selección adversa incluida pero sin modelo de cola.

Estado: `COST_UNVERIFIED_FOR_SHORT`, no bloqueante para este veredicto (ver `COST_MODEL_AUDIT.md` §3).

---

## 6. La premisa de RFC-TDM-011 (G0-6) — **FALLA**

RFC-TDM-011 §1 afirma que TDM-10 encontró "concentración de residuos positivos en el lado SHORT durante
tendencias bajistas (5 de 6 mejores cubetas)". Dos problemas, ambos medidos:

**(a) El artefacto publicado no contiene dirección.** `regime_table.csv` (192 filas = 144 de régimen + 48
de corte temporal) tiene columnas `strategy_id, trades, regime, label, count, share_pct, gross_bps, net_bps,
net_ci_*`; **no hay columna de dirección**. La atribución direccional no es verificable desde la evidencia
publicada.

**(b) Recomputada desde las barras selladas, la afirmación es 3 de 6, no 5 de 6.** Reconstruí las 24 celdas
del HOLD con la definición congelada (ventana 100, hold 30 min, una posición a la vez) y etiquetas de régimen
trailing-only: **16 316 operaciones, idénticas celda a celda a las publicadas**, y **23/23 recuentos de la
cubeta `trend=down` idénticos** (`volatility@1h` no tiene cubeta `down`). Con la reproducción validada,
el top-6 por edge bruto queda:

| # | Celda | Cubeta | n | % SHORT | gross bps |
| --- | --- | --- | --- | --- | --- |
| 1 | `breakout@1h` | trend `down` | 7 | 100 % | +63,34 |
| 2 | `volatility@5m` | trend `down` | 4 | **25 %** | +27,18 |
| 3 | `volatility@5m` | vol `high_vol` | 8 | 62,5 % | +25,46 |
| 4 | `ema_crossover@1h` | trend `down` | 32 | 90,6 % | +19,34 |
| 5 | `breakout@30m` | trend `down` | 12 | 75,0 % | +19,16 |
| 6 | `mean_reversion@1h` | trend `unclassified` | 7 | 85,7 % | +18,70 |

Cubetas que son a la vez tendencia bajista y mayoritariamente cortas: **3 de 6** (#1, #4, #5). La #2 es un
bucket de **cuatro** operaciones de las que **una** es corta; la #6 está en régimen `unclassified`, que no
es "bajista". Usando la lista de 6 cubetas que el propio `ROBUSTNESS_REPORT.md` §6 destaca, el resultado es
el mismo: 3 de 6 (`ema_crossover@1h` 0,906 · `momentum@5m` 0,77 · `trend@15m` 1,0).

**Consecuencia para este WP:** la hipótesis SHORT-bajista **no** hereda una premisa verificada; hereda una
atribución direccional que el artefacto no soporta y un recuento que no se reproduce. WP-TDM-11B la trata,
por tanto, como hipótesis **generada por exploración sobre datos expuestos**, sin grado de evidencia previo.
El error es de la afirmación, no de los números de TDM-10: sus 24 celdas, hashes y veredicto `NO_GO_ALPHA`
se reproducen exactamente.

---

## 7. Defectos heredados que este WP declara y no corrige

| ID | Defecto | Estado |
| --- | --- | --- |
| D-01 | Artefactos de TDM-08/10 bajo `reports/**`, **ignorados por Git** → no recuperables desde un clon | abierto; WP-TDM-11 publica en `evidence/tdm/` |
| D-02 | Afirmación direccional "5 de 6" no reproducible (G0-6) | **documentado**; no se reescribe el informe histórico |
| D-03 | Coste del corto: funding perp no cobrado por defecto y fill maker asumido (H-02) | `COST_UNVERIFIED_FOR_SHORT` |
| D-04 | Preregistro citó mal el 9,25 como no modelado; corregido por enmienda 01 | **RETRACTADO Y CORREGIDO** |
| D-05 | Mismo autor en builder y verificador en TDM-10 | se arrastra; WP-TDM-11 aplica separación de implementación, no de autor (§ INDEPENDENT_VERIFICATION) |
| D-06 | Spread por barra ESTIMADO (1 bp), no observado | abierto |
| D-07 | Celdas @1h: horizonte de 30 min colapsa a 1 barra (60 min) | evitado en el diseño de 11B (timeframe 5m) |
| D-08 | `reports/*` ignorado; sin política de retención de evidencia | mitigado en este WP |

---

## 8. Veredicto de 11A

`PASS` en aislamiento, integridad, sellos y costes reproducibles.
`FINDING` en la premisa direccional (3/6, no 5/6) y en el coste del lado corto (no modelado).
**Nada del checkout compartido, de la spec congelada ni de los artefactos TDM-08/10 fue modificado.**
Procede continuar a 11B con la hipótesis rebajada a "generada por exploración".
