## Resumen

Cierra **TSK-103.5 (F5 wiring con Settings + BDD + 6 quality gates)** dentro de `TSK-103`. F1..F5 cierran el parent ticket por completo; el siguiente desbloqueado natural es **TSK-104 (portfolio layer sobre los snapshots activos)** y **TSK-105 (multi-exchange sandbox verification)**.

F5 ABI los 5 sub-tickets F1..F4 en una superficie operativa: (a) `tests/unit/scanner/conftest.py` con `FakeMarketDataSource` + `build_settings` + `make_flat_ohlcv` + `settings_paper/settings_research/settings_live` fixtures exportables (TSK-103.5.1.*); (b) `tests/bdd/` con pytest-bdd glue + 7 modulos de step_defs cubriendo los 23 escenarios de `bdd/features/market_scanner.feature` (6 pre-existentes + 17 anyadidos en [06:00] retrieval log); (c) `scripts/validate_gates_f5.ps1` para que el host Windows pueda correr las 6 quality gates verdes sin transcription errors; (d) bookkeeping flip de TSK-103.5 a `done` en backlog + sprint-002 + retrieval-log.

The cross-layer AST enforcement de F4 (`tests/unit/scanner/test_cross_layer.py` + nuevo `/tests/bdd/` entry en CODEOWNERS) ya pinea que el scanner package nunca importa `execution`/`strategies`/`risk`/`portfolio`/`indicators`/`paper`/`observability`/`storage`. La decision ADR-0013 (TSK-103 scope reconciliation, firmada per [11:00]) cubre F5 endogamicamente; no requiere nueva ADR.

## Ticket / ADR

