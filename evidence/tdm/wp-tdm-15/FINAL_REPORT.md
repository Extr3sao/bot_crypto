# FINAL REPORT — RFC-TDM-015 (Live Signal Intelligence, Paper Operations & Dashboard)

**Fecha:** 2026-10-26 · **Run de referencia:** `tdm15-live-02` · **Modo:** `PAPER_ONLY`
**Estado económico heredado:** `NO_ELIGIBLE_CANDIDATE / REJECTED_ALPHA` — **sin cambios**.

**Veredicto: `PARTIAL`.** El plano de señales está verificado en ejecución real; PAPER
experimental está cableado y bloqueado por la admisión (0 estrategias elegibles, 0
órdenes simuladas); la IA real está **BLOCKED** por falta de credenciales; la ventana
de 72 h **no se intentó** y se declara `NOT_YET_VERIFIED`. Ninguna ACC se marca PASS
por inspección estática, y ninguna se marca PASS por conveniencia.

---

## 1. Tabla ACC (global)

| ID | Estado | Evidencia |
| --- | --- | --- |
| ACC-01 Mapa de runtime y baseline | **PASS** | [runtime_authority_map.md](../../docs/runtime/runtime_authority_map.md) (sección RFC-TDM-015, re-derivada por ejecución) + [BASELINE_RUN_REPORT.json](BASELINE_RUN_REPORT.json): suite 3406 pass / 90 fail / 14 error en 531 s, comparada nodo a nodo contra el commit padre en worktree limpio |
| ACC-02 Publicación en el remoto correcto | **PASS** | `origin = https://github.com/Extr3sao/bot_crypto.git` (no el snapshot `Bot-Trading` de §2); SHA remoto en [GITHUB_SYNC_REPORT.json](GITHUB_SYNC_REPORT.json), sin force-push y sin merge |
| ACC-03 Ciclos vivos BTC/ETH/SOL | **PASS** | 21 eventos sobre 7 velas cerradas (09:35→10:05 UTC), 7 por activo, `source=REAL`, `data_quality=OK`; [SIGNAL_RUN_REPORT.json](SIGNAL_RUN_REPORT.json). **Límite declarado:** `config/realdata/exchange.yaml` fija `sandbox: true`, así que el venue es el testnet público, no el libro de producción |
| ACC-04 Cero futuro, stale, gaps, duplicados | **PASS** | verificador: `signals.no_look_ahead`, `traces.hash_chain_intact`, integridad `{duplicates: 0, malformed: 0, pit_violations: 0}`; 119 tests dirigidos verdes; el colector declara sus gaps en su propio estado (34 en la ventana reanudada) |
| ACC-05 Observaciones, candidatas, rechazos, NO_TRADE | **PASS** | 21 filas `CANDIDATE/ALPHA` con motivo objetivo `gross_edge_not_positive:-4.56bps`, `risk_state=APPROVED`, 0 órdenes; contadores reconciliados con 21 trazas y con la API (21/21) |
| ACC-06 Estrategias clasificadas, propuestas solo con datos reales | **PASS** | ledger: 24 estrategias, `COST_KILLED=7`, `NO_GROSS_EDGE=17`, 0 admitidas; cada propuesta lleva `strategy_id` y proviene de la vela cerrada real |
| ACC-07 PAPER experimental con gates deterministas | **PARTIAL** | ruta cableada y gate determinista evaluado (`APPROVED`), pero `PAPER_ORDER: BLOCKED` porque el ledger no admite ninguna estrategia: **0 órdenes simuladas**. No se puede acreditar el ciclo de vida completo sin estrategia elegible, y no se fabricó una |
| ACC-08 Ledger/portfolio/reconciliación tras restart | **PASS** | `--restart` con el mismo run id: `reconciliation=CONSISTENT` → `RECOVERED`, 21 ids únicos, secuencia estrictamente monótona, `duplicate_ids=0`; 57 tests de `tests/unit/paper` verdes, incluidos los 9 casos de caída |
| ACC-09 IA REAL instrumentada | **BLOCKED** | sin `SIGNAL_ANALYST_API_KEY`: 6 filas `NOT_CONFIGURED / PROVIDER_NOT_CONFIGURED`, 0 inferencias, 0 mocks. `AI_REAL_VERIFIED` no se declara. Desbloqueo único: definir la clave y relanzar el sidecar |
| ACC-10 UI con eventos reales | **PASS (con salvedad)** | navegador real sobre `http://127.0.0.1:8790`: título `tdm15-live-02`, banner `REJECTED_ALPHA — EXPERIMENTAL PAPER, NOT VALIDATED`, filtro `ETH/USDT` → `showing 7/7`; `/healthz`, `/api/*` 200; `POST /api/signals` → 405. **Salvedad:** el compositor no produjo fotogramas, así que no hay PNG; se fija el `sha256` del texto DOM y los hashes HTTP ([DASHBOARD_E2E.json](DASHBOARD_E2E.json)) |
| ACC-11 Operación continua 72 h | **NOT_YET_VERIFIED** | ventana medida: 30 min de cierres de vela en dos tramos + parada limpia + reanudación; 72 h no se intentaron. No se certifica 24×7 ([SOAK_REPORT.json](SOAK_REPORT.json)) |
| ACC-12 Sin live orders, secretos ni saltos de riesgo | **PASS** | `live_orders=0`, `orders_created=0`, 0 credenciales de exchange en los hijos PAPER (solo la clave LLM del sidecar, por entorno); verificador 29/29 checks; `POST` 405; ninguna ruta LIVE habilitada |
| ACC-13 Informe sin false success | **PASS** | este informe + [FINAL_REPORT.json](FINAL_REPORT.json); fallos de suite y defectos abiertos visibles; `false_success=0` |

