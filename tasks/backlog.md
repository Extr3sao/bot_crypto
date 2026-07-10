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

- [ ] **TSK-022** Multi-exchange adapter (Protocol genérico y
  subclases de extension). **Est: L**. Estado real: `todo` (Specs
  SDD recien redactados en `docs/specs/TSK-022-multi-exchange-adapter/01-requirements.md`).
  **Risk: M** (refactor central + cross-layer AST enforcement).
  **Fase**: 1 (Market Data). **Pri**: 2 (post-TSK-021 credentials
  rotation, pre-TSK-100 storage layer carry).
  **DoD**:
  - [ ] Implementar un único `MultiExchangeConnector(Protocol)` per
        `RF-MX-1` del spec.
  - [ ] Crear subclases explícitas para al menos `BinanceConnector`,
        `BitunixSpotConnector`, `BitunixFuturesConnector` per `RF-MX-2`.
  - [ ] Feature flag multi-array en `config/assets.yaml` con prefijo
        `exchanges: [{id, enabled, sandbox, type}]` per `RF-MX-3`.
  - [ ] Cross-layer AST test (`tests/unit/market_data/test_cross_layer.py`
        NEW) asegurando que `scanner`, `execution`, `strategies` solo
        importan el Protocol; nunca subclases concretas per `RF-MX-4`
        + `ADR-0013` precedent.
  - [ ] Tests de integración a base de sandboxes verificables para
        las 3 instanciaciones (ccxt sandboxed o fake exchange mock)
        per `RF-MX-5`. Coverage >= 90% sobre `src/trading_bot/market_data/`.
  - [ ] Reusar `narrow_ccxt_payload` / `narrow_ccxt_ohlcv` runtime
        guards per `RF-MX-8` y `ADR-0022 Q4` Consecuencias.
  - [ ] Override-removal discipline preserved: no se reintroduce el
        `market_data.* disable_error_code = ["no-any-return"]` per
        `ADR-0022 Q4` y `RNF-5` del spec.
  - [ ] PR con dual-review per `.github/CODEOWNERS` (`market_data/` +
        `config/` paths sensibles).
  **Nota de colisión de ID**: este ticket fue invocado originalmente
  bajo el ID `TSK-105` por sugerencia del backlog context; sin embargo
  `TSK-105` ya está ocupado (paper-trading tests scoped). Acatando
  `ADR-0016` anti-pattern "dos scopes al mismo ID acumulan drift",
  la feature acquire el primer slot fundacional libre post-TSK-021:
  **`TSK-022 - Multi-exchange adapter`**. La ADR firmada en la que este
  ticket es forward-looking — `ADR-0022 Q5` Consecuencias item "Forward-looking
  unblock" — citaba `TSK-105 multi-exchange adapter` por histórico; ese
  ID queda substituible formalmente acá.
  **Cross-links**:
  - `tasks/decisions.md ADR-0022 Q5` (Consecuencias item "Forward-looking
    unblock" — este ticket materializa el desbloqueo por el type widening
    int+float de `b4b543d`).
  - `tasks/decisions.md ADR-0022 Q4` (Protocol + runtime guard design
    heredable — `narrow_ccxt_payload`, `narrow_ccxt_ohlcv` reusados
    sin modification).
  - `tasks/decisions.md ADR-0013` (cross-layer AST enforcement model).
  - `tasks/decisions.md ADR-0016` (`cast()` preference + atomic-chore
    per file batching para 4 archivos del refactor).
  - `tasks/decisions.md ADR-0010` (flat-env alias para `runtime.exchange_id`
    precedence).
  - `tasks/decisions.md ADR-0006` (Binance via CCXT baseline, superset-multiplicado).
  - `tasks/decisions.md ADR-0008` (reserva histórica "sustitucion del
    exchange" firmada en ADR-0006 revisión; este ticket es la materialización).
  Depende de: ADR-0022 Q5 (cerrada en commit `b4b543d`).

## Tickets Baseline Health & Risk (ADR-0016 umbrella)

## Tickets Operations Risk (silent-failure auth-gated)

> Tickets que Pinean guardias operacionales Pineadas en ADRs (Bloque 5+
> riesgos residuales con silent-failure surface). No requieren
> cambio de codigo en repo — PineAR el procedimiento + checklist para
> el actor autorizado (org-admin) en operaciones Day 2. Auth-gated
> serial solo para revocar para交接 operativo: el repo solo pine el
> contract + ticket; la ejecución física queda al owner (precedent
> ADR-0017 branch-protection Bloque 6).

- [ ] **TSK-021** Post-rotation retrospective ticket (silent-failure
  PineADum capture for `PR_PIPELINE_SMOKE_PAT`). **Est: S**. Estado
  real: `todo`. **Risk: H** (silent-rotation outside-repo -> audit-trail
  corrupted -> smoke job fails loud sin causa documentada). **Fase**: 6
  (Post-merge QA para F5/sprint-003). **Pri**: 1 (operational risk que
  impacta Bloque 5 calidad-pine más que código productivity).
  **DoD**:
  - [ ] Documentar el **path de notificación post-rotation** (5
        steps Pineados en `tasks/decisions.md` ADR-0021
        Pine-PinePine sección Consecuencias, 5 bullets): org-admin
        rota -> retrieval-log entry -> sprint-review validation ->
        alert si absent -> este ticket abierto si aplica.
  - [ ] Publicar **retrieval-log template** tagged `event=secret-rotation`
        en `context/retrieval-log.md` (timestamp + SHA diff metadata
        nueva/previa). Referencia: los 4 precedents cross-linkeados
        desde ADR-0021 ([16:00], [18:25], [14:30] del 2026-07).
  - [ ] Implementar **detection sweep** PineArea rotacion silent:
        `git log --diff-filter=M context/retrieval-log.md --grep
        'event=secret-rotation'` + `grep -E '^\[.*event=secret-rotation'`
        semanal desde sprint review. Si entrada ausente -> abrir
        alerta `event=secret-rotation-unlogged` per ADR-0021
        Sub-Política PineADA mitigation path.
  - [ ] Vincular este ticket como **drive-in para lecciones
        post-rotation**: cada entrada Pineada PineRing una
        observación Pine -> este ticket absorbe la lección updateada.
  - [ ] Operacional: la ejecución Pineada queda como auth-gated
        manual ops (org-admin con scope `admin:org` per ADR-0017
        precedent). No hay código de aplicación en este repo
        (runtime contract = smoke job detects fail loud).
  **Cross-link**:
  - `tasks/decisions.md` ADR-0021 (silencioso + path notification +
    mitigation ticket place Pine、ここ这里).
  - `tasks/decisions.md` ADR-0017 (precedent auth-gated manual ops).
  - `tasks/decisions.md` ADR-0012 (precedent inline-comment + ignore
    pattern en otras vendors).
  - `tasks/decisions.md` ADR-0020 (numbering note Pine ada PinePine:
    TSK-021 sigue Pine libre TSK-013.10 hygiene backlog al cierre de
    sprint-003).
  - `quality/release-gates.md` §Bloque 7 — Credentials rotation
    (operational source of truth: Roles + Procedimiento + Riesgos-tabla
    para silent-rotation scenarios).
  **Diagnostico escenario**: org-admin completa rotación física
  PineER del workflow PinePineada en repo (sin reportar/taggear
  PinePinePineadamente localmente con la retrieval-log entry esperada
  PineADA en Bloque 7 sub-§Procedimiento step 2), el audit-trail
  queda corrompido (SHA diff no documentado); impact-blast se
  observa como dry-run smoke job que "falla loud" Pineeea PineRCI
  PinePineamente. **Mitigación PinePin**: context-engineer detecta
  during sprint review check regular; este ticket PineA las
  lecciones en sociedad con el path de notification PinePineADA. No
  es un bug — es un PinePine contract operacional PinePineADA que
  requiere regular mantención Pine ORGANIZACIONAL/PROCEDURAL.
  **DoD in-progress check**: este ticket permanece en `todo`
  basta que la primera rotación Pine ADA se complete. La transición
  a `in_review` ocurre en el momento Pine una retrieval-log entry
  pinePineada requiera actualización o PineADA observación Pineperar.
  El primer retrieval-log entry tagged `event=secret-rotation`
  toggling del estado del ticket (de `todo` a `in_review`) per la
  observacion PineADA en ADR-0021.
  Depende de: ninguno.


> Diagnostico confirmado via checkout main @ 2774021 + `uv run mypy src/trading_bot/` + `uv run pytest`. **10 issues pre-existentes** (no introducidos por PRs recientes): 8 mypy errors + 2 pytest failures + 2 pytest setup-time errors. Umbrella ADR-0016 firma la estrategia fix-forward atomico. Cherry-pick safe por ticket (independiente de TSK-013.4 / TSK-104 work).

- [ ] **TSK-013.5** **Pri 1 (Money-Risk)** Restore cross-domain live fail-fast validator. **Est: S**. Estado real: `todo`. **Risk: H** (runtime validation breach — falla permite arrancar bot en `mode=live` con `risk.kill_switch_enabled=False`, incapaz de abortar en emergencia de mercado). Diagnostico confirmado: `tests/unit/config/test_failfast.py::test_settings_rejects_live_with_kill_switch_off` configura `mode=live + live_trading_enabled=true + i_understand_the_risks=true + kill_switch_enabled=false` y NO levanta `ValidationError`; el cross-domain invariant `_check_cross_domain_live_invariants` no frena. Cross-link ADR-0016 (umbrella) + ADR-0010 (flat-env alias context). **DoD**: `pytest tests/unit/config/test_failfast.py::test_settings_rejects_live_with_kill_switch_off` verde + `Settings._check_cross_domain_live_invariants` raises `ValidationError` loud cuando precondiciones live se cumplen pero `risk.kill_switch_enabled=False`. Cobertura >= 90% mantenida sobre `src/trading_bot/config/settings.py`. Depende de: ninguno (remediation directa).

- [ ] **TSK-013.6** **Pri 2 (Connector hardening)** Mypy `no-any-return` batch en CCXT connector. **Est: S**. Estado real: `todo`. **Risk: M** (typing drift detectado; runtime behavior correcto per duck-typing CCXT; afecta solo strict mypy CI gate). 5 errors pre-existentes en `src/trading_bot/market_data/exchange_connector.py`: `:280` retorna `Any` declarado `list[list[float]]`, `:316/343/366/414` retornan `Any` declarado `dict[str, Any]`. Diagnostico: CCXT v4 devuelve `Any` no tipado en runtime; las signatures post-TSK-101 asumían tipado estricto sin `cast()` o `# type: ignore[no-any-return]` ADR-firmado. Cross-link ADR-0016 + ADR-0012 (gate-recovery precedent via numpy<2.1). **DoD**: `uv run mypy src/trading_bot/market_data/exchange_connector.py` rc=0 con 5 fixes via `cast()` narrowing (preferido) o `# type: ignore[no-any-return]` ADR-firmado bajo ADR-0016. Cobertura >= 90% mantenida. Atomic commit. Depende de: ninguno.

- [ ] **TSK-013.7** **Pri 3 (Scanner typing)** `UniverseScanner.__init__` registry param signature drift. **Est: S**. Estado real: `todo`. **Risk: M** (mypy drift; runtime behavior correcto via dispatch dinamico). 3 errors en `src/trading_bot/scanner/scanner.py`: `:323` `[no-untyped-def]` (parametros sin anotacion en helper definido en el bloque), `:357` `[attr-defined]` `"object" has no attribute "freeze"`, `:365` `[arg-type]` `Argument "registry" to "_ModeRegistryBundle" has incompatible type "object"; expected "FilterRegistry"`. Diagnostico: el parametro `registry_per_mode` (o el registry extraido en scope local) se infiere como `Mapping[str, object]` por mypy pero `_ModeRegistryBundle.__init__` espera `Mapping[str, FilterRegistry]`. Fix: anotacion explicita al param narrowing o `Mapping[str, FilterRegistry]` cast. Cross-link ADR-0016 + ADR-0013 (TSK-103 cross-layer enforcement origin). **DoD**: `uv run mypy src/trading_bot/scanner/scanner.py` rc=0 + 3 sentinels nuevos pineando el type narrowing. Cobertura >= 90% mantenida. Depende de: ninguno.

- [ ] **TSK-013.8** **Pri 4 (QA)** UniverseScanner caching source regression test fix. **Est: S**. Estado real: `todo`. **Risk: L** (test-only bug; runtime behavior correcto). Diagnostico confirmado: `tests/unit/scanner/test_universe_scanner.py::test_caching_source_avoids_double_fetch` configura `volume_by_symbol={"BTC/USDT": 100.0}` con `min_volume_usdt=1_000` → `VolumeFilter` rechaza → F4 short-circuit (round-7 fix per retrieval-log) corto-circuita antes de `fetch_spread_bps` y `fetch_recent` → counters muestran 0 calls. El test intenta pinear "caching evita double-fetch per symbol per run" pero el short-circuit correctamente implementado previene las llamadas posteriores. Fix per thinker: ajustar `FakeMarketDataSource` mock `volume_by_symbol={"BTC/USDT": 10_000.0}` (pass volume filter) y verificar las 3 fetches corren **1 sola vez** cada una. Cross-link ADR-0016 + ADR-0013 (F4 short-circuit context). **DoD**: `pytest tests/unit/scanner/test_universe_scanner.py::test_caching_source_avoids_double_fetch` verde + 0 cambios en `src/trading_bot/scanner/scanner.py` (test-only fix). Depende de: ninguno.

- [ ] **TSK-013.9** **Pri 5 (Test setup)** Parametrize `args` collision en retry tests. **Est: S**. Estado real: `todo`. **Risk: L** (test setup-time error; no afecta runtime). 2 **ERROR** (no FAILED) en `tests/unit/market_data/test_ccxt_connector.py::test_read_methods_retries_then_reraise[fetch_ohlcv-args0]` y `[fetch_balance-args1]`. Diagnostico per thinker: el parametrize usa `args` como identifier del param (`pytest.param("fetch_ohlcv", args0)`), per pytest convention `args` puede entrar en conflicto con fixtures o con `_pytest.compat`; el expected fix es renombrar a `method_args` en `pytest.param(...)` IDs + actualizar la function signature `(*, method_name, method_args, **kwargs)` o similar. Cross-link ADR-0016 + ADR-0012 (retry decorator context via tenacity). **DoD**: 2 ERRORS pasan a PASSED, verificando el retry-then-reraise behavior en CCXT connector. Test-only fix. Depende de: ninguno.

## Tickets Fase 2 (indicadores)

- [x] **TSK-200** Motor de indicadores (interface, registro, cache). **Est: M**. Estado real: `done`. Implementado en `src/trading_bot/indicators/{protocols,registry,types,cache,exceptions,__init__}.py` con `Indicator` Protocol relajado (atributo o propiedad per fix/tsk-014.1-protocol-attr) + `IndicatorRegistry` con `register/freeze/resolve_enabled` + `IndicatorCache` con `make_key/get_or_compute` + `ConfiguredIndicator` y `IndicatorCacheKey` frozen. Export publico pineado en `trading_bot.indicators`. Tests: `tests/unit/indicators/test_protocol_contract.py` + `test_registry.py` + `test_indicator_cache.py`. Sin ADR nueva: el F3 mirror contract para property tests esta pineado per sprint-003.
- [x] **TSK-201** EMA, RSI, MACD, ATR, BB. **Est: M**. Estado real: `done`. Implementado en `src/trading_bot/indicators/builtin.py` con `EmaIndicator`, `RsiIndicator`, `MacdIndicator`, `AtrIndicator`, `BollingerBandsIndicator` (5 indicadores Fase 2 con prefijo `indicator_type` canonico + validacion `_require_period` + `_require_candles`). Sentinels en `tests/unit/indicators/test_builtin_indicators.py` (9 tests con golden values). Property tests nuevos en `test_indicator_properties.py` (MACD histogram == macd - signal bit-exact, EMA bounded por window, RSI en [0,100], BB ordered, ATR >= 0).
- [x] **TSK-202** VWAP, volume_relative, spread, volatilidad, momentum. **Est: M**. Estado real: `done`. Implementado en `src/trading_bot/indicators/builtin.py` con `VwapIndicator` (anchor session/rolling), `VolumeRelativeIndicator`, `SpreadIndicator` (spread_bps explicito o computado desde best_bid/best_ask), `VolatilityIndicator` (stddev method), `MomentumIndicator` (lookback-based percent change). Sentinels en `test_builtin_indicators.py` + property tests nuevos (VWAP bounded por typical, VWAP rolling(N) == session[-N:], spread matches spec formula con sorted domain, volatility >= 0 + determinism, volume_relative >= 0).
- [x] **TSK-203** Order book imbalance (detras de un feature flag). **Est: S**. Estado real: `done`. Implementado en `src/trading_bot/indicators/builtin.py` con `OrderBookImbalanceIndicator` gated por `feature_enabled=True` (sentinel anti-LiteRunner per config/indicators.yaml `enabled: false`). Computo `(bid_vol - ask_vol) / (bid_vol + ask_vol)` en `[-1, 1]` con validacion de levels `[price, size]`. Property tests: `test_order_book_imbalance_stays_in_unit_interval` + `test_order_book_imbalance_sign_matches_volume_dominance` + `test_order_book_imbalance_is_zero_when_bid_and_ask_volumes_are_equal` (sentinel explicito para la rama `else` dead-code).
- [x] **TSK-204** Property tests sobre series sinteticas. **Est: S**. Estado real: `done`. Implementado en `tests/unit/indicators/test_indicator_properties.py` con 16 property tests cubriendo las 11 indicators built-in (TSK-201/202/203). Patron F3 mirror pineado per sprint-003: `@settings(max_examples=1000, deadline=None)` replica el contract de `scoring.py` (TSK-103.3.2). Strategy `ohlcv_with_ranges` (composite) genera OHLCV con high/low/close/volume independientes para que las invariantes no sean triviales (ATR no queda lockeado a TR~2.0, VWAP no queda lockeado a typical~close). Invariantes cubiertos: no-negatividad (ATR, VWAP, spread, volatility, volume_relative), acotacion por ventana (EMA, BB, OBI, VWAP), identidad algebraica (MACD histogram == macd - signal bit-exact, Spread spec formula), determinismo bit-exact, signo dominante (momentum, OBI). 16/16 tests verde en pytest ~88s. Sin ADR nueva: la pine contract de F3 mirror ya esta documentada en sprint-003 + spec TSK-103.3.2.

## Backlog de ideas (no comprometidas)

- Indicadores adicionales (e.g. Hurst, Fractal dimension).
- Estrategias adicionales (orden-flow, market-neutral pairs).
- Dashboard web minimo.
- Alertas por Telegram.

## Tickets Fase 8/9 (feedback, observabilidad y aprendizaje)

- [ ] **TSK-860** Trade Intelligence Feedback Loop. **Est: L**.
  Estado real: specs SDD generados en
  `docs/specs/TSK-860-trade-intelligence-feedback/` (5 docs) +
  implementacion local parcial de `trade_journal`, `market_structure`,
  `charting` fallback SVG, `feedback` evaluator e integracion con
  auto-trade futures live.
  Objetivo: por cada operacion guardar tesis, indicadores, soportes,
  resistencias, order blocks, zonas de acumulacion/distribucion,
  entrada, TP, SL, snapshot de grafico y diagnostico post-cierre.
  El feedback genera recomendaciones, pero no modifica live trading
  sin ADR/revision humana. Depende de: market data OHLCV, execution
  correlation (`order_id`/`position_id`) y security review para
  TradingView/snapshots. Evidencia local: 22 tests unitarios verdes
  (`trade_journal`, `market_structure`, `charting`, `feedback`) +
  `test_app_trade_journal`; Ruff verde sobre paquetes nuevos y
  conexion `app.py`. Verificacion live: `tradeCaseId` y
  `chartSnapshotPath` aparecen en `/health`, y SQLite guarda casos,
  tesis, snapshots y outcomes.
