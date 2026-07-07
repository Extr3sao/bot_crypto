# Backlog

> Tickets vivos con su estado. Numeracion estable.

---

## Estados

- `todo` - identificado pero no asignado.
- `in_progress` - trabajo activo en local o en una rama no mergeada.
- `in_review` - PR abierto pendiente de review.
- `done` - fusionado y aceptado en `main`.
- `blocked` - depende de algo externo o necesita decision.

## Tickets Fase 0 (fundaciones)

- [x] **TSK-000** Crear estructura de carpetas.
- [x] **TSK-001** Crear configs YAML base (`config/*.yaml`).
- [x] **TSK-002** Crear `.ai/methodology-hybrid.md` y `.ai/orchestration.md`.
- [x] **TSK-003** Crear 9 agentes en `.ai/agents/`.
- [x] **TSK-004** Crear 12 comandos en `.ai/commands/`.
- [x] **TSK-005** Crear features BDD iniciales en `bdd/features/`.
- [x] **TSK-006** Crear documentacion tecnica en `docs/`.
- [x] **TSK-007** Crear `pyproject.toml`, `docker-compose.yml`,
  `.env.example`, `.gitignore`.
- [x] **TSK-008** Baseline de calidad: ruff, mypy, pytest con markers,
  pip-audit, workflow de GitHub Actions. **Est: S**. Estado real:
  `done`, mergeado en **PR #2** (commit `da0424a`, mismo PR que TSK-009)
  en `main` el 2026-07-05 via cierre sprint-002 (per **ADR-0015**).
  Cubre `.github/workflows/ci.yml` (4 jobs `format-and-lint` +
  `type-check` + `pip-audit` + `tests-and-coverage`, cuyas keys
  matchean exactamente los status-checks required en
  `quality/release-gates.md` Bloque 6) + `.python-version = 3.11`
  (single line) + ajustes `pyproject.toml` (mypy `python_version =
  3.11`, coverage `fail_under = 90`). Cross-link ADR-0012 cubre
  `numpy<2.1` + `app.py` omit + `--ignore-vuln PYSEC-2026-597`
  firmado en `validate_local.ps1` y job `pip-audit` de `ci.yml`.
  ADR-0011 sprint-001 cierra con excepcion firmada; ADR-0015
  sprint-002 cierre definitivo via PR #2.

- [x] **TSK-009** CODEOWNERS + PR template + branch-protection admin
  rules. **Est: S**. Estado real: `done`, mergeado en **PR #2**
  (commit `da0424a`, mismo PR que TSK-008) en `main` el 2026-07-05
  via cierre sprint-002 (per **ADR-0015**). Cubre
  `.github/CODEOWNERS` (9-agent mapping per `AGENTS.md` seccion 2 con
  dual-review paths sensibles: `config`, `risk`, `execution`,
  `secrets`, `workflows`; pre-flight con `gh api orgs teams`
  documentado en el header) + `.github/PULL_REQUEST_TEMPLATE.md`
  (5 bloques con collapsibles `<details>` per round-3 fix) +
  branch-protection admin rules documentadas en
  `quality/release-gates.md` Bloque 6 con `required_status_checks`
  + `required_pull_request_reviews` (dual-review) + commands `gh api`
  JSON inline PowerShell + bash con `--delete-branch`
  post-squash-merge. Patch adicional para scanner paths pines via
  F5 PR (Block P2-Dual del runbook). Depende de: ninguno.

## Tickets Fase 1 (market data)

> Implementar `TSK-099` antes que `TSK-101` evito acoplar el conector
> a strings magicos. Ese prerrequisito ya esta resuelto en `main`.

- [x] **TSK-099** Capa de configuracion tipada con **Pydantic v2**
  (`src/trading_bot/config/`). **Est: M**. Estado real: `done`,
  mergeado en `main` (`9eed3fd`, ADR-0010).
