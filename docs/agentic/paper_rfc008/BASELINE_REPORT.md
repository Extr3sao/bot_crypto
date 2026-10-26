# BASELINE_REPORT — RFC-PAPER-008 / WP-PAPER-008A

**Fecha:** 2026-10-26 · **Host:** Windows 11, Python 3.11.15, uv 0.11.26
**Repositorio:** `Extr3sao/bot_crypto` (`origin=https://github.com/Extr3sao/bot_crypto.git`)
**Worktree de trabajo:** `ff-wt-paper008` (checkout limpio, rama nueva `feat/rfc-paper-008`)
**Estado:** baseline auditada y defectos bloqueantes corregidos; WP-008B/C/D en curso.

---

## 1. SHAs y estado del árbol

| Elemento | Valor |
| --- | --- |
| Base de la rama | `4d36e150` (`docs(rfc): fix markdown formatting in PAPER-008`) |
| `origin/main` | `5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d` |
| Merge-base con `main` | `5e6f9632` (la rama de señales está 288 commits por delante) |
| PR #51 (punta remota al iniciar) | `4d36e150` |
| PR #51 (punta remota durante el WP) | `c30a826b` — otro proceso publicó RFC-TDM-015 el 2026-10-26 11:25 +0100 |
| Rama G-7 | `ea87dc1f` (`audit/g7-real-paper`), no integrada en esta rama |
| Worktrees | 53 registrados; el checkout principal `bot freebuff` tiene 10 ficheros modificados de otro proceso, **no tocados** |
| Árbol de este worktree al iniciar | limpio (`git status --porcelain` vacío) |

El worktree principal se dejó intacto. Todo el trabajo de este RFC ocurre en
`C:\Users\GVLLFR0035\Downloads\ff-wt-paper008`, con `.venv` propio, para que
`trading_bot` se importe desde el código auditado y no desde una copia editable
del checkout sucio.

> Concurrencia: mientras se ejecutaba este WP, otro agente publicó `879bafc9` y
> `c30a826b` en `feat/wp-signal-001-003` (RFC-TDM-015). Este trabajo se rebasa
> sobre esa punta para no duplicar ni pisar sus correcciones; las diferencias se
> resuelven en el commit de integración, no con force-push.

## 2. Auditoría de entrypoints

| Entrypoint | Qué hace | Estado |
| --- | --- | --- |
| `scripts/start_paper_lab.py` | supervisor único: PAPER, collector, retention, strategy lab, analyst; preflight de disco y capacidades; STOP por fichero | IMPLEMENTED / arrancado en real |
| `scripts/autonomous_paper.py` | runtime PAPER/SHADOW: scanner → router → propuesta → revisión → decisión → riesgo → `PaperBroker` → `DecisionTrace` → `signals.jsonl` | IMPLEMENTED / ciclos reales ejecutados |
| `scripts/paper_lab_dashboard.py` | consola read-only loopback: `/`, `/signals`, `/api/signals`, `/api/analysis`, `/api/status`, `/healthz`; 405 en mutaciones | IMPLEMENTED / verificado en WP-008B |
| `scripts/ai_signal_analyst.py` | sidecar read-only: `signals.jsonl` → `analysis.jsonl`, `NOT_CONFIGURED` sin clave, presupuesto durable | IMPLEMENTED / defecto de arranque corregido |
| `scripts/wp_signal_verify.py` | verificador independiente sin importar `trading_bot.autonomous`; recomputa hashes y lee HTTP | IMPLEMENTED / ejecutado |
| `config/strategy_admission.json` | ledger de admisión: 24 estrategias, `COST_KILLED=7`, `NO_GROSS_EDGE=17`, **0 admitidas** | BLOCKED (correcto) |

## 3. Matriz de capacidades (evidencia, no intención)

| Capacidad | Estado | Evidencia |
| --- | --- | --- |
| `INGEST` datos públicos | **VERIFIED** | ciclo real `paper-lab-rfc008-probe`, BTC/ETH/SOL 5m, 120 barras por activo, `fetch_ohlcv_ok` |
| `SIGNALS` proyección de trazas | **VERIFIED** | 6 filas (`_sequence` 1–6) desde 6 trazas, hash de traza recomputado, 0 duplicados |
| `SHADOW` | **IMPLEMENTED, sin observaciones** | 0 `shadow_trades`: ninguna propuesta superó el coste; no se fabricó una |
| `PAPER_ORDER` | **BLOCKED** | 0/24 admitidas; `capabilities.PAPER_ORDER.state=BLOCKED` en `LAB_PLAN.json` |
| `LIVE` | **DISABLED** | no existe ruta LIVE; hijos = datos read-only + `PaperBroker` |
| `IA` | **BLOCKED_NOT_CONFIGURED** | sin `SIGNAL_ANALYST_API_KEY`; el sidecar debe registrar `NOT_CONFIGURED` |
| Datos REAL | **FIXED** | el perfil `config/realdata` leía Binance **testnet** y publicaba `source=REAL`; ver D-01 |
| Dashboard HTTP | **VERIFIED en WP-008B** | `/healthz`, `/api/status`, `/api/signals`, `/api/analysis` 200; `POST` 405 |
| Verificador independiente | **VERIFIED en WP-008D** | `wp_signal_verify.py` sobre ficheros + HTTP |

## 4. Defectos encontrados y corregidos

### D-01 — `source=REAL` sobre datos de testnet (bloqueante)

`config/realdata/exchange.yaml` y `config/realdata/assets.yaml` declaraban
`sandbox: true`. El connector CCXT resolvía
`https://testnet.binance.vision/api/v3` y el runtime etiquetaba cada señal como
`REAL` porque el proveedor era `ccxt`, sin mirar el venue.

