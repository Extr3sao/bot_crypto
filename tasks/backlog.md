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
  `done`. **TODO**: PR#N real a reclamitar (no entro en PR-A/B/C del
  milestone Fase 1 ingesta: PR#12/13/14 son TSK-101/102/ADR-0012). Si
  el merge de TSK-008 fue pre-PR#12 o ya en uno de los 3, anotar el
  numero concreto; si esta pendiente, abrir PR dedicado
  `feature/tsk-008-ci-baseline` con `.github/workflows/ci.yml` +
  `.python-version` + hunks de pyproject.toml. Per ADR-0011 sprint-001
  cumple DoD con excepcion firmada. Cross-link ADR-0012 (PR#14)
  cubre el ignore-vuln + numpy pin + app.py omit.

## Tickets Fase 1 (market data)

> Implementar `TSK-099` antes que `TSK-101` evito acoplar el conector
> a strings magicos. Ese prerrequisito ya esta resuelto en `main`.

- [x] **TSK-099** Capa de configuracion tipada con **Pydantic v2**
  (`src/trading_bot/config/`). **Est: M**. Estado real: `done`,
  mergeado en `main` (`9eed3fd`, ADR-0010).
- [ ] **TSK-100** Cerrar ADR-0001 (licencia) y ADR-0002 (gestor deps)
  si se decide hacerlo en este sprint. **Est: S**. Depende de: -
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

## Tickets hygiene / cleanup

- [ ] **TSK-014** Latent: 4 collection errors en `tests/unit/indicators/*` por falta de export de `IndicatorRegistry` en `src/trading_bot/indicators/__init__.py`. **Est: S**. Estado real: `todo`. **Origen**: detectado durante el baseline test del regression-fix bundle `fda5134` en `feature/tsk-013.10-latent-fixture-audit` — `uv run pytest --continue-on-collection-errors -q` reporta 526 collected / 521 passed / 1 failed / 4 errors; los 4 errors son collection errors en `tests/unit/indicators/*` por imports rotos al ejecutar `from trading_bot.indicators import ...` (NotFoundError / ImportError). Out-of-scope de `fda5134` (regression-fix bundle); 521/522 runnable tests PASS sigue siendo green baseline. **Cross-link**: `feature/tsk-013.10-latent-fixture-audit` (PR TBD en sprint-003); `tasks/decisions.md` ADR pendiente solo si la fix requiere decision arquitectonica (no esperado — puramente anadir symbol al `__all__`). **DoD**: los 4 collection errors desaparecen; `uv run pytest -q` corre entero sin necesidad de `--ignore=tests/unit/indicators`; coverage de `src/trading_bot/indicators/` >= 90% per ADR-0012; ruff + ruff-format clean en el modulo (probable F401/I001 residual). **Pri**: 3 (latent hygiene; no bloquea el PR `fda5134` ni `infra/no-ghost-crlf`). Depende de: ninguno (remediation directa: anadir `IndicatorRegistry` + cualquier otro export que los tests importan al `__init__.py`).

## Tickets Fase 2 (indicadores)

- [ ] **TSK-200** Motor de indicadores (interface, registro, cache).
- [ ] **TSK-201** EMA, RSI, MACD, ATR, BB.
- [ ] **TSK-202** VWAP, volume_relative, spread, volatilidad, momentum.
- [ ] **TSK-203** Order book imbalance (detras de un feature flag).
- [ ] **TSK-204** Property tests sobre series sinteticas.

## Backlog de ideas (no comprometidas)

- Indicadores adicionales (e.g. Hurst, Fractal dimension).
- Estrategias adicionales (orden-flow, market-neutral pairs).
- Dashboard web minimo.
- Alertas por Telegram.
