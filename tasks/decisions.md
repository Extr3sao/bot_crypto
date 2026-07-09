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


## ADR-0015 - Cierre de sprint-002 + Apertura de sprint-003 (firmada 2026-07-05)

> **Nota de renumeracion (2026-07-05)**: este bloque estaba
> originalmente etiquetado como `ADR-0012` (mismo ID que ya
> documentaba gate-recovery post-TSK-102 arriba), creando una
> colision. Se renumera a **ADR-0015** (la siguiente libre
> despues de ADR-0014 F5 closure pendiente) para evitar la
> duplicacion. La verdadera **ADR-0012** (gate-recovery) queda
> arriba de este bloque, intacta.
>
> **Trazabilidad historica**: el bloque bajo el ID antiguo
> `ADR-0012` (ahora colapsado a `ADR-0015` per esta firma
> 2026-07-05) esta presente en commits previos de
> `tasks/decisions.md`. Grep `ADR-0012 cierre sprint-002` en
> `git log -- tasks/decisions.md` senala donde existio el ID
> antiguo antes del rename; el cuerpo de esa entrada previa
> referenciaba un PR distinto (`PR #3 (TSK-104 F1+F2)`) y un
> scope distinto (`TSK-104 = backtest engine`), ambos
> descartados al reconciliar con el ledger actualizado.
>
> **Ademas**: el cuerpo original de este bloque referenciaba `PR #3 (TSK-104 F1+F2 = backtest engine)` que **NO corresponde** al estado real del worktree al cierre de sprint-002 (el scope actual de `TSK-104` es **OHLCV Scheduler**, no backtest engine, per `tasks/sprint-002.md` y `tasks/sprint-003.md`). Se reescribe el cuerpo para reflejar la realidad per el ledger actualizado en `tasks/sprint-002.md` y `tasks/sprint-003.md`.

- **Estado**: Decidido y aplicado. Firmada 2026-07-05 tras merge del **PR #2** (commit `da0424a`).

