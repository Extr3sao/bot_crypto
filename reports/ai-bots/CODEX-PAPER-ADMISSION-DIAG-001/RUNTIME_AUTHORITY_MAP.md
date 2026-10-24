# RUNTIME_AUTHORITY_MAP — PAPER-ADMISSION-DIAG-001

> Fecha: 2026-10-23 · Auditoría sobre `codepaper/supervisor-001` @ `3b758e22`
> worktree aislado creado desde `3b758e22` y retirado al terminar; `main` sin tocar.
> Modo: solo lectura + ejecución de verificadores. 0 órdenes, 0 claves, 0 LIVE.

Pregunta que responde: **¿qué runtime PAPER es realmente ejecutable y quién decide si una
estrategia puede tocarlo?**

---

## 1. La cadena de autoridad (arriba → abajo)

| Eslabón | Qué decide | Dónde | Evidencia |
| --- | --- | --- | --- |
| 1. Ledger de admisión | única fuente de «¿esta estrategia puede hacer PAPER?» | `config/strategy_admission.json` | docstring de `src/trading_bot/autonomous/admission_ledger.py` L1-20: *«The runtime never decides by itself that a strategy is good enough… It reads a committed ledger»* |
| 2. `AdmissionLedger` | fail-closed: estrategia ausente → `UNKNOWN` → no admitida | `admission_ledger.py` `entry()` / `is_paper_admitted()` | `entry()` devuelve `AdmissionStatus.UNKNOWN`, `rationale="strategy absent from the admission ledger (fail closed)"` |
| 3. `StrategyRegistry` | traduce el ledger a registros y **refusa** estados incoherentes | `src/trading_bot/autonomous/strategy_state.py` | `paper_executable()` L344-350: exige `is_paper_executable(status)` **y** `admitted_for_paper` **y** datos disponibles |
| 4. Constructor del ledger | decide el `status` de cada entrada | `scripts/build_strategy_admission.py` L91-96 | `status = "PAPER_CANDIDATE" if (family in paper_candidates and gross_bps > 0) else "COST_KILLED" if gross_bps > 0 else "NO_GROSS_EDGE"`; `admitted = status == "PAPER_CANDIDATE"` |
| 5. Runtime | enruta lo admitido; si no hay nada, `NO_TRADE` | `src/trading_bot/autonomous/runtime.py` L776, L1250-1254, L1566 | el trace publica `admitted_for_paper` y `admission_status` por estrategia considerada |
| 6. Estados posibles | no existe `LIVE` en el vocabulario | `src/trading_bot/autonomous/contracts.py` L102-116, L210-217 | `PAPER_AUTHORISING_STATUSES = {PAPER_CANDIDATE, PAPER_ACTIVE}`; `PAPER_PROMOTABLE_STATUSES = {PAPER_CANDIDATE}` |

**Consecuencia estructural:** el runtime no puede «decidir» que una estrategia es buena. Si el
ledger no trae `PAPER_CANDIDATE`, no hay nada que ejecutar y el sistema emite `NO_TRADE` con
traza. Eso es lo que se observa: `data/recovery/wp9/evidence/runtime/traces.jsonl` L1-L2 →
6 estrategias consideradas, todas `admitted_for_paper: false`, `mode: "NO_TRADE"`,
`reason: "no_candidate_emitted_an_alpha"`, `risk.state: "NOT_APPLICABLE"`.

---

## 2. Inventario de runtimes PAPER: ¿cuál es ejecutable?

Clasificación: **EXECUTABLE** = existe, tiene evidencia de haber corrido y su verificador cierra.
**EXECUTABLE SIN SUJETO** = arranca pero no tiene ninguna estrategia admitida que ejecutar.
**NO EJECUTABLE AQUÍ** = depende de un recurso que no está en este checkout.

