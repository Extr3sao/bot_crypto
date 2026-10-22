# RUN REPORT — RFC-PAPER-ISOLATION-005

- `run_id`: `20261021T165123Z-18208`
- `source_commit`: `0bdda77d4b4c66273c4cda2b23b6ef0dcae3a7c8`
- Decisión: **PASS (LAB ONLY)**
- `PAPER_VALIDATION = NOT_PERFORMED` · `OS_SANDBOX = NOT_AVAILABLE`

## Matriz de aislamiento

| ID | Qué se intenta | Modo | Veredicto |
|---|---|---|---|
| `ISO-00` | the paper runtime runs end to end under the policy | `runtime` | PASS |
| `ISO-01` | CCXT create/cancel refused before the venue object is used | `order-ccxt` | PASS |
| `ISO-02` | Bitunix futures client and connector refuse before HTTP | `order-futures` | PASS |
| `ISO-03` | Bitunix spot connector refuses before its client | `order-spot` | PASS |
| `ISO-04` | the documented live CLI route refuses in a paper process | `app-route` | PASS |
| `ISO-05` | external connect and DNS are denied and recorded | `network` | PASS |
| `ISO-06` | urllib and http.client are denied by the same hook | `network` | PASS |
| `ISO-07` | a ccxt venue client cannot complete a call under the policy | `ccxt-constructor` | PASS |
| `ISO-08` | environment and re-installation cannot weaken the policy | `disarm` | PASS |
| `ISO-09` | a child process is outside the hook: declared limitation | `subprocess` | LIMITATION |

## Red

16 de 16 intento(s) auditado(s) denegados.
Hosts externos intentados: ['api.binance.com', 'https://api.binance.com/api/v3/ping'].
Intentos externos permitidos: **0**.

## Órdenes

13 ruta(s) inventariada(s); 8 rechazo(s) con
`ISO_ORDER_ROUTE`. Llamadas a venue/HTTP/cliente spot: **0**. CLI live: exit
`2` sin `--confirm-live` y
`2` con él en proceso paper.

## Suite

`.venv/Scripts/python.exe -m pytest -q tests/unit/vision tests/unit/paper tests/unit/risk tests/unit/execution tests/unit/market_data` → **734 passed in 569.02s (0:09:29)**, `exit 0`, 569.02 s.

Repo completo: 102 fallos y
14 errores de recolección, idénticos al commit
padre `e661c32`
(1 nuevos).

**Exclusiones registradas** (heredadas del comando de baseline, no silenciosas):
`tests/unit/observability/test_vision_panel.py`, `tests/unit/research/test_edge16_pit.py`. Motivo completo en `SUITE_IDENTITY.json.repo_wide.excluded_paths`.
La suite de aceptación se ejecuta sin ningún `--ignore`.

## Estado por dimensión

| Dimensión | Resultado |
|---|---|
| `IMPLEMENTATION_STATUS` | PASS |
| `TEST_STATUS` | PASS |
| `RUNTIME_VALIDATION` | PASS |
| `NETWORK_ISOLATION` | PASS |
| `EXTERNAL_ORDER_PREVENTION` | PASS |
| `INDEPENDENT_VERIFICATION` | PASS |
| `PAPER_VALIDATION` | NOT_PERFORMED |
| `FALSE_SUCCESS` | 0 |

Base de cada valor en `FINAL_REPORT.md`/`FINAL_REPORT.json`; el recibo del verificador
independiente está en `VERIFICATION.json`.
