# FINAL_REPORT — CODEX PAPER-ADMISSION-DIAG-001

**Fecha:** 2026-10-23 · **HEAD auditado:** `codepaper/supervisor-001` @ `3b758e22`
**Modo:** diagnóstico de solo lectura · 0 órdenes · 0 claves · 0 LIVE · 0 merges
**Veredicto:** `NO_GO` para admisión PAPER · `GO` para **un** experimento de coste medido

---

## 1. Las cinco respuestas

### ¿Qué runtime PAPER es realmente ejecutable?

**El de recuperación de sesión, probado; el de estrategias, ejecutable pero sin sujeto.**

| Runtime | Estado | Prueba |
| --- | --- | --- |
| `paper_supervisor.py` + `def_run_019_prospective_run.py` | **EJECUTABLE, verificado** | `paper_supervisor_verify.py` → **PASS 33/33**, `false_success 0`, exit 0 sobre una campaña de 5 caídas y 6 `SESSION_START` |
| `start_paper_trading.py` / `autonomous_paper.py` | **EJECUTABLE SIN SUJETO** | construyen el ledger y el registry; con 0 candidatos solo pueden emitir `NO_TRADE` (traza real en `data/recovery/wp9/evidence/runtime/traces.jsonl`) |
| Lane de visión (`ai_vision_lane.py`) | **NO EJECUTABLE en entorno congelado** | `vision/chart.py` importa `matplotlib` y `uv.lock` no lo contiene |
| `paper_lock_campaign_verify.py` | **NO APLICA** a la evidencia del supervisor | juzga otra campaña; ver §4 |

Detalle y cadena de autoridad: [RUNTIME_AUTHORITY_MAP.md](RUNTIME_AUTHORITY_MAP.md).

### ¿Por qué ninguna estrategia está admitida?

Porque `admitted = (familia ∈ paper_candidates) ∧ (gross > 0)` y **`paper_candidates` está vacío**.
Tres cerrojos independientes, cada uno suficiente:

1. **Criterios**: 0/6 familias superan `c2` (net > 0), `c3` (PF > 1), `c4` (OOS > 0) y `c7` (2× coste).
2. **Coste**: el gross máximo medido es **+8.912 bps**; la línea taker más barata observada es
   **12.177 bps** y la del runtime **23.354 bps**.
3. **Procedencia**: 18/24 entradas declaran `sample_trades = 0`; `c6` (drawdown) y `c8`
   (dominancia) **nunca se midieron**, ni siquiera en las 6 familias @5m.

Ninguno es un bug. El runtime hace lo correcto: se niega.
Detalle: [PAPER_ADMISSION_DIAGNOSIS.md](PAPER_ADMISSION_DIAGNOSIS.md).

### ¿Tenemos alguna estrategia con evidencia de ventaja económica?

**No.** Hay **señal bruta** positiva en 7 de 24 celdas — es real, está medida, y no basta:

| | bps |
| --- | ---: |
| Mejor gross medido (`volatility@30m`, 194 trades) | **+8.912** |
| Taker más barato observado (USDⓈ-M, 200 USD, deep) | 12.177 |
| Línea de admisión del runtime | 23.354 |
| **Déficit frente al taker** | **−3.265** |
| **Déficit frente a la admisión** | **−14.442** |

La única línea que haría viables 7 celdas es **1.25 bps maker asumido**, sin modelo de llenado.
Y la prueba más dura que ya existe —EXP-003M, fills maker medidos contra la cinta— encontró que
el **techo** de bruto (0.266909 USD) cubre solo **0.356×** del **suelo** de comisiones (0.75 USD).

Detalle: [STRATEGY_ECONOMIC_STATUS.md](STRATEGY_ECONOMIC_STATUS.md).

### ¿Qué experimento concreto permitiría avanzar?

**[EXP-COST-LINE-001](NEXT_EXPERIMENT.md)** — medir, no suponer, la línea maker real de
`volatility@30m` y `volatility@1h` con el motor de fills de EXP-003M, comisiones USDⓈ-M VIP0
(maker 2 / taker 5 bps) y cinta `aggTrades` pública.

