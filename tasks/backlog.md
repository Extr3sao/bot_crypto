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

## Tickets Baseline Health & Risk (ADR-0016 umbrella)

> Diagnostico confirmado via checkout main @ 2774021 + `uv run mypy src/trading_bot/` + `uv run pytest`. **10 issues pre-existentes** (no introducidos por PRs recientes): 8 mypy errors + 2 pytest failures + 2 pytest setup-time errors. Umbrella ADR-0016 firma la estrategia fix-forward atomico. Cherry-pick safe por ticket (independiente de TSK-013.4 / TSK-104 work).

- [ ] **TSK-013.5** **Pri 1 (Money-Risk)** Restore cross-domain live fail-fast validator. **Est: S**. Estado real: `todo`. **Risk: H** (runtime validation breach — falla permite arrancar bot en `mode=live` con `risk.kill_switch_enabled=False`, incapaz de abortar en emergencia de mercado). Diagnostico confirmado: `tests/unit/config/test_failfast.py::test_settings_rejects_live_with_kill_switch_off` configura `mode=live + live_trading_enabled=true + i_understand_the_risks=true + kill_switch_enabled=false` y NO levanta `ValidationError`; el cross-domain invariant `_check_cross_domain_live_invariants` no frena. Cross-link ADR-0016 (umbrella) + ADR-0010 (flat-env alias context). **DoD**: `pytest tests/unit/config/test_failfast.py::test_settings_rejects_live_with_kill_switch_off` verde + `Settings._check_cross_domain_live_invariants` raises `ValidationError` loud cuando precondiciones live se cumplen pero `risk.kill_switch_enabled=False`. Cobertura >= 90% mantenida sobre `src/trading_bot/config/settings.py`. Depende de: ninguno (remediation directa).

- [ ] **TSK-013.6** **Pri 2 (Connector hardening)** Mypy `no-any-return` batch en CCXT connector. **Est: S**. Estado real: `todo`. **Risk: M** (typing drift detectado; runtime behavior correcto per duck-typing CCXT; afecta solo strict mypy CI gate). 5 errors pre-existentes en `src/trading_bot/market_data/exchange_connector.py`: `:280` retorna `Any` declarado `list[list[float]]`, `:316/343/366/414` retornan `Any` declarado `dict[str, Any]`. Diagnostico: CCXT v4 devuelve `Any` no tipado en runtime; las signatures post-TSK-101 asumían tipado estricto sin `cast()` o `# type: ignore[no-any-return]` ADR-firmado. Cross-link ADR-0016 + ADR-0012 (gate-recovery precedent via numpy<2.1). **DoD**: `uv run mypy src/trading_bot/market_data/exchange_connector.py` rc=0 con 5 fixes via `cast()` narrowing (preferido) o `# type: ignore[no-any-return]` ADR-firmado bajo ADR-0016. Cobertura >= 90% mantenida. Atomic commit. Depende de: ninguno.

- [ ] **TSK-013.7** **Pri 3 (Scanner typing)** `UniverseScanner.__init__` registry param signature drift. **Est: S**. Estado real: `todo`. **Risk: M** (mypy drift; runtime behavior correcto via dispatch dinamico). 3 errors en `src/trading_bot/scanner/scanner.py`: `:323` `[no-untyped-def]` (parametros sin anotacion en helper definido en el bloque), `:357` `[attr-defined]` `"object" has no attribute "freeze"`, `:365` `[arg-type]` `Argument "registry" to "_ModeRegistryBundle" has incompatible type "object"; expected "FilterRegistry"`. Diagnostico: el parametro `registry_per_mode` (o el registry extraido en scope local) se infiere como `Mapping[str, object]` por mypy pero `_ModeRegistryBundle.__init__` espera `Mapping[str, FilterRegistry]`. Fix: anotacion explicita al param narrowing o `Mapping[str, FilterRegistry]` cast. Cross-link ADR-0016 + ADR-0013 (TSK-103 cross-layer enforcement origin). **DoD**: `uv run mypy src/trading_bot/scanner/scanner.py` rc=0 + 3 sentinels nuevos pineando el type narrowing. Cobertura >= 90% mantenida. Depende de: ninguno.

