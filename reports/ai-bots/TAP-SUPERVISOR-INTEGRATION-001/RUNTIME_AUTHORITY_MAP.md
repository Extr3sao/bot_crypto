# RUNTIME AUTHORITY MAP — qué corre de verdad y qué no

Método: cierre estático de imports (`tools/lane_graph.py`, artefactos
`evidence/lane_graph.json` y `evidence/lane_graph_broad.json`), leído desde objetos de Git, más
**ejecución** de cada entry point y de una sesión real. Nunca se deduce autoridad de que un test
pase: `RUNTIME_AUTHORITATIVE` exige que algo lo ejecute en la ruta operativa.

Universo: **1 257** ficheros `.py` en la lane, **818** en `main`. De los 448 `.py` que solo
existen en la lane (en `src/`, `scripts/`, `tests/`):

| Clase | Nº | Qué significa | Evidencia |
| --- | ---: | --- | --- |
| `RUNTIME_AUTHORITATIVE` / `RUNTIME_REACHABLE` | **35** | alcanzables desde los entry points del supervisor | `lane_graph.json → reachable_missing_from_main` |
| `RESEARCH_ONLY` / `EXPERIMENTAL` | **303** | alcanzables solo desde otros scripts (`edge*`, `exp_*`, `def_run_016..018`) | `lane_graph_broad.json` menos `lane_graph.json` |
| `TEST_ONLY` | **3** | ningún script los importa; solo los tests | `tests_per_module` |
| `ORPHAN` | **107** | ni script ni test los alcanzan | resto |
| `DEAD_CODE` | **0 declarados** | la alcanzabilidad estática no prueba muerte; no afirmo ninguna | — |

## Veredicto por componente

### `RUNTIME_AUTHORITATIVE` — corre en la ruta operativa

| Componente | Por qué es autoritativo |
| --- | --- |
| `scripts/paper_supervisor.py` + `src/trading_bot/ops/paper_supervisor.py` | supervisa y reintenta una sesión; **ejecutado**: `STOP_COMPLETED`, `STOP_NO_PROGRESS`, `RUNTIME_PATHS_DIRTY` |
| `scripts/def_run_019_prospective_run.py` + `src/trading_bot/vision/prospective.py` | *entry point* por defecto del supervisor; **ejecutado**: 5 ciclos en la lane, 1 ciclo en la rebanada migrada |
| `src/trading_bot/ops/{windowless,single_writer,session_status}.py` | ventana oculta, lock de escritor único, estado de sesión; los importa el supervisor y los usan los verificadores |
| `src/trading_bot/vision/{lane,contract,execution,guards,clock,ledger,provenance,quotes,provider,prompt,chart,settings,signal_sources}.py` | cadena de decisión y su auditoría; sin ellos el *entry point* no importa |
| `src/trading_bot/paper/*` (14 ficheros), `risk/{manager,defensive_blocks}.py`, `research/strategy_router.py`, `research/families/*`, `scanner/*`, `market_data/*` | ejecución, riesgo y señal del ciclo; alcanzables desde `prospective.py` |
| `src/trading_bot/research/economic_recovery/{alpha15,contracts,costs,evidence,experiments,pit15}.py`, `research/equity_drawdown.py` | cálculo económico del ciclo; **`costs.py` faltaba en el primer cierre** y el import lo destapó |
| `config/vision.yaml`, `config/strategy_candidates_edge15.json` | **no aparecen en ningún grafo de imports** y son obligatorios: sin ellos la sesión termina `STOP_BLOCKED`, con ellos `STOP_COMPLETED`. Medido, no supuesto |

### `RUNTIME_REACHABLE` — es runtime, pero no en la ruta por defecto

| Componente | Nota |
| --- | --- |
| `scripts/paper_supervisor_campaign.py`, `scripts/paper_lock_campaign.py`, `scripts/paper_lock_campaign_verify.py` | campaña con crashes y su verificador; **ejecutados**, con resultados en RUN_REPORT |
| `scripts/paper_supervisor_verify.py`, `scripts/paper_session_status.py` | verificación y estado; ejecutados |
| `scripts/start_paper_trading.py` | otro entry PAPER (`--provider fake`), no el del supervisor; el supervisor usa `def_run_019` |

### `TEST_ONLY` — existen para sus tests

Tres módulos que ningún script de la lane importa. Su PASS no acredita comportamiento.

### `RESEARCH_ONLY` / `EXPERIMENTAL` — 303 ficheros

Familias de scripts: `edge*` (101), `exp_003*`/`exp004a*` (62), `def_run_016..018` (18),
`ai_bots_*` (7), `wp*` (4), más soporte bajo `src/trading_bot/research/` y
`src/trading_bot/paper/lifecycle/`. Alcanzables, pero solo desde experimentos: no son
dependencia del supervisor.

### `LEGACY` — sustituido, no borrado

| Componente | Evidencia |
| --- | --- |
| `scripts/cap004_supervisor.py` | nombrado en `docs/agentic/EXECUTION_CHECKPOINT.md` y `docs/runtime/WINDOWLESS_EXECUTION.md` como predecesor; el supervisor vigente es `ops/paper_supervisor.py` |
| `scripts/tap_unblock_{paper,audit}.py`, `tap_lock_recovery_*` | un solo uso de recuperación; no aparecen en la ruta ni en los tests |

### `ORPHAN` — 107 ficheros

Ningún script ni test los alcanza: utilidades dentro de `reports/…` (por ejemplo
`reports/edge-recovery/diagnostics/build_run_report.py`) y herramientas de un solo uso. Antes de
migrar nada: verificar dos veces, porque un ORPHAN puede ser simplemente una entrada que el
cierre no modela (scripts `.cmd`, tareas programadas).

## Lo que este mapa **no** prueba

- La alcanzabilidad es estática: un import dentro de una función, un `importlib`, o un
  subprocess por ruta no se ven. Por eso la config necesitó una sesión real para aparecer.
- `AUTHORITATIVE` significa "alguien lo ejecuta en la ruta", no "está bien". El test de riesgo
  roto es runtime autoritativo y aun así incorrecto para `main`.
