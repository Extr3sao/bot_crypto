# TSK-103 - Universe Scanner: Tasks (Command 05)

> Tareas pequenas, trazables y ejecutables una a una. Cada tarea
> cabe en un commit. Metodologia: `.ai/commands/05-tasks.md`.

Convenciones:
- `P` = prioridad dentro del ticket (1 = mas alta).
- `dep` = dependencias (`-` si ninguna).
- `DoD` = Definition of Done.

---

## TSK-103.1 - Tipos y protocolos (F1)

| ID            | Descripcion                                                | Archivos                                                                                | Tests esperados                                                            | dep | P | DoD                                                              |
| ------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | --- | - | ---------------------------------------------------------------- |
| TSK-103.1.1   | Crear paquete `scanner/` con `__init__.py` docstring-only. | `src/trading_bot/scanner/__init__.py`                                                   | `tests/unit/scanner/__init__.py` vacio                                    | -   | 1 | Import no side-effects; `python -c "import trading_bot.scanner"` exit 0. |
| TSK-103.1.2   | Dataclasses `MarketSnapshot`, `FilterOutcome` con frozen.  | `src/trading_bot/scanner/types.py`                                                      | `tests/unit/scanner/test_types.py::test_snapshot_frozen`, `...::test_outcome_frozen` | TSK-103.1.1 | 1 | mypy strict verde; `FrozenInstanceError` al mutar. |
| TSK-103.1.3   | Literal `RejectionReason` con 7 valores.                   | `src/trading_bot/scanner/types.py`                                                      | `test_types.py::test_rejection_reason_literal_values`                     | TSK-103.1.2 | 2 | `Literal["not_whitelisted", ...]` exportado en `__all__`.       |
| TSK-103.1.4   | `Protocol` `MarketDataSourceProtocol` (runtime_checkable). | `src/trading_bot/scanner/protocols.py`                                                  | `test_protocols.py::test_protocol_runtime_checkable`                      | TSK-103.1.2 | 1 | isinstance(fake, MarketDataSourceProtocol) -> True.               |
| TSK-103.1.5   | `Protocol` `Filter`.                                       | `src/trading_bot/scanner/protocols.py`                                                  | `test_protocols.py::test_filter_protocol_attr_name`                       | TSK-103.1.4 | 2 | mypy detecta implementaciones parciales como error.             |
| TSK-103.1.6   | Excepciones custom.                                        | `src/trading_bot/scanner/exceptions.py`                                                 | `test_types.py::test_exceptions_inherit_scanner_error`                    | TSK-103.1.2 | 2 | `KillSwitchActiveError` y `ConfigurationError` importables.      |

Gate de F1: `pytest tests/unit/scanner/test_types.py
tests/unit/scanner/test_protocols.py` >= 8 verde; `mypy
src/trading_bot/scanner/` exit 0.

---

## TSK-103.2 - Filtros y registry (F2)

| ID            | Descripcion                                                | Archivos                                                | Tests esperados                                                                                  | dep       | P | DoD                                                         |
| ------------- | ---------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | --------- | - | ----------------------------------------------------------- |
| TSK-103.2.1   | `FilterRegistry` con OrderedDict y registro idempotente.   | `src/trading_bot/scanner/registry.py`                   | `test_registry.py::test_register_new`, `...::test_register_duplicate_raises`, `...::test_all_order` | TSK-103.1.5 | 1 | Duplicados -> `ValueError`; orden preservado.               |
| TSK-103.2.2   | `VolumeFilter` con `min_usdt` y `live_min_usdt` opcionales. | `src/trading_bot/scanner/filters.py`                  | `test_filters.py::test_volume_filter_pass`, `...::test_volume_filter_fail`, `...::test_volume_filter_live_min` | TSK-103.2.1 | 1 | live_min endurece el umbral; motivo `volume_below_threshold_for_live_min_10M` cuando aplica. |
| TSK-103.2.3   | `SpreadFilter` con `max_bps`.                              | `src/trading_bot/scanner/filters.py`                    | `test_filters.py::test_spread_filter_pass_fail`                                                | TSK-103.2.1 | 1 | Parametrizado 8 casos con mock source.                       |
| TSK-103.2.4   | `AtrFilter` con `min_pct`, `max_pct`, `min_history`.       | `src/trading_bot/scanner/filters.py`                    | `test_filters.py::test_atr_filter_history`, `...::test_atr_filter_out_of_range`                  | TSK-103.2.1 | 1 | N<min_history -> `insufficient_history`.                     |
| TSK-103.2.5   | Parametrize `pytest.mark.parametrize` por 24 casos.        | `tests/unit/scanner/test_filters.py`                    | (cuenta arriba; total >= 14)                                                                    | TSK-103.2.2..2.4 | 2 | Una suite parametrizada cubre los 3 filtros. |

