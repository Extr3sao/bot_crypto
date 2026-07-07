# Decisions (ADR)

> Log append-only de decisiones arquitectonicas y excepciones firmadas.
> Cada ADR tiene: contexto, opciones, decision, consecuencias.

---

## ADR-0001 - Licencia del proyecto

- **Estado**: Decidido.
- **Contexto**: el repositorio necesita una licencia de codigo abierta
  o propietario.
- **Opciones**:
  - MIT.
  - Apache-2.0.
  - Licencia propietaria.
- **Decision**: Licencia propietaria / uso interno privado.
- **Razon**: el proyecto es un bot de trading automatico y debe mantenerse
  privado hasta validar seguridad, riesgos, arquitectura y cumplimiento.
- **Consecuencias**:
  - impacto legal y de adopcion externa.
  - no se permite distribucion externa ni publicacion open source sin un nuevo ADR.

## ADR-0002 - Gestor de dependencias

- **Estado**: Decidido.
- **Contexto**: hay que decidir entre `pip + venv`, `poetry`, `uv`,
  o `pdm`.
- **Opciones**:
  - `pip + venv`: simple, estandar.
  - `poetry`: lockfile robusto, ya extendido.
  - `uv`: rapido, moderno, compatible con `pyproject.toml`.
- **Decision**: usar `uv` como gestor de dependencias.
- **Razon**: es rapido, moderno, compatible con `pyproject.toml` y permite lockfile reproducible.
- **Consecuencias**:
  - afecta onboarding, CI y velocidad de resolucion.
  - el onboarding y CI deben documentar comandos con `uv`.

## ADR-0003 - Dashboard

- **Estado**: Decidido.
- **Contexto**: si se implementa un dashboard web y cuando.
- **Opciones**:
  - Grafana + Prometheus en Fase 8.
  - Streamlit como dashboard rapido.
  - CLI avanzadas con `rich` + exportar CSVs.
- **Decision**: pendiente, no antes de Fase 8.
- **Consecuencias**: requiere infraestructura y mantenimiento.

## ADR-0004 - Telemetria

- **Estado**: Decidido.
- **Contexto**: Prometheus, OpenTelemetry o ninguno.
- **Opciones**:
  - Prometheus + Grafana.
  - OpenTelemetry -> backend externo.
  - Logs JSON como unica fuente.
- **Decision**: usar logs JSON estructurados como fuente inicial de observabilidad. Prometheus + Grafana queda reservado para Fase 8.
- **Razon**: reduce complejidad operacional en fases tempranas.
- **Consecuencias**: todos los eventos importantes deben registrarse como logs estructurados.

## ADR-0005 - Persistencia (DAL/ORM)

- **Estado**: Decidido.
- **Contexto**: SQLAlchemy, `sqlite3` directo, Tortoise u ORM ligero.
- **Opciones**:
  - `SQLAlchemy 2.x` con `aiosqlite` opcional.
  - `sqlite3` directo en primera iteracion.
- **Decision**: usar `sqlite3` directo para Fase 6/Fase 7, especialmente backtesting y paper trading. Revisar migracion a SQLAlchemy antes de Fase 9 (live) si se requiere concurrencia/async.
- **Razon**: reduce dependencias y permite avanzar rapido con persistencia local, alineado con el principio de no anadir complejidad prematuramente.
- **Consecuencias**: si se requiere concurrencia, async, multiusuario o live trading robusto, se abrira nuevo ADR para migrar a SQLAlchemy/PostgreSQL.

## ADR-0006 - Exchange y modo iniciales

- **Estado**: Decidido. Revisable via nuevo ADR que lo reemplace.
- **Contexto**: que exchange y modo por defecto.
- **Decision**: **Binance via CCXT**, modo `paper`, sandbox `true`.
- **Razones**: liquidez alta, documentacion abundante, testnet publico.
- **Consecuencias**: cualquier exchange nuevo requiere ADR.
- **Revision**: si se decide cambiar, abrir ADR-0008 con la nueva decision; este ADR se mantiene para trazabilidad pero queda marcado como superseded.

## ADR-0007 - Politica de no overfitting