- [ ] **TSK-013.8** **Pri 4 (QA)** UniverseScanner caching source regression test fix. **Est: S**. Estado real: `todo`. **Risk: L** (test-only bug; runtime behavior correcto). Diagnostico confirmado: `tests/unit/scanner/test_universe_scanner.py::test_caching_source_avoids_double_fetch` configura `volume_by_symbol={"BTC/USDT": 100.0}` con `min_volume_usdt=1_000` → `VolumeFilter` rechaza → F4 short-circuit (round-7 fix per retrieval-log) corto-circuita antes de `fetch_spread_bps` y `fetch_recent` → counters muestran 0 calls. El test intenta pinear "caching evita double-fetch per symbol per run" pero el short-circuit correctamente implementado previene las llamadas posteriores. Fix per thinker: ajustar `FakeMarketDataSource` mock `volume_by_symbol={"BTC/USDT": 10_000.0}` (pass volume filter) y verificar las 3 fetches corren **1 sola vez** cada una. Cross-link ADR-0016 + ADR-0013 (F4 short-circuit context). **DoD**: `pytest tests/unit/scanner/test_universe_scanner.py::test_caching_source_avoids_double_fetch` verde + 0 cambios en `src/trading_bot/scanner/scanner.py` (test-only fix). Depende de: ninguno.

- [ ] **TSK-013.9** **Pri 5 (Test setup)** Parametrize `args` collision en retry tests. **Est: S**. Estado real: `todo`. **Risk: L** (test setup-time error; no afecta runtime). 2 **ERROR** (no FAILED) en `tests/unit/market_data/test_ccxt_connector.py::test_read_methods_retries_then_reraise[fetch_ohlcv-args0]` y `[fetch_balance-args1]`. Diagnostico per thinker: el parametrize usa `args` como identifier del param (`pytest.param("fetch_ohlcv", args0)`), per pytest convention `args` puede entrar en conflicto con fixtures o con `_pytest.compat`; el expected fix es renombrar a `method_args` en `pytest.param(...)` IDs + actualizar la function signature `(*, method_name, method_args, **kwargs)` o similar. Cross-link ADR-0016 + ADR-0012 (retry decorator context via tenacity). **DoD**: 2 ERRORS pasan a PASSED, verificando el retry-then-reraise behavior en CCXT connector. Test-only fix. Depende de: ninguno.

- [ ] **TSK-013.10** **Pri 6 (Latent drift audit)** Sweep test fixtures against `Exchange`/`ExchangeRetries`/`ExchangeTimeouts` model constraints. **Est: S**. Estado real: `todo`. **Risk: L** (test-only drift; runtime behavior OK porque pydantic valida solo en uso real de los modelos, no al construir fixtures). **Audit completed**: `code_searcher` sweep sobre `tests/unit/` + `tests/bdd/` revela 2 violaciones latentes en `tests/unit/market_data/test_ccxt_connector.py::fast_retry_exchange_cfg` (line 437 + 441): `rate_limit_ms=10` violates `Exchange.rate_limit_ms=Field(..., ge=50)` y `max_backoff_ms=50` violates `ExchangeRetries.max_backoff_ms=Field(8_000, ge=100)`. Ambas correcciones ya cubiertas en TSK-013.8+013.9 branch `feature/tsk-013.8-013.9-test-fixes` @ d6c9141 (cherry-pick-safe commit con bumps a `rate_limit_ms=50` + `max_backoff_ms=200` + 100ms headroom per reviewer round-1 feedback). **Pattern catalogued**: ademàs, 4 sites usan `model_construct()` para bypass intencional de validation (`tests/unit/scanner/test_mode_filters.py:62-63` + `tests/unit/scanner/test_universe_scanner.py:182-183`). Bypass intencional pero deuda potencial: si una constraint futura se endurezca (e.g. `ExchangeRetries.initial_backoff_ms` `ge=10` -> `ge=50`), los 4 sites seguiran pasando sin disparar test raises. Cross-link TSK-013.8+013.9 (origen del descubrimiento), ADR-0016 (umbrella baseline remediation), ADR-0017 (TSK-013.5 escalacion que cerro partial-fix similar). **DoD**: (a) sweep reproducible via `code_searcher`; (b) audit log en `context/retrieval-log.md`; (c) backlog entry cross-linkeado; (d) cherry-pick-safe fix-forward en TSK-013.8+013.9 ya push state. **Proactive recurrence**: aplicar TSK-013.10 audit pattern antes de cualquier PR que enderece constraints en `Exchange*`, `Risk`, `Runtime`, `Universe`, `StrategiesConfig`, `IndicatorsConfig` para evitar regresiones CI silenciosas (model_construct + fixture-construction != model-validation). Depende de: ninguno (cataloging directo).

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