- **Gate**: net > 0 con IC95 % inferior > 0, ≥100 trades, ≥30 OOS, PF > 0.9 con 2× coste.
- **Kill switch, decidido ahora**: si la línea medida supera **8.912 bps**, se cierra la lane
  OHLCV intradía completa y no se financia otra campaña de indicadores.
- **Coste**: offline, ~1 h de CPU + una descarga pública. Reutiliza motor de fills, modelo de
  coste, señales y patrón de verificador que ya existen.

### ¿Qué cambios técnicos son verdaderos bloqueos y cuáles pueden esperar?

| ID | Bloqueo | Clase |
| --- | --- | --- |
| B1 | `test_windowless` rojo: 3 offenders, **2 introducidos por el lane** (`ce02a810`) | **BLOCKER** de integración |
| B2 | `uv.lock` sin `matplotlib`; `uv sync --frozen` **sale 0 igualmente** | **BLOCKER** de reproducibilidad |
| B3 | evidencia del supervisor ignorada por `.gitignore:463` | **BLOCKER** de «reproducible desde Git» |
| B4 | dos verificadores con el mismo flag, sin guarda de schema (`FAIL 28/32`) | HAZARD |
| B5 | `main` stale (1 999 vs 3 712 ficheros); merge limpio | CAN WAIT |
| B6 | 18/24 entradas con muestra 0 | CAN WAIT |

**Ninguno, arreglado, admitiría una estrategia.** Son condiciones para *creer* el estado, no para
cambiarlo. Detalle: [OPERATIONAL_BLOCKERS.md](OPERATIONAL_BLOCKERS.md).

---

## 2. Decisión

```
PAPER_ADMISSION            = NO_GO
ECONOMIC_ADVANTAGE         = false
BEST_MEASURED_GROSS_BPS    = 8.912
NET_POSITIVE_STRATEGIES    = 0
LIVE_TRADING               = DISABLED
NEXT                       = EXP-COST-LINE-001 (una sola pregunta, un solo gate)
```

No se cambia ningún límite de riesgo, criterio de admisión, B-1/B-2, ni el ledger. No se abre el
holdout. No se toca el checkout compartido.

---

## 3. Verificación (BUILDER ≠ VERIFIER)

Los documentos los escribí yo. El verificador **no lee mi prosa**: relee los artefactos y
recomputa cada cifra. Es independiente en implementación, **no en autor**, y eso se declara.

```
$ wt-sup001/.venv/Scripts/python.exe reports/ai-bots/CODEX-PAPER-ADMISSION-DIAG-001/verify_claims.py
28/28 PASS · evidence/CLAIM_CHECKS.json · exit 0
```

| Comprobación | Resultado real | Exit |
| --- | --- | --- |
| `verify_claims.py` (28 claims contra artefactos) | **28/28 PASS**, `false_success 0` | 0 |
| `paper_supervisor_verify.py --campaign …/supervisor-001/campaign` | **PASS 33/33**, `false_success 0` | 0 |
| `paper_lock_campaign_verify.py --campaign …` (mismo directorio) | **FAIL 28/32**, `false_success 2` | 1 |
| `pytest tests/unit/ops/test_windowless.py -q` | **1 failed, 12 passed** | 1 |
| `uv lock --check` | *lockfile needs to be updated* | 1 |
| `uv sync --frozen --dry-run` | 0 errores **y sin `matplotlib`** | 0 |
| `git merge-tree --write-tree main codepaper/supervisor-001` | sin conflictos | 0 |

Evidencia cruda de las ejecuciones: [`evidence/`](evidence/) —
`SUPERVISOR_VERIFY.json`, `CAMPAIGN_VERIFY.json`, `LOCK_VERIFIER_STDOUT.log`, `CLAIM_CHECKS.json`.
Un check que no puede ejecutarse se reporta como `FAIL`, nunca como PASS.

---

## 4. Los dos errores que esta auditoría encontró en el paquete del supervisor

1. **«Preexisting failure» era media verdad.** `RUN_REPORT.json` atribuye el rojo de
   `test_windowless` a una causa previa. El test ya estaba rojo en `60455b46`, sí, pero el lane
   añadió **2 de los 3** offenders (`ce02a810`) y el recuento pasó de 1 a 3.
