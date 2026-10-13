# RUNTIME AUTHORITY MAP — WP-EDGE-05

**Qué es.** El mapa de autoridad del runtime **de este work package**: qué entrypoints existen de verdad,
qué código ejecutan, quién escribe qué, y qué queda fuera. Se ha establecido leyendo el repositorio,
ejecutando los entrypoints y consultando el sistema operativo — no infiriéndolo del informe de un
predecesor.

**Relación con el mapa del proyecto.** `reports/edge-recovery/runtime_authority_map.md` (WP-EDGE-00)
clasifica el runtime **PAPER** del proyecto y no menciona `edge03`/`edge04`/`edge05`: esa cadena no
participaba en él. Este documento cubre lo que WP-EDGE-00 no cubría y **no lo sustituye**.

**Ámbito.** Observación SHADOW. Sin órdenes, sin credenciales, sin capital, sin promoción.

---

## 1. Leyenda

| Clase | Significado |
| --- | --- |
| `RUNTIME_AUTHORITATIVE` | Lo ejecuta una tarea programada del sistema operativo y su salida es la evidencia viva. |
| `RUNTIME_REACHABLE` | Se ejecuta a mano o desde otro proceso del work package; escribe evidencia, nunca estado de trading. |
| `TEST_ONLY` | Solo lo ejecutan tests o verificadores. |
| `RESEARCH_ONLY` | Simulación/experimento offline. |
| `EXPERIMENTAL` | Prototipo sin consumidor estable. |
| `LEGACY` | Camino antiguo conservado sin uso verificado. |
| `ORPHAN` | Sin consumidores verificables. |
| `DEAD_CODE` | Código no alcanzable por ninguna ruta. |

## 2. Baseline técnico y operativo

| | |
| --- | --- |
| Rama / base | `agent/edge-recovery/WP-EDGE-00-baseline`, base WP-EDGE-04 `e07785b` |
| Commits de este WP | `40ba11c`, `17d0e44`, `6d62c79`, `aea659a`, `ad2e3e7`, `685a1ce`, y el que publica este mapa |
| Árbol de trabajo | limpio en todo lo de WP-EDGE-05; **131 entradas sucias de otros workstreams**, intactas |
| Host / intérprete | `DESKTOP-4CHO695` · `.venv\Scripts\python.exe` 3.11.15 |
| Tarea de la lane | `TradingAgentic-EDGE04-Forward` — `Ready`, `InteractiveToken`, `PT15M`, `IgnoreNew`, `StartWhenAvailable=true`, `RestartOnFailure 3×PT5M`, `ExecutionTimeLimit PT1H`, `LeastPrivilege`, último resultado `0` |
| Tarea del vigilante | `TradingAgentic-EDGE05-Watchdog` — instalada `19:01:32Z`, `Enabled`, `PT15M`, último resultado `0`, ejecución desatendida observada |
| Volumen | 5,653 GiB libres de 237,5 GiB (97,62 % usado) — suelos declarados 5 GiB / 2 GiB |
| Crecimiento de la lane | 1 493 484 bytes/día medidos en una ventana de 8,0 h |
| Snapshot de evidencia | `evidence/SNAPSHOT.json` (tamaño y `sha256` de cada artefacto del cierre) |
| Verificación vigente | `VERIFY_PASS` 13/13 · `SELF_TEST_PASS` 15/15 · exit 0 |

## 3. Entrypoints reales de esta cadena

| Entrypoint | Qué hace | Clase | Cómo se comprobó |
| --- | --- | --- | --- |
| `scripts/edge04_observer.py --scheduled --due` | El **único** entrypoint portátil de la lane de observación: toma el lease, preflight, ingesta PIT, reconciliación, evaluación SHADOW, sello, heartbeat | `RUNTIME_AUTHORITATIVE` | import verificado `from trading_bot.research.edge03.autonomous import …`; es el comando registrado en la tarea del sistema; 42 tick(s) en `runs.jsonl` |
| `scripts/edge05_watchdog.py` | Una lectura de salud; sin lease, sin pipeline, sin petición de mercado | `RUNTIME_AUTHORITATIVE` | tarea propia; 9 lecturas en `watchdog.jsonl`, todas con `market_requests: 0` y `wrote_to_lane: false` |
| `scripts/edge05_reconcile.py` | Reconstruye la cadena ledger↔barras desde los ficheros crudos y **escribe** los artefactos de reconciliación | `RUNTIME_REACHABLE` | ejecutado en este paquete: 42 ticks, 0 defectos abiertos |
| `scripts/edge05_verify.py` | Verificador independiente + matriz de sabotajes sobre copias | `TEST_ONLY` | exit 0; 15/15 sabotajes detectados |
| `scripts/edge05_closure.py` | Regenera los artefactos publicados desde el estado vivo | `TEST_ONLY` | 9 artefactos escritos, con su digest |
| `scripts/cap004_supervisor.py` | Supervisor de **otro** workstream (CAP-004), proceso propio por tarea del sistema | fuera de esta cadena | sin import cruzado con `edge03/04/05` en ninguna dirección; no tocado |