Gate de F2: `pytest tests/unit/scanner/test_filters.py
tests/unit/scanner/test_registry.py` >= 14 verde.

---

## TSK-103.3 - Scoring y normalizacion (F3)

| ID            | Descripcion                                                | Archivos                                                | Tests esperados                                       | dep       | P | DoD                                          |
| ------------- | ---------------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------------------- | --------- | - | -------------------------------------------- |
| TSK-103.3.1   | `compute_rank_score` con formula cerrada.                  | `src/trading_bot/scanner/scoring.py`                    | `test_scoring.py::test_rank_score_formula_edge`, `...` parametrizados | TSK-103.1.2 | 1 | Formula coincide con RF-10; ∈[0,1] estricto. |
| TSK-103.3.2   | Property test con `hypothesis` (invariante rango).         | `tests/unit/scanner/test_scoring.py`                    | `test_scoring.py::test_rank_score_in_unit_interval`   | TSK-103.3.1 | 1 | 1000 ejemplos `hypothesis` sin falla.        |
| TSK-103.3.3   | Tie-break alfabetico documentado (test de regresion).     | `tests/unit/scanner/test_scoring.py`                    | `test_scoring.py::test_tie_break_alphabetical`        | TSK-103.3.1 | 2 | `sorted(snapshots, key=lambda s: s.symbol)` para `rank_score` identico. |

Gate de F3: `pytest tests/unit/scanner/test_scoring.py` verde,
incluyendo property; coverage del modulo 100%.

---

## TSK-103.4 - Orquestador `UniverseScanner` (F4)

