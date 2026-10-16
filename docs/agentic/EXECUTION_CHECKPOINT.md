# Execution checkpoint — reanudación entre sesiones

> Documento vivo. **Antes de empezar cualquier sesión**: leer este fichero y validarlo contra Git
> (`git log -1`, `git status --porcelain`, rama actual). Si hay discrepancia, manda Git y este
> fichero se corrige con el estado real. **Después de cada paquete de trabajo relevante**:
> actualizar las secciones marcadas.
>
> Política completa en `AGENTS.md` §7. Reglas de campaña: `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`,
> nada de trading real, credenciales, apalancamiento ni cambios de límites de riesgo.

*Última actualización: 2026-10-16, sesión de recuperación RFC-EDGE-014R (segunda mitad).*

## 1. Objetivo actual

**WP-EDGE-014R** (RFC-EDGE-014R): recuperación económica del camino de paper trading.
Entregables: paquete de evidencias en `reports/economic-recovery/RFC-EDGE-014R/`
(`FINAL_REPORT.md`, `RUN_REPORT.md/json`, `INFORME_EJECUTIVO.md`, evidencia de ejecución paper,
reconciliación de comisiones, benchmarks externos Freqtrade/VeighNa/Jesse, verificación
independiente y suite adversarial), más su publicación por commits en la rama de trabajo.

## 2. Estado Git

- Rama: `agent/edge-recovery/WP-EDGE-00-baseline`, publicada por fast-forward en `origin`
  (`ee3922e..92327fd`).
- Últimos commits: `92327fd` — *Repair the cross-package failures the suite surfaced, and record
  the autonomy policy. [RFC-EDGE-014R]*; `dbddc58` — *Answer the recovery brief with executed
  evidence, and reconcile the paper arm's ledger. [RFC-EDGE-014R]*; base `ee3922e`
  (*Render every deliverable the brief names…*, RFC-EDGE-014).
- Publicado y ya no pendiente: el paquete `reports/economic-recovery/RFC-EDGE-014R/**`
  (incluido el dataset del replay en `scratch/PAPER_REPLAY_BARS.jsonl`), `scripts/edge14r_*.py`,
  `src/trading_bot/research/economic_recovery/**`, `.gitignore`, `tests/conftest.py`,
  `tests/unit/research/test_st6_scheduler.py`,
  `data/recovery/wp7/COST_BARRIER_CERTIFICATION.json` re-emitido, `AGENTS.md` §7 y este fichero.
- Sin preparar: modificaciones de otros agentes/WPs (p. ej. `data/st6/**`, `.ci/**`,
  `docs/research/work_packages/**`, `reports/economic-recovery/RFC-EDGE-014/**`,
  `evidence/real_decisions/**`, tests nuevos de `swing`/`rfc035*` de otro agente). **No se tocan
  ni se preparan**; se dejan intactas.

## 3. Hecho (con evidencia)

### Paquete 014R (ya generado, en staging)

| Pieza | Evidencia |
| --- | --- |
| Ejecución paper canónica aislada, dos brazos (GATE_INTACT / SANDBOX_ADMISSION), 879 ciclos sobre barras reales | `PAPER_EXECUTION_EVIDENCE.json|md` |
| Diagnóstico del camino de trading: 1758 invocaciones de router, todas `NO_TRADE:no_strategy_passed_gates` | `TRADE_PATH_RECONCILIATION.json|md` |
| Reconciliación de las dos convenciones de comisiones | `FEE_CONVENTION_RECONCILIATION.json|md` |
| Motores externos ejecutados: Freqtrade, VeighNa, Jesse (los tres en sus propios entornos) | `EXTERNAL_ENGINE_EXECUTION*.json`, `BENCHMARK_PARITY_REPORT*.json|md`, `ENGINE_DIFF*.csv` |
| Intento bloqueado de Jesse preservado con su causa | `EXTERNAL_ENGINE_JESSE_ATTEMPT_BLOCKED.json` |
| Comparación económica de 6 brazos | `ECONOMIC_COMPARISON.csv|json` |
| Prerregistro y captura del holdout prospectivo (estado `OOS_ACCRUING`) | `OOS_PREREGISTRATION.*`, `OOS_CAPTURE_MANIFEST.json` |
| Verificación independiente (builder ≠ verifier): 30/31, con `V04b` abierto | `INDEPENDENT_VERIFICATION.json|md` |
| Suite adversarial: 10/10 casos ejecutados | `ADVERSARIAL_SUITE.json` |
| Informes finales generados | `FINAL_REPORT.md`, `RUN_REPORT.md/json`, `INFORME_EJECUTIVO.md` |
| Capacidad en disco recuperada (1 823 182 848 bytes de cachés regenerables) | `CAPACITY_RECLAIM.json` |

