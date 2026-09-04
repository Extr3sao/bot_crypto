# Impact Analysis

> Plantilla viva. Se actualiza con cada cambio (PR o tarea grande). El
> agente responsable la rellena antes de implementar.

## Cómo usar este documento

Por cada cambio:

1. Identifica el archivo/módulo tocado.
2. Marca los efectos colaterales previsibles.
3. Marca los efectos colaterales desconocidos (Riesgo === Desconocido).
4. Define mitigaciones y verificaciones.

## Tabla de impacto por tipo de cambio

### Cambiar `config/assets.yaml`
- `market_data` puede fallar al cargar.
- `strategies` puede operar sobre pares nuevos (verificación: lista de pares en `codebase-map.md`).
- **Riesgos desconocidos**: pares sin volumen o con volatilidad extrema.
- **Mitigación**: validar con `runtime.yaml.filters`.

### Cambiar `config/risk.yaml`
- TODO cambio pasa por `risk-manager` + revisión humana.
- Riesgo crítico: relajar límites.
- **Mitigación**: tests + ADR obligatorio.

### Cambiar `config/strategies.yaml`
- Cambiar estado (`research → paper → live_candidate`) sin pasar por gates.
- **Mitigación**: `risk-manager` y `release-live` lo bloquean.

### Cambiar `config/indicators.yaml`
- Indicadores nuevos pueden depender de datos no disponibles.
- **Mitigación**: smoke-tests con data sintética + paper.

### Cambiar `config/exchange.yaml`
- Riesgo crítico: usar exchange no soportado por CCXT o sin sandbox.
- **Mitigación**: `security-reviewer` + ADR + release gate.

### Cambiar `config/runtime.yaml`
- Riesgo: habilitar live accidentalmente.
- **Mitigación**: `LIVE_TRADING_ENABLED` siempre `false` por defecto; variable de entorno requerida.

## Cambios recientes

| Fecha | Cambio | Módulos afectados | Riesgos | Mitigación |
|---|---|---|---|---|
| 2026-07-03 | TSK-099 cerrado: Pydantic v2 typed config + `FlatEnvAliasSource` | `config/` | Drift de contrato flat-env vs nested-path | ADR-0010 firmada; regression tests. |
| 2026-07-03 | ADR-0011 firmada: cierre sprint-001 con excepción | docs/tasks | Pérdida de trazabilidad | Excepción registrada en `tasks/decisions.md`. |
| 2026-07-03 | TSK-008 arranque de spec | docs | Bajo | Spec anclado en Python 3.11, coverage 90% y uv. |

## MA-0A + MA-0B — Multi-Agent Foundation

### Scope

Added a neutral `trading_bot.multi_agent` foundation containing strict
Pydantic contracts and deterministic governance registries. The package is not
imported by the existing paper runtime.

### Affected artifacts

- `src/trading_bot/multi_agent/contracts/`
- `src/trading_bot/multi_agent/registry/`
- `tests/unit/multi_agent/`
- `scripts/validate_multi_agent_foundation.py`
- `docs/architecture/multi_agent/`
- `reports/multi_agent/ma0/`

### Explicitly not affected

- `scanner/`
- `research/asset_intelligence/`
- `research/families/`
- `research/strategy_router.py`
- `paper/paper_cycle.py`
- `paper/candidate_portfolio.py`
- `paper/broker.py`
- `risk/manager.py`
- live/exchange execution paths

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| Duplicate trade-proposal vocabulary | Use canonical `TradeProposal`; retain research `Proposal` only as a distinct code-generation input and document the decision. |
| Capability accidentally grants execution | Separate declarations from policies; CapabilityRegistry permanently denies production action, risk override, and direct broker access. |
| Future data leakage | Require aware timestamps and enforce `data_time <= created_at`; evidence exposes `is_valid_at`. |
| Builder verifies its own artifact | Immutable `VerificationMetadata` rejects equal identities when independent verification is required. |
| Runtime boundary regression | AST architecture test rejects MA-0 imports from paper, risk, execution, market-data, and config layers. |
| False certification claim | Reports explicitly distinguish focused PASS from full-regression INCOMPLETE/FAIL. |

### Verification status

- MA-0 tests: PASS — 19 passed.
- Affected scanner/paper/router tests: PASS — 165 passed.
- Ruff scoped to MA-0: PASS.
- Mypy scoped to MA-0: PASS.
- Deterministic smoke: PASS.
- Full repository regression: INCOMPLETE/FAIL — 599 passed, with one current configuration expectation mismatch and one expected untracked-file dependency-closure failure before commit.

### Runtime authority classification

MA-0 contracts and registries are FOUNDATION artifacts and are not trading
runtime-authoritative. Existing L5 paper components remain unchanged.

## MA-1 deterministic communication runtime

### Affected artifacts

- `src/trading_bot/multi_agent/{bus,blackboard,session,communication_errors}.py`
- `tests/unit/multi_agent/test_communication.py`
- `tests/unit/multi_agent/test_fixture_e2e.py`
- `docs/architecture/multi_agent/RFC-MA-003-communication-runtime.md`
- `reports/multi_agent/ma1/`

### Explicit non-impact

No changes to `RiskManager`, `PaperBroker`, strategy runtime, live execution,
exchange connectors, configuration, or specialist agents. MA-1 has no trading
capability and fixture E2E counters remain zero.

### Verification

- MA-1 focused tests: 28 passed.
- Dependency closure: 3 passed.
- Affected scanner/paper/router tests: 165 passed.
- Scoped Ruff/Mypy: PASS.
- Independent detached checkout: PASS.
- Full regression: 609 passed, one independently reproduced baseline config
  expectation failure; not hidden or converted to PASS.

## Pendientes por clarificar

- Convención de IDs (`request_id`, `signal_id`, `order_id`).
- Política de retención de logs (días) en runtime.
- IPC entre módulos (funciones vs eventos vs msgpack).
