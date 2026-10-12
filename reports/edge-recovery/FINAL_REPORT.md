# FINAL REPORT — WP-EDGE-00

> WP: runtime real, baseline, primer ciclo PAPER con decisión observable y publicación segura.
> Fecha: 2026-10-12. Este informe cierra **exclusivamente** WP-EDGE-00; WP-EDGE-01 no se ha ejecutado.

```text
PHASE:               WP-EDGE-00 (RFC-TAP-EDGE-001 / ROADMAP-TAP-EDGE-001)
STATUS:              PASS (runtime, evidencia y verificación)  +  GIT_SYNC: BLOCKED_GITHUB_AUTH
COMMITS:             95bc418 (evidencia + verificador, 23 ficheros)
                     87826d489148b480bab7950f73720a0013cba2f3 (este informe + git_sync_status.json, 2 ficheros)
LOCAL_SHA:           95bc41804661dd51253c4c592dbb3b4ecfe4a738 (evidencia) · 87826d489148b480bab7950f73720a0013cba2f3 (informe)
BRANCH_TIP:          git log -1 agent/edge-recovery/WP-EDGE-00-baseline (los commits posteriores a 87826d4 solo tocan reports/edge-recovery/** y scripts/wp_edge_00_verify.py: evidencia y verificador del propio WP, nunca codigo de runtime)
REMOTE_SHA:          NOT_VERIFIED — la rama no existe en el remoto; sin credencial de escritura
BRANCH:              agent/edge-recovery/WP-EDGE-00-baseline (creada desde main @ 1d2192b)
main (intacta):      1d2192b0aec8cfe1bf2bfcaa308c4787229b3d22  ·  259 commits por delante de origin/main
origin/main:         5e6f9632e8d9c15dabd60ea92ac68f350ca28c9d  (2026-09-22)
FALSE_SUCCESS:       0
IMPLEMENTED:         authority map + baseline + git divergence + first observable PAPER run + independent verifier; no runtime code changed
TESTS:               python -m pytest tests/unit/autonomous tests/unit/paper tests/unit/cert tests/integration -q -> 385 passed, 0 failed, 0 skipped; ruff + mypy OK
RUNTIME_VALIDATION:  PASS - scripts/autonomous_paper.py @ 1d2192b: 6 decisiones, 0 ordenes, trace chain intacta (TEST_TARGET == RUNTIME_TARGET)
PAPER_VALIDATION:    PASS con 0 trades: ZERO_BY_NO_TRADE (el ledger no admite ninguna estrategia); sin posiciones
STRATEGY_RESULTS:    NO_TRADE esperado; ninguna ventaja economica demostrada en este WP
DEFECTS:             4 (DEF-WP00-01 .. DEF-WP00-04; ver seccion 5)
EVIDENCE:            reports/edge-recovery/{RUN_REPORT.md,RUN_REPORT.json,runtime_authority_map.md,baseline.json,git_divergence_report.md,git_sync_status.json,INDEPENDENT_VERIFICATION.json,runs/**,diagnostics/**}
ARCHITECTURE_STATUS: unchanged (WP de observacion y evidencia)
RFC_STATUS:          RFC-TAP-EDGE-001 E0 completado en su parte local; GIT_SYNC_VERIFIED pendiente de autenticacion
NEXT_PHASE:          WP-EDGE-01 (no ejecutado)
```

## 1. Implementado

- **Mapa de autoridad del runtime** desde el checkout real, no desde la documentación:
  entrypoints, cadena de decisión PAPER, componentes clasificados
  (`RUNTIME_AUTHORITATIVE`/`RUNTIME_REACHABLE`/`TEST_ONLY`/`RESEARCH_ONLY`/`LEGACY`/`ORPHAN`/`STALE_VERIFIER`),
  tests, datos y artefactos → `reports/edge-recovery/runtime_authority_map.md`.
- **Baseline** con commit, entorno, configuración saneada, ledger de admisión (hash), datos,
  campañas previas y reproducibilidad → `reports/edge-recovery/baseline.json`.
- **Informe de divergencia Git** sin operaciones destructivas → `reports/edge-recovery/git_divergence_report.md`.
- **Primer RUN_REPORT económico visible**, con datos reales y con el run sintético etiquetado →
  `reports/edge-recovery/RUN_REPORT.md` / `.json`.
- **Verificador independiente** (proceso separado, solo artefactos, sin importar el runtime) con
  8 controles negativos → `scripts/wp_edge_00_verify.py` + `reports/edge-recovery/INDEPENDENT_VERIFICATION.json`.
- **Commit y push intentado** con scope acotado; resultado real registrado →
  `reports/edge-recovery/git_sync_status.json`.
- **Cero cambios en código de runtime, estrategias, riesgo, límites o credenciales.** LIVE sigue
  desactivado; no se tocó ningún componente de producción.

## 2. Validación de runtime (lo que realmente se ejecutó)

| Entrypoint | Datos | Resultado |
|---|---|---|
| `scripts/autonomous_paper.py` | **Reales** (Binance spot público vía ccxt 4.5.63), BTC/ETH/SOL, 5m, 2 ciclos | exit 0 · **6 decisiones** · 0 TRADE · 6 NO_TRADE (4 estratégicos por coste, 2 de datos) · 0 órdenes · 0 acciones de producción · trace chain 6/6 intacta · replay 6/6 PARTIAL (sin outcomes) |
| `scripts/start_paper_trading.py` | **Sintéticos** (provider fake) + ledger fixture etiquetado | exit 0 · `contexts_built=3` · `router_invocations=3` · `strategy_invocations=3` · equity 10 000 · 0 órdenes |