- **Contexto**: sprint-002 arranca tras ADR-0011 (cierre sprint-001) con 7 tickets en scope (`TSK-008`, `TSK-009`, `TSK-101`, `TSK-102`, `TSK-103`, `TSK-104`, `TSK-105`) + 1 secondary (`TSK-110`). Las milestones de Fase 1 ingesta culminan antes del cierre: `TSK-099` (prereq) + `TSK-101` (PR#12) + `TSK-102` (PR#13) + `TSK-103.4` (F4 orquestador) + `TSK-103.5` (F5 wiring + 17 BDD + ADR-0013) mergeados en `main`. La governance arrastre (`TSK-008` desde sprint-001 + `TSK-009`) cierra via **PR #2** (commit `da0424a`) en un solo PR.

- **PR #2 scope detallado**: `.github/workflows/ci.yml` (4 jobs `format-and-lint` + `type-check` + `pip-audit` + `tests-and-coverage`, cuyas keys matchean exactamente los status-checks required en `quality/release-gates.md` Bloque 6) + `.python-version = 3.11` (single line) + `pyproject.toml` hunks (mypy `python_version = 3.11`, coverage `fail_under = 90`) + `.github/CODEOWNERS` (9-agent mapping con dual-review paths sensibles: `config`, `risk`, `execution`, `secrets`, `workflows`) + `.github/PULL_REQUEST_TEMPLATE.md` (5 bloques con collapsibles `<details>` en los checklists por tipo de cambio, round-3 fix) + branch-protection admin rules en `quality/release-gates.md` Bloque 6 (con `required_status_checks` + `required_pull_request_reviews` dual-review + commands `gh api` JSON inline PowerShell + bash con `--delete-branch` post-squash-merge).

- **Opciones consideradas para el cierre sprint-002**:
  - mantener sprint-002 abierto hasta cerrar todos los TSK-1xx
    restantes (`TSK-104` OHLCV Scheduler + `TSK-105` paper trading
    harness) — descarte: el scaffolding `tasks/sprint-003.md` ya
    existe con scope pre-definido y la governance arrastre no
    requiere esperar a los TSK-1xx para ser marcada como done.
  - cerrar sprint-002 via nueva ADR y abrir sprint-003
    (recomendado): retrocompatible con el scaffold pre-existente
    y permite cerrar la governance arrastre limpia.

- **Decision**: opcion 2. sprint-002 cerrado via **ADR-0015**;
  las 3 exit criteria cumplen: (1) `TSK-008` cerrado ✅ PR #2, (2)
  al menos uno de `TSK-101..103` cerrado y mergeado ✅ (los 4:
  `TSK-101` PR#12, `TSK-102` PR#13, `TSK-103.4` F4, `TSK-103.5`
  F5 wiring), (3) `TSK-009` cerrado ✅ PR #2. Backlog.md flips
  aplicados: `TSK-008` + `TSK-009` → `done` + `TSK-110` → `done`
  (absorbed por TSK-103.5 close).

- **Sprint-003 apertura continuidad**: las 3 tickets que dependian
  de TSK-101..103 (TSK-104, TSK-105, TSK-110) ahora quedan
  **formalmente unblocked** per esta ADR. `TSK-110` ashbeen
  absorbed por TSK-103.5 close y queda removido del scope sprint-003
  (ya esta `done` en `tasks/backlog.md`).

  - **Primary bloque gouvernance ya cerrado**: `TSK-008` ✅ `TSK-009` ✅ via PR #2 (ya done, columna `Pri` ajustada a `-`).
  - **Primary actual sprint-003**: `TSK-104` F3a (OHLCVScheduler orchestrator con DI + `_execute_iteration` + per-pair loop + reentrancy guard) + F3b (jitter+Retry-After retries + run loop + 7 structlog events + connector_reinjector + cross-layer AST). Branch reconciliation operativa: `feature/tsk-104-scheduler-spec` arranca divergido (2 vs 1 commits vs origin) + 17 dirty files que mezclan F2 work + F1 market_data + unrelated. Operative tactic (no ADR firmada — operational only, no architectural change): cherry-pick F1+F2 a fresh branch `feature/tsk-104-f3a-implementation` desde `main`, drop divergencia, implement F3a stub, abrir PR con dual-review per `quality/code-quality.md`. Cualquier decision arquitectonica que emerja (e.g. concurrencia pineada vs ADR-0014) requiere nueva ADR.
  - **Secondary**: `TSK-105` paper trading harness (reporter PineStructlog-based, retention TTL). DoD per `docs/paper-trading-methodology.md`.
  - **Hygiene backfill (Pri 1 ahora que TSK-008/009 done)**: `TSK-013.4` ruff format + ruff check cleanup sobre `main` (deferred del sweep TSK-013.3 cierre round-1 code-reviewer).
  - **Tertiary**: `TSK-100` (storage layer carry, low priority — `OHLCVStore` minimal ya cubre Fase 1).
  - **Fase 2 indicators arranca con `TSK-200`** (interface + registro) — `TSK-201..204` quedan bloqueados hasta `TSK-200` cerrado.

- **Out of scope sprint-003**: `TSK-101..103` (ya mergeados en main a cierre sprint-002); `TSK-110` (ya absorbed y done); `TSK-103.6` placeholder (solo se materializa si ADR-0014 detecta scope changes en F5 review chain).

- **Excepciones ratificadas al cierre** (ya vigentes de sprints previos):
  - **ADR-0011** (sprint-001 cierre con TSK-008 arrastre) — **consumada** por esta ADR-0015.
  - **ADR-0012** (gate-recovery post-TSK-102: numpy<2.1 + app.py omit + `--ignore-vuln PYSEC-2026-597` firmado) — **vigente sin cambios**.
  - **ADR-0013** (scope reconcile TSK-103: TSK-102 absorbe persistencia OHLCV + TSK-103 scanner in-memory via `MarketDataSourceProtocol` + cross-layer AST pine contract) — **vigente sin cambios**.
  - **ADR-0014** (F5 closure pendiente per sprint-003 retrieval-log) — **pendiente sin firmar** al cierre sprint-002; se firmara en el cierre sprint-003 cuando el F5 review chain + dual-team discussion confirmen no-scope-drift.

- **Consecuencias**:
  - 7/7 quality gates verdes per `docs/ci.md sec 3` (incluido Gate 7 BDD fixture injection contract per round-24..27 review chain).
  - `feature/tsk-104-scheduler-spec` mantiene scope pero requiere reconciliation pre-F3a implementation.
  - Columna `Pri` ajustada en `tasks/sprint-003.md` Foundations table: `TSK-013.4` ahora Pri 1; `TSK-008/009` done sin Pri; `TSK-104` adjustada a Pri 3; `TSK-105` Pri 4.
  - `TSK-008/009` ya no son arrastre en sprint-003 (overhead reducido: 2 governance tickets fuera del scope, 5 primary/secondary quedan).
  - Branch lifecycle: PR #2 mergeable a main; el squash-merge con `--delete-branch` borrara `feature/tsk-008-009-governance` post-merge per las branch-protection rules pineadas.

## ADR-0017 — Branch Protection `gh api` Apply Auth-Gated (TSK-008/009 follow-up)

- **Estado**: Decidido.
- **Fecha**: 2026-07-08
- **Contexto**: TSK-008 (CI baseline) y TSK-009 (CODEOWNERS + PR template + branch-protection specs) cerraron por merge de PR #2 → commit `da0424a` al cierre sprint-002 (ADR-0015). El Bloque 6 de `quality/release-gates.md` documenta la ejecución física del JSON payload de branch-protection via `gh api repos/Extr3sao/bot_crypto/branches/main/protection ...` PERO requiere permisos `admin:org` que ni los agentes locales ni el CI tienen. Consecuencia directa: el gate humano está desactivado silenciosamente si el PR se mergea sin que un admin haya aplicado primero las reglas.
- **Decision**: TSK-008 / TSK-009 permanecen formalmente cerrados. La ejecución del Bloque 6 queda como "Day 2 Operation" (auth-gated manual ops) a ser ejecutada por el owner del repo a discreción, sin re-abrir los tickets. Cualquier cambio de scope posterior debe pasar por un ADR numerado ≥ ADR-0018 o superior.
- **Consecuencias**:
  - Cierra el "ghost technical debt" (tickets siempre in_progress por falta de permisos de red): ambos tickets pueden permanecer archivados sin arrastrar el sprint-003.
  - `main` queda sin branch-protection enforced on GitHub hasta que el owner aplique Bloque 6 manualmente. Riesgo aceptable para repo en desarrollo temprano; revisar pre-promoción a live (`docs/live-trading-checklist.md`).
  - Cross-link: el código de Bloque 6 sigue en `quality/release-gates.md` con su pre-flight de teams (`gh api /orgs/Extr3sao/teams --jq '.[].slug'`); ejecutar ese comando antes del apply es obligatorio per el aviso de ERRORES SILENCIOSOS documentado en `.github/CODEOWNERS` header.
  - F5-precedent reuse: el patrón `<HANDLER_PLACEHOLDER>` que ya uso F5 (`<F5_PR_URL>`, `<F5_MERGE_DATE>`) aplica también acá: el bloque de branch-protection en sí está mergeado como código; solo falta la ejecución del API call por el actor autorizado.
- **Alternativas consideradas**:
  - (a) Mantener TSK-009 en in_progress hasta que `gh api` corra — RECHAZADO porque bloquea indefinidamente y carece de plan de resolución formal.
  - (b) Reabrir el ticket cuando un admin aplique el payload — RECHAZADO porque desdibuja la frontera entre "trabajo mergeado" y "operación post-merge", creando historial confuso.
  - (c) Firmar ADR-0017 (esta opción) — ACEPTADO porque documenta la delegación sin crear overtime y mantiene ADR-0015 como fuente única de verdad del cierre real.

## ADR-0018 - Cierre de Fase 2 Indicators (TSK-200..204) y formalización del F3 mirror contract para property tests

- **Estado**: Decidido.
- **Fecha**: 2026-07-09.
- **Contexto**: la Fase 2 (indicators) del bot de trading se ha cerrado a nivel de calidad tras la implementación completa de los 5 tickets que la componen (`TSK-200`, `TSK-201`, `TSK-202`, `TSK-203`, `TSK-204`) sobre el branch `fix/tsk-014.1-protocol-attr`. La pine contract transversal que comparten todos los property tests nuevos es el **F3 mirror contract** — `@settings(max_examples=1000, deadline=None)` — replicado desde `tests/unit/scanner/test_scoring.py` (TSK-103.3.2). Sin una ADR formal, futuros tickets de Fase 4 (strategy-engineer) o Fase 5 (execution-engineer) podrían divergir accidentalmente (e.g. usar `max_examples=100` o reintroducir un deadline), rompiendo la consistencia entre suites de property tests.
- **Alcance del cierre de Fase 2**:
  - `TSK-200`: `Indicator` Protocol relajado (atributo o propiedad) + `IndicatorRegistry` (`register/freeze/resolve_enabled`) + `IndicatorCache` (`make_key/get_or_compute`) + tipos frozen (`ConfiguredIndicator`, `IndicatorCacheKey`).
  - `TSK-201`: `EmaIndicator`, `RsiIndicator`, `MacdIndicator`, `AtrIndicator`, `BollingerBandsIndicator` (5 built-ins con prefijo `indicator_type` canonico + `_require_period` + `_require_candles`).
  - `TSK-202`: `VwapIndicator` (anchor session/rolling), `VolumeRelativeIndicator`, `SpreadIndicator` (spread_bps explicito o computado), `VolatilityIndicator` (stddev), `MomentumIndicator` (lookback percent change).
  - `TSK-203`: `OrderBookImbalanceIndicator` gated por `feature_enabled=True` (sentinel anti-LiteRunner per `config/indicators.yaml`).
  - `TSK-204`: 16 property tests hypothesis con F3 mirror contract cubriendo las 11 indicators built-in.
- **Opciones consideradas**:
  - (a) **No firmar ADR**: dejar el F3 mirror contract implícito per spec TSK-103.3.2 + sprint-003. Riesgo: futuras PRs de Fase 4/5 divergen silenciosamente.
  - (b) **Firmar ADR-0018** pineando el F3 mirror contract + documentando el cierre de Fase 2 con cross-links a TSK-200..204.
  - (c) **Reabrir TSK-103.3.2** y modificar `tests/unit/scanner/test_scoring.py` para incluir TSK-204 explícitamente. Riesgo: introduce scope drift en un ticket ya cerrado y validado.
- **Decision**: opcion (b). El F3 mirror contract queda formalizado como decision arquitectonica visible y buscable; el cierre de Fase 2 queda trazado con cross-link a cada sub-ticket.
- **Razon**:
  - El `Indicator` Protocol, `IndicatorRegistry`, `IndicatorCache` y los 11 built-in indicators son infraestructura crítica que strategy-engineer (Fase 4) y execution-engineer (Fase 5) consumiran via `IndicatorRegistry.resolve_enabled(...)`. Sin ADR de cierre, la trazabilidad "por qué el contrato se ve así" se diluye entre commits.
  - El F3 mirror contract es una decision transversal: cualquier nuevo property test (Fase 4 strategy, Fase 5 execution, Fase 7 risk) DEBE heredar el patrón o justificar desviación. Pinearlo en una ADR evita que el contrato se rompa silenciosamente.
  - Los invariantes matematicos cubiertos (no-negatividad, acotación por ventana, identidad algebraica, determinismo bit-exact, signo dominante) son pin contract verificado por los 16 property tests: cualquier regresión futura rompe pytest y queda visible en CI.
- **Consecuencias**:
  - TSK-200..204 marcados como `done` en `tasks/backlog.md` con Estado real verificable + retrieval-log cross-link.
  - **F3 mirror contract pineado**: cualquier property test futuro DEBE usar `@settings(max_examples=1000, deadline=None)` salvo justificación firmada en code review o ADR de reemplazo. El reviewer debe rechazar PRs que reintroduzcan `max_examples<1000` o `deadline=...`.
  - Strategy `ohlcv_with_ranges` (composite hypothesis) queda documentada como patron canonico para property tests que requieren OHLCV con high/low/close/volume independientes; futuros indicators o strategies que necesiten generar series sinteticas pueden reutilizarla sin reinventar.
  - Cross-link con: TSK-103.3.2 (F3 mirror origin en `scoring.py`), sprint-003 (Foundations table + DoD Criterio C), `src/trading_bot/indicators/` (implementación), `tests/unit/indicators/test_indicator_properties.py` (16 property tests verde en ~88s).
  - `Indicator` Protocol relajado (acepta atributo O propiedad) es un sub-detalle de diseño pineado por el test `test_protocol_contract.py`; cualquier futura restricción (e.g. exigir solo `@property` decorated) requiere nueva ADR.
  - `OrderBookImbalanceIndicator` feature-flagged requiere que `feature_flags.indicators.order_book_imbalance=true` este en `config/indicators.yaml` antes de que `IndicatorRegistry.resolve_enabled(...)` lo exponga; este gating es operacional, no arquitectónico, y queda documentado en `config/indicators.yaml` directamente.
  - Sin codigo nuevo: esta ADR es living documentation que formaliza el cierre de Fase 2 y la decision sobre el F3 mirror. Cualquier ticket de Fase 4+ que introduzca property tests debe cross-linkear esta ADR.
  - **Riesgo residual**: si el codebase migra a `pytest>=8.x` o `hypothesis>=7.x` y la API de `@settings` cambia, el F3 mirror contract puede romperse. Monitoreo: `uv run pytest tests/unit/indicators/test_indicator_properties.py -q` debe seguir verde tras cada upgrade de `hypothesis`.

---

## ADR-0020 - pwsh-only workflow scripts (`.ps1` a `pwsh` 7+, drop Windows PowerShell 5.1 compat)

- **Estado**: Decidido.
- **Fecha**: 2026-07-09.
- **Contexto**: los scripts de workflow `scripts/open-pr-tsk-0204.ps1` y `scripts/open-pr-tsk-104-walk-forward.ps1` arrastran preámbulos declarando compatibilidad simultánea con Windows PowerShell 5.1 y PowerShell 7+. Esa compat dual obliga a evitar patterns scope-qualified (`$scope:` falla en PS 5.1 con "La referencia de variable no es válida" — observado en los commits `7f6f42f` y `4f8ad98` con el caso concreto `$branch:`) y here-strings `@"..."@` con `$variable` interpolada (PS 5.1 falla con "Falta la cadena en el terminador: '@"). El workaround sistemático es reescribir con `-f` format-strings y/o here-strings literales `@'...'@`, lo que infla el PR-body code y abre bugs de parser silenciosos. En paralelo, `README.md` pineado en este mismo PR la nueva subsección `## 🪟 Windows hosts: prefer pwsh (PowerShell 7+) over Windows PowerShell 5.1` que recomienda `pwsh` sobre Windows PowerShell 5.1 para hosts Windows. La política está implícita en docs pero no firmada en el ledger.
- **Opciones consideradas**:
  - **(a) Mantener compat dual PS 5.1 + pwsh** (status quo): cada `.ps1` nuevo recarga los workarounds PS5.1; el reviewer debe memorizar el truco cada vez (romper here-strings en concatenación, evitar `$var:` patterns). Coste recurrente y silencioso.
  - **(b) Pivot a pwsh-only** (esta opción): nuevos `.ps1` declaran `#!/usr/bin/env pwsh` + `#requires -Version 7` y no mantienen fallback Windows PowerShell 5.1. Here-strings pueden ser `@"..."@` con interpolación libre (`$variable` directa), `-f` format-strings innecesarios. Habilita además features pwsh 7+: `??` null-coalescing, `using namespace`, `ForEach-Object -Parallel`, constructores shorthand de objeto (`[PSCustomObject]@{...}` shorthand).
  - **(c) Pitch pwsh como prereq de OS** (instalar `pwsh` a nivel SO vía bootstrap); excede scope de un ADR — sería decisión de tooling/infra de runner.
- **Decision**: opción (b). Todo `.ps1` nuevo bajo `scripts/` DEBE declarar `#!/usr/bin/env pwsh` + `#requires -Version 7` en la cabecera y NO mantener fallback Windows PowerShell 5.1.
- **Razon**: el coste de mantener PS 5.1 compat no se justifica. Windows PowerShell 5.1 está congelado desde 2017 sin features nuevas; los PR-pipeline scripts solo corren desde el host del developer o un maintainer con `pwsh` instalado; `pwsh` 7+ es el baseline de facto en hosts Windows modernos (Microsoft Store + `winget install --id Microsoft.PowerShell` + `choco install powershell-core` son first-class). Eliminar el workaround reduce PR-body code ~10-20 líneas por script nuevo, baja riesgo de bugs de parser, y deja una frontera clara (pwsh-only vs heredar compat) que puede romperse vía ADR de reemplazo.
- **Consecuencias**:
  - **Backlog cross-link**: id `TSK-013.10` (siguiente libre despues de `TSK-013.9` que cerró el parametrize rename per ADR-0016) en `tasks/backlog.md` sección "Hygiene" — scope = drop los preámbulos "Compatible con Windows PowerShell 5.1 + PowerShell 7+" de los scripts existentes + reemplazar los `-f` format-strings y here-strings literales `@'...'@` con `@"..."@` interpolados donde shrinke el código. PR atómico separado del PR `feat/tsk-0204-fase2-f3b-structlog` actual; merge tras el squash-merge de TSK-0204 para preservar trazabilidad atómica.
  - **Sprint-003 ledger sync**: `tasks/sprint-003.md` ya pineado `feat/tsk-0204-fase2-f3b-structlog` como PR-activo; esta ADR firma la política del README sin bloquear el PR.
  - **README cleanup**: la frase placeholder neutral "La formalización del pivot pwsh-only vivirá en `tasks/decisions.md` (entry pendiente de firmar)" se puede borrar en el mismo commit TSK-013.10 una vez esta entrada firme — cierra el TODO inline.
  - **Code review contract**: cualquier nuevo PR con `.ps1` que omita `#!/usr/bin/env pwsh` + `#requires -Version 7` será marcado por @context-engineer (CODEOWNERS) para revisión; consistente con el rol de context-engineer como guardian del flujo 06-implement-next.md.
  - **Reuso del rewrite previo**: el rewrite PS5.1-compatible de `scripts/open-pr-tsk-0204.ps1` (commits `7f6f42f` + `4f8ad98`) sigue siendo válido como prueba de patrón; sirve de precedente documentado en code review para futuros scripts **mientras sigan requiriendo PS5.1 compat** — tras TSK-013.10 esa carga se levanta.
- **Cross-link**: ADR-0017 (precedente — patrón `<HANDLER_PLACEHOLDER>` del mismo cleanup sprint-003: firma una política parcial cuando el actor autorizado no la ejecuta); ADR-0018 (precedente metodológico — `pine contract` transversal para policy docs).
- **Numbering note**: este ADR usa `ADR-0020`, saltando el `ADR-0019` libre del ledger. Si en el futuro surge un ticket cuya firma lógica demande específicamente `0019` (e.g. close formal del F5 pendiente en `ADR-0014`), abrir nuevo ADR-0019 retroactivo y renumerar; `ADR-0020` queda como referencia del pivot pwsh-only independientemente.

Riesgo residual: si un CI Windows self-hosted corre con Windows PowerShell 5.1 stock (e.g. Windows Server 2016 sin `pwsh` preinstalado), nuevos `.ps1` fallarán al parse del shebang `#requires -Version 7`. Mitigación: documentar prerequisite `pwsh` ≥ 7.0 en `docs/ci.md` setup section + bootstrap step en `.github/workflows/ci.yml` para runners Windows (`winget install --id Microsoft.PowerShell --accept-package-agreements` o instalador MSI previo).