- **Estado**: Decidido.
- **Contexto**: como se evita promover una estrategia sobreajustada.
- **Decision**: walk-forward obligatorio + `min_trades_for_promotion`.
- **Consecuencias**: cualquier estrategia que no supere la promocion por N trades sigue en `research`.

## ADR-0009 - Hosting y repositorio remoto

- **Estado**: Decidido.
- **Contexto**: el repositorio necesita hosting versionado con CI/CD y
  control de acceso coherente con ADR-0001 (licencia propietaria).
- **Opciones**:
  - GitHub (publico).
  - GitHub (privado).
  - GitLab self-hosted.
  - Sin remoto (local unicamente).
- **Decision**:
  - **GitHub** como hosting del repositorio.
  - Repositorio **estrictamente privado**.
  - Protocolo **HTTPS** para `fetch` / `push`.
  - Rama principal **`main`** desde el inicio.
  - Remoto inicial: `https://github.com/Extr3sao/bot_crypto.git`.
- **Razon**: GitHub Actions cubre el CI/CD del baseline (TSK-008) sin coste y se integra con la mayoria de herramientas.
- **Consecuencias**:
  - no se inyectan secrets de GitHub Actions para claves de exchange hasta que se requiera CI real con testnet.
  - el CI inicial solo ejecuta chequeos estaticos y tests locales.
  - cualquier migracion a GitLab u otro hosting requiere un ADR que reemplace este.
- **Nota sobre numeracion**: `ADR-0008` se reservo como forward-reference en ADR-0006 para una posible sustitucion del exchange. Esta ADR-0009 asume hosting sin colisionar con esa reserva.

---

## ADR-0010 - Alias de variables planas -> rutas anidadas en Settings

- **Estado**: Decidido.
- **Contexto**: el cargador de `Settings` usa `env_nested_delimiter="__"` para soportar overrides profundos, pero la documentacion publica y operativa usa nombres planos como `TRADING_MODE`, `LIVE_TRADING_ENABLED`, `I_UNDERSTAND_THE_RISKS`, `EXCHANGE_ID` o `LOG_LEVEL`.
- **Problema**: sin intervencion, los nombres planos se ignoran silenciosamente y `load_settings()` devuelve los defaults del YAML. Esto es especialmente peligroso en los release gates de live trading.
- **Opciones**:
  - eliminar `env_nested_delimiter="__"`;
  - renombrar toda la documentacion y compose a la forma anidada;
  - **introducir un `FlatEnvAliasSource`** que remapee un conjunto estable de nombres planos a sus rutas anidadas.
- **Decision**: opcion 3. Implementada en `src/trading_bot/config/settings.py` mediante `FLAT_ENV_ALIASES` y `FlatEnvAliasSource`.
- **Mantenimiento**:
  - cualquier nuevo nombre plano agregado a `.env.example`, `docker-compose.yml`, `docs/live-trading-checklist.md` o `bdd/features/*.feature` debe aparecer tambien en `FLAT_ENV_ALIASES`;
  - los nombres anidados siguen siendo la fuente canonica para automation, fixtures y tests;
  - retirar `env_nested_delimiter="__"` requiere ADR de reemplazo.
- **Consecuencias**:
  - `FLAT_ENV_ALIASES` es un single point of failure para la doc publica;
  - el coste de carga es despreciable;
  - el contrato plano -> anidado queda como decision visible y buscable.

---

## ADR-0011 - Cierre de sprint-001 con excepcion y apertura de sprint-002

- **Estado**: Decidido.
- **Contexto**: `TSK-099` quedo cerrado y mergeado en `main`, pero el baseline de CI (`TSK-008`) no entro en el mismo merge.
- **Problema**: mantener `sprint-001` abierto mezclaba un hito ya consolidado con trabajo activo todavia local.
- **Opciones**:
  - mantener `sprint-001` abierto hasta cerrar tambien `TSK-008`;
  - reescribir retrospectivamente el alcance para fingir que ambos tickets quedaron terminados;
  - **cerrar `sprint-001` con excepcion firmada**: `TSK-099` queda como entrega consolidada y `TSK-008` se arrastra a `sprint-002` como prioridad 1.
