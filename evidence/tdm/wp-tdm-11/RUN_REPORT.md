# WP-TDM-11 — RUN REPORT

**RFC:** RFC-TDM-011 · **Hipótesis:** `TDM11-H1`
**Commit fijado:** `e67194e79a42aef2a2ded3aca21ac4a0ea3689c5`
**Worktree:** `C:\Users\GVLLFR0035\Downloads\ff-wt-tdm11` (detached, árbol trackeado limpio)
**Entorno:** Python 3.11.15 · Windows 10.0.26200 · numpy 2.0.2 · sin red en ninguna fase
**Resultado:** **`NO_GO_ALPHA`** · **estado operativo `AWAITING_NEW_DATA`** · `FALSE_SUCCESS = 0`

---

## 1. Qué se ejecutó realmente

| Paso | Comando | Salida | Estado |
| --- | --- | --- | --- |
| 11A reconciliación | `python scripts/tdm11_g0.py` | `.tdm11/g0.json`, `regime_direction.csv` | exit 0, G0-1…G0-5 PASS |
| 11B potencia | `python scripts/tdm11_prereg.py` | `.tdm11/prereg.json` | exit 0 |
| 11B firma | `sha256` + timestamp → `.tdm11/prereg_freeze.json` | `ef68b4c3…` a 11:49:52Z | congelado |
| 11C disponibilidad | `python scripts/tdm11_availability.py` | `.tdm11/availability.json` | exit 0, `AWAITING_NEW_DATA` |
| 11D evaluación retrospectiva | `python scripts/tdm11_retro.py` | `RETROSPECTIVE_LEDGER.csv`, `retro.json` | exit 0, 115 operaciones |
| 11D controles | `python scripts/tdm11_controls.py` | `.tdm11/controls.json` | **11/11 PASS** |
| 11D verificación | `python scripts/tdm11_verify.py` | `.tdm11/verification.json` | 12/12 PASS |
| 11E publicación | `python scripts/tdm11_publish.py` | `RUN_REPORT.json`, `DATASET_PROVENANCE.json` | exit 0 |

Ninguna barra con `open_time >= 2026-10-24T16:00Z` fue descargada, contada desde precios ni evaluada
(`V4`: barra máxima leída `1792857000000`, corte `1792857600000`).

## 2. Qué NO se ejecutó

| Actividad | Estado |
| --- | --- |
| Órdenes PAPER | `NOT_EXERCISED` — 0 órdenes |
| Órdenes LIVE | `NOT_EXERCISED` — 0 órdenes |
| Evaluación confirmatoria | **no ejecutada**: no existe muestra admisible (0,83 días, ~1,07 ops esperadas vs 36 requeridas) |
| Cambios en risk / sizing / execution / accounting | **ninguno** |
| Cambios en archivos existentes | **ninguno** (17 archivos ya modificados del checkout compartido siguen intactos) |
| `CONFIRMATORY_RESULTS.csv` / `TRADE_LEDGER.csv` | **no creados por diseño**: solo deben existir con muestra limpia ejecutada |

## 3. Resultados

### 3.1 Veredicto

`NO_GO_ALPHA` para `TDM11-H1`, emitido por la regla §7 del preregistro sobre la ventana retrospectiva
(anterior a la selección), con `n = 115 ≥ 36`:

- neto medio **−36,37 bps** por operación;
- IC95 neto **[−48,06, −24,18]** → `NET_CI_UPPER_BELOW_ZERO`;
- corroboración independiente del coste: IC95 bruto superior **−0,39** (percentil), **−0,73** (bloques),
  **−2,25** (analítica y jackknife) — con coste cero ya se pierde.

### 3.2 Estado operativo separado

`AWAITING_NEW_DATA`: la ventana confirmatoria admisible empieza en `2026-10-24T16:00Z` y hoy contiene
~1,07 operaciones esperadas frente a las 36 preregistradas. Fecha más temprana para reabrir: **2026-11-21**
(sujeta a que el régimen bajista esté presente). **No se sustituye con más backtests del HOLD.**

### 3.3 Gobernanza

La premisa del RFC — "5 de 6 mejores cubetas son SHORT en bajista" — **no se reproduce**: son **3 de 6**, y
`regime_table.csv` no contiene la columna de dirección. Las 24 celdas y los 16 316 trades de TDM-10 sí se
reproducen exactamente (`claim.reproduced_trades = 16316`).

### 3.4 Costes

23,7906 bps (spot taker, Δ +0,0006 vs publicado), 41,25 (spot maker p=0,5) y **9,25 (perp maker)** salen del
modelo del repo. `COST_UNVERIFIED_FOR_SHORT`: funding perp no se cobra por defecto y el fill maker es una
asunción p=0,5. Irrelevante para el signo.

## 4. Verificación

- **Controles adversariales: 11/11** (`controls.json`), incluido el control de borde plantado
  (+12,95 bps, IC95 inferior +7,11) y el de look-ahead (que convertiría −12,58 en +17,05).
- **Verificación independiente de implementación: 12/12** (`verification.json`), con estadística
  recomputada por t analítica y jackknife, ledger rederivado de barras crudas y reproducibilidad
  byte a byte (SHA `28d76c0b…`).
- **Independencia de autor: `INDEPENDENCE_NOT_DEMONSTRATED`.** Builder y verificador son el mismo agente.
  No se presenta como revisión de terceros.

## 5. Hashes y artefactos

El manifiesto completo (`evidence_sha256`, `code_sha256`, hashes de los 24 datasets) está en
[`RUN_REPORT.json`](RUN_REPORT.json). Preregistro: `ef68b4c3b520435391420b0e3ed11d7224790015bcb347c4973fc86b7c53f949`
(firmado antes de abrir la ventana confirmatoria; enmienda 01 corrige la lista de escenarios de coste sin
tocar el hash).

## 6. Errores e incidentes del propio WP

| ID | Qué pasó | Estado |
| --- | --- | --- |
| E1 | G0-6 comparaba contra el total de la celda en vez del recuento de la cubeta (1/24 coincidencias) | corregido → 23/23 exactas |
| E2 | el recuento del checkout compartido devolvió 0 y luego 62 | corregido → 17 archivos trackeados, sin tocar |
| E3 | los controles de borde plantado daban 0 operaciones (timestamps fuera de ventana) | corregido → 622 ops detectadas |
| E4 | este WP afirmó que el 9,25 bps no estaba modelado | **falso**; V8 lo detectó, enmienda 01 y documentos corregidos; efecto en el veredicto: ninguno |

Los cuatro errores se detectaron con las comprobaciones del propio WP (verificador y controles) y quedan
registrados; ninguno se oculta ni se "arregla" debilitando una aserción.

## 7. Defectos que quedan abiertos

1. Coste del corto no verificado (funding/fill) — bloqueante para cualquier PASS futuro.
2. Spread por barra ESTIMADO (1 bp), no observado.
3. Sin ventana confirmatoria; el protocolo no se puede completar antes del 2026-11-21.
4. Independencia de autor no demostrada.
5. `reports/**` sigue ignorado por Git: este WP publica en `evidence/tdm/wp-tdm-11/` para que la evidencia
   sea recuperable desde un clon.