- **TSK parent**: `TSK-103` (Universe scanner + filters).
- **Sub-ticket cerrado por este PR**: `TSK-103.5` (F5 wiring + BDD + gates).
- **Sub-tickets previos en este chain**: F1..F4 (cuyos artifacts viven en `src/trading_bot/scanner/{types,protocols,filters,registry,scoring,scanner,mode_filters,exceptions}.py` y `tests/unit/scanner/*`).
- **ADR precursora**: [ADR-0013 — Reconciliacion de scope TSK-103](tasks/decisions.md#adr-0013) firmada en retrieval-log `[11:00]`. Decision D1-a formalizada como opcion 3: TSK-102 monopoliza persistencia OHLCV (`OHLCVStore` SQLite WAL); TSK-103 opera strictly in-memory sobre `MarketDataSourceProtocol` abstracto pineado en F1 + cross-layer AST en F4.

## Convencion tipada + atributos obligatorios

### `tests/unit/scanner/conftest.py`

```python
@dataclass
class FakeMarketDataSource:  # sin MagicMock per ADR-0011
    volume_by_symbol: dict[str, float] = field(default_factory=dict)
    spread_by_symbol: dict[str, float] = field(default_factory=dict)
    ohlcv_by_symbol: dict[str, list[OHLCV]] = field(default_factory=dict)
    call_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    # async methods: fetch_recent, fetch_24h_volume_usdt, fetch_spread_bps

def build_settings(*, pairs, min_volume_usdt=5_000_000, mode="paper", ...) -> Settings
def make_flat_ohlcv(symbol: str, n: int, *, last_close: float) -> list[OHLCV]

@pytest.fixture(scope="session") def settings_paper() -> Settings
@pytest.fixture(scope="session") def settings_research() -> Settings
@pytest.fixture(scope="session") def settings_live() -> Settings
def load_settings_from_assets_yaml(repo_root=None, *, mode_override=None) -> Settings
```

### `tests/bdd/`

23 escenarios (6 pre-existentes + 17 nuevos) distribuidos entre los 7 modulos en `tests/bdd/step_defs/`:

| Modulo | RF / CL que covers | # scenarios |
|--------|-------------------|-------------|
| `test_legacy_steps.py` | RF-1 (2 pre-existentes) + RF-3 (2) + RF-4 (kill_switch) + RF-5 (transient) | 6 (pre-existentes) |
| `test_snapshot_steps.py` | RF-2 (snapshot 10 fields) + RNF-6 (frozen) | 2 |
| `test_state_steps.py` | RF-3 (ATR + history) + RF-5 (counter + timeout) | 4 |
| `test_runtime_steps.py` | RF-4 (kill_switch, claimed aqui) + RF-6 (duration + counters) + RF-7 (live + backtest) | 4 |
| `test_ast_and_registry_steps.py` | RF-8 (cross-layer AST) + RF-9 (FilterRegistry + custom filter) | 3 |
| `test_scoring_steps.py` | RF-10 (rank_score formula + lista orden insercion) | 2 |
| `test_edge_steps.py` | CL-1 + CL-3 + CL-6 | 3 |
| **Total** | | **23** |

## Precedentes firmados

- **Pre-merge context**: TSK-099 merged; TSK-101+102 merged via PR#12+PR#13; ADR-0012 merged via PR#14; F4 TSK-103.4 done per [12:00]; ADR-0013 firmada per [11:00].
- **Spec pack cross-link**: [`docs/specs/TSK-103-universe-scanner/02-bdd.md`](docs/specs/TSK-103-universe-scanner/02-bdd.md) §3.1..§3.9 documenta los 17 nuevos escenarios Pineados RF-1..RF-10 + CL-1/CL-3/CL-6; [`docs/specs/TSK-103-universe-scanner/03-specify.md`](docs/specs/TSK-103-universe-scanner/03-specify.md) §10 documenta los 5 structlog events (con `early_exit` + `all_failed`).
- **Retrieval-log cross-link**: [11:00] (ADR-0013 firma) + [12:00] (F4 close-out 11 rondas) + [13:00] (F5 kickoff) + [14:30] (CODEOWNERS dual-review patch aplicado).

## Risk-level-of-change

- **Riesgo contractual**: BAJO. No introduce logica nueva en `src/trading_bot/scanner/`; unicamente agrega infrastructure de testing (fixtures + BDD step_defs + validate-gates script + PR bookkeeping).
- **Riesgo operacional**: BAJO. El PR no afecta el runtime del bot — el `print(__name__)` + `trading_bot.scanner.scanner.UniverseScanner.run()` API sigue identico.
- **Riesgo de regresion contratos existentes**: BAJO via conservative migration policy (conftest.py agrega aliases publicos; los F4 sentinels inline quedan intactos).

## Checklist (`.github/PULL_REQUEST_TEMPLATE.md` condensed)

### Tipo de cambio

- [x] Nueva feature (cambio infra de tests/wiring; no breaking)
- [ ] Breaking change (NO)
- [ ] Bug fix (NO; F4 ya cerrado por [12:00])
- [ ] Config / YAML (NO)
- [ ] Documentacion (NO; solo PR bookkeeping flip)
- [x] Tests (SI — pytest-bdd conftest glue + 7 step_defs modules + 23 scenarios)

### Quality gates

- [ ] `ruff check .` — `format-and-lint` job verde
- [ ] `ruff format --check .` — `format-and-lint` job verde
- [ ] `mypy strict src/trading_bot + tests/` — `type-check` job verde
- [ ] `pytest -m "not slow" --cov --cov-fail-under=90` — `tests-and-coverage` verde
- [ ] `safety check` (ADR-0012 firmado: nltk ignore-vuln) — `pip-audit` verde
- [ ] `pip-audit --ignore-vuln PYSEC-2026-597` (ADR-0012 firmado) — `pip-audit` verde

### Riesgo

- [x] R-1: `.gitignore` no expone secrets (sin `__pycache__`, sin `*.pyc` en `src/`)
- [x] R-2: ADR-0013 firmada; los casos bordes del cross-layer AST (FORBIDDEN_LAYERS) coinciden con spec section 12.
- [x] R-3: F4 cerrado antes de F5 (cadena sub-ticket respeta dep order).
- [x] R-4: CODEOWNERS dual-review pineado via [14:30] patch (`/src/trading_bot/scanner/`, `/tests/unit/scanner/`, `/tests/bdd/`).

### F5-specific riesgos (carry-forward)

- **`pytest-bdd` collection surface**: si los 23 scenarios no se collect al correr `pytest tests/bdd/`, el smoke gate 7.7 de F5 falla. Mitigacion: `tests/bdd/conftest.py` re-exporta los helpers del conftest unit; los step_defs usan `scenarios("../../bdd/features/market_scanner.feature")` (path relative) para evitar dependencies de cwd.
- **`CONFTEST.md` duplication risk**: F4 sentinels inline en `test_universe_scanner.py::_build_settings` + `FakeMarketDataSource`. Migracion a conftest (TSK-103.5.1.7) queda como future polish post-fase actual; el conftest solo agrega aliases nuevos para uso downstream.
- **CODEOWNERS bleibt bisher single-review si los teams no existen**: pre-flight `gh api /orgs/Extr3sao/teams --jq '.[].slug'` obligatorio antes del merge. Si faltan `@Extr3sao/strategy-team` o `@Extr3sao/security-team`, el PR cae a single-review via `@Extr3sao/maintainers` fallback.

## Sign-off table (per `.github/PULL_REQUEST_TEMPLATE.md` §5)

| Agente (AGENTS.md) | Estado | Justificacion |
|---------------------|--------|----------------|
| context-engineer | [x] | 11 rondas code-review F4 cerradas + F5 spec/kickoff + retrieval-log entries |
| quant-researcher | [x] | F4 scoring formula + RF-10 BDD scenario templating validado |
| bdd-analyst | [x] | 17 nuevos BDD scenarios firmados per spec [06:00] + 23-total smoke pre-F5.7 |
| risk-manager | [x] | RF-4 kill_switch mode + empty_universe verificables; `all_failed` M-sided ties a soft-warn |
| strategy-engineer | [x] | RF-7 live endurece a 10M USDT per spec section 7.1 |
| execution-engineer | [ ] | N/A — Fase 1 (market data + scanner) |
| backtest-engineer | [ ] | N/A — Fase 2 (backtesting) |
| observability-engineer | [x] | 5 structlog events pinados per spec §10 + `scan_iteration_id` via contextvars |
| security-reviewer | [ ] | N/A — sin config/secrets/workflow diff |

## Procedimiento de merge

1. Validar pre-flight CODEOWNERS: `gh api /orgs/Extr3sao/teams --jq '.[].slug' | grep -E 'strategy-team|security-team'`.
   - Si FALTA, abrir ADR de bootstrap team creation antes del PR (no auto-generate).
2. Abrir branch `feature/tsk-103-5-bdd-wiring` desde main con el contenido de este PR body.
3. `gh pr create --body-file pr-body-TASK-103.5.md --base main --head feature/tsk-103-5-bdd-wiring --title "TSK-103.5 (F5): BDD wiring + 23 scenarios + 6 quality gates wrap-up"`.
4. Esperar dual-review (CODEOWNERS pinea el par `strategy-team` + `security-team`).
5. Squash-merge con conventional message: `feat(scanner): TSK-103.5 (F5) BDD wiring con Settings + 23 scenarios + 6 quality gates wrap-up`.
6. Post-merge: `git tag -a v0.5.0-rc.1 -m "TSK-103.5 (F5) BDD wiring rc"` y abrir backlog de TSK-104 kickoff.

## Quality gate references

- C6 baseline: [`docs/ci.md`](docs/ci.md) §3 (5 jobs).
- ADR-0012 (numpy<2.1 pin + app.py omit + PYSEC-2026-597 firmado): [`tasks/decisions.md`](tasks/decisions.md).
- Spec pack unified: [`docs/specs/TSK-103-universe-scanner/`](docs/specs/TSK-103-universe-scanner/).
- Backlog flip: [`tasks/backlog.md`](tasks/backlog.md) TSK-103.5 row flipped `todo` -> `done` per this PR.
- Sprint-002 update: [`tasks/sprint-002.md`](tasks/sprint-002.md) log entry `[2026-07-04 HH:MM]` con F5 cierre.
- Retrieval-log entry: [`context/retrieval-log.md`](context/retrieval-log.md) `[2026-07-04 HH:MM]` con F5 cierre cross-linkeado a `[11:00]` + `[12:00]` + `[13:00]` + `[14:30]`.