- **Decision**: opcion 3. `sprint-001` se considera cerrado por hito alcanzado (`TSK-099`), y `sprint-002` se abre con foco en `TSK-008`, `TSK-009` y la ingesta Fase 1.
- **Consecuencias**:
  - `TSK-099` queda trazado como `done` y mergeado en `main`.
  - `TSK-008` pasa a `in_progress` en `sprint-002`.
  - los tickets de market data dejan de figurar como deuda de `sprint-001` y pasan a plan activo o backlog de `sprint-002`.
  - la documentacion de sprint/backlog/roadmap debe distinguir entre estado mergeado en `main` y trabajo local pendiente de PR.

## ADR-0012 - Recover de quality gates post-TSK-102 (numpy stub, coverage app.py, pip-audit nltk)

- **Estado**: Decidido.
- **Contexto**: tras merge de TSK-102 el user ejecuto los 6 quality gates per
  `docs/ci.md` seccion 3 en `.venv` local y obtuvo 4 rojos:
  (R1) mypy strict por stub de numpy con sintaxis 3.12+ en `.venv` 3.11,
  (R2) pytest con `--cov-fail-under=90` en 88.79 por ciento por `app.py` 0%,
  (R3) pip-audit con `nltk 3.9.4 PYSEC-2026-597` como dep transitiva de dev-tools,
  (R4) ruff format + ruff check con lints menores de estilo.
  Los 2 funcion-fixes de TSK-102 (P1 contrato OHLCV, P2 path absoluto Windows)
  estaban validados por el pre-flight de las suites afectadas; los rojos son
  higiene/entorno del repo, no defectos del ticket.
- **Opciones para R1 (mypy vs numpy)**:
  - override `numpy.*` con `ignore_missing_imports = true`: insuficiente
    porque mypy parsea `numpy/__init__.pyi` aunque ignore missing imports en
    nuestro codigo.
  - subir `python_version = "3.12"`: contradice la decision del user de
    quedarse en 3.11 hasta tener toolchain estable.
  - **pinear `numpy>=1.26.0,<2.1`** y dejar que uv resuelva a una version
    con stubs pre-3.12 (`numpy 1.26/2.0.x`). Causa raiz.
- **Opciones para R2 (coverage app.py)**:
  - escribir `test_app.py` con smoke tests de los 4 subcommands stubs.
  - marcar `print("[stub] ...")` con `# pragma: no cover`.
  - **omitir `src/trading_bot/app.py` en `[tool.coverage.run].omit`** hasta
    que la logica real llegue en Fase 1+ (precedente: `__main__.py`
    ya estaba omit). Se quita del omit en el sprint que introduzca
    comandos reales.
- **Opciones para R3 (pip-audit nltk)**:
  - investigar culprit transitive y pinear a version que no requiera nltk.
  - pinear `nltk>=X.Y.Z` con override-uv y rezar por version segura.
  - **ADR firmada + `pip-audit --ignore-vuln PYSEC-2026-597`** tratandolo
    como falso positivo en `dev-only` (nltk no se usa en runtime del bot).
- **Decision**:
  - R1: pinear `numpy>=1.26.0,<2.1` en `pyproject.toml [project.dependencies]`.
  - R2: omitir `src/trading_bot/app.py` en `[tool.coverage.run].omit`.
  - R3: ADR firmada + flag `pip-audit --ignore-vuln PYSEC-2026-597` en
    `validate_local.ps1` y job `pip-audit` de `.github/workflows/ci.yml`.
    Action item: cuando se identifique la transitive culprit (parent dev-tool),
    abrir ADR de sustitucion.
- **Consecuencias**:
  - `numpy` queda pineado hasta que Python 3.14 sea baseline oficial;
    rama 3.11 sigue verde en mypy strict.
  - `coverage` del repo no refleja `app.py` hasta Fase 1+; ADR obliga a
    quitar del omit cuando llegue logica real.
  - `nltk` queda como riesgo firmado; debe revisarse en cada sprint review.
    Cualquier introduccion de nltk en runtime es violation de este ADR.
  - ruff format/check siguen siendo auto-fixables via `ruff format .` + `ruff check --fix .`
    localmente antes de cada PR.