### Gates separados

| Gate | Resultado |
| --- | --- |
| `SIGNAL_STREAM_VERIFIED` | **PASS** — datos + evaluación + auditoría + UI |
| `EXPERIMENTAL_PAPER_VERIFIED` | **NOT DEMONSTRATED** — 0 estrategias elegibles, 0 órdenes simuladas |
| `AI_REAL_VERIFIED` | **BLOCKED** — sin proveedor configurado |
| `PAPER_OPERATIONAL_VERIFIED` | **NOT ACHIEVED** — requiere los tres anteriores + continuidad |
| `ALPHA_ELIGIBLE` | **NO** — `REJECTED_ALPHA` intacto |
| Independencia del verificador | `INDEPENDENCE_NOT_DEMONSTRATED` — mismo operador; solo la ruta de código es distinta |

---

## 2. Qué se ejecutó de verdad

```text
run_id      tdm15-live-02
ventanas    2 (una parada por duración + una reanudación con --restart)
cierres     7 velas de 5m (09:35:05Z … 10:05:06Z)
activos     BTC, ETH, SOL (7 eventos cada uno)
decisiones  21  →  stage CANDIDATE=21, kind ALPHA=21, risk APPROVED=21
órdenes     0 PAPER, 0 LIVE
análisis    6 filas NOT_CONFIGURED (cobertura 6/21 = 28.6 %)
parada      stop_report.verdict = CLEAN, escalated = [], todos los hijos exit 0
reanudación reconciliation CONSISTENT → RECOVERED
```

Comandos reproducibles:

```powershell
# servicio PAPER + colector + retención + laboratorio + analista
uv run python scripts/start_paper_lab.py --run-id tdm15-live-02 --provider ccxt `
  --assets BTC,ETH,SOL --symbols BTCUSDT,ETHUSDT,SOLUSDT --timeframe 5m `
  --paper-cadence bar-close --duration-hours 0.45 `
  --data-root reports/microstructure-forward-lab/tdm15-live-02

# consola read-only (loopback)
uv run python scripts/paper_lab_dashboard.py --port 8790 --run-id tdm15-live-02