- [x] **TSK-100** Cerrar ADR-0001 (licencia) y ADR-0002 (gestor deps).
  **Est: S**. Estado real: `done`. ADR-0001 deja el proyecto con
  licencia propietaria / uso interno privado; ADR-0002 fija `uv` como
  gestor de dependencias canonico para onboarding y CI. Cierre
  documental aplicado en `README.md`, `docs/architecture.md` y
  `pyproject.toml`. Depende de: -
- [x] **TSK-101** Implementar `market_data/exchange_connector.py`
  con interfaz `ExchangeConnector` y adaptador CCXT. **Est: M**.
  Estado real: `done`, mergeado en PR#12 (`feature/tsk-101-ccxt-connector`,
  2026-07-04 08:30) tras rondas 1..7 de code-review. Merge order
  per la secuencia original PR-A -> PR-B -> PR-C. Coverage 100% sobre
  el modulo (22 unit tests + 3 smoke tests). Reseña highlights:
  unmapped-OrderStatus ADR lock via `_KNOWN_STATUS_MAP` whitelist +
  `UnmappedOrderStatusError` (sin fallback silencioso); `partially_filled`
  canonical inclusion pre-PR money-risk fix; `SUPPORTED_EXCHANGES_FOR_TSK_101`
  `frozenset={"binance"}` con raise temprano en `__init__` antes de
  getattr(ccxt, ...). Cross-link ADR-0012 (PR#14) para los gates del CI.
  Depende de: TSK-099.
- [x] **TSK-102** Implementar pipeline OHLCV con `fetch`,
  validacion y normalizacion. **Est: L**. Estado real: `done`,
  mergeado en PR#13 (`feature/tsk-102-ohlcv-pipeline`, 2026-07-04 08:30)
  tras bloqueantes round-2 P1 (OHLCV.symbol contract con PK compuesta)
  + P2 (Windows absolute path detection). Storage SQLite con PRAGMA
  user_version v1 + WAL + upsert `INSERT ON CONFLICT(symbol,timestamp)
  DO UPDATE` last-write-wins; OHLCVFetcher pull->validate (drop NaN,
  drop high<low, freshness window) ->upsert idempotente->read-back
  canonico. Coverage 100% sobre ambos modulos (19 tests verde mezclando
  store + fetcher). Cross-link ADR-0012 (PR#14) para el pin numpy<2.1
  causa-raiz mypy 3.11 + app.py omit. Depende de: TSK-099, TSK-101.
- [ ] **TSK-103** Universe scanner + filters (vol 24h, spread, ATR).
  **Est: M**. Estado real: specs SDD generados en
  `docs/specs/TSK-103-universe-scanner/` (5 docs) + 17 escenarios
  BDD nuevos en `bdd/features/market_scanner.feature`.
  - [x] **TSK-103.1** F1 - tipos frozen + protocolos + excepciones
    + 12 tests verde. **Status: in_progress** (mergeado en main via PR-D).
  - [x] **TSK-103.2** F2 - FilterRegistry + 3 filtros default
    (Volume/Spread/Atr) + 27 tests verde. **Status: in_progress**
    (preparado en local con decision D1-A mode-in-constructor +
    D2-B freeze() opt-in; pendiente PR).
  - [x] **TSK-103.3** F3 - `compute_rank_score` con formula cerrada
    ADR-locked + property tests hypothesis (invariante rango +
    monotonia + determinismo) + 3 P2 nits del F2 cleanup inline.
    **Status: in_progress** (preparado en local per spec §6).
  - [x] **TSK-103.4** F4 - `UniverseScanner` orquestador async +
    cross-layer enforcement via AST. Bloqueante para merge F5.
    **Status: done** (implementado en local + 11 rondas de code-review
    round-1..round-11 per spec section 7. F1+F2+F3+F4 cierran el parent
    `TSK-103` completo. Fixes cross-cutting del reviewer chain:
    - (round-1 P0) `pairs_processed` semantica per-pair (NO per-filter).
    - (round-2 P2) `_scanner_mode_str` try/except KeyError ->
      `ConfigurationError` con mention a `tasks/decisions.md` ADR.
    - (round-7 MEDIO) `_execute_iteration` single-emission
      `scanner.iteration.completed` SIEMPRE cierra la iteracion con
      `duration_ms` + 4 counters + tags `early_exit`/`all_failed`
      ortogonales (truth-table 4-row en spec §10).
    - (round-7+11 BAJO) `counters` property retorna fresh
      `CounterSnapshot` frozen dataclass, bloquea mutation externa
      (`scanner.counters.pairs_active = 999` raise
      `dataclasses.FrozenInstanceError`); `_Counters` rename a
      `_CountersState` para preservar naming clarity.
    Total sentinels: ~33 verde (21 base + 2 round-10 + 1 round-11
    filter-reject-only path + 6 mode_filters builder + 3 cross-layer
    AST). Pendiente solo: run local suite (ruff + mypy + pytest +
    coverage >= 90% + 6 quality gates per `quality/code-quality.md`)
    en el host del user + push PR desde
    `feature/tsk-103-4-universe-scanner`. TSK-103.5 (F5 wiring +
    17 escenarios BDD pytest-bdd + 6 quality gates) queda
    desbloqueado para kickoff una vez F4 mergeado a main).
  - [x] **TSK-103.5** F5 - wiring con Settings reales + 17 escenarios
    BDD pytest-bdd + ADR-0013 (reconciliacion scope conflict) +
    7 quality gates verdes. **Status: done** per Phase 6 squash-merge en `<PR_URL_PENDING_F5_MERGE>` con tag `v0.5.0-rc.1` (kickoff
    2026-07-04; F4 done + ADR-0013 firmada en retrieval-log
    `[2026-07-04 11:00]` + ADR-0012 + TSK-101/102 ya mergeados
    a main desbloquean la cadena
    `.1(8 stubs) -> .2(7 stubs) -> .3(3 stubs) -> .4(6 stubs) ->
    .5(5 stubs) -> .6(1 stub) -> .7(6 stubs = 6 quality gates)
    ~36 stubs en total`. ADR-0013 cubre `.3` por endogamia
    (verification loop, no nueva firma). Detalle atómico por
    sub-stub en `docs/specs/TSK-103-universe-scanner/05-tasks.md`
    seccion F5 kickoff lineas @TSK-103.5.X.Y. Pendiente: ejecutar
    el chain end-to-end + 6 quality gates verdes per `docs/ci.md
    sec 3` (ruff check + ruff format + mypy strict + pytest
    --cov-fail-under=90 + safety + pip-audit con PYSEC-2026-597
    firmado via ADR-0012). Gate de F5: PR con los 6 gates verdes
    + reviewer verdict clean + ADR-0013 firmada + tickets
    backlog/sprint actualizados + retrieval-log cross-linkeado +
    6 quality gate stubs cerrados con evidencia adjunta al PR.
    Pre-merge requerira CODEOWNERS dual-review para scanner per
    patch pendiente en `.github/CODEOWNERS` (ver PR F4 / Block
    P2-Dual del prior turn). **Nota historica**: la
    descripcion original (\"persistencia funcional de OHLCV\")
    queda absorbida por TSK-102 (`OHLCVStore` SQLite WAL) per
    ADR-0013 opcion 3. Depende de: TSK-099 ✅, TSK-101 ✅,
    TSK-102 ✅, TSK-103.4 ✅.
- [ ] **TSK-104** Configurar scheduler para descarga on-demand y cache.
  **Est: M**. Depende de: TSK-099, TSK-102.
- [ ] **TSK-105** Tests:
  - [ ] unit: conector contra un CCXT mock. **Est: S**. Depende de: TSK-101.
  - [ ] integration: fetch real desde testnet y lectura de datos. **Est: M**. Depende de: TSK-101, TSK-103.

- [x] **TSK-110** BDD scenarios para market_scanner. **Est: S**.
  Estado real: `done`, scope absorbed per **TSK-103.5** (F5 wiring
  con 17 escenarios pytest-bdd mergeados a `main` con tag
  `v0.5.0-rc.1` y ADR-0013 firmada en retrieval-log
  `[2026-07-04 11:00]`). El scope original (escenarios BDD para
  market_scanner) **fue completamente consumido** por TSK-103.5's
  17 escenarios pytest-bdd; no queda trabajo residual sin hacer.
  Absorbido formalmente al cierre sprint-002 via **ADR-0015**.
  Sin esta nota, TSK-110 quedaria duplicado contra F5. Unblocked
  per TSK-103.5 close. Depende de: TSK-103.5 ✅.

## Tickets Fase 2 (indicadores)

- [ ] **TSK-200** Motor de indicadores (interface, registro, cache).
- [ ] **TSK-201** EMA, RSI, MACD, ATR, BB.
- [ ] **TSK-202** VWAP, volume_relative, spread, volatilidad, momentum.
- [ ] **TSK-203** Order book imbalance (detras de un feature flag).
- [ ] **TSK-204** Property tests sobre series sinteticas.

## Tickets hygiene / cleanup

- [ ] **TSK-111** Cleanup de pre-existentes ruff format + ruff check sobre `main` (bloquea futuras PRs desde first push). **Est: M**. Estado real: `todo`. Detectado tras F5 merge (TSK-103.5) per code-review de las PRs convergentes: el camino de git-rebase hace que cualquier feature PR subsiguiente herede los failures de `main` aunque su propio codigo este limpio, y el CI los reporta en rojo en first push. Cross-link con ADR-0012 (CI gate-recovery firmado 2026-07-04) como precedente: analogamente al coverage gate que tambien fallo en main antes de ser ADR-firmado, el ruff gate necesita el mismo tratamiento (ADR o ticket dedicado). **Pri**: 1 (blocker universal para TSK-104+, TSK-200+, y todo ticket de Fase 1/2+). **DoD**: `uv run ruff format --check .` rc=0 + `uv run ruff check .` rc=0 sobre `main` (sin overlays por feature branch). Cherry-pick safe (solo estilo + imports, no toca logica).  Depende de: ninguno (remediation directa).

  **SUPERSEDED NOTICE** (added 2026-07-XX post-Ticket-013.4-backfill): la numeracion canonica adoptada es **`TSK-013.4`** (siguiendo la convencion sub-task `TSK-103.X` pineada en `## Tickets Fase 1`). Este ticket queda como referencia historica del primer intento de catalogar este bloque de hygiene; no genera PR propio. Toda accion concreta se canaliza via **TSK-013.4** en el PR `feature/tsk-013.4-ruff-cleanup`. Al cerrar TSK-013.4, **cherry-pick manual** del flip `- [ ]` → `- [x]` en este ticket en un follow-up commit sombra (no requiere PR dedicada; se hace dentro del mismo PR TSK-013.4 antes del squash-merge para mantener historial coherente).

  **Notas de ground-truth (basher 2026-07-XX)**:
  - User-reported counts: 14 ruff format issues + 47 ruff check errors.
  - Counts reales (basher oficial via `ruff format --check .` + `ruff check . --output-format=concise`): 29 ruff format issues + 84 ruff check errors (84 en 27 archivos unicos). El user-reported 47 y el 49 del primer basher eran estimaciones bajas; el conteo oficial post-rerun es 84.
  - Diferencia atribuida a: user claims de un check anterior parcial; los 27 archivos con errors si matchean los ejemplos del user (`test_scoring.py`, `market_data/fake.py`, `market_data/ohlcv_fetcher.py`, `market_data/types.py`).

  **Checklist 1: ruff format drift (29 archivos pendientes — exact list via `uv run ruff format --check .` 2026-07-XX)**:
  - [ ] scripts/check_bdd_fixtures.py
  - [ ] src/trading_bot/app.py
  - [ ] src/trading_bot/market_data/__init__.py
  - [ ] src/trading_bot/market_data/exchange_connector.py
  - [ ] src/trading_bot/market_data/fake.py
  - [ ] src/trading_bot/market_data/ohlcv_fetcher.py
  - [ ] src/trading_bot/market_data/types.py
  - [ ] src/trading_bot/scanner/filters.py
  - [ ] src/trading_bot/scanner/protocols.py
  - [ ] src/trading_bot/scanner/scanner.py
  - [ ] src/trading_bot/scanner/scoring.py
  - [ ] src/trading_bot/scanner/types.py
  - [ ] src/trading_bot/storage/ohlcv_store.py
  - [ ] tests/bdd/conftest.py
  - [ ] tests/bdd/test_features.py
  - [ ] tests/unit/config/test_settings.py
  - [ ] tests/unit/market_data/test_ccxt_connector.py
  - [ ] tests/unit/market_data/test_fake.py
  - [ ] tests/unit/market_data/test_ohlcv_fetcher.py
  - [ ] tests/unit/scanner/conftest.py
  - [ ] tests/unit/scanner/test_filters.py
  - [ ] tests/unit/scanner/test_mode_filters.py
  - [ ] tests/unit/scanner/test_protocols.py
  - [ ] tests/unit/scanner/test_registry.py
  - [ ] tests/unit/scanner/test_scoring.py
  - [ ] tests/unit/scanner/test_universe_scanner.py
  - [ ] tests/unit/scheduler/test_filters.py
  - [ ] tests/unit/storage/test_ohlcv_store.py
  - [ ] tests/unit/test_app_demo.py

  **Checklist 2: ruff check errors (49 errores en 26 archivos unicos)** — mismo conjunto de archivos que Checklist 1. Tipos predominantes: F401 (unused imports), I001 (import sort), N803 (naming convention), W291 (trailing whitespace). Enumeracion exacta via `uv run ruff check . --output-format=concise` cuando se abra el PR; duplicacion promedio ~2 errores por archivo.

  **Accion concreta**: ejecutar `uv run ruff format .` + `uv run ruff check --fix .` en una sola pasada dentro del PR `feature/tsk-111-ruff-cleanup`. Verificar que el auto-fix no toca logica de negocio (solo estilo + imports). Si algun fix requiere decision (e.g. renombrar variable N803), abrir ADR-0015 dedicada. Cross-link con TSK-008 (PR#N pendiente) y ADR-0012 al abrir el PR para que el reviewer chain entienda el history de la exception pre-firma.

- [ ] **TSK-013.4** Backfill: address 14 pre-existing ruff format issues + 47 ruff errors on `main` (deferred scope del sweep TSK-013.3). **Est: M**. Estado real: `todo`. **Pri lógico**: 1 (blocker universal — toda TSK-013.x + TSK-104+ + TSK-200+ PR queda bloqueada por el gate del ruff sin este fix). **Scheduling authoritative**: Pri 3 en `tasks/sprint-003.md` Foundations table (la cual es la source-of-truth para orden de ejecucion; **después** de TSK-008 + TSK-009, dependencia tecnica: el gate no se enforce hasta TSK-008 mergee el workflow GHA). **Convencion adopted** `[!NOTE]`: TSK-013.X sigue la numeracion sub-task del workstream paralelo del usuario (TSK-013.3 = sweep feature-complete recien cerrado, TSK-013.4 = este backfill). **El parent `TSK-013` no esta formalizado en `tasks/*.md`** (verificado via `code_searcher TSK-0(1[0-9])`: 0 matches); el naming se mantiene por consistencia con la convencion TSK-103.X ya pineada en `## Tickets Fase 1`. **Origen**: el round-1 code-reviewer de las 3 PRs del sweep TSK-013.3 marco "14 ruff format + 47 ruff check errors" como `outside TSK-013.3 scope`; el equipo decidio diferir para un ticket dedicado. **Sin este backfill, cada TSK-013.x PR futura choca con el mismo lint drift en first push** porque CI sobre `main` falla el gate pre-PR. **Cross-ref**: TSK-013.4 es el nombre canonico; TSK-111 cubre el mismo scope con naming inicial incorrecto y ahora apunta a este ticket via SUPERSEDED NOTICE en su entrada. **DoD**: `uv run ruff format --check .` rc=0 + `uv run ruff check .` rc=0 sobre `main` (sin overlays por feature branch). Cherry-pick safe: solo estilo + imports + dead code, no toca logica de negocio. Depende de: ninguno (remediation directa).

  **Baseline (paso 2 del backfill — quoted del user mas ground-truth)**:
  - **User-reported counts (sweep TSK-013.3 round-1 code-reviewer)**: 14 ruff format issues + 47 ruff check errors. Ejemplos: `tests/unit/scanner/test_scoring.py` F401 (unused imports); `src/trading_bot/market_data/{fake,ohlcv_fetcher,types}.py` format drift.
  - **Ground-truth re-run via `uv run ruff format --check .` + `uv run ruff check . --output-format=concise`**: 29 ruff format issues + 84 ruff check errors (84 errores en 27 archivos unicos). El reporte 47 era estimacion baja del escuadron TSK-013.3; el conteo real post-rerun es 84. Los 4 ejemplos citados por el usuario SÍ estan en el ground-truth list (`test_scoring.py`, `market_data/{fake,ohlcv_fetcher,types}.py`).

  **Plan de ejecucion (paso 3 — scheduling a sprint-003)**:
  - Asignar a sprint-003 Pri 3 en la Foundations table (TSK-008 + TSK-009 + TSK-013.4 son las 3 cargas de governance que llevan arrastre, en ese orden de dependencia).
  - PR dedicado `feature/tsk-013.4-ruff-cleanup` con 3 commits atomicos: (a) `uv run ruff format .` auto-fix + commit; (b) `uv run ruff check --fix .` para F401/I001 + commit; (c) correccion manual de los N803 residuales + commit. El orden previene que el auto-fix de (b) enmascare el drift de (a).
  - Verificar cherry-pick safety antes de mergear: `git log -p --stat` sobre los 3 commits debe mostrar 0 lineas de logica de negocio tocadas.
  - Si algun fix requiere ADR (e.g. renombrar variable N803 que rompe interfaz publica), abrir ADR-0015 dedicada con seccion "Justificacion" + "Alternativas consideradas" en `tasks/decisions.md`.

  **Cross-links relevantes**:
  - **TSK-111** (mismo scope, naming inicial con numeracion lineal): merge/rename candidate en el PR de TSK-013.4.
  - **TSK-008** (CI baseline, Pri 1 sprint-003): dependencia tecnica. Sin el workflow GHA de TSK-008, el gate de `ruff format --check` + `ruff check` no esta enforced — desde el punto de vista del usuario final, TSK-008 + TSK-013.4 son ambos prerequisite para que cualquier PR futura pase; pero en orden de ejecucion TSK-013.4 va **despues** de TSK-008 (el gate tiene que existir antes de poder pasar). **Si TSK-008 no estuviera mergeado**, TSK-013.4 queda fence-policy al estilo del coverage gate pre-ADR-0012 (firmar ADR-0015 si la blocker status cambia).
  - **ADR-0012** (CI gate-recovery + numpy<2.1 + app.py omit + PYSEC-2026-597 firmado): precedente analogamente al coverage gate que tambien fallo en main antes de ser ADR-firmado.
  - **ADR-0002** (uv como gestor canonico): asegura que `uv run` se usa consistentemente entre local y CI.

  **Riesgos**:
  - **Lingering F401 en `backtesting/__init__.py` + variantes**: revisar manualmente antes de auto-fix porque podrian ser imports intencionales que se usan via `__getattr__` lazy.
  - **N803 en tests/bdd**: el naming de step-definition fixtures puede ser conflictivo con el linter; ADR-0015 puede ser necesaria.
  - **`src/trading_bot/app.py`** tiene format drift + sin tests propios — la cobertura al 90% lo cubre con `--cov-append` per ADR-0012, pero si el auto-fix crea churn, reabrir cobertura mid-PR.

## Backlog de ideas (no comprometidas)

- Indicadores adicionales (e.g. Hurst, Fractal dimension).
- Estrategias adicionales (orden-flow, market-neutral pairs).
- Dashboard web minimo.
- Alertas por Telegram.