2. **Un verificador juzgó una campaña ajena.** `paper_lock_campaign_verify.py` leyó
   `episodes/` como si fuera `iterations/`, no comprobó
   `schema_version: TAP_PAPER_SUPERVISOR_CAMPAIGN_V1`, y emitió `FAIL` + `false_success=2`
   legítimos según su contrato. El verificador correcto (`paper_supervisor_verify.py`) da
   **PASS 33/33** sobre esa misma evidencia. El peligro no es el FAIL: es que un release gate
   que corra ambos se queda rojo para siempre.

---

## 5. Lo que este informe NO afirma

- **No** ejecuté una sesión PAPER nueva. Afirmo que existe evidencia registrada de que el
  runtime de recuperación funciona y que sus verificadores se comportan como se describe al
  re-ejecutarlos hoy.
- **No** hay backtest nuevo. Todas las cifras económicas son de artefactos ya commiteados.
- **No** afirmo que no exista edge en ningún mercado: afirmo que **en la población evaluada**
  (6 familias × 4 TFs, 3 candidatas, 12 celdas de régimen, 24 experimentos) no hay ventaja neta.
- **No** afirmo que la línea maker de 1.25 bps sea falsa: afirmo que **no está medida**, y que
  mientras no lo esté, la admisión no puede apoyarse en ella.
- **No** hice merge, no hice commit y no publiqué nada.

## 6. Límites del diagnóstico

- El corte del supervisor es `taskkill /F /T` (no pérdida de energía) y en un solo host.
- Los fills del runtime son PAPER; ningún experimento tocó un exchange.
- La cinta de EXP-003M es spot y de 2026-06; extrapolarla a futuros exige el experimento
  propuesto, no una regla de tres.
- `main` se movió durante la auditoría (observé `1d2192b0`, `47ca8dac` y `0e13160a`; solo el
  último queda en la historia). Los conteos de árbol son una foto del instante y están fechados;
  el merge limpio se comprobó contra el estado de ese momento, no contra un `main` congelado.
- El paquete vive en `reports/ai-bots/`, que `.gitignore:463` ignora: **estos seis documentos no
  viajan con el commit** salvo que se promuevan explícitamente (ver B3).

## 7. Entregables

| Fichero | Qué contiene |
| --- | --- |
| [RUNTIME_AUTHORITY_MAP.md](RUNTIME_AUTHORITY_MAP.md) | cadena ledger → registry → runtime; qué ejecuta y qué no |
| [PAPER_ADMISSION_DIAGNOSIS.md](PAPER_ADMISSION_DIAGNOSIS.md) | los 3 cerrojos y el motivo por estrategia (24 filas) |
| [STRATEGY_ECONOMIC_STATUS.md](STRATEGY_ECONOMIC_STATUS.md) | gross/costes/OOS/frecuencia; 7 celdas positivas y sus déficits |
| [OPERATIONAL_BLOCKERS.md](OPERATIONAL_BLOCKERS.md) | B1–B6 con comando, salida y clasificación |
| [NEXT_EXPERIMENT.md](NEXT_EXPERIMENT.md) | EXP-COST-LINE-001 con gates y kill switch pre-registrados |
| [FINAL_REPORT.md](FINAL_REPORT.md) | este documento |
| [verify_claims.py](verify_claims.py) | verificador independiente: 28/28 PASS |
| [evidence/](evidence/) | salidas crudas de verificadores y del chequeo de claims |

## 8. Estado del árbol

- Se creó un worktree aislado (`../CODEX-PAPER-ADMISSION-DIAG-001`, rama
  `codepaper/admission-diag-001`) desde `3b758e22` para ejecutar las comprobaciones, y **se retiró
  al terminar**: `git worktree remove …` + `git branch -D …`. La rama apuntaba a `3b758e22`, sin
  commits propios; no se perdió nada.
- **`main` no se tocó.** Se movió mientras duró la auditoría: observé `1d2192b0`, luego
  `47ca8dac`, y al cerrar `0e13160a` (el intermedio fue reemplazado). Ninguno de esos commits es mío.
- Los únicos ficheros escritos en el checkout compartido son los de
  `reports/ai-bots/CODEX-PAPER-ADMISSION-DIAG-001/`, una ruta ignorada por `.gitignore:463`:
  no altera código, tests ni evidencia de otros lanes.