# verificación independiente contra ficheros + HTTP
uv run python scripts/wp_signal_verify.py --run-id tdm15-live-02 `
  --dashboard-url http://127.0.0.1:8790
```

`--data-root` es obligatorio para un run id nuevo: un mismo árbol de captura
pertenece a una sola ejecución (ver D-01).

---

## 3. Defectos

| ID | Estado | Descripción | Evidencia |
| --- | --- | --- | --- |
| D-01 | **FIXED** | Un run id nuevo sobre un árbol de captura ya usado hacía crash-loop del colector (3 reinicios, lab `DEGRADED`) hasta agotar el presupuesto. Ahora el lanzador lo rechaza antes de crear nada (`EXIT_CAPTURE_ROOT_CONFLICT = 5`) y nombra las dos salidas (`--data-root` / `--resume`) | `tdm15-live-01` (3 restarts, exit 2, `STORAGE_WRITE_FAILURE`) vs `tdm15-live-02` (0 restarts, `HEALTHY`) |
| D-02 | **FIXED** | La espera de cierre de vela dormía hasta 5 min sin mirar el STOP: el supervisor tenía que matar PAPER y el veredicto era `FAILED`. Ahora `wait_for_cadence` duerme en rodajas y responde al mismo predicado | `tdm15-live-01` verdict `FAILED`/`escalated:[paper]` vs `tdm15-live-02` verdict `CLEAN` |
| D-03 | **FIXED** | La consola gastaba 12,8 s por petición: 25 `tasklist` por página (dos por hijo). Una tabla de procesos cacheada la deja en 65–130 ms medidos | `status_payload` 12 973 ms → 1 812 ms (código) y 65–129 ms servido |
| D-04 | **FIXED** | `filter` cambiaba la URL pero no el tablero (18 filas para `?symbol=BTC/USDT`). El tablero se renderiza filtrado en la misma respuesta | `showing 18/18` antes vs `showing 7/7` después, en el mismo submit |
| D-05 | **FIXED** | El analista salía si el run dir aún no existía (carrera con el arranque del supervisor) y quemaba el presupuesto de reinicios | 2 reinicios en `tdm15-live-01`, 0 en `tdm15-live-02` |
| D-06 | **OPEN** | `PAPER_RUN.json` se reescribe al terminar sin `provider`, `environment`, `assets` ni `timeframe`: se pierde la procedencia del run y el verificador no puede contrastar `source` contra el proveedor (`provider: null`) | [SIGNAL_RUN_REPORT.json](SIGNAL_RUN_REPORT.json) lee el proveedor del plan de lanzamiento y lo declara |
| D-07 | **OPEN** | El analista vuelve a seleccionar las mismas filas `NOT_CONFIGURED` en cada pasada (límite 6): 15 de 21 señales nunca reciben fila de análisis | `logs/analyst.log`: los mismos 5 ids repetidos; cobertura 6/21 |
| D-08 | **OPEN** | Tras una parada limpia `final_state` es `DEGRADED` porque `system_state()` cuenta a los hijos críticos detenidos como degradación. El veredicto autoritativo es `stop_report.verdict = CLEAN` | [SOAK_REPORT.json](SOAK_REPORT.json), [SIGNAL_RUN_REPORT.json](SIGNAL_RUN_REPORT.json) |
| D-09 | **OPEN** | `--restart` reescribe `LAB_RUN_REPORT.json` y reinicia `heartbeat.jsonl`: se pierde el informe de la ventana anterior (sobreviven los ciclos del log) | [SOAK_REPORT.json](SOAK_REPORT.json) → `windows.replaced_by_restart` |
| D-10 | **OPEN** | La captura reanudada declara 34 gaps en su propio estado; hay que clasificarlos (recuperables/irrecuperables) en el manifiesto | `SOAK_REPORT.json` → `collector` |
| D-11 | **EXPLAINED** | 9 nodos fallan sólo en este checkout compartido: 8 por artefactos locales no versionados (`data/rfc046`, `data/economic001`) presentes aquí y ausentes en el worktree limpio, cuyo hash ya no coincide con su registro; 1 por la captura de otro actor escribiendo segmentos durante el digest. Ninguno toca módulos modificados | [BASELINE_RUN_REPORT.json](BASELINE_RUN_REPORT.json) → `comparison.regressions` |

