# DEPENDENCY MAP — la rebanada real del supervisor

## 1. Cierre de imports

Semillas: los ocho entry points que la lane documenta y ejecuta —
`paper_supervisor.py`, `paper_supervisor_campaign.py`, `paper_supervisor_verify.py`,
`paper_lock_campaign.py`, `paper_lock_campaign_verify.py`, `paper_session_status.py`,
`start_paper_trading.py` y **`def_run_019_prospective_run.py`** (el hijo por defecto del
supervisor; omitirlo ocultaba toda la cadena de `vision/`).

| Medida | Valor |
| --- | ---: |
| Ficheros `.py` alcanzables | **110** |
| Ya byte-idénticos en `main` | **68** |
| Ausentes en `main` | **35** |
| Presentes pero distintos | **7** |
| **Delta a migrar (código)** | **42** |
| Commits de la lane que tocan esos 42 | **38** |
| Config requerida, invisible al grafo | **2** (`config/vision.yaml`, `config/strategy_candidates_edge15.json`) |
| Dependencia de terceros no declarada en `main` | **1** (`matplotlib>=3.8,<4.0` en `pyproject.toml` + `uv.lock`) |
| Política de ignore que `main` no tiene | **1** (`.gitignore`: sin ella `reports/*` está excluido y ningún informe puede commitearse) |
| **Total de rutas del plan** | **47** (42 + 2 config + 2 dependencia + 1 ignore) |

Artefacto: `evidence/lane_graph.json` (`reachable_*`).

## 2. Las 42 rutas de código

**7 scripts** — `paper_supervisor.py`, `paper_supervisor_campaign.py`,
`paper_supervisor_verify.py`, `paper_lock_campaign.py`, `paper_lock_campaign_verify.py`,
`paper_session_status.py`, `def_run_019_prospective_run.py`.

**5 módulos `ops/`** — `__init__.py`, `paper_supervisor.py`, `session_status.py`,
`single_writer.py`, `windowless.py`. **El paquete `trading_bot.ops` no existe en `main`.**

**14 de `vision/`** — `chart`, `clock`, `contract`, `execution`, `guards`, `lane`, `ledger`,
`prompt`, `prospective`, `provenance`, `provider`, `quotes`, `settings`, `signal_sources`.

**9 de investigación y datos** — `market_data/minute_collector.py`,
`research/economic_recovery/{alpha15,contracts,costs,evidence,experiments,pit15}.py`,
`research/equity_drawdown.py`.

**7 modificados** — `scripts/start_paper_trading.py` (+5), `paper/broker.py` (+481/−28),
`paper/harness.py` (+51/−7), `paper/paper_cycle.py` (+93/−1),
`paper/reconciliation_v4.py` (+5), `risk/manager.py` (+339/−9),
`autonomous/contracts.py`.

## 3. Blast radius de los 7 modificados

Importadores en `main` (contados con `git grep` sobre `main`):

| Fichero | Δ | Importadores en `main` |
| --- | --- | ---: |
| `paper/broker.py` | +481/−28 | 18 |
| `risk/manager.py` | +339/−9 | 17 |
| `paper/harness.py` | +51/−7 | 6 |
| `paper/paper_cycle.py` | +93/−1 | 6 |
| `paper/reconciliation_v4.py` | +5 | 3 |
| `autonomous/contracts.py` | — | — |
| `start_paper_trading.py` | +5 | script |

Los dos grandes no son cosméticos: cambian el libro de papel (coste de venue dentro del
broker) y el gestor de riesgo (resolución de stops, ventana semanal). **Esa es la parte que
exige firma del risk-manager**, no la parte nueva de `ops/`.

## 4. Qué rompe la rebanada en `main`

`tests/unit/paper tests/unit/risk` sobre `main` + 42 ficheros: **6 failed, 170 passed**
(`evidence/PYTEST_42files_partial_migration.log`).

| Fallo | Causa | ¿La lane actualizó el test? |
| --- | --- | --- |
| `test_paper_cycle.py::test_broker_none_result_counts_but_no_idempotency` | contrato del broker cambió | **sí** (+10/−3 en la lane) |
| `test_paper_recovery.py` ×3 | reconciliación devuelve otro delta | **sí** (+6) |
| `test_futures_independent_verifier.py` ×2 | el gestor emite 28 checks más por decisión (`bracket_provenance`…) | **no** |

Los dos últimos **fallan también en la lane** (`evidence/PYTEST_lane_futures_verifier.log`,
2 failed / 6 passed): no los introduce la migración, los hereda. Es una regresión viva de la
lane sobre un test que existía en el merge-base y que la lane nunca tocó.

## 4-bis. La política de ignore

`main` tiene `reports/*` y solo `!reports/.gitkeep`: **todo informe está fuera del árbol**.
La lane añade ~250 líneas re-incluyendo cada subárbol (`!reports/edge-recovery/WP-EDGE-01/`,
…). Consecuencia doble: (a) el trabajo documental no podía aterrizar en `main` y por eso vive
en una rama; (b) cualquier migración que quiera llevar su evidencia necesita la regla, o el
commit se queda en silencio sin los informes. Este worktree de auditoría tuvo que usar
`git add -f` por lo mismo.

## 5. Dependencias que el grafo no ve (y costaron una sesión)

Sin `config/vision.yaml` y `config/strategy_candidates_edge15.json`, la rebanada arranca y
termina con **0 ciclos** (`STOP_BLOCKED`, exit 3). Con ellos: **1 ciclo**,
`STOP_COMPLETED (CLEAN_END)`, `live_orders 0`. Un grafo de imports no puede sustituir a
ejecutar la cosa.

## 6. Comparación con fusionar la lane

| | Rebanada | Lane completa |
| --- | ---: | ---: |
| Rutas | 47 | 1 804 |
| Commits | 38 | 301 |
| Ficheros `.py` nuevos en `main` | 35 | 450 |
| Informes arrastrados | 0 | 1 248 |
| Conflictos de merge | — (aplicación directa) | 0 |
| Test heredado roto | 2 (heredados, ver §4) | los mismos 2 |

## 7. Reproducir

```bash
python reports/ai-bots/TAP-SUPERVISOR-INTEGRATION-001/tools/lane_graph.py \
  --json reports/ai-bots/TAP-SUPERVISOR-INTEGRATION-001/evidence/lane_graph.json
python reports/ai-bots/TAP-SUPERVISOR-INTEGRATION-001/tools/lane_graph.py --broad \
  --json reports/ai-bots/TAP-SUPERVISOR-INTEGRATION-001/evidence/lane_graph_broad.json
```

La herramienta lee objetos de Git (`git show ref:path`), no un checkout, así que no depende de
en qué worktree se ejecute.