Evidencia de ejecución:

```text
[paper.log] multi_exchange.connector.resolved ... sandbox=True
[paper.log] fetch_ohlcv_ok ... (todas las llamadas sandbox=True)
[signals.jsonl] source=REAL en las 6 filas
```

Comparación directa del mismo par/vela (medida el 2026-10-26):

| Fuente | endpoint | BTC/USDT 5m close | volumen de la vela |
| --- | --- | --- | --- |
| `sandbox=True` | `testnet.binance.vision` | 80 428.93 | 0.777 BTC |
| `sandbox=False` | `api.binance.com` | 80 435.35 | 15.357 BTC |

Corrección:

1. El plano de datos del scanner usa el módulo público de G-7
   (`market_data/public_rest.py`, ya probado en `audit/g7-real-paper`):
   `https://api.binance.com/api/v3/*`, sin claves y con allowlist de rutas. El
   connector del hub **sigue en sandbox**, porque el invariante de `Settings`
   lo exige en modo PAPER; simplemente ya no es la fuente de las señales.
2. `PublicRestKlineSource.sandbox_enabled=False` y `venue=binance` declaran la
   procedencia; `HubMarketDataSource.sandbox_enabled` sigue existiendo para que
   ningún connector sandbox pueda publicarse como REAL.
3. `resolve_data_provenance()` **rechaza** arrancar con `source` REAL desde un
   connector sandbox. La opción explícita `--allow-testnet-market-data`
   conserva el modo demo, pero publica `source=FAKE` y `market_data=TESTNET`.
4. `PAPER_RUN.json` registra `market_data`, `market_data_sandbox`,
   `data_transport` y `signal_source`; el dashboard los muestra.

Prueba de la corrección (ciclo real, `paper008-sourcecheck2`):

```text
[preflight] market data provider=ccxt venue=binance
            mode=MAINNET signal_source=REAL
PAPER_RUN environment=ccxt:binance:binance-public-rest
signals.jsonl 3 filas source=REAL data_quality=OK
```

### D-02 — el sidecar de IA moría antes de la primera señal (bloqueante para IA)

El supervisor arranca los hijos en paralelo. `ai_signal_analyst.py` resolvía el
run exigiendo `signals.jsonl`, que aún no existía, y salía con código 2. El
supervisor lo reinició 3 veces y lo dejó `FAILED` (`crash loop: 3 restarts inside
900s`) justo cuando el primer ciclo escribió las señales.

Evidencia: `logs/analyst.log` (4 salidas “no run with a signal stream”),
`SYSTEM_HEARTBEAT.json` `analyst: FAILED, restarts=3`, `signals.jsonl` creado a
las 11:20.

Corrección: un run nombrado se resuelve por su directorio; el modo `--loop`
espera al stream en lugar de salir; un pase sin stream escribe heartbeat
(`stream_present: false`) y **no** crea un `signals.jsonl` vacío.

### D-03 — el descriptor de parada olvidaba la procedencia

La escritura final de `PAPER_RUN.json` reemplazaba el descriptor de arranque y
perdía `provider`, `assets` y `timeframe`. El verificador no podía distinguir
REAL de FAKE tras una parada limpia. Corrección: la escritura es un **merge**
atómico, no un reemplazo.

## 5. Discrepancias G-7 / PR #51 revisadas

| Punto | Hallazgo | Decisión |
| --- | --- | --- |
| `provider` ausente de `PAPER_RUN.json` | reproducido tras la parada | corregido (D-03); además se añaden `market_data` y `signal_source` |
| `require_confirmed` | `autonomous_paper` usa `False`; `start_paper_trading` usa `True` | **no se cambia**: son dos lanes distintos. El lane de señales permite *candidatos* de investigación; la admisión se recomputa en el verificador y el `PaperBroker` sigue bloqueado por ledger. El lane con capacidad de orden mantiene el gate estricto. Queda documentado como riesgo de integración, no como permiso para operar |
| Atribución de outcomes | los outcomes se unen por `decision_id`; el dashboard no muta la fila de señal | sin divergencia reproducida en este lane; se añade resumen separado SHADOW/PAPER en `/api/signals` |
| Datos de G-7 | G-7 usó REST público real; esta rama usaba testnet | se adopta el criterio de G-7 (D-01) |

## 6. Pruebas ejecutadas

| Comando | Resultado | Exit |
| --- | --- | --- |
| `uv run pytest -q tests/unit/autonomous/test_signal_*.py tests/unit/autonomous/test_lab_operations.py tests/unit/observability/test_paper_lab_signal_view.py tests/unit/observability/test_dashboard_server.py` (baseline) | **94 passed** | 0 |
| Suite focal tras las correcciones (5 ficheros) | **51 passed** | 0 |
| `uv run ruff check` sobre los ficheros modificados | limpio | 0 |

Los totales definitivos de la suite focal y de regresión se registran en
`RUN_REPORT.json` (WP-008D); no se declaran tests no ejecutados.

## 7. Bloqueos heredados

- **Admisión:** 0/24 estrategias; `PAPER_ORDER` no puede habilitarse sin una
  estrategia con evidencia económica que supere el coste (22–24 bps).
- **Alpha:** las propuestas reales observadas tienen gross negativo
  (`ema_crossover@5m`, -4.56 bps) y net -27 bps; no hay `PAPER_TRADE` ni
  rentabilidad que declarar.
- **IA real:** sin clave de proveedor. `NOT_CONFIGURED` es el estado honesto;
  no se declara `AI_REAL_PASS`.
- **24 h:** no verificadas todavía; la ventana de 24 h se intenta en WP-008D y,
  si no se completa, el estado es `24H_NOT_VERIFIED`, nunca `PASS`.