### Gates de calidad sobre los ficheros de 014R (esta sesión)

| Gate | Resultado |
| --- | --- |
| `ruff check` sobre `scripts/edge14r_*.py` + `src/trading_bot/research/economic_recovery/` | **All checks passed** (antes: 24 errores) |
| `ruff format --check` sobre los mismos ficheros | **26 files already formatted** |
| `mypy` (strict, config del repo) sobre los mismos ficheros | **0 errores** (antes: 136) |

### Suite de tests: primera pasada completa y reparaciones

Primera pasada completa (`tests/unit`, 3952 tests): **10 fallos, 3942 pasados (26:32)**. Cada fallo
quedó diagnosticado y reparado por su causa, nunca por el síntoma:

| Fallo | Causa real | Reparación | Verificación |
| --- | --- | --- | --- |
| 8 fallos en `tests/unit/scanner/test_universe_scanner.py` (captura structlog vacía) | fuga de estado global: `research/edge03/run.py::quiet_runtime_logs` deja el wrapper de structlog en CRITICAL y nunca lo restaura; los tests de scanner corren después | `tests/conftest.py` nuevo: fixture autouse que captura y restaura `structlog.get_config()` alrededor de cada test | reproducido en par (`test_edge03_forward.py` + scanner: 8 failed) → tras el fix: **64 passed** |
| `test_cost_barrier_adversarial.py::test_the_certification_record_digests_content_not_a_checkout` | el registro de certificación (emitido 2026-10-11) quedó obsoleto cuando WP-EDGE-01 regeneró `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` en `7522255` (2026-10-12) | re-emisión por el propio certificador (`scripts/cost_barrier_certify.py --supersedes-reason ...`), que anota la supersesión en el registro | run 1 escribió el registro al día (sus contract tests aún veían el viejo → status FAILED); **run 2: EXIT=0, `status: CERTIFIED`, 0 razones, 0 advertencias, 0 digests desajustados**; cadena de supersesión con `previous_fingerprint` y motivo; lane tests: **93 passed** |
| `test_st6_scheduler.py::test_an_observed_slot_costs_nothing_to_re_tick` | el test leía las dos últimas filas del log compartido; la tarea programada real escribe en él y un reintento deja filas `ALREADY_RUNNING` entre medias | el test se ata al resumen que cada tick imprime en su propio stdout (`tick_summary()`), no al tail del log ajeno | test aislado: **1 passed** |

Suites complementarias: `tests/integration` + `tests/regression` → **24 passed** (1 run, 4.7 s);
`tests/bdd` → **23 passed**.

### Defecto del libro paper: diagnosticado y cerrado (V04b → reconciliado)

El paquete declaraba abierto `LEDGER_OPEN_CLOSE_MISMATCH` (299 aperturas vs 301 cierres). Diagnóstico
ejecutado sobre el **mismo dataset exportado** (`scratch/PAPER_REPLAY_BARS.jsonl`), con el broker
instrumentado para registrar cada transición que él mismo realiza:

- el broker abrió **348** posiciones y cerró **347** (301 por la liquidación del bucle, **46 dentro del
  propio ciclo del motor**);
- el registro publicado veía 299 aperturas porque (a) identificaba cada apertura por
  `(symbol, position.opened_at)` — un instante de `time.time()` que dos aperturas del mismo símbolo
  pueden compartir en un replay rápido — y el dedupe **descartaba aperturas reales** (2 colisiones
  medidas en la reproducción), y (b) solo leía los cierres que devolvía su propia llamada, de modo
  que los 46 cierres del motor quedaban invisibles.
- Reparación en `paper_exec._run_arm`: la identidad de una apertura pasa a ser
  `(symbol, opened_at, entry_price)` y los cierres se drenan del propio libro del broker
  (`closed_trades`), etiquetando su origen (`engine_cycle` / `settlement_check` / `final_mark`).
- Evidencia regenerada **offline desde el dataset exportado**: `canonical_digest` y
  `exported_sha256` **sin cambios**; ahora `realised_pnl = −212.544674 =` variación de equity
  (antes −76.5958), 348 aperturas / 347 cierres / 1 posición abierta al terminar, y cada cierre
  nombra una apertura registrada.
- Verificación independiente re-ejecutada: **31/31, veredicto VERIFIED**; `open_items: []`; los
  informes declaran el cierre en vez de absorberlo.

Artefactos regenerados en consecuencia: `PAPER_EXECUTION_EVIDENCE.*`, `TRADE_PATH_RECONCILIATION.*`,
`FEE_CONVENTION_RECONCILIATION.*`, `ECONOMIC_COMPARISON.*`, `ADVERSARIAL_SUITE.*`,
`INDEPENDENT_VERIFICATION.*`, `RUN_REPORT.*`, `FINAL_REPORT.md`, `INFORME_EJECUTIVO.md`.

