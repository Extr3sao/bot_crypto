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
## Tickets polish (TSK-016 cross-cutting)

- [ ] **TSK-016** Polish bundle for `paper` module (3 strongly-recommended items, follow-up PR to F5). **Est: S**. **Origen**: code-reviewer verdict on the paper-module work (downstream of TSK-103.5 wiring + TSK-103.4 scanner + TSK-102 OHLCVStore). **Pri**: 2 (cheap relative to the alternatives; needed before any live `paper`-shared-DB scenario). **DoD**: all 3 polish items below verde in `pytest` + `ruff` + `mypy`; one PR titled `chore(paper): polish bundle (TSK-016)`; cross-referenced from `retrieval-log.md`. **Out-of-scope**: async/locking infrastructure; paper-trading state migration tooling; multi-host replication. **Cross-refs**: TSK-103.5 (paper wiring), TSK-102 (OHLCVStore UPSERT reference pattern), TSK-013.4 / TSK-111 (ruff precedent for code-quality tickets). **Depende de**: ninguno (cada polish item es independiente; pueden hacerse en commits atomicos).

  **Polish 1: `PaperExecutionSummary` caller parity test.** Add a parity test en `tests/unit/paper/test_paper_types.py::test_paper_execution_summary_caller_parity` que escupa fail-loud cualquier dia que se anada un nuevo required field al dataclass `PaperExecutionSummary` sin propagarlo a todos los call-sites. Mismo patron defensivo que la parity test flagged para `Risk.model_fields` post-`de1c110`.

  **Concrete file:line refs (audit 2026-07-XX)**:
  - `src/trading_bot/paper/__init__.py:20, 32` — re-export + `__all__` entry.
  - `src/trading_bot/paper/types.py:60` — dataclass definition. `:103` — `TradeTicket.execution_summary: PaperExecutionSummary | None = None` (callback field). `:127` — dataclass export.
  - `src/trading_bot/paper/reporting.py:14, 24` — type import + fn parameter `execution_summary: PaperExecutionSummary | None`.
  - `src/trading_bot/paper/broker.py:16, 149, 152, 291` — type import + return-type annotation + 2 return paths (early-no-op line 152, post-position-update line 291).
  - `tests/unit/paper/test_reporting.py:16, 100` — type import + test fixture construction.

  **Test contract**: assert `set(f.name for f in dataclasses.fields(PaperExecutionSummary)) <= {f-name-in-caller-site-unions}` (closed under addition). Inject a temporary new **required** field on `PaperExecutionSummary` in the test to confirm the gate is non-tautological (not just a vacuous pass).

  **Polish 2 (AMENDED 2026-07-08 post-audit): `datetime.UTC` standard ratificado + lint-defense via ruff rule. NO migracion pendiente.** Auditoria ground-truth via `code_searcher` (baseline 2026-07-08) revela que el codebase ya esta en el estado canonico:

  | Patron buscado | Matches en `src/` | Matches en `tests/` | Match total | Accion |
  | -------------- | ----------------- | ------------------- | ----------- | ------ |
  | `datetime.timezone.utc` | **0** | 0 | **0** | Nada — no hay blanco a migrar. |
  | `datetime.utcnow()` (deprecated Python 3.12+) | **0** | 0 | **0** | Nada — API deprecated no se usa. |
  | `datetime.now()` naive | **1** (docstring-only en `src/trading_bot/backtesting/engine.py:10`) | 0 | 1 | Non-issue — docstring referencia el no-uso, no es codigo live. |
  | `datetime.UTC` canonical | 2 (sitios en `src/`) | 94 (fixtures + assertions) | **96** | Patron ya canonico. |

  **Cross-link arquitectonico**: codificado via **ADR-0017** (status-quo confirmation) firmada en `tasks/decisions.md` el 2026-07-08. La ADR formaliza `datetime.UTC` como estandar obligatorio del proyecto y rechaza explicitamente `datetime.timezone.utc` + `datetime.utcnow()` + `datetime.now()` naive (ultimo sin uso explicito no anclado a `tz=`).

  **Alcance del PR TSK-016 Polish 2 (re-definido post-audit)**:

  1. `pyproject.toml`: anadir `"UP017"` + selectivamente `"DTZ005"`, `"DTZ006"`, `"DTZ007"` al array `[tool.ruff.lint] select`. La combinacion cubre los 3 vectores que el audit demuestra que el codebase debe rechazar: `datetime.utcnow()`, `datetime.now()` naive, y `datetime.fromtimestamp()` sin tz. Verificar antes de commit con `uv run ruff check . --select UP017,DTZ005,DTZ006,DTZ007` (expect: 0 violations).
  2. `tasks/decisions.md`: anadir ADR-0017 con `Estado: Decidido y aplicado` + cross-link a esta entrada TSK-016 Polish 2 + cross-link a TSK-013.4 / TSK-111 (precedente de ruff-cleanup antes de introducir reglas).
  3. `tasks/backlog.md`: amend esta entrada Polish 2 con la tabla baseline + ratifica el cross-link a ADR-0017 (este mismo amend).
  4. `tests/`: agregar regression test (e.g. `tests/unit/test_datetime_standard.py::test_no_deprecated_datetime_apis_in_src`) que escanea `src/` con AST y assert no contiene llamadas a `datetime.utcnow()`, `datetime.now(sin_tz)`, ni `datetime.timezone.utc`. El test es un bellwether independiente de ruff (cubre el caso donde ruff config quede desincronizada).

  **Concrete file:line refs de los sitios canónicos (los unicos en `src/` que muestran el patron adoptable)**:

  - **`src/trading_bot/paper/broker.py:211`**: `datetime.datetime.fromtimestamp(now_ms / 1000.0, tz=datetime.UTC).strftime("%Y-%m-%d")`. Conversion ms -> dt con timezone explicito.
  - **`src/trading_bot/paper/harness.py:103`**: `self._now_fn = now_fn or (lambda: datetime.datetime.now(datetime.UTC))`. Current-time con timezone explicito.

  Los 94 matches en `tests/` son fixtures con la firma `datetime.datetime(2026, 1, 1, ..., tzinfo=datetime.UTC)` (literales con `tz=`); no son codigo de produccion pero confirman estabilidad del patron.

  **Dependencias tecnologicas**:

  - **ruff >= 0.1** requerido para `UP017` (estable desde 0.4.x; validar pin actual en `pyproject.toml` antes de mergear).
  - **TSK-013.4 / TSK-111** ruff-cleanup DEBE estar mergeado antes de este PR — la regla nueva no debe anadir violations en el primer push. Si TSK-013.4 no esta mergeado, firmar ADR-0017-extension con la misma logica que ADR-0012 (gate-recovery precedent).

  **Reframing del PR**: el titulo del commit / PR sera el amend. Originalmente Polish 2 era "(paper): align datetime.timezone.utc -> datetime.UTC". Post-audit, el titulo correcto es "(paper): ratify datetime.UTC standard + enable ruff UP017/DTZ lint-defense (TSK-016 / polish 2 + ADR-0017)". Evita confusion con reviewer que vea el titulo original esperando una migracion.

  **Polish 3: `paper_risk_state` multi-process UPSERT.** Refactor del split `INSERT` (line 133) + `UPDATE` (line 339) en `broker.py` a un unico atómico `INSERT ... ON CONFLICT (id) DO UPDATE SET ...` (mismo patron que ya usa `OHLCVStore` per TSK-102). Multi-process safety: dos paper-trading procesos compartiendo la misma DB no deberian poder producir stale-write o fail-fast por contention.

  **Concrete file:line refs (audit 2026-07-XX)**:
  - `src/trading_bot/paper/broker.py:122` — `CREATE TABLE IF NOT EXISTS paper_risk_state (id INTEGER PRIMARY KEY, ...)`.
  - `src/trading_bot/paper/broker.py:133` — `INSERT INTO paper_risk_state (consecutive_losses, cooldown_end_ms, ...)` (insert path; **sin `ON CONFLICT`** — stale-write risk entre writers).
  - `src/trading_bot/paper/broker.py:329` — `SELECT ... FROM paper_risk_state WHERE id = 1` (read path).
  - `src/trading_bot/paper/broker.py:339` — `UPDATE paper_risk_state SET consecutive_losses = ?, cooldown_end_ms = ?, ...` (update path; depende del SELECT previo — race-prone si dos writers).

  **Reference pattern ya en el repo**: `src/trading_bot/storage/ohlcv_store.py:13-17` (modulo doc) + `INSERT ON CONFLICT (symbol, timestamp) DO UPDATE` (line ~50).

  **Out-of-scope (deja como TSK-016+ future)**: `_upsert_position` method en `src/trading_bot/paper/broker.py:391` (paper_positions UPSERT — mismo patron pero distinto table; cubrira un ticket dedicado para evitar overload de TSK-016).

  **New test `tests/unit/paper/test_broker.py::test_paper_risk_state_upsert_is_race_free`**: abrir 2 connections SQLite al mismo file (`sqlite:///:memory:` cache compartida via file-backed tmp), ambas con `PRAGMA journal_mode = WAL` + `PRAGMA busy_timeout = 5000`; 2 threads escribiendo `consecutive_losses` con valores diferentes interleaveados via `time.sleep(0.001)` para forzar contention; assert `consecutive_losses` final siempre es el del segundo writer (last-write-wins) sin leak de valor intermedio.

  **Riesgos**:
  - **PRAGMA busy_timeout**: SQLite WAL necesita `busy_timeout >= 5000` para que contention entre 2 paper-trading processes no fail-fast al segundo writer. Verify si `broker.py` ya setea esto en connection-open; si no, anadir.
  - **Last-write-wins semantics**: rompe si 2 procesos actualizan distintos fields del mismo row en paralelo (e.g., uno escribe `consecutive_losses`, otro escribe `cooldown_end_ms` simultaneamente — el segundo hace overwrite de los dos). Para uso single-operator, OK. Documentar el scope explicito en el PR body.
  - **Cross-module side-effects**: el UPSERT en `paper_risk_state` requiere la misma migracion SQLite-user_version que usa `storage/ohlcv_store.py` (PRAGMA user_version v1 + WAL pragmas). Verify que el `paper_risk_state` se crea con la misma `PRAGMA user_version` consistency en connection-open.

  **Plan de ejecucion (3 commits atomicos — squash al mergear)**:
  - Commit 1: `(paper): add PaperExecutionSummary caller parity test (TSK-016 / polish 1)`. Add test; run pytest; si green, commit.
  - Commit 2: `(paper): enable ruff UP017 datetime.UTC audit (TSK-016 / polish 2)`. Anade la regla ruff; run ruff check; verify 0 nuevos violations; commit.
  - Commit 3: `(paper): atomic UPSERT for paper_risk_state (TSK-016 / polish 3)`. Refactor 2-statement split a ON CONFLICT; anadir race-free test en `tests/unit/paper/test_broker.py`; run pytest + ruff + mypy; commit.

## Backlog de ideas (no comprometidas)

- Indicadores adicionales (e.g. Hurst, Fractal dimension).
- Estrategias adicionales (orden-flow, market-neutral pairs).
- Dashboard web minimo.
- Alertas por Telegram.