---

## 4. Bloqueos y límites

1. **IA real (B-01).** Falta `SIGNAL_ANALYST_API_KEY` en este host. Sin ella no hay
   inferencia y la ACC-09 queda `BLOCKED`; no se ha simulado ninguna respuesta.
2. **72 h (B-02).** No se intentó la ventana de soak. Lo medido es 30 min de cierres
   más parada y reanudación limpias. `PAPER_OPERATIONAL_VERIFIED` no se reclama.
3. **Venue.** `sandbox: true` en la configuración de exchange: es el testnet público.
   Los precios y la liquidez no son los del libro de producción.
4. **PAPER real.** El ledger no admite ninguna de las 24 estrategias (`COST_KILLED=7`,
   `NO_GROSS_EDGE=17`), así que ningún ciclo `EXPERIMENTAL_PAPER` puede existir.
   Mostrar 0 órdenes es la verdad, no una carencia de instrumentación.
5. **Verificador.** `wp_signal_verify.py` no importa el productor y recomputa hashes,
   pero lo ejecuta el mismo operador. `INDEPENDENCE_NOT_DEMONSTRATED`.
6. **Suite.** 90 fallos + 14 errores en esta máquina, heredados en su mayoría
   (97 nodos fallan también en el commit padre). No se han ocultado ni "arreglado"
   con supresiones. El defecto D-05 del cierre TDM-014A pertenece a otro linaje y
   no se ha re-evaluado aquí.
7. **Captura de pantalla.** El webview no compuso fotogramas; el E2E se acredita con
   la interacción real, el texto DOM hasheado y las respuestas HTTP, no con un PNG
   inventado.

---

## 5. Cierre obligatorio (§10)

```text
PHASE                 RFC-TDM-015 — WP-00 a WP-05, primera ventana operativa
COMMITS               ver GITHUB_SYNC_REPORT.json y la respuesta de sesión
PUSHED_REMOTE_SHA     ver GITHUB_SYNC_REPORT.json (verificado con git ls-remote)
IMPLEMENTED           plano de señales (proyección), analista asesor, consola con
                      banner económico, preflight del árbol de captura, parada
                      consciente del cierre de vela, tabla de procesos cacheada,
                      filtro SSR del tablero, generador de evidencia
TESTS                 3406 pass / 90 fail / 14 error (531 s) + 119 dirigidos + 57 paper
RUNTIME_VALIDATION    2 ventanas, 7 cierres, 21 decisiones, parada CLEAN, restart RECOVERED
PAPER_VALIDATION      0 órdenes (PAPER_ORDER BLOCKED por admisión); broker intacto
AI_VALIDATION         UNAVAILABLE — 6 filas NOT_CONFIGURED, 0 inferencias
FALSE_SUCCESS         0
DEFECTS               D-01..D-05 FIXED · D-06..D-10 OPEN · D-11 EXPLAINED
BLOCKERS              B-01 clave LLM ausente · B-02 ventana 72 h no intentada
EVIDENCE              evidence/tdm/wp-tdm-15/** (10 artefactos + este informe)
ARCHITECTURE_STATUS   sin orquestador nuevo, sin dashboard nuevo, sin BD nueva:
                      reutiliza PAPER, trazas, ledger, consola y supervisor existentes
RFC_STATUS            PARTIAL — SIGNAL_STREAM_VERIFIED; PAPER/AI/operacional no certificados
NEXT_PHASE            clave del proveedor LLM + admisión de una estrategia experimental
                      + 72 h de soak con SLO definidos antes del ensayo
```
