# FINAL_REPORT — RFC-PAPER-008 (PAPER/SHADOW 24×7 sobre datos públicos reales)

**Fecha:** 2026-10-26 · **Rama:** `feat/rfc-paper-008` · **PR:** [#52](https://github.com/Extr3sao/bot_crypto/pull/52) (DRAFT)
**Commit de la evidencia:** `039e3db1` (`fix(dashboard): refresh the health cards, not only the signals table`)
**Host:** Windows 11 (10.0.26200), Python 3.11.15, uv 0.11.26
**Estado global:** `E2E_REAL_VERIFIED` · `AI_REAL_BLOCKED_NOT_CONFIGURED` · `24H_NOT_VERIFIED` · `PAPER_ORDER_BLOCKED`

---

## 1. Resumen ejecutivo

El PAPER/SHADOW funciona de extremo a extremo con datos públicos reales de
Binance (`api.binance.com`, sin claves): ingesta → decisión → `DecisionTrace` →
`signals.jsonl` → dashboard HTTP (loopback) → sidecar de IA read-only. Se observaron
**dos ventanas supervisadas** (1 h 0 min + 32 min 39 s = **0 h 57 min** de
laboratorio, 16 ciclos de decisión y **33 señales** en la ventana certificada), con
**0 órdenes PAPER**, **0 fills**, **1 observación SHADOW** y **0 duplicados**.

Lo que **no** se puede afirmar y no se afirma:

- **24 h continuas**: no observadas ⇒ `24H_NOT_VERIFIED`.
- **IA real**: no hay `SIGNAL_ANALYST_API_KEY` en el host ⇒ `AI_REAL_BLOCKED_NOT_CONFIGURED`.
  El camino HTTP se probó con un stub local y está etiquetado como contrato, no como IA real.
- **PAPER_ORDER**: 0/24 estrategias admitidas ⇒ bloqueado por diseño (`PAPER_ORDER_BLOCKED_ADMISSION_0_OF_24`).
- **Rentabilidad**: no medida; no hay fills PAPER. `realised_paper_pnl_after_costs = null`.

## 2. Qué corre y dónde verlo

| Elemento | Valor |
| --- | --- |
| Dashboard | `http://127.0.0.1:8981/` (loopback, read-only, auto-recarga 60 s) |
| Run certificado | `paper-lab-rfc008-live-02` |
| Datos | `ccxt` / `binance-public-rest` / `MAINNET` / `source=REAL` |
| Símbolos / temporalidad | BTC, ETH, SOL · `5m` |
| Capacidades | `INGEST=ENABLED`, `SIGNALS=ENABLED`, `SHADOW=ENABLED`, `PAPER_ORDER=BLOCKED`, `LIVE=DISABLED` |
| Arranque manual | `uv run python scripts/start_paper_lab.py --provider ccxt --assets BTC,ETH,SOL --timeframe 5m --paper-cadence bar-close --duration-hours 2 --data-root reports/lab-data/<run-id>` |
| Dashboard manual | `uv run python scripts/paper_lab_dashboard.py --run-id <run-id> --port 8981` |

La instalación persistente en el Programador de tareas de Windows **no se ha
hecho**: requiere autorización explícita sobre el host (RFC §5, WP-008D).

## 3. Ventanas observadas

| Ventana | Inicio (UTC) | Fin (UTC) | Duración | Ciclos | Señales | SHADOW | Reinicios | Parada |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `live-02` / 1 | 12:21:38 | 12:46:03 | 1 475,27 s (24,6 min) | 5 | 15 | 1 | 1 (sidecar, recuperado) | `--restart` |
| `live-02` / 2 | 12:46:03 | 13:18:42 | 1 958,98 s (32,7 min) | 11 | 33 (acumuladas) | 1 | 0 | `STOP` file |

Total de laboratorio observado: **3 434,25 s (0,95 h)** · 24 h: **NO**.

La ventana 2 es una **reanudación con el mismo `run_id`**: las 15 señales previas se
conservaron, las nuevas se añadieron con `signal_id` único (33/33) y 0 análisis
duplicados. Evidencia: `evidence/paper008/live-02/window-1/` y `window-2/`.

## 4. Defectos reales encontrados y corregidos

| ID | Defecto | Evidencia de ejecución | Corrección | Test |
| --- | --- | --- | --- | --- |
| D-01 | `source=REAL` sobre datos de **testnet** | `sandbox=True` en el connector; precios 80 428,93 vs 80 435,35 en mainnet; 6 filas `REAL` | el scanner lee `market_data/public_rest.py` (G-7); `PAPER_RUN.json` publica `data_transport`; testnet solo puede publicar `FAKE` | `test_real_data_provenance.py`, `test_public_rest.py`, `test_real_data_validation.py` |
| D-02 | `GET /healthz` sin respuesta | `tasklist` midió **10,2 s** para 557 procesos y una vez colgó más allá de su timeout; conexiones aceptadas sin respuesta | consulta Win32 acotada (`OpenProcess` + `QueryFullProcessImageNameW`), sin subproceso | `test_windows_liveness_never_spawns_a_process`; medido `/healthz` **0,098 s** |
| D-03 | El sidecar sin clave nunca cubría señales nuevas | `coverage 8/12`; los mismos 5 `signal_id` re-examinados en cada pasada | `NOT_CONFIGURED` terminal mientras no haya proveedor; el backlog vuelve al aparecer la clave | `test_not_configured_rows_do_not_starve_newer_signals`, `test_sidecar_marks_not_configured_and_keeps_running` |
| D-04 | Un reinicio dejaba el laboratorio `DEGRADED` para siempre | sidecar muerto y recuperado en 5 s; 40 min después seguía `DEGRADED` | ventana de recuperación de 300 s; `restarts` se conserva como historia | `test_a_recovered_restart_does_not_pin_the_lab_to_degraded` |
| D-05 | El dashboard no refrescaba la salud | tras `--restart`, la página seguía mostrando `DEGRADED` y uptime viejo hasta recargar a mano | recarga completa cada 60 s, omitida si el operador escribe en un filtro | `test_the_page_refreshes_the_health_cards_and_not_only_the_table` |

## 5. Métricas certificadas (RUN_REPORT.json)

```text
run_id                  paper-lab-rfc008-live-02
git_commit              039e3db17276d9b800ecd935dc91679580a7ffa3
provider / venue        ccxt / ccxt:binance:binance-public-rest
market_data             MAINNET          signal_source REAL
uptime                  1958.982 s       cycles 11
signals                 33               traces 33
stages                  CANDIDATE/ALPHA 28 · REJECTED/NO_ALPHA 4 · SHADOW/ALPHA 1
no_trade_reasons        NO_TRADE_STRATEGIC 4
admission_eligible      0                paper_orders 0
shadow_outcomes         1                paper_fills 0
realised_pnl            null (no fills)
data_age                3.746 s          max_gap 301.093 s
duplicate_count         0
analysis                NOT_CONFIGURED 33
llm_provider            null             llm_cost_usd null
verifier_result         true             false_success 0
blockers                PAPER_ORDER_BLOCKED_ADMISSION_0_OF_24, AI_NOT_CONFIGURED
```

Hashes de todos los artefactos en `RUN_REPORT.md` § Evidence sha256.

## 6. Verificación independiente (BUILDER ≠ VERIFIER)

Dos verificadores separados, ninguno importa el código productor:

1. `scripts/wp_signal_verify.py --run-id paper-lab-rfc008-live-02 --dashboard-url http://127.0.0.1:8981`
   → **PASS**: 33/33 filas enlazadas a su traza, hash recomputado, sin look-ahead,
   `source` coherente, 33 análisis honestos, dashboard 33/33, `POST` 405.
2. `scripts/rfc_paper_008_verify.py --report docs/agentic/paper_rfc008/RUN_REPORT.json --dashboard-url http://127.0.0.1:8981`
   → **PASS**: todas las comprobaciones `ok`, hashes de evidencia frescos, métricas
   iguales a los ficheros, `false_success=0`, duración honesta con `24H_NOT_VERIFIED`.
   Resultado: `docs/agentic/paper_rfc008/VERIFY_RUN_REPORT.json`.

El verificador **rechazó** un informe intermedio generado mientras la ventana seguía
escribiendo (`report.evidence_hashes: stale`, `analysis_counts` desalineado). Es el
comportamiento correcto: solo un run cerrado se certifica.

## 7. Pruebas ejecutadas

| Comando | Resultado |
| --- | --- |
| `uv run pytest tests/unit/autonomous tests/unit/observability tests/unit/market_data tests/unit/paper tests/unit/risk tests/unit/scanner tests/unit/test_app_demo.py -q` | **831 passed** (57,9 s), árbol sin captura activa |
| `uv run pytest tests/unit/autonomous/test_signal_analysis.py -q` | 23 passed |
| `uv run pytest tests/unit/autonomous/test_pid_identity.py tests/unit/autonomous/test_lab_ops_hardening.py -q` | 28 passed |
| `uv run pytest tests/unit/autonomous/test_supervisor.py tests/unit/autonomous/test_lab_operations.py -q` | 38 passed |
| `wp_signal_verify.py` sobre `live-01` y `live-02` | PASS (exit 0) |
| `rfc_paper_008_verify.py` sobre el informe final | PASS (exit 0) |

Nota de honestidad: durante la captura activa,
`tests/unit/observability/test_dashboard_server.py::test_runtime_artifacts_are_untouched_by_serving`
falla porque el test digiere todo el árbol y el colector está escribiendo segmentos.
Con el laboratorio parado pasa (verificado). No se ha relajado el test.

**Rojo preexistente, ajeno a este RFC:** `tests/unit/research/test_recovery_determinism.py::test_repeated_reproduction_is_byte_identical`
falla por un `payload_sha256` del audit económico ya divergente en la rama. Ningún
fichero de ese módulo fue tocado por este trabajo. La suite `tests/unit` completa
además se detiene en un test de *clean-checkout rehearsal* que exige un árbol limpio.

## 8. IA (WP-008C)

- Sin clave: 33/33 filas `NOT_CONFIGURED`, `analysed=0`; nunca se inventó un análisis.
- Con un endpoint compatible local **stub** (no un modelo): 9 `ANALYZED` con `claim`,
  `counter_evidence`, `uncertainties`, `model`, `prompt_version`, `latency_ms`,
  `cost_usd=0,000768`, visibles en `/api/analysis` (9/9, p95 30 ms).
- Inyecciones reales: proveedor caído → 4 `FAILED` sin crash; HTTP 405 → 2 `FAILED`;
  timeout → 1 `FAILED`; presupuesto 0 → 5 `PENDING`, 0 llamadas; recuperación
  posterior → `ANALYZED` sin borrar las filas fallidas.
- Detalle y límites: `docs/agentic/paper_rfc008/AI_CONTRACT.md` y
  `evidence/paper008/ai_contract/`.

## 9. Resiliencia (WP-008D)

| Prueba | Resultado | Evidencia |
| --- | --- | --- |
| Parada limpia por STOP | `final_state=DEGRADED`, `stop_reason=STOP file`, hijos sellados | `window-2/LAB_RUN_REPORT.json` |
| Reanudación con el mismo `run_id` | 33 señales, 0 duplicados, 0 análisis duplicados | `window-2/signals.jsonl`, `SIGNAL_VERIFY.json` |
| Reinicio del sidecar | nuevo PID, `restarts=1`, PAPER intacto (PID sin cambios) | `window-1/` + log del supervisor |
| Disco insuficiente | `INSUFFICIENT_FREE_SPACE`, exit **4**, nada arrancado | `evidence/paper008/DISK_REFUSAL.json` |
| Mutaciones HTTP | `POST/PUT/DELETE/PATCH` → **405**, ruta desconocida → 404, bind solo `127.0.0.1` | `evidence/paper008/http_hardening.json` |
| Paginación / filtros | 2 páginas de 5 sin solape, `limit` acotado a 200, filtro por símbolo | `evidence/paper008/pagination.json` |
| Corte de red del proveedor de mercado | **NO VERIFICADO** | no se manipuló la red del host |

## 10. Seguridad

- 0 órdenes LIVE, 0 fills PAPER, 0 admitidas ⇒ ninguna ruta de capital ejercitada.
- El único binario de ejecución es `PaperBroker`; `LIVE` no existe en el plan.
- Dashboard loopback, read-only, sin endpoints de control; secretos no presentes
  (`SIGNAL_ANALYST_API_KEY` ausente) y ninguna credencial escrita en evidencia.
- El sidecar no recibe credenciales de trading ni puede crear órdenes
  (`authority_over_orders=false` en cada registro).

## 11. Criterios de aceptación

| AC | Estado | Nota |
| --- | --- | --- |
| AC-01 GitHub | **PASS con reserva** | commits `030bbad5`, `039e3db1` empujados a PR #52 (head `039e3db1`, mergeable). CI: **no hay workflow run registrado para esta rama** |
| AC-02 Runtime | PASS | proveedor, venue y temporalidad identificados; ciclo y señales reproducibles en traza y HTTP |
| AC-03 Honestidad | PASS | `NO_ALPHA`/`NO_TRADE`/`OPERATIONAL_FAILURE` diferenciados; 0/24 bloquea PAPER_ORDER; 0 filas fake como REAL |
| AC-04 Dashboard | PASS | `/api/signals` 33/33 y `/api/analysis` 33/33 del mismo run; `STALE/DOWN` fieles tras la parada; mutaciones 405 |
| AC-05 IA | **BLOCKED** | contrato HTTP y fallos inyectados PASS; sin proveedor real no hay `AI_LIVE_PASS` |
| AC-06 Durabilidad | PASS | reinicio con mismo `run_id` sin duplicados ni pérdida; los análisis previos se conservan |
| AC-07 Continuidad 24 h | **BLOCKED** | 0,95 h observadas ⇒ `24H_NOT_VERIFIED` |
| AC-08 Seguridad | PASS | 0 LIVE, 0 fills sin admisión, `false_success=0`, sin secretos |
| AC-09 Verificador independiente | PASS | `TEST_TARGET == RUNTIME_TARGET`, hashes frescos, HTTP real |
| AC-10 Información | PASS | este informe + resúmenes por WP |

## 12. Bloqueos pendientes (y qué los desbloquea)

1. **`PAPER_ORDER_BLOCKED_ADMISSION_0_OF_24`** — ninguna estrategia supera el gate de
   coste/edge. No se toca el ledger ni los umbrales: requiere research con edge
   validado (fuera de este RFC).
2. **`AI_REAL_BLOCKED_NOT_CONFIGURED`** — falta `SIGNAL_ANALYST_API_KEY` y autorización
   de gasto. Con clave, el mismo sidecar analiza el backlog sin cambios de código.
3. **`24H_NOT_VERIFIED`** — hace falta una ventana continua de 24 h en un host con
   alimentación y red; el arranque manual está probado, la tarea programada no se instaló.
4. **Corte de red / proveedor de mercado** — no simulado; pendiente de una prueba
   controlada de pérdida de red.
5. **CI de la rama** — no hay workflow ejecutado para `feat/rfc-paper-008`; el estado
   de CI es desconocido, no “verde”.

## 13. Reproducción

```bash
# 1. preflight (refusa si el host no puede pagar la ventana)
uv run python scripts/start_paper_lab.py --dry-run --provider ccxt \
  --assets BTC,ETH,SOL --timeframe 5m --paper-cadence bar-close \
  --duration-hours 2 --run-id paper-lab-rfc008-live-03 \
  --data-root reports/lab-data/paper-lab-rfc008-live-03

# 2. ventana supervisada
uv run python scripts/start_paper_lab.py --provider ccxt --assets BTC,ETH,SOL \
  --timeframe 5m --paper-cadence bar-close --duration-hours 2 \
  --run-id paper-lab-rfc008-live-03 --data-root reports/lab-data/paper-lab-rfc008-live-03

# 3. dashboard read-only
uv run python scripts/paper_lab_dashboard.py --run-id paper-lab-rfc008-live-03 --port 8981

# 4. verificación independiente
uv run python scripts/wp_signal_verify.py --run-id <run-id> \
  --dashboard-url http://127.0.0.1:8981 --out reports/autonomous-paper/<run-id>/SIGNAL_VERIFY.json
uv run python scripts/rfc_paper_008_report.py --run-id <run-id> --dashboard-url http://127.0.0.1:8981
uv run python scripts/rfc_paper_008_verify.py \
  --report docs/agentic/paper_rfc008/RUN_REPORT.json --dashboard-url http://127.0.0.1:8981
```

## 14. Próximos pasos

1. Autorizar una ventana de 24 h (host encendido) y repetir el cierre con el mismo
   procedimiento; solo entonces cambiar `24H_NOT_VERIFIED` → `PAPER_SHADOW_24H_VERIFIED`.
2. Configurar `SIGNAL_ANALYST_API_KEY` con presupuesto acotado y ejecutar 3–5 análisis
   reales; comparar coste/latencia y pasar a `AI_REAL_VERIFIED` solo con respuesta real.
3. Decidir si se instala la tarea programada de Windows (`install_paper_lab_task.ps1`);
   requiere autorización explícita sobre el host.
4. Investigar el rojo preexistente del audit económico
   (`test_recovery_determinism`) en un WP aparte; no se tocó aquí.

---

**Conclusión:** el plano PAPER/SHADOW con datos públicos reales, su dashboard y su
verificador independiente están **operativos y verificados**. El análisis de IA está
**implementado y probado en contrato**, pero **no certificado con proveedor real**.
La operación 24×7 **no está certificada**. Ninguna orden PAPER o LIVE se ha ejecutado.