| ID            | Descripcion                                                | Archivos                                                | Tests esperados                                                                                  | dep            | P | DoD                                                                |
| ------------- | ---------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | -------------- | - | ------------------------------------------------------------------ |
| TSK-103.4.1   | `UniverseScanner.__init__` con DI.                          | `src/trading_bot/scanner/scanner.py`                    | `test_universe_scanner.py::test_init_minimal_args`                                              | TSK-103.2.1, TSK-103.3.1 | 1 | Constructor solo acepta kwargs; settings=None -> `ConfigurationError`. |
| TSK-103.4.2   | `_Counters` interno (mutable dataclass, no API publico).   | `src/trading_bot/scanner/scanner.py`                    | (cubierto por tests del orquestador)                                                            | TSK-103.4.1    | 1 | Counters incrementan en test.                                       |
| TSK-103.4.3   | `UniverseScanner.run()` async; loop sobre `universe.pairs`.| `src/trading_bot/scanner/scanner.py`                    | `test_universe_scanner.py::test_run_empty_universe`, `...::test_run_full_universe_ordering`     | TSK-103.4.1, TSK-103.4.2 | 1 | `universe.pairs` vacio -> `[]` + warn.                              |
| TSK-103.4.4   | Composicion de filtros via registry; primer fallo bloquea. | `src/trading_bot/scanner/scanner.py`                    | `test_universe_scanner.py::test_filter_composition`                                             | TSK-103.4.3    | 1 | Filter fail corto-circuita el resto (decision de perf).            |
| TSK-103.4.5   | Try/except por par con `ccxt.NetworkError` y timeout.      | `src/trading_bot/scanner/scanner.py`                    | `test_universe_scanner.py::test_transient_error_isolation`                                      | TSK-103.4.3    | 1 | Exception transitoria no aborta; contador `scanner_errors+=1`.      |
| TSK-103.4.6   | Kill check antes del loop (RF-4).                          | `src/trading_bot/scanner/scanner.py`                    | `test_universe_scanner.py::test_kill_switch_aborts_iteration`                                    | TSK-103.4.3    | 1 | `kill_switch=True` -> `[]` + log `scanner.paused.kill_switch`.     |
| TSK-103.4.7   | Logs estructurados `structlog` (5 eventos).                | `src/trading_bot/scanner/scanner.py`                    | `test_universe_scanner.py::test_structlog_events_emitted`                                       | TSK-103.4.3    | 1 | Captura `structlog.testing.capture_logs` verifica 5 eventos.       |
| TSK-103.4.8   | Comportamiento por modo (RF-7).                            | `src/trading_bot/scanner/scanner.py`                    | `test_universe_scanner.py::test_mode_live_endures_volume`, `...::test_mode_backtest_offline`     | TSK-103.4.3    | 1 | Test parametrizado `mode ∈ {research, backtest, paper, live}`.     |
| TSK-103.4.9   | Cross-layer enforcement via AST.                           | `tests/unit/scanner/test_cross_layer.py`                | `test_cross_layer.py::test_scanner_does_not_import_forbidden_layers`                            | TSK-103.4.7    | 1 | Falla el test si scanner importa `execution`/`strategies`/`risk`/`portfolio`. |