## 4. Inventario y clasificación

| Componente | Clase | Evidencia |
| --- | --- | --- |
| `src/trading_bot/research/edge03/autonomous.py`, `run.py`, `ingest.py`, `forward_plan.py`, `reporting.py`, `shadow.py`, `parity.py` | `RUNTIME_AUTHORITATIVE` | es el camino que ejecuta el entrypoint de la lane en cada tick |
| `src/trading_bot/research/edge05/watchdog.py` | `RUNTIME_AUTHORITATIVE` | ejecutado por la tarea del vigilante cada 15 minutos |
| `src/trading_bot/research/edge05/reconcile.py` | `RUNTIME_REACHABLE` | lo invoca el cierre/el operador; **no** está en el camino del tick |
| `src/trading_bot/research/edge05/__init__.py` | `RUNTIME_REACHABLE` | docstring del paquete, sin efectos |
| `scripts/edge05_*.py` | `TEST_ONLY` salvo el vigilante | ver §3 |
| `src/trading_bot/research/edge01/*`, `edge02/*` | `RESEARCH_ONLY` | campañas económicas offline; escriben `reports/`, no estado de observación |
| `src/trading_bot/research/campaign_lock.py` | `RUNTIME_AUTHORITATIVE` (compartido) | provee el lease de la lane; corregido en WP-EDGE-04, sin cambios aquí |
| `src/trading_bot/risk/manager.py`, `config/risk.yaml` | `RUNTIME_AUTHORITATIVE`, **no tocado** | `git diff HEAD` vacío sobre ambos |
| `src/trading_bot/strategies/*` | `RUNTIME_AUTHORITATIVE`, **no tocado** | `git diff HEAD` vacío: las estrategias están congeladas (`params_hash d073a2d6…`) |
| otros workstreams (`data/st6/*`, `evidence/real_decisions/*`, `docs/source_registry.md`, `scripts/cap004c_verify.py`, `scripts/st6_scheduler_witness.py`, …) | ajenos | 131 entradas sucias: **ninguna** se ha preparado, mezclado ni descartado |

## 5. Superficies de escritura, y quién escribe en cada una

| Superficie | Ruta | Escribe la lane | Escribe el vigilante |
| --- | --- | --- | --- |
| Tienda de barras forward | `data/forward/edge03/{1h,15m}/*.jsonl` | **sí** (append) | **no** |
| Ledger de ingesta | `data/forward/edge04/ledger/INGEST_LEDGER.jsonl` | **sí** | **no** |
| Ledger de slots y sellos | `data/forward/edge04/slots.jsonl`, `runs.jsonl` | **sí** | **no** |
| Lease | `data/forward/edge04/lock/*` (según `campaign_lock`) | **sí** | **no** (solo lo lee) |
| Cobertura / presupuesto de la lane | `data/forward/edge04/{coverage,resource_budget,health}.json`, `daily/<fecha>.json` | **sí** | **no** |
| Evidencia del vigilante | `data/forward/edge05/{watchdog.jsonl,watch_alerts.jsonl,LATEST.json,daily/*}` | **no** | **sí** (solo lo suyo) |
| Reconciliación | `data/forward/edge05/reconciliation/*` | **no** | **no** (la escribe el reconciliador) |
| Informes publicados | `reports/edge-recovery/WP-EDGE-05/*` | **no** | **no** (los escribe el cierre) |

## 6. Lo que este work package no toca

`git diff HEAD` **vacío** sobre `src/trading_bot/risk/`, `config/risk.yaml`,
`src/trading_bot/research/edge03/` y `src/trading_bot/strategies/`: no se ha modificado sizing, límites,
kill switch, estrategias, señales ni gates de promoción. La lane WP-EDGE-04 **no** se ha detenido ni
sustituido: la única interrupción fue el ensayo controlado y reversible de §4 del RUN_REPORT, con su
recibo y su reactivación. No se ha creado ningún segundo orquestador de trading.

## 7. Dominio de fallo y límites de la detección

* El vigilante cubre: tarea de la lane deshabilitada o fallando, cadencia rota, disparos perdidos,
  lease huérfano, tick muerto a mitad de escritura, tienda estancada, barras no recogidas, disco por
  debajo del suelo, evidencia ilegible, prueba de reinicio rota y su **propia** cadencia.
* **No** cubre: un host apagado, ni una caída de la propia tarea del vigilante más allá de lo que su
  última lectura deja escrito; para garantía fuera del host hace falta un observador externo, que este
  work package no ha creado y declara como limitación.
* `UNKNOWN` no equivale a éxito en ninguna comprobación del vigilante.

## 8. Reproducir el baseline

```bash
git log --oneline -8
git status --porcelain | wc -l
python scripts/edge05_watchdog.py --status
python scripts/edge05_reconcile.py
python scripts/edge05_verify.py --self-test
python scripts/edge05_closure.py
```