| Entrypoint | Rol | Estado | Evidencia |
| --- | --- | --- | --- |
| `scripts/paper_supervisor.py` | supervivencia de una sesión PAPER: arranca, detecta caída, reclama el lock y reanuda | **EXECUTABLE (probado)** | campaña de 5 episodios en `reports/ai-bots/CODEX-PAPER-SUPERVISOR-001/campaign`; `paper_supervisor_verify.py --campaign …` → **PASS 33/33, false_success 0, exit 0** (re-ejecutado en `3b758e22`) |
| `scripts/def_run_019_prospective_run.py` | sesión PAPER con procedencia de sesión, 9 ciclos, ledger por ciclo | **EXECUTABLE (probado)** | usado por DEF-RUN-019; los tests `tests/unit/vision/test_session_provenance.py` y `test_session_lock_recovery.py` lo cubren |
| `scripts/autonomous_paper.py` | runtime autónomo completo (ledger → registry → router → risk → broker) | **EXECUTABLE SIN SUJETO** | imprime `[admission] paper candidates=NONE` (L325) y corre ciclos `NO_TRADE` |
| `scripts/start_paper_trading.py` | arranque operativo clásico | **EXECUTABLE SIN SUJETO** | construye `AdmissionLedger` + `StrategyRegistry` (L273-274) antes de crear el runtime |
| `scripts/paper_lock_campaign.py` | campaña de caídas/reclamos de lock con evidencia por iteración | EXECUTABLE (builder) | escribe `iterations/iteration-NN/` (L397, L427-440) |
| `scripts/paper_lock_campaign_verify.py` | verificador de esa campaña | **NO APLICA a la evidencia existente** | ver §4 |
| `scripts/tap_unblock_paper.py` | lane PAPER del paquete TAP-UNBLOCK | EXECUTABLE (evidencia en el paquete) | `reports/ai-bots/…` del lane TAP |
| `scripts/ai_vision_lane.py` / `def_run_016_*` | lane PAPER de un modelo de visión sobre charts | **NO EJECUTABLE sin `matplotlib`** | `src/trading_bot/vision/chart.py` L36-42 importa `matplotlib` en top-level; el lock no lo resuelve (§4) |
| `scripts/exp_003p_pipeline.py`, `exp_003m_*` | ejecución PAPER offline sobre datos congelados (fills inferidos de la cinta) | EXECUTABLE (offline) | `reports/ai-bots/EXP-003P-PAPER-EXECUTION-001/`, `EXP-003M-MAKER-FILL-REALITY-001/` |

### Qué ejecuté yo, exactamente

| Comando | Resultado real |
| --- | --- |
| `paper_supervisor_verify.py --campaign reports/…/CODEX-PAPER-SUPERVISOR-001/campaign` | `verdict=PASS`, `checks 33/33`, `false_success=0`, **exit 0** |
| `paper_lock_campaign_verify.py` sobre la **misma** campaña | `verdict=FAIL`, `checks 28/32`, `false_success=2`, **exit 1** |
| `pytest tests/unit/ops/test_windowless.py -q` | `1 failed, 12 passed`, **exit 1** |
| `uv lock --check` | *«The lockfile at `uv.lock` needs to be updated»*, **exit 1** |
| `uv sync --frozen --dry-run` | **exit 0**, pero no instala `matplotlib` ni 5 de sus dependencias |

**No ejecuté** una sesión PAPER nueva (habría requerido alimentar barras 1m y abrir una ventana
de ejecución). Por tanto **no afirmo** que el runtime PAPER completo funcione hoy de punta a
punta: afirmo que hay evidencia registrada de que funcionó, y que sus verificadores se
comportan como se describe arriba al re-ejecutarlos.

---

## 3. De dónde salen los datos que consume

- El runner de campaña materializa barras de 1 minuto en `campaign/session/market-1m/*.jsonl`
  con `source: "binance_spot_rest_1m"` y `delivery_latency_ms` registrado (ej. 7 382 036 ms).
  Es decir: **barras reales grabadas**, no sintéticas, entregadas a la sesión con su latencia.
- Ese feed es también el que sostiene la prueba de causalidad del lane de visión
  (`src/trading_bot/vision/clock.py`, `quotes.py`).
- Una sesión nueva necesita su propio seed `market-1m/`; el repo no trae un dataset universal
  de 1m versionado para ese fin.

**Decisión:** el runtime PAPER ejecutable hoy es el de recuperación de sesión
(`paper_supervisor.py` + `def_run_019_prospective_run.py`) sobre un feed 1m registrado. El
runtime de estrategias (`start_paper_trading.py`, `autonomous_paper.py`) también ejecuta, pero
**no tiene sujeto**: 0 estrategias admitidas ⇒ solo puede producir `NO_TRADE`.

---

## 4. Dónde se rompe la cadena (con números)

| Ruptura | Detalle | Evidencia |
| --- | --- | --- |
| El ledger no tiene candidatos | 24 entradas, `admitted_for_paper=true` en **0** | `config/strategy_admission.json`, contado programáticamente (17 `NO_GROSS_EDGE` + 7 `COST_KILLED`) |
| El constructor exige pertenencia a `paper_candidates` | `paper_candidates` está vacío ⇒ **aunque el gross fuera positivo, el estado máximo es `COST_KILLED`** | `build_strategy_admission.py` L91-96 |
| Dos verificadores, un mismo flag `--campaign` | `paper_lock_campaign_verify.py` no comprueba el `schema_version` de la campaña (`TAP_PAPER_SUPERVISOR_CAMPAIGN_V1`) y la juzga con el contrato de otra (`iterations/`), reportando `FAIL 28/32` y `false_success=2` sobre evidencia que no le corresponde | `CAMPAIGN.json` declara `schema_version: TAP_PAPER_SUPERVISOR_CAMPAIGN_V1`; el verificador no lo lee (no hay comprobación de schema en su cabecera) |

**Decisión:** la primera ruptura es de *evidencia económica* (no de código). La tercera es de
*contrato de verificación* y es la que produce el número más peligroso del paquete: un
`false_success=2` real emitido por un verificador que no debía juzgar ese directorio.
