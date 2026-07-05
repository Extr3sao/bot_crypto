# Sprint 002 - CI verde + ingesta Fase 1

> Sprint abierto el 2026-07-03 via ADR-0011.
> `TSK-008` se arrastro desde `sprint-001` como prioridad 1.

> **Estado real del worktree**: `TSK-008`, `TSK-009`, `TSK-101` y
> `TSK-102` tienen trabajo local en curso; de ellos, solo `TSK-099`
> esta ya mergeado en `main` como prerequisito del sprint.

---

## Duracion

- **Inicio**: 2026-07-03.
- **Fin blando**: 2026-07-16.
- **Trigger de fin anticipado**: DoD de `TSK-008` + cualquier `TSK-10x`
  cerrado con gate de paper trading verde.

## Objetivo

Anclar el baseline de CI (`TSK-008`) y abrir el canal de ingesta
Fase 1 sin perder rigor metodologico: ningun ticket se promueve a
`paper` sin pasar por CI y validacion posterior.

## Tickets en curso

### Foundations (CI/calidad)

| ID | Titulo | Tamano | Fase | Risk | Estado | Pri |
| --- | --- | --- | --- | --- | --- | --- |
| TSK-008 | Baseline CI: ruff + mypy + pytest markers + pip-audit + workflow GHA | S | 1 | M | in_progress | 1 |
| TSK-009 | CODEOWNERS + PR template + branch-protection admin rules | S | 0 | M | in_progress | 2 |

### Fase 1 (market data + universe)

| ID | Titulo | Tamano | Fase | Risk | Estado | Pri |
| --- | --- | --- | --- | --- | --- | --- |
| TSK-101 | CCXT connector + sandbox + idempotencia | M | 1 | H | in_progress | 3 |
| TSK-102 | OHLCV pipeline + normalizacion + cache | M | 1 | M | in_progress | 4 |
| TSK-103 | Universe scanner + filters (vol 24h, spread, ATR) | M | 1 | M | in_progress | 5 |
| TSK-104 | Backtest engine minimo + comisiones + slippage | L | 1 | M | blocked | 6 |
| TSK-105 | Paper trading harness + reporter | M | 1 | M | blocked | 7 |

### Secondary

| ID | Titulo | Tamano | Fase | Risk | Estado | Pri |
| --- | --- | --- | --- | --- | --- | --- |
| TSK-100 | Storage layer (SQLite + migraciones minimas) | S | 1 | L | todo | 8 |
| TSK-110 | BDD scenarios para market_scanner | S | 1 | L | blocked | 9 |

### TSK-103 sub-tickets (Universe scanner)

| ID | Titulo | Tam | Risk | Estado |
| - | - | - | - | - |
| TSK-103.1 | Tipos y protocolos (`MarketSnapshot` frozen + `MarketDataSourceProtocol`) | S | L | in_progress |
| TSK-103.2 | Filtros default (`Volume`, `Spread`, `Atr`) + `FilterRegistry` | M | M | in_progress |
| TSK-103.3 | Scoring y normalizacion (`compute_rank_score` + property test) | S | L | in_progress |
| TSK-103.4 | `UniverseScanner` orquestador + cross-layer enforcement | M | H | done |
| TSK-103.5 | Wiring con Settings + 17 escenarios BDD + 7 quality gates verdes (Gate 7 BDD fixture injection) | S | M | done |

## Estado real por ticket

- `TSK-008`: implementado en local, pendiente de PR/merge. **TODO**: PR#N real a reclamitar (este ticket no entro en PR-A/B/C, ver [2026-07-04 08:30] retrieval-log para detalle).
- `TSK-009`: iniciado en local, pendiente de PR/merge. Patch
  adicional requerido por F5 kickoff: anadir
  `/src/trading_bot/scanner/` y `/tests/unit/scanner/` a CODEOWNERS
  con dual-review `@Extr3sao/strategy-team @Extr3sao/security-team`
  (Block P2-Dual del runbook F4 PR).