Contra la regresión: `tests/unit/research/test_edge14r_paper_ledger.py` (5 checks, **5 passed**) lee
la evidencia publicada y comprueba las identidades del libro; con la evidencia saboteeada en las
tres formas que cubre (quitar los cierres del motor, tirar dos aperturas, duplicar una) el test
falla — 1, 2 y 1 fallos respectivamente — y con la evidencia intacta pasa.

## 4. Pendiente

Nada de esta ronda queda sin ejecutar. Los dos elementos que siguen abiertos **no son trabajo
pendiente de una sesión**, sino estado del mundo que solo el tiempo o una estrategia admitida
pueden cambiar:

1. **Holdout prospectivo `OOS_ACCRUING`** — necesita al menos el umbral congelado de operaciones
   cerradas por estrategia antes de poder aceptar o rechazar nada; hoy tiene una fracción.
2. **Una estrategia admitida** con borde bruto positivo medido tras costes: es la entrada que el
   paquete no produce a propósito. Ninguna familia de las evaluadas la alcanza.

Ronda cerrada y publicada: `tests/unit` completo **3952 passed** (`/tmp/edge14r/unit_tests_full2.log`,
EXIT=0), `tests/integration` + `tests/regression` **24 passed**, `tests/bdd` **23 passed**,
verificación independiente **31/31 VERIFIED**, suite adversarial **10/10**, registro de
certificación re-emitido **CERTIFIED**, `ruff check` + `ruff format --check` + `mypy` limpios en
los ficheros del paquete.

## 5. Bloqueos / items abiertos (no ocultar)

- **Cerrado**: `V04b` / `LEDGER_OPEN_CLOSE_MISMATCH` ya no es un item abierto — ver §3
  (identidad de apertura y drenaje de cierres desde el libro del broker; 31/31 checks).
- **Sin estrategia admitida**: el ledger de admisión comprometido (`config/strategy_admission.json`)
  no admite ninguna familia. Es el freno correcto, no un defecto.
- **Holdout prospectivo** `OOS_ACCRUING`: sin barras suficientes para puntuar.
- **Contención con la tarea programada ST6** (entorno, no defecto): en este host corre la tarea
  real `TradingAgentic-ST6-Forward` (ventanas a las 12:03/16:03/20:03 UTC y latido cada 15 min);
  puede hacer esperar a los tests de `test_st6_scheduler.py` y escribía en el log compartido. Los
  tests ya no dependen del tail de ese log, pero las esperas por el lease siguen siendo del entorno.
- `quiet_runtime_logs` sigue dejando el structlog global en CRITICAL en un proceso largo del
  *runtime*; el guardia creado es de tests. Un arreglo de producción (context manager que restaure)
  queda **pendiente y fuera de este paquete** para no cambiar comportamiento de runtime sin su RFC.

## 6. Comandos de reanudación

```bash
# 0. Estado real
git -C "$(git rev-parse --show-toplevel)" log --oneline -3
git -C "$(git rev-parse --show-toplevel)" status --porcelain | head -40

# 1. Suite unitaria completa (log persistente; ~26 min)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit -q \
  --tb=short -rf -p no:cacheprovider > /tmp/edge14r/unit_tests_full2.log 2>&1; echo "EXIT=$?"

# 2. Integración, regresión y BDD
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/integration tests/regression tests/bdd -q \
  --tb=short -rf -p no:cacheprovider > /tmp/edge14r/integration_regression.log 2>&1; echo "EXIT=$?"

# 3. Re-emitir el registro de certificación (el propio certificador corre sus contract tests)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/cost_barrier_certify.py \
  --supersedes-reason "<por qué este registro reemplaza al de HEAD>" > /tmp/edge14r/cert_run2.log 2>&1; echo "EXIT=$?"

# 4. Gates de estilo/tipos sobre el paquete 014R
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m ruff check scripts/edge14r_*.py src/trading_bot/research/economic_recovery/
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m mypy scripts/edge14r_*.py src/trading_bot/research/economic_recovery/

# 5. Verificación independiente del paquete (re-deriva los números)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge14r_verify.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge14r_adversarial.py
```

## 7. Protocolo de actualización

- Al **cerrar un hito**: marcar la fila correspondiente en §3 y actualizar §4/§5.
- Al **cortarse la sesión**: anotar el comando exacto que se estaba ejecutando y su log.
- **Nunca** mover un elemento de §4 a §3 sin evidencia ejecutada (log, artefacto, exit code).