`TEST_TARGET == RUNTIME_TARGET`: ambos son entrypoints del checkout en HEAD, no copias ni mocks presentados como reales.
La única señal viva (ema_crossover@5m) fue **rechazada por economía**: ventaja bruta `-4.56 bps`
frente a coste re-derivado `22.7918 bps` → neto `-27.3518 bps`, con verificación interna de la aritmética.

## 3. PAPER_VALIDATION y resultados económicos

- **PnL bruto / fees / slippage / neto: 0.0 / 0.0 / 0.0 / 0.0 — `ZERO_BY_NO_TRADE`.**
  No se abrió posición: el 0 es aritmética, **no un beneficio**. Ningún resultado de este WP demuestra
  ventaja económica (STRATEGY_RESULTS = `NO_TRADE` esperado; 0 de 24 estrategias admitidas:
  17 `NO_GROSS_EDGE`, 7 `COST_KILLED`).
- PAPER_PROMOTION sigue **no autorizado**; el ledger no contiene `PAPER_CANDIDATE`.

## 4. Tests ejecutados (exactos)

```text
python -m pytest tests/unit/autonomous tests/unit/paper tests/unit/cert tests/integration -q
-> 385 passed, 0 failed, 0 skipped (28.59 s)

gate de contrato incluido: tests/unit/cert/test_paper_smoke_decision_path.py
-> SMOKE_EXIT_ZERO != STRATEGY_PATH_VERIFIED (fail-closed) PASS

verificador independiente: python scripts/wp_edge_00_verify.py
-> PASS 12/12 checks · 8/8 controles negativos detectados · false_success = 0

lint/type de lo nuevo:
-> ruff check + format OK · mypy OK (scripts/wp_edge_00_verify.py)
```

## 5. Defectos y observaciones (ninguno ocultado)

| ID | Defecto | Severidad | Fail-closed | Evidencia |
|---|---|---|---|---|
| DEF-WP00-01 | Un activo inactivo (SOL, `volume_below_threshold`) se convierte en `NO_TRADE_DATA`/`context_error` en lugar de una clasificación de universo | reporting | Sí (no hay orden) | `PAPER_DAILY_REPORT.md` + `errors[]` del RUN_REPORT real |
| DEF-WP00-02 | `scripts/verify_l5_independent.py` es un **verificador obsoleto** (`STALE_VERIFIER`): su fixture usa `status="CONFIRMED"`, que el gate DEF-AUTO-4 ya no admite → 8/11 | verificación | Sí | `diagnostics/verify_l5_independent_HEAD.stdout.txt` + `research/strategy_router.py` |
| DEF-WP00-03 | `provider_verified=false` / `provider_supported=null` en el preflight de mercados del proveedor | observabilidad | No bloqueante | log del run real |
| DEF-WP00-04 | **Verificador del propio WP demasiado estricto**: equiparaba el `commit` del run con `HEAD`; al commitear la evidencia el chequeo pasaba a FAIL. Corregido a la invariante correcta (el commit del run es ancestro de HEAD **y** solo cambiaron paths de evidencia/verificador) y re-ejecutado: 12/12 | verificación | Sí | `scripts/wp_edge_00_verify.py` (check `RUN_COMMIT_IS_ANCESTOR`) |

## 6. BLOCKERS

- **`BLOCKED_GITHUB_AUTH`**: el push falló con `could not read Username for 'https://github.com'`
  (exit 128, sin credencial almacenada disponible; `gh` no está instalado, no hay token).
  La rama **no** está publicada (`git ls-remote` vacío). Los commits se han conservado íntegros.
  Desbloqueo: autenticar git en esta máquina y ejecutar
  `git push -u origin agent/edge-recovery/WP-EDGE-00-baseline`, después verificar con
  `git ls-remote origin refs/heads/agent/edge-recovery/WP-EDGE-00-baseline`.
- **PR: BLOCKED** por la misma causa (sin `gh` ni token).

## 7. Evidencia

- `reports/edge-recovery/RUN_REPORT.md` · `reports/edge-recovery/RUN_REPORT.json`
- `reports/edge-recovery/runtime_authority_map.md`
- `reports/edge-recovery/baseline.json`
- `reports/edge-recovery/git_divergence_report.md`
- `reports/edge-recovery/git_sync_status.json`
- `reports/edge-recovery/INDEPENDENT_VERIFICATION.json`
- `reports/edge-recovery/runs/WP-EDGE-00-smoke-real/**` (RUN_REPORT, traces, daily, heartbeat del runtime)
- `reports/edge-recovery/runs/WP-EDGE-00-smoke-fixture/**` (stdout con el JSON de estado del ciclo)
- `reports/edge-recovery/diagnostics/verify_l5_independent_HEAD.stdout.txt`
- `scripts/wp_edge_00_verify.py`

## 8. ARCHITECTURE_STATUS / RFC_STATUS

- Arquitectura: **sin cambios** (el WP es de observación y evidencia; no se añadieron componentes).
- RFC-TAP-EDGE-001: `E0` completado en su parte local (`G0_RUNTIME_OBSERVED`); la parte remota del
  milestone transversal queda `GIT_SYNC_VERIFIED` **pendiente** por autenticación.
- `FALSE_SUCCESS = 0` en todas las comprobaciones ejecutadas.

## 9. NEXT_PHASE

**WP-EDGE-01 (no ejecutado)**: registro de fuentes (`source_registry.md` por versión/licencia) y
features causales (`asof_swing_resistance`, `atr`, `ema`, `confirmed_fvg`, `retest_zone`) con tests de
truncation parity y anti-lookahead. Recomendaciones de arrastre: re-basar o retirar el verificador
obsoleto (DEF-WP00-02) y revisar la clasificación de activos inactivos (DEF-WP00-01).