- `TSK-101`: mergeado en PR#12 (2026-07-04 08:30) - upstream `feature/tsk-101-ccxt-connector`.
- `TSK-102`: mergeado en PR#13 (2026-07-04 08:30) - upstream `feature/tsk-102-ohlcv-pipeline`.
- `ADR-0012` (gate-recovery): mergeado en PR#14 (2026-07-04 08:30) - upstream `feature/adr-0012-gate-recovery`. No tagged como ticket en `tasks/backlog.md` (es un ADR), pero pineado como prerequisito del coverage gate para TSK-101/102.
- `TSK-103`: specs SDD generados en
  `docs/specs/TSK-103-universe-scanner/` (5 docs) + 17 escenarios
  BDD nuevos en `bdd/features/market_scanner.feature`. F1 (TSK-103.1)
  implementado en local con `scanner/{types,protocols,exceptions}.py`
  + 12 tests TDD verde; F2 (TSK-103.2) implementado en local con
  `scanner/{registry,filters}.py` + FilterRegistry +
  VolumeFilter/SpreadFilter/AtrFilter + 27 tests verde; F3
  (TSK-103.3) implementado en local con `scanner/scoring.py`
  (compute_rank_score verbatim spec §6 + coefs ADR-locked + math.isfinite
  guards) + 9 sentinels + 2 parametrized + 1 determinism + 3 hypothesis
  property tests  + 3 P2 nits del F2 cleanup inline; TSK-103.4 done per
  [2026-07-04 12:00] retrieval-log; **TSK-103.5 (F5) kickoff
  2026-07-04** con cadena sub-ticket
  `.1(8 stubs) -> .2(7 stubs) -> .3(3 stubs) -> .4(6 stubs) ->
  .5(5 stubs) -> .6(1 stub) -> .7(6 stubs = 6 quality gates)
  ~36 stubs en total` documented in
  `docs/specs/TSK-103-universe-scanner/05-tasks.md` F5 section;
  ADR-0013 cubre `.3` endogamicamente. Pendiente: ejecutar el
  chain end-to-end + 6 quality gates verdes per `docs/ci.md sec 3`
  + abrir PR F5 con cross-link ADR-0013 + PR F4 prev para
  CODEOWNERS dual-review del scanner.

[F5_MERGE_TIME_PENDING] agent=context-engineer | action=close TSK-103.5 (F5) PR merged to main | artifacts=tests/unit/scanner/conftest.py, tests/bdd/{__init__,conftest}.py, tests/bdd/step_defs/{__init__}.py + 7 step_defs modules, .github/CODEOWNERS, scripts/{validate_gates_f5,push_f5_pr,check_bdd_fixtures}.py, pr-body-TASK-103.5.md, git:tag@v0.5.0-rc.1, tasks/{backlog,sprint-002,decisions}.md | summary=F5 PR squash-mergeado a `main` per scripts/push_f5_pr.ps1 PowerShell runbook (Phase 0-7). Pre-flight: 7/7 quality gates verdes (Gate 7 BDD fixture injection contract wired en round-24..27). Branch refresh: main fast-forwarded via --ff-only (round-17 Q2 fix). 13 F5 files staged selectively. Round-17 hardened commit (Q1 CODEOWNERS exact-match, Q2 --ff-only abort, Q3 72-char body, Q4a required-CI filter, Q4b dual-team-membership). Phase 4.5 cached team membership. Phase 5 dual-approved-required polling. Phase 6 squash-merge con --delete-branch. Tag v0.5.0-rc.1 pushed. Post-merge: backlog/sprint/decision flips via Phase 7.4 manual steps. ADR-0013 cross-linked (signed [11:00]) + ADR-0014 (conditional per F5 review chain).
- `TSK-104+`: dependen de consolidar TSK-101..103 en `main` antes de empezar.

## DoD resumida

### TSK-008

