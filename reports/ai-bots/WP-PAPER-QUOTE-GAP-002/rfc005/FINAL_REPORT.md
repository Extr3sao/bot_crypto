# FINAL REPORT — RFC-PAPER-ISOLATION-005 / WP-003-02

**Decisión: `PASS (LAB ONLY)` · WP-003-03: `GO`.**

El runtime paper/offline arranca bajo una política que no admite red externa ni rutas de
orden, y cada intento de saltarla se rechaza antes de tocar la red. No es autorización de
trading real ni una validación paper E2E.

## COMMITS

| | |
|---|---|
| `source_commit` (runtime ejecutado) | `0bdda77d4b4c66273c4cda2b23b6ef0dcae3a7c8` |
| `code_sha` | `0bdda77d4b4c66273c4cda2b23b6ef0dcae3a7c8` |
| ancla de evidencia | el commit que contiene este fichero |

## IMPLEMENTED

- `src/trading_bot/execution/isolation.py`: política estricta salvo `live`, audit hook de
  proceso (`sys.addaudithook`), registro de intentos y `assert_order_allowed`.
- Rutas con puerta: `CCXTExchangeConnector.create_order/cancel_order`,
  `BitunixFuturesClient.place_order`, `BitunixFuturesConnector.create_order/cancel_order`,
  `BitunixSpotConnector.create_order/cancel_order`, `app._cmd_place_order`.
- Entrypoints aislados: `scripts/ai_bots_run.py --mode mock` y
  `scripts/ai_vision_lane.py --mode replay`, antes de construir nada.
- `trading_bot.execution` importa `live_gate` de forma perezosa: el ciclo
  `config.universe → market_data → isolation` impedía arrancar el runtime paper.

## TESTS

`.venv/Scripts/python.exe -m pytest -q tests/unit/vision tests/unit/paper tests/unit/risk tests/unit/execution tests/unit/market_data` → **734 passed in 569.02s (0:09:29)**, `exit 0`, 569.02 s.

Repo completo: `exit 1`,
102 fallos preexistentes
(1 nuevos).

## RUNTIME_VALIDATION

10 procesos hijos: 9 PASS,
1 LIMITATION, 0 FAIL.

## NETWORK_ISOLATION

16/16 intentos denegados; externos permitidos
= 0. `OS_SANDBOX = NOT_AVAILABLE`.

## EXTERNAL_ORDER_PREVENTION

8 rechazos `ISO_ORDER_ROUTE`; 0 órdenes reales; 0 credenciales.

## INDEPENDENT_VERIFICATION

**PASS** · controles negativos rechazados
**8/8**

| Control | Mutación | Resultado | Rechazado por |
|---|---|---|---|
| NEG | NEG-01-scenario-dropped | rejected | lab_shape, network_denied |
| NEG | NEG-02-order-allowed | rejected | order_routes_refused |
| NEG | NEG-03-venue-called | rejected | order_routes_refused, no_orders |
| NEG | NEG-04-os-sandbox-claimed | rejected | lab_shape, subprocess_limitation |
| NEG | NEG-05-denied-host-hidden | rejected | network_denied |
| NEG | NEG-06-source-commit-falsified | rejected | inventory_gated, runtime_identity, reports_consistent |
| NEG | NEG-07-runtime-hash-falsified | rejected | runtime_identity |
| NEG | NEG-08-runtime-attempt-hidden | rejected | runtime_isolated |

## PAPER_VALIDATION

`NOT_PERFORMED`.

## FALSE_SUCCESS

0. Una limitación nunca se cuenta como PASS; el verificador exige que sus 8 controles
negativos sean rechazados antes de aceptar el bundle.

## DEFECTS

- **DEF-01** (runtime): no refusal existed between an adapter and the venue: a paper process could call create_order — isolation.assert_order_allowed in 7 concrete order methods; wrappers delegate to them
- **DEF-02** (packaging): execution/__init__ imported live_gate, which closed a cycle through config.universe and market_data — lazy PEP 562 import in trading_bot.execution
- **DEF-03** (evidence): the RFC003 narrative said ccxt opens its session in the constructor; in this version the constructor performs no I/O and the first call does — the lab asserts the first-call refusal instead of repeating the narrative

## BLOCKERS

Ninguno dentro del alcance. Declarado fuera: sandbox de sistema operativo (no disponible),
paper E2E y reconciliación externa.

## EVIDENCE

`ISOLATION_LAB.json`, `ISOLATION_INVENTORY.json`, `NETWORK_ISOLATION_AUDIT.json`,
`EXTERNAL_ORDER_PREVENTION.json`, `SUITE_IDENTITY.json`, `EVIDENCE_MANIFEST.json`,
`VERIFICATION.json` y los logs de cada hijo en `lab/`.

## RFC_STATUS

WP-003-02 cerrado como `PASS (LAB ONLY)`.

| Dimensión | Resultado | Base |
|---|---|---|
| IMPLEMENTATION_STATUS | PASS | one policy module, 4 order-capable modules gated, 2 paper entry points isolated |
| TEST_STATUS | PASS | acceptance 734 passed, exit 0; repo-wide 102 failing ids, 1 not at baseline, 0 unexplained |
| RUNTIME_VALIDATION | PASS | 10 child process(es): 9 PASS, 1 LIMITATION, 0 FAIL |
| NETWORK_ISOLATION | PASS | 16 of 16 audited attempt(s) denied; external attempts allowed: 0; OS sandbox: NOT_AVAILABLE |
| EXTERNAL_ORDER_PREVENTION | PASS | 8 refusal(s) across 13 inventoried route(s); venue calls, HTTP requests and spot client calls are all 0 |
| INDEPENDENT_VERIFICATION | PASS | verify_isolation.py PASS: 16/16 check(s) accepted, 8/8 negative control(s) rejected, against the evidence commit |
| PAPER_VALIDATION | NOT_PERFORMED | out of scope by the RFC; WP-003-03 owns the end-to-end paper session |
| FALSE_SUCCESS | 0 | a limitation is never counted as PASS; the verifier's eight negative controls must all be rejected before it accepts the bundle |

## NEXT_PHASE

`WP-003-03` (paper E2E) con este aislamiento como condición previa: **GO**.