Gate de F4: `pytest tests/unit/scanner/` >= 30 verde total;
cobertura >= 90%; mypy strict verde; `ruff format` + `ruff check`
verdes.`

---

## TSK-103.5 - Wiring con Settings + BDD + gates (F5)

> **Kickoff 2026-07-04**: F5 se arranca con la cadena sub-ticket
> `.1(8 stubs) -> .2(7 stubs) -> .3(3 stubs) -> .4(6 stubs) ->
> .5(5 stubs) -> .6(1 stub) -> .7(6 stubs = 6 quality gates) =
> ~36 stubs en total`. ADR-0013 firmada en retrieval-log `[11:00]`
> ya cubre `.3` por endogamia; .3 queda como verification loop, no
> nueva firma. Total ejecutable end-to-end ~33 stubs nuevos.

### Cadena de sub-tickets F5

#### .1 — Fixture `settings_repr` + DI wiring con `Settings` real (8 stubs)

| ID              | Descripcion                                                                                              | Archivos                                                                              | DoD                                                              |
| --------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| TSK-103.5.1.1   | Crear `tests/unit/scanner/conftest.py` con import-time guards (`pytest`).                                 | `tests/unit/scanner/conftest.py`                                                      | `pytest --collect-only` no muestra errores de import.            |
| TSK-103.5.1.2   | Loader `load_settings_from_assets_yaml(repo_root)` que reutiliza TSK-099 `load_settings()`.               | `tests/unit/scanner/conftest.py`                                                      | 1 linea reusable; puro path, sin red.                            |
| TSK-103.5.1.3   | Fixture `settings_paper` (YAML-real `assets.yaml`, `runtime.mode=paper`).                                | `tests/unit/scanner/conftest.py`                                                      | test_settings_paper_loads_yaml verde.                            |
| TSK-103.5.1.4   | Fixture `settings_research` para mode-bake F2/F4 isolation.                                              | `tests/unit/scanner/conftest.py`                                                      | 1 invocacion; sin cross-mode bleed.                              |
| TSK-103.5.1.5   | Helper `_build_settings(pairs, kill_switch, min_volume_usdt, ...)` que delega en `Settings(...)` directo. | `tests/unit/scanner/conftest.py`                                                      | Public; no FI; puro factory.                                     |
| TSK-103.5.1.6   | Parametrize `mode in {research, backtest, paper, live, shadow_live}` via `indirect=True`.                 | `tests/unit/scanner/test_universe_scanner.py`                                         | `pytest -m "not slow" -k mode` verde.                            |
| TSK-103.5.1.7   | Migrar 4 tests F4 inline-Settings al helper `_build_settings`.                                           | `tests/unit/scanner/test_universe_scanner.py`                                         | 4 sentinels refactorizados sin semantic drift.                   |
| TSK-103.5.1.8   | Smoke `pytest tests/unit/scanner -m "not slow"`.                                                         | (CI)                                                                                  | 30+ tests verde.                                                 |

#### .2 — Anadir los 17 escenarios BDD nuevos (preservar 6 = 23 totales) (7 stubs)

| ID              | Descripcion                                                                                              | Archivos                                                                              | DoD                                                              |
| --------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| TSK-103.5.2.1   | Crear `tests/bdd/conftest.py` con `pytest-bdd` glue + `@given/@when/@then` shared rules.                  | `tests/bdd/conftest.py`                                                               | `pytest-bdd --collect-only` lista 23 scenarios.                  |
| TSK-103.5.2.2   | Step definitions RF-1.x + RF-2.x: `Snapshot contains 10 fields`, `Snapshot is frozen`, `ATR out of range`.| `tests/bdd/step_defs/test_snapshot_steps.py`                                           | 3 scenarios verde.                                               |
| TSK-103.5.2.3   | Step definitions RF-3.x + RF-5.x: `Motivo insufficient_history`, `Counter scanner_errors`, `OHLCVFetcher timeout`. | `tests/bdd/step_defs/test_state_steps.py`                                  | 3 scenarios verde.                                               |
| TSK-103.5.2.4   | Step definitions RF-6.x + RF-7.x: `Iteracion registra duracion`, `Modo live endurece`, `Modo backtest offline`. | `tests/bdd/step_defs/test_runtime_steps.py`                                 | 3 scenarios verde.                                               |
| TSK-103.5.2.5   | Step definitions RF-8.x (cross-layer AST extension) + RF-9.x (`FilterRegistry`, `Custom filter`).         | `tests/bdd/step_defs/test_ast_and_registry_steps.py`                                  | 3 scenarios verde.                                               |
| TSK-103.5.2.6   | Step definitions RF-10.x (`rank_score formula`, `Lista en orden de insercion`).                          | `tests/bdd/step_defs/test_scoring_steps.py`                                           | 2 scenarios verde.                                               |
| TSK-103.5.2.7   | Step definitions CL-1 / CL-3 / CL-6 (lista vacia, all-failed, tie-break). Smoke `pytest-bdd` 23/23.      | `tests/bdd/step_defs/test_edge_steps.py`                                              | 23/23 verde, cero `uncollected`.                                 |

#### .3 — ADR-0013 verification loop (3 stubs)

> Estado: ya firmada en retrieval-log `[11:00]`. Esta sub-ticket queda
> como re-verification + sync, no nueva firma.

| ID              | Descripcion                                                                                              | Archivos                                                                              | DoD                                                              |
| --------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| TSK-103.5.3.1   | Confirmar que ADR-0013 vive en `tasks/decisions.md` con status `Decidido` + Excepciones entry firmadas.   | `tasks/decisions.md`                                                                  | grep `ADR-0013` -> 1 entrada en cada seccion.                   |
| TSK-103.5.3.2   | Confirmar que spec `04-plan.md` Decision D1-a esta alineada con la ADR (sin relecturas contradictorias). | `docs/specs/TSK-103-universe-scanner/04-plan.md`                                     | Revision manual OK; firmado por context-engineer.                |
| TSK-103.5.3.3   | Confirmar que F4 scanner respeta el cross-layer AST (no importa `storage.*` ni capsulas vedadas).        | `tests/unit/scanner/test_cross_layer.py`                                              | `pytest tests/unit/scanner/test_cross_layer.py` verde.           |

#### .4 — Actualizacion `tasks/backlog.md` (6 stubs)

| ID              | Descripcion                                                                                              | Archivos                                                                              | DoD                                                              |
| --------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| TSK-103.5.4.1   | Marcar TSK-103.5 `todo` -> `in_progress` tras kickoff.                                                    | `tasks/backlog.md`                                                                    | `[ ] TSK-103.5` -> `[ ] **TSK-103.5**` + `Estado: in_progress`.  |
| TSK-103.5.4.2   | TSK-099 entry: anadir nota de cross-link TSK-102 + TSK-101 (cubre F4 wiring).                             | `tasks/backlog.md`                                                                    | TSK-099 descripcion menciona TSK-101/102.                        |
| TSK-103.5.4.3   | TSK-100 entry: anadir nota de seguir bloqueado hasta FASE 6+.                                            | `tasks/backlog.md`                                                                    | TSK-100 description updated.                                    |
| TSK-103.5.4.4   | TSK-101/102 entries: mantener `done` + cross-link a PR#12/13 + ADR-0012 firmado.                         | `tasks/backlog.md`                                                                    | Existing entries sin changes contractuales.                      |
| TSK-103.5.4.5   | TSK-103 entries: marcar F1/F2/F3/F4 con `done` + indicar que F5 kickoff = esta entrada `.1[8]->.2[7]->`. | `tasks/backlog.md`                                                                    | Sub-tickets table refleja kickoff.                               |
| TSK-103.5.4.6   | TSK-104 entry: mantener `blocked` + anadir nota de depende de F5 merge.                                   | `tasks/backlog.md`                                                                    | TSK-104 description updated.                                    |

#### .5 — Actualizacion `tasks/sprint-002.md` (5 stubs)

| ID              | Descripcion                                                                                              | Archivos                                                                              | DoD                                                              |
| --------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| TSK-103.5.5.1   | Update TSK-103 sub-tickets table: .1/.2/.3/.4 `done`, .5 `in_progress`.                                  | `tasks/sprint-002.md`                                                                 | Tabla refleja estados reales.                                    |
| TSK-103.5.5.2   | Update "Estado real por ticket": TSK-103 esta cerrado por F4 + F5 en kickoff.                             | `tasks/sprint-002.md`                                                                 | Estado real aria F5 kickoff.                                     |
| TSK-103.5.5.3   | Anadir entrada F5 kickoff al final del bloque `Log` con `[2026-07-04 HH:MM]`.                            | `tasks/sprint-002.md`                                                                 | Nueva entrada con summary cross-cutting.                        |
| TSK-103.5.5.4   | Update DoD resumida: anadir Bloque 2 + Bloque 3 + 6 quality gates como acceptance line para F5.           | `tasks/sprint-002.md`                                                                 | DoD section incluye `6 CI gates verdes` y `ADR-0013 firmada`.    |
| TSK-103.5.5.5   | Update Riesgos detectados: anadir F5 specific risks (pytest-bdd collection, cross-layer enforcement <-> BDD RF-8). | `tasks/sprint-002.md`                                                       | 3 riesgos adicionales documentados.                              |

#### .6 — `context/retrieval-log.md` F5 kickoff entry (1 stub)

| ID              | Descripcion                                                                                              | Archivos                                                                              | DoD                                                              |
| --------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| TSK-103.5.6.1   | Append una entrada `[2026-07-04 HH:MM] agent=context-engineer | action=kickoff TSK-103.5 (F5) | summary=...`. | `context/retrieval-log.md`                                                          | Entry persistente con chain reference.                            |

#### .7 — 6 quality gates verdes (6 stubs = 6 gates per `docs/ci.md §3`)

> Gates gate-specificos del release per `docs/ci.md sec 3`.
> NO se confunde con `quality/release-gates.md Bloque 2` (que es
> estrategia/backtest/paper y NO aplica todavia — Fase 4+).

| ID              | Gate (Bloc 1 de Bloque 1 release + ci.yml job)                                                          | Comando                                                                                | DoD                                                              |
| --------------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| TSK-103.5.7.1   | Gate 1 - `ruff check .` (Bloque 1 / CI job `format-and-lint`).                                            | `uv run ruff check . --exit-zero` (scoped F5)                                           | Exit 0, errores auto-fixables via `ruff check --fix`.            |
| TSK-103.5.7.2   | Gate 2 - `ruff format --check .`.                                                                        | `uv run ruff format --check .`                                                          | Exit 0, todo formato conforme.                                    |
| TSK-103.5.7.3   | Gate 3 - `mypy strict src/trading_bot + tests/`.                                                        | `uv run mypy src/trading_bot tests/`                                                    | Exit 0; coverage mypy = full repo.                                |
| TSK-103.5.7.4   | Gate 4 - `pytest -m "not slow" --cov=src/trading_bot --cov-fail-under=90`.                               | `uv run pytest -m "not slow" --cov=src/trading_bot --cov-fail-under=90 -q`              | 99+ tests verde + cobertura scanner >= 90%.                      |
| TSK-103.5.7.5   | Gate 5 - `safety check` (ADR-0012 firmado).                                                              | `uv run safety check -r requirements --output text`                                     | 0 red; nltk PYSEC-2026-597 ignorado via signed ignore-vuln.    |
| TSK-103.5.7.6   | Gate 6 - `pip-audit --ignore-vuln PYSEC-2026-597` (ADR-0012 firmado).                                    | `uv run pip-audit --ignore-vuln PYSEC-2026-597 --format columns`                       | 0 red en runtime deps; PYSEC-2026-597 firmado.                  |

Gate de F5: PR con los 6 gates verdes; reviewer verdict clean;
ADR-0013 ya firmada; tickets backlog/sprint actualizados; retrieval-log
con entrada cross-linkeada; 6 quality gate stubs todos cerrados con
evidencia (logs/coverage report) adjunta al PR description.

### Criterios de salida (cross-cutting)

1. Los 6 quality gates verdes en CI verde real (no fake-pass).
2. CODEOWNERS dual-review (a agregar explicitamente para scanner per
   PR#F4 / F5 si todavia no esta).
3. `pytest-bdd` 23/23 verde end-to-end (no `uncollected`, no `skipped`).
4. `pytest tests/unit/scanner -m "not slow" --cov` >= 90% en scanner.
5. ADR-0013 firmada + entries Excepciones firmadas consistente.
6. Backlog/sprint/retrieval-log sincronizados con el estado ejecutado.

---

## Resumen de cobertura esperada

- `test_types.py`: ~6 tests.
- `test_protocols.py`: ~2 tests.
- `test_registry.py`: ~4 tests.
- `test_filters.py`: ~14 tests parametrizados.
- `test_scoring.py`: ~4 tests + 1 property.
- `test_universe_scanner.py`: ~12 tests.
- `test_cross_layer.py`: ~3 tests.
- BDD (`pytest-bdd`): 23 escenarios.

**Total ~46 tests + 1 property + 23 BDD scenarios en paquete
  `tests/unit/scanner/`.**

## Notas operativas

- Cualquier cambio de formula en `compute_rank_score` o de los
  motivos `RejectionReason` requiere ADR nueva antes del commit.
- Los filtros custom se anaden via `FilterRegistry.register` sin
  tocar el orquestador; esto cubre RF-9.
- El cross-layer enforcement no bloquea el desarrollo inicial
  (TSK-103.4) pero es bloqueante para merge (TSK-103.5).