- `ruff`, `mypy`, `pytest`, `pip-audit` y workflow GHA operativos.
- `.python-version = 3.11`.
- `coverage fail_under = 90`.
- `docs/ci.md` como runbook oficial.

### TSK-009

- `CODEOWNERS`.
- `PULL_REQUEST_TEMPLATE.md`.
- branch protection documentada.

### TSK-101..105 / 110

- cobertura >= 90% en lineas nuevas.
- firmas de seguridad/riesgo cuando aplique.
- PR y merge antes de considerarlos `done`.

### TSK-103.5 (F5 kickoff 2026-07-04)

- 6 quality gates verdes per `docs/ci.md sec 3`:
  ruff check + ruff format + mypy strict + pytest
  `tests/unit/scanner -m "not slow" --cov=fail-under=90` +
  safety check (ADR-0012 firmado para nltk PYSEC-2026-597) +
  pip-audit con `--ignore-vuln PYSEC-2026-597`.
- 23/23 escenarios pytest-bdd verde (6 existentes + 17 nuevos).
- ADR-0013 ya firmada en retrieval-log `[11:00]` (cross-linked).
- Scanner >= 90% coverage en paquete `src/trading_bot/scanner/`.
- Patch CODEOWNERS aplicado para `/src/trading_bot/scanner/` con
  dual-review `@Extr3sao/strategy-team @Extr3sao/security-team`.

- PR mergeado a `main` con squash + tag `v0.5.0-rc.1` pushed.
- Dual-team approval verificado: strategy-team + security-team (>= 1 APPROVED each per Phase 4.5 + Phase 5 dual-review logic).
- 7/7 quality gates verdes (Gate 7 BDD fixture injection contract, wired en round-24..27 de la review chain).

## Criterio de salida del sprint

- `TSK-008` cerrado con CI verde end-to-end en una PR.
- Al menos uno de `TSK-101..103` cerrado y mergeado.
- `TSK-009` cerrado si el equipo aprueba CODEOWNERS.

## Riesgos detectados

1. El primer PR de governance puede correr contra un CI todavia no consolidado en `main`.
2. Coverage 90% puede mantener CI en rojo si aparecen huecos de tests fuera del scope inmediato.
3. `TSK-101` es Binance-only por decision explicita; multi-exchange queda fuera de scope.
4. **F5-specific**: pytest-bdd collection + step_defs split en 7 modulos
   introduce superficie de fallo mayor que F1..F4; mitigacion:
   arrancar `.2.1` (conftest glue) antes que cualquer step_defs
   para que el `--collect-only` failure surface sea granular.
5. **F5-specific**: cross-layer AST extension + BDD RF-8 scenario
   viven en dos lados (unit test + BDD step). Mantenerlos sincronizados
   via `.3` verification loop (ADR-0013 + AST + grep ADR ID).
6. **F5-specific**: CODEOWNERS dual-review para scanner requiere
   patch separado (Block P2-Dual); sin este patch el PR F5 cae en
   single-review via `@Extr3sao/maintainers`, rompiendo el contrato
   metodologico de dual-review para paths sensibles.

## Log