---

## ADR-0013 - Reconciliacion de scope TSK-103: TSK-102 absorbe persistencia OHLCV, TSK-103 aisla dominio scanner

- **Estado**: Decidido.
- **Contexto**: el backlog original de TSK-103 definia el scope como `persistencia funcional de OHLCV` ademas del scanner; durante sprint-002, TSK-102 (PR#13 mergeado en main) implemento `OHLCVStore` SQLite con PRAGMA user_version v1 + WAL + upsert last-write-wins + cross-platform path detection. La intencion original de TSK-103 quedo absorbida por minimo churn (Decision D1-a del spec `docs/specs/TSK-103-universe-scanner/04-plan.md`). El spec pack documenta la reconciliacion pero sin firma humana previa en `tasks/decisions.md`; esto pinea el pendiente ADR-0013 en retrieval-log entradas `[06:00]` y `[07:00]` y bloquea `TSK-103.5` como prerequisito de merge per `04-plan.md` Pre-condicion #3 + F5 TSK-103.5.3.
- **Opciones**:
  1. TSK-103 ignora TSK-102 e implementa su propio storage paralelo (duplicaria `OHLCVStore` y la politica WAL/upsert; sin valor anadido, riesgo de divergencia entre stores).
  2. TSK-103 absorbe retroactivamente el codigo de TSK-102 (romperia la separacion de concerns ya lograda + ensucia el scope scanner con dependencias directas de sqlite3).
  3. **dividir por minimo churn**: TSK-102 monopoliza la persistencia OHLCV como fuente canonica; TSK-103 (F1-F5) opera strictly in-memory sobre `MarketDataSourceProtocol` abstracto (Decision D2 del spec `03-specify.md` seccion 3).
- **Decision**: opcion 3. La frontera queda pinada por:
  - `OHLCVStore` (`src/trading_bot/storage/`) es la unica puerta hacia SQLite en runtime.
  - `UniverseScanner` (TSK-103.4) y filtros (TSK-103.2) NO importan `sqlite3` ni modulos directos de `storage.*`; solo consumen `MarketDataSourceProtocol` (`src/trading_bot/scanner/protocols.py`) que abstrae `OHLCVFetcher + OHLCVStore`.
  - Cross-layer enforcement via `tests/unit/scanner/test_cross_layer.py` (TSK-103.4.9) parsea AST y falla el gate si scanner importa `storage.*` directo (extension de las capas ya prohibidas: `execution`, `strategies`, `risk`, `portfolio`, `paper`, `observability`, `indicators`, ahora `storage`).
- **Razon**: la politica ADRs pineada en `.ai/methodology-hybrid.md` exige firma humana para cualquier scope shift del roadmap. Esta ADR formaliza el reparto sin reintroducir complejidad; el spec pack (`03-specify.md` seccion 3 + `04-plan.md` F5) y los 99+ tests verde de Fase 1 ya validan la frontera en cobertura. Cualquier regresion futura (e.g. un dev reintroduciendo `import sqlite3` dentro de `scanner/`) rompe el test cross-layer y la incursion queda visible en code review.
- **Consecuencias**:
  - TSK-103 puede validarse offline via `FakeMarketDataSource` sin red ni testnet (cubierto por 27 sentinels de F2 + 9 sentinels + 3 property tests hypothesis de F3 + el AST cross-layer test de F4.9).
  - Las sub-decisiones internas de F1-F3 (D1-A VolumeFilter mode-in-constructor, D3 `MarketSnapshot` frozen+slots, D4-`B` `FilterRegistry` freeze opt-in, D5 `rank_score` se computa per-snapshot sin reordering (ordenamiento delegado a la capa estrategias en Fase 4), formulacion cerrada ADR-locked del `compute_rank_score` en spec seccion 6) quedan documentadas en `03-specify.md` sin requerir ADRs separados: son diseno interno al scope del scanner pinado por tests + coverage gate + cross-layer test.
  - TSK-103.5 (wiring con `Settings` real + 17 escenarios BDD pytest-bdd + 6 quality gates) queda desbloqueado como prerequisito de merge: ADR firmada cierra el pendiente `[06:00]` del retrieval-log.
  - Live-trading (Fase 9 per `docs/roadmap.md`) sigue requiriendo su propio ADR futuro; esta ADR no acelera Fase 9 ni introduce dependencias de TSK-103 sobre el connector real.
  -  Cualquier inversion futura del scope (e.g. subsumir `OHLCVStore` dentro de `UniverseScanner` como `single source of truth`) requiere ADR de reemplazo firmada por el responsable de Fase 9 o ticket posterior; esta ADR queda trazable para auditoria.

---

## ADR-0016 - Baseline Health Remediation (mypy + pytest pre-existentes en main)

- **Estado**: Decidido.
- **Contexto**: verificacion via `git checkout main @ 2774021` + `uv run mypy src/trading_bot/` + `uv run pytest` revela **10 issues pre-existentes** (no introducidos por PRs recientes en `main`):
  - **8 mypy errors** (gate `-p` strict):
    - `src/trading_bot/market_data/exchange_connector.py:280` `[no-any-return]` retorna `Any` declarado `list[list[float]]`
    - `src/trading_bot/market_data/exchange_connector.py:316/343/366/414` `[no-any-return]` retornan `Any` declarado `dict[str, Any]`
    - `src/trading_bot/scanner/scanner.py:323` `[no-untyped-def]` parametros sin anotacion
    - `src/trading_bot/scanner/scanner.py:357` `[attr-defined]` `"object" has no attribute "freeze"`
    - `src/trading_bot/scanner/scanner.py:365` `[arg-type]` `_ModeRegistryBundle` espera `FilterRegistry` mypy ve `object`
  - **2 pytest FAILED** (assertion-time):
    - `tests/unit/config/test_failfast.py::test_settings_rejects_live_with_kill_switch_off` configura `mode=live + live_trading_enabled=true + i_understand_true + kill_switch_enabled=false` y NO raises `ValidationError`; `_check_cross_domain_live_invariants` no frena.
    - `tests/unit/scanner/test_universe_scanner.py::test_caching_source_avoids_double_fetch` `volume=100.0` vs `min_volume_usdt=1000` → `VolumeFilter` fail → F4 short-circuit corto-circuita antes de `fetch_spread_bps`/`fetch_recent`; counters muestran 0 calls; el test asume que todas las fetches corren.
  - **2 pytest ERROR** (setup-time):
    - `tests/unit/market_data/test_ccxt_connector.py::test_read_methods_retries_then_reraise[fetch_ohlcv-args0]`
    - `tests/unit/market_data/test_ccxt_connector.py::test_read_methods_retries_then_reraise[fetch_balance-args1]`
    - Diagnostico per thinker: parametrize `args` identifier collision con pytest convention.
- **Opciones**:
  - 1 PR unico "main baseline health" (10 fixes en un solo commit) — coverage CI failure se rechaza al primer pase, alto blast radius.
  - 5 PRs atómicos separados por ticket (TSK-013.5..013.9) — cherry-pick safe independientes, review chain simple, rollback granular.
  - Firmar ADR-0016 sin PR — no resuelve; gate sigue rojo, deuda documentada pero no fix-forwarded.
- **Decision**: opcion **2**. 5 tickets atomicos en `tasks/backlog.md` seccion "Baseline Health & Risk" con numeracion TSK-013.5..013.9:
  - **TSK-013.5**: Pri 1, money-risk. Restore cross-domain live fail-fast validator.
  - **TSK-013.6**: Pri 2, connector hardening. 5 mypy `no-any-return` via `cast()` narrowing (preferido) o `# type: ignore[no-any-return]` ADR-firmado sola donde el `cast()` es invasive.
  - **TSK-013.7**: Pri 3, scanner typing. 3 mypy errors en `_ModeRegistryBundle.__init__`.
  - **TSK-013.8**: Pri 4, QA. Test mock fix (no codigo de produccion).
  - **TSK-013.9**: Pri 5, test setup. Parametrize identifier rename `args` → `method_args`.
  El method ADR-firmado es **`cast()` preferida** sobre `# type: ignore` salvo justificación técnica en code review (e.g. CCXT v4 internal typing sin stub exportado).
- **Razon**: money-risk primero per `docs/risk-policy.md` (TSK-013.5 — runtime validation breach permite LIVE sin kill switch). Cherry-pick safe (independientes). Documenta el method (DSO — Domain-Specific Override) para futuros tickets similares. Anti-pattern evitada: *un PR grande acumula risk*; *ADR sin accion no resuelve*.
- **Consecuencias**:
  - 5 PRs atomicos seran abiertos contra `main`. Cada uno aislado para blame + rollback.
  - Post-fix: 8 mypy errors cerrados (TSK-013.6 + TSK-013.7); 4 pytest issues cerrados (TSK-013.5 + TSK-013.8 + TSK-013.9).
  - Cross-link con ADRs existentes: **ADR-0012** (gate-recovery precedent — numpy<2.1 + coverage.run omit + pip-audit --ignore-vuln), **ADR-0010** (flat-env alias context para TSK-013.5), **ADR-0013** (cross-layer enforcement context para TSK-013.7 + TSK-013.8).
  - Tickets no son gate-blocker para TSK-013.4 ruff backfill (independiente scopes lint) ni para TSK-104 scheduler work (independiente scopes OHLCV).
  - El use de `cast()` y la justificacion de cualquier `# type: ignore` quedan documentadas en el cuerpo de cada PR (inline comment). Si un upstream CCXT cambia signature y el `cast()` queda stale, reabri este ADR.
  - **Riesgo residual**: si el reviewer chain rechaza un PR individual, los demas pueden merge independientemente. Senate-style review no es necesario (no son cambios atomicos entre si).

## ADR-0014 - F5 closure (TSK-103.5 merge review)

- **Estado**: Pendiente (se firma solo si scope changes emerged durante F5 review chain o dual-team discussion).
- **Contexto**: PR F5 squash-mergeado a `main` con tag `v0.5.0-rc.1` y dual-team approval. Review post-merge observada para detectar scope drift, scope expansion o sub-ticket creation inesperada.
- **Scope changes detectados**: PENDING_F5_MERGE_REVIEW. Si el merge fue limpio, esta ADR queda como stub con `<NO_SCOPE_CHANGES>` placeholder.
- **Decision**: PENDING_F5_MERGE_REVIEW. Si limpio: se descarta el stub y se anota en retrieval-log; si hubo scope changes: se documenta la decision especifica + consecuencias + cross-link al nuevo TSK-103.6 si surge follow-up work.
- **Consecuencias**: PENDING_F5_MERGE_REVIEW. Posibles follow-ups:
  - nuevo sub-ticket TSK-103.6 si la review chain solicito scope expansion;
  - patch retroactivo a docs si emerged nueva informacion arquitectonica;
  - actualizacion del spec pack `docs/specs/TSK-103-universe-scanner/` si la review chain pinto drift con spec §10 pine contract.

---

## Excepciones firmadas

> Aqui se documentan desviaciones del flujo SDD o del release gate.
> Sin entrada aqui = la desviacion no existio.

```
ADR-XXXX | fecha | contexto | desviacion | mitigacion | firmas
```

ADR-0011 | 2026-07-03 | cierre de sprint-001 | sprint cerrado sin `TSK-008` mergeado | arrastre explicito de `TSK-008` a sprint-002 como Pri 1 y actualizacion documental | context-engineer + usuario

ADR-0012 | 2026-07-04 | gate-recovery post-TSK-102 | mypy numpy stub 3.12+ en 3.11 + coverage 88.79<90 por app.py 0% + pip-audit nltk 3.9.4 PYSEC-2026-597 transitiva | (a) numpy>=1.26.0,<2.1 en pyproject; (b) app.py omit en coverage.run; (c) --ignore-vuln PYSEC-2026-597 firmado en validate_local.ps1 + ci.yml | context-engineer + usuario

ADR-0013 | 2026-07-04 | TSK-103 reconcile scope | ADR-0013 pendiente pineada en retrieval-log `[06:00]` como pre-condicion de merge de TSK-103.5 | split TSK-102 persiste OHLCV + TSK-103 scanner in-memory via MarketDataSourceProtocol + cross-layer enforcement via AST pine contract scanner no importa `storage.*` directo | context-engineer + usuario


## ADR-0012 — Cierre de sprint-002 + Apertura de sprint-003 (firmada 2026-07-05)

**Estado**: firmada y aplicada (PR #3 sqsh-merged a `main` + este commit de docs de cierre).

**Contexto**: sprint-002 arranca tras ADR-0011 (cierre sprint-001) con 7 tickets en scope.
Tras PR #2 (TSK-008 + TSK-009 + TSK-103.5 BDD wiring) y PR #3 (TSK-104 F1+F2) sprint-002 llega a su fin.

**Tickets cerrados (sprint-002)**: ver `tasks/sprint-002-closure-evidence.md` (referencia primaria) para la tabla completa con notas de cierre. Sumario: TSK-008 + TSK-009 + TSK-101 + TSK-103.5 + TSK-110 + TSK-104 = 6 cerrados.

**Excepciones firmadas** (heredadas de ADR-0011, ratificadas):

| Excepcion                                                          | Mitigacion                                                              |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| TSK-103 (universe scanner core, pre-F5 wiring)                     | scheduled for sprint-003 dentro de TSK-104 F3a scope (reportes per fold) |
| Adapter `OHLCVStoreSource` (storage -> `OHLCVSourceProtocol`)      | scheduled for sprint-003 con prioridad 2 (TSK-104 F3b blocker Check 1)  |

**Sprint-003 apertura** (RE-SPLIT de TSK-104 F3 segun reviewer del cierre sprint-002):

- **Primary**: TSK-104 F3a (multi-symbol + reports). **DoD**: (1) `BacktestEngine.run` acepta `List[str]` de symbols; (2) `src/trading_bot/backtesting/reports.py::build_fold_report(result) -> FoldReport` con Sharpe/Calmar/Sortino/CAGR/max_drawdown/expectancy/win_rate/profit_factor per-fold; (3) tests unitarios verde (analysis-only, no toca folds); (4) coverage >= 90% sobre el nuevo reports module.
- **Secondary**: TSK-104 F3b (walk-forward + cross-fold reports). **DoD**: (1) `walk_forward_splits: list[tuple[datetime, datetime, datetime, datetime]]` field en `BacktestInputs` con strict invariant `train_end <= test_start` + no-overlapping entre folds; (2) `walk_forward_run(input, splits) -> list[BacktestResult]` con data-leakage checker (assert que el primer fold's end < el segundo fold's start en el test engine); (3) Hypothesis property tests para no-leak invariant. Bloqueado por storage adapter (Check 1: `OHLCVStoreSource` no en scope todavia, no-fatal para F3b POC).
- **Tertiary**: TSK-103 (universe scanner core front-end).
- **Tertiary**: Storage adapter `OHLCVStoreSource`.

**Out of scope (F4+)**: TSK-105 paper trading prep, TSK-106 risk gate integration, TSK-107 execution idempotencia, TSK-108 observability stack (structlog -> Sentry bridge), TSK-109 strategy catalog beyond BacktestEngine.

**Razon**: PR #3 cierra F1+F2 de TSK-104 con cobertura 97.69% y pine contract explicito (Units section en `engine._compute_metrics` + `Metrics TypedDict`). ADR firmada previene el lifecycle gap de sprints previos. **F3a/F3b split** reduce blast radius: walk-forward tiene data-leakage risk si folds se eligen naive; aislarlo en F3b permite F3a cerrar primero (multi-symbol + reports basicos) sin bloquear el camino si F3b se atrasa.

**Consecuencias**:

- Branch `origin/feature/tsk-104-backtest-engine` borrada.
- Cobertura `src/trading_bot/backtesting/` pineada a 97.69% (gate 90%).
- 64 tests verdes cierran regression risk para F3a.
- Sprint-003 con 4 tickets bien priorizados vs sprint-002 con 7 (overhead reducido).

**Co-authored-by**: context-engineer