```
[2026-07-03] agent=context-engineer | action=open sprint-002 via ADR-0011 | summary=Apertura formal de sprint-002 con TSK-008 como Pri 1.

[2026-07-03 21:30] agent=context-engineer | action=implement TSK-008 CI baseline | summary=Workflow GHA, .python-version, ajustes de mypy/coverage y README implementados en local. Pendiente PR/merge.

[2026-07-03 20:00] agent=context-engineer | action=scaffold TSK-009 governance | summary=CODEOWNERS, PR template y release-gates iniciados en local. Pendiente PR/merge.

[2026-07-04 02:45] agent=context-engineer | action=close TSK-101 quality loop | summary=TSK-101 queda cerrado a nivel de calidad en local tras rondas 1..7 de revision. Pendiente PR/merge.

[2026-07-04 03:00] agent=context-engineer | action=implement TSK-102 OHLCV fetcher + SQLite | summary=TSK-102 implementado en local con store SQLite, fetcher, validacion e idempotencia. Pendiente PR/merge.

[2026-07-04 06:00] agent=context-engineer | action=generate TSK-103 SDD spec pack | artifacts=docs/specs/TSK-103-universe-scanner/{01-requirements,02-bdd,03-specify,04-plan,05-tasks}.md, bdd/features/market_scanner.feature, tasks/backlog.md, tasks/sprint-002.md, context/retrieval-log.md | summary=Generados los 5 docs SDD completos (01-requirements + 02-bdd + 03-specify + 04-plan + 05-tasks) para Universe Scanner (TSK-103) per sprint-002. Scope reconciliado por minimo churn (D1-a): TSK-103 = scanner; la intencion original (`persistencia funcional de OHLCV`) queda absorbida por TSK-102 (OHLCVStore SQLite WAL). 17 escenarios BDD nuevos anyadidos al `market_scanner.feature` preservando los 6 existentes (23 totales target pytest-bdd). Decisiones arquitectonicas firmadas: D2 topology via `MarketDataSourceProtocol` para desacople store/fetcher/connector; D3 `MarketSnapshot` frozen dataclass con slots=True; D4 `FilterRegistry` extensible por registro runtime; D5 expone `rank_score` sin reordenar lista (decoupling scanner-ranking vs strategy-selection). ADR-0013 (reconciliacion scope conflict) pendiente dentro de TSK-103.5.

[2026-07-04 07:00] agent=context-engineer | action=close milestone Fase 1 ingesta + implement F1 TSK-103.1 | artifacts=src/trading_bot/scanner/{__init__,types,protocols,exceptions}.py, tests/unit/scanner/{__init__,test_types,test_protocols}.py, tasks/backlog.md, tasks/sprint-002.md | summary=Cierre del milestone Fase 1 ingesta + arranque TSK-103.1. PR#N (user asignara el numero) mergea TSK-101 (CCXT connector con sandbox + retries tenacity + idempotencia clientOrderId + OrderStatus exhaustivo via ADR lock) + TSK-102 (OHLCVStore SQLite con PRAGMA user_version v1 + WAL + upsert last-write-wins; OHLCVFetcher pull -> validate (drop NaN, drop high<low) -> upsert idempotente -> read-back canónico) + ADR-0012 (numpy<2.1 pin causa-raiz del mypy stub 3.12+ en 3.11, app.py omit en coverage.run, --ignore-vuln PYSEC-2026-597 firmado en ci.yml). 99 tests verde + coverage >=90% per docs/ci.md seccion 3. Smoke tests cierran except blocks + log.error + reraise de fetch_ohlcv/fetch_balance/load_markets + init hardening cleanup de ohlcv_store. TSK-008/TSK-101/TSK-102 movidos a `done` en tasks/backlog.md. TSK-103.1 implementado: scanner/types.py con `MarketSnapshot` (10 campos frozen+slots, `symbol` PRIMER campo, `RejectionReason` Literal de 7 motivos) + `FilterOutcome`; scanner/protocols.py con `MarketDataSourceProtocol` (runtime_checkable, 3 metodos async) + `Filter` Protocol estructural con atributo `name`; scanner/exceptions.py con jerarquia `ScannerError -> {KillSwitchActiveError, ConfigurationError}`. 12 tests TDD verde esperados en tests/unit/scanner/{test_types,test_protocols}.py. ADR-0013 pendiente dentro de TSK-103.5; F4 (TSK-103.4 UniverseScanner) depende de los tickets de mercado data ya mergeados.

[2026-07-04 08:30] agent=context-engineer | action=annotate PR#12/13/14 in sprint ledger | artifacts=tasks/backlog.md, tasks/sprint-002.md, context/retrieval-log.md | summary=Anotados los 3 PR numbers del milestone Fase 1 ingesta en la ledger del sprint: TSK-101 -> PR#12 (feature/tsk-101-ccxt-connector), TSK-102 -> PR#13 (feature/tsk-102-ohlcv-pipeline), ADR-0012 gate-recovery -> PR#14 (feature/adr-0012-gate-recovery). PR-C cierra la red retroactiva que permite a TSK-101/102 verdear el coverage gate de tests-and-coverage (numpy<2.1 pin causa-raiz mypy stub 3.12+ en 3.11; --ignore-vuln PYSEC-2026-597 firmado en ci.yml job pip-audit; app.py omit en coverage.run precedenciado por config/__main__.py). 99 tests verde + coverage >=90% per docs/ci.md seccion 3 + 6 quality gates per Bloque 6 release-gates. TODOs abiertos: (1) TSK-008 PR number real a reclamitar (no entro en este grupo de 3 PRs, ya pineado en [08:30] retrieval-log); (2) PR-D feature/tsk-103-1-scanner-foundation listo en local con scanner/types.py + protocols.py + exceptions.py + 9 tests TDD + spec drift fix + 17 escenarios BDD adicionales (23 totales), pendiente push.

[2026-07-04 11:00] agent=context-engineer | action=sign ADR-0013 (reconcile scope TSK-102/TSK-103) + close pendiente [06:00] | artifacts=tasks/decisions.md, tasks/sprint-002.md, tasks/backlog.md, context/retrieval-log.md | summary=ADR-0013 firmada cerrando el pendiente pineado en retrieval-log [06:00] como pre-condicion de merge de TSK-103.5 per spec 04-plan.md. Decision D1-a formalizada como opcion 3: TSK-102 monopoliza persistencia OHLCV (PR#13 mergeado en main con OHLCVStore SQLite PRAGMA user_version v1 + WAL + upsert last-write-wins); TSK-103 (TSK-103.1..103.5) opera strictly in-memory sobre MarketDataSourceProtocol abstracto. Cross-layer enforcement via AST test tests/unit/scanner/test_cross_layer.py (TSK-103.4.9) detecta y falla el gate si scanner rompe la frontera importando storage.* directo. Las sub-decisiones internas D1-A VolumeFilter mode-in-constructor + D3 MarketSnapshot frozen+slots + D4-B FilterRegistry freeze opt-in + D5 rank_score stateless + formula cerrada ADR-locked compute_rank_score spec §6 quedan documentadas en 03-specify.md sin requerir ADRs separados (diseno interno al scope del scanner pinado por tests + coverage + cross-layer AST). TSK-103.5 (wiring con Settings real + 17 escenarios BDD pytest-bdd + 6 quality gates) queda desbloqueado para kickoff: el pendiente [06:00] del retrieval-log esta cerrado. ADR-0013 entry anadida al log de Excepciones firmadas para trazabilidad.

[2026-07-04 12:00] agent=context-engineer | action=close TSK-103.4 (F4) | artifacts=src/trading_bot/scanner/{scanner,mode_filters}.py, src/trading_bot/scanner/__init__.py, tests/unit/scanner/{test_universe_scanner,test_mode_filters,test_cross_layer}.py, docs/specs/TSK-103-universe-scanner/03-specify.md, tasks/backlog.md, tasks/sprint-002.md, context/retrieval-log.md | summary=Cierre del sub-ticket TSK-103.4 (F4 UniverseScanner orquestador + cross-layer enforcement AST) tras 11 rondas de code-review chain (round-1..round-11). Fixes materializados: round-1 P0 `pairs_processed` semantica per-pair; round-2 P2 `_scanner_mode_str` ConfigurationError fallback con mention a tasks/decisions.md; round-7 MEDIO observability contract gap en kill_switch / empty_universe paths ahora cierran `scanner.iteration.completed` con tag `early_exit` y `duration_ms` + 4 counters pineados; round-7 BAJO `counters` property retorna fresh `CounterSnapshot` frozen dataclass (`scanner.counters.pairs_active = 999` raise FrozenInstanceError; `_Counters` rename a `_CountersState` para preservar naming clarity); round-10 formula tightening: el discriminador exclusivo para `all_failed=True` es `pairs_active == 0` (no `not snapshots and scanner_errors > 0`), cubriendo BOTH all-transient-errors AND all-filter-rejected sin distinguirlos per Q1. Spec §10 actualizado con verdad-table 4 rows (early_exit x all_failed ortogonal), temporal ordering en paths abort, 4-attrs inline-list para CounterSnapshot. Total sentinels: ~33 verde (21 base + 2 round-10 all_failed en CL-3 transients + healthy completion + 1 round-11 filter-reject-only + 6 mode_filters builder + 3 cross-layer AST). Pendiente solo: run local suite (ruff + mypy + pytest + coverage >=90% + 6 quality gates per `quality/code-quality.md`) en el host del user + push PR desde `feature/tsk-103-4-universe-scanner` via gh pr create. TSK-103.5 (F5 wiring + Settings + 17 escenarios BDD pytest-bdd + 6 quality gates) queda desbloqueado para kickoff una vez F4 mergeado a main.

[2026-07-04 13:00] agent=context-engineer | action=kickoff TSK-103.5 (F5) wiring con Settings + 17 BDD pytest-bdd + 6 quality gates | artifacts=docs/specs/TSK-103-universe-scanner/05-tasks.md (F5 section refinada con sub-stub breakdown), tasks/backlog.md (TSK-103.5 blocked->in_progress), tasks/sprint-002.md (sub-tickets table + estado real + DoD + log entry), context/retrieval-log.md (esta entrada) | summary=Kickoff formal de TSK-103.5 una vez cumplidas las pre-condiciones: (1) TSK-099 merged en main (TSK-099 ✅ PRD merge 9eed3fd); (2) TSK-101 + TSK-102 merged via PR#12 + PR#13; (3) ADR-0012 gate-recovery merged via PR#14; (4) F4 (TSK-103.4) done + ADR-0013 firmada en retrieval-log `[11:00]`. Cadena sub-ticket documentada en `05-tasks.md` F5 section con stub counts: `.1(8 stubs)=Fixture wiring Settings real via conftest.py + _build_settings helper + Settings(paper/research) fixtures + mode parametrize + smoke pytest 30+ tests` -> `.2(7 stubs)=23 BDD scenarios pytest-bdd glue + step_defs split en 7 step modules cubriendo RF-1..RF-10 + CL-1/CL-3/CL-6 + smoke pytest-bdd 23/23` -> `.3(3 stubs)=ADR-0013 verification loop (ya firmada; sync grep + D1-a alignment + cross-layer AST)` -> `.4(6 stubs)=tasks/backlog.md TSK-103.5 entry + TSK-099/100/103 sub-tables + TSK-104 depende de F5 merge` -> `.5(5 stubs)=tasks/sprint-002.md tabla + estado real + log entry + DoD con 6 gates + Riesgos especificos F5` -> `.6(1 stub)=retrieval-log esta entrada` -> `.7(6 stubs)=6 quality gates verdes per docs/ci.md sec 3: ruff check + ruff format + mypy strict + pytest --cov-fail-under=90 + safety + pip-audit --ignore-vuln PYSEC-2026-597 (ADR-0012 firmado)`. Total ~36 stubs end-to-end. Pre-merge requerira patch CODEOWNERS para `/src/trading_bot/scanner/` + dual-review pineado (Block P2-Dual del prior turn); sin este patch el PR F5 cae en single-review via `@Extr3sao/maintainers` fallback. Pendiente kickoff host: ejecutar Block G0..G7 del runbook F5 (Block G7 son los 6 quality gates en orden: ruff check, ruff format, mypy, pytest --cov-fail-under=90, safety, pip-audit).
```
