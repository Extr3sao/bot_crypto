# Codebase Map

> Mapa vivo de la estructura `src/trading_bot/`. Refrescado por
> `context-engineer` (comando `00-context-scan.md`).

---

## Visión general

```
src/trading_bot/
├── __init__.py            # paquete raíz
├── app.py                 # entrypoint CLI/Rich + scheduler + scan --demo
├── config/                # cargado tipado (Pydantic) desde /config
├── market_data/           # conector CCXT, descarga OHLCV, FakeMarketDataSource
├── indicators/            # motor enchufable de indicadores técnicos
├── strategies/            # estrategias; emiten señales, no órdenes
├── scanner/               # UniverseScanner + ranking + filtros + scoring (F5 IMPLEMENTADO)
├── risk/                  # risk manager, sizing, drawdown, kill switch
├── execution/             # órdenes, retries, idempotencia
├── portfolio/             # estado de posiciones, balances, PnL
├── backtesting/           # motor de backtest, walk-forward, métricas (F1 en branch aparte)
├── paper/                 # paper trading: órdenes simuladas
├── observability/         # logs estructurados, métricas, alertas
├── storage/               # persistencia (sqlite3); OHLCVStore en branch aparte (TSK-102)
└── utils/                 # helpers (time, math, IO, ids)
```

## Por módulo

| Módulo              | Responsabilidad                                              | Estado (PR #2 → main)             | Agente(s) responsable(s)         |
| ------------------- | ------------------------------------------------------------- | -------------------------------- | -------------------------------- |
| `app`               | Entrypoint CLI; argparse/Rich; scheduler; `scan --demo`.       | implementado (97% coverage)      | App-level                        |
| `config`            | Cargador Pydantic tipado de YAML; validación; defaults; `FlatEnvAliasSource` (ADR-0010). | implementado | strategy-engineer                |
| `market_data`       | CCXT connector (TSK-101); OHLCV fetcher; pair validation; sandbox; `FakeMarketDataSource` test injection. | implementado (TSK-101+103) | execution-engineer               |
| `indicators`        | EMA, RSI, MACD, ATR, BB, VWAP, vol rel., spread, volatilidad, momentum, OB imbalance. | skeleton   | strategy-engineer                |
| `strategies`        | Catálogo; interfaz `Strategy.generate(snapshot) -> Signal?`. | skeleton   | strategy-engineer                |
| `scanner`           | `UniverseScanner` async iteration; filtros Volume/Spread/ATR vía `FilterRegistry` pluggable; scoring formula; retry-tolerant; 23 BDD scenarios verdes. | implementado (TSK-103.5 F5) | strategy-engineer + risk-manager |
| `risk`              | Veredicto de señal; sizing; drawdown; kill switch.            | skeleton                        | risk-manager                     |
| `execution`         | Órdenes con `client_order_id`; retries tenacity; slippage.   | skeleton                        | execution-engineer               |
| `portfolio`         | Posiciones; balances; reconciliación.                        | skeleton                        | risk-manager + execution-engineer |
| `backtesting`       | Motor determinista; comisiones; slippage; métricas; walk-forward. F1 (engine skeleton) en rama `feature/tsk-104-backtest-engine`; F2/F3 pending. | F1 solo en rama aparte | backtest-engineer                |
| `paper`             | Órdenes simuladas con comisión y slippage configurables.      | skeleton                        | execution-engineer               |
| `observability`     | Logger JSON; métricas Prometheus placeholder; alertas.        | skeleton                        | observability-engineer           |
| `storage`           | ORM ligero (`sqlite3` per ADR-0005). `OHLCVStore` en rama aparte (TSK-102). | skeleton (TSK-102 en otra rama) | observability-engineer           |
| `utils`             | helpers (timestamps, ids, math).                             | skeleton                        | —                                |
| `tests/bdd/`        | pytest-bdd Pattern A consolidation en `conftest.py` (23 scenarios consolidates; step_defs/ NO splitteado per pine contract). | implementado (F5) | bdd-analyst |

## Reglas arquitectónicas (no negociables)

1. **`strategies` no sabe del exchange**, `indicators` ni `execution`.
2. **`execution` no decide tamaño** — eso viene de `risk`.
3. **`risk` no envía órdenes** — solo veredictos.
4. **`market_data` no calcula señales** — solo datos normalizados.
5. **`observability` no muta estado** — solo lo describe.
6. **`config` no contiene secretos** — solo defaults leídos desde `.env` en runtime.
7. **`scanner` no importa** de `execution`, `strategies`, `risk`, `portfolio`, `exchange` (verificado por el BDD scenario "Scanner no importa exchange/strategies/execution/risk/portfolio" en `bdd/features/market_scanner.feature`; el ``conftest.py`` pine contract es independiente - consolida step defs en Pattern A).

## Estado

Estado actual: **fase 1 (Market data + Scanner) en transición** post-PR #2 sqsh-merge. Los
módulos `scanner/`, `market_data/`, `app.py`, `tests/bdd/` y `tests/unit/scanner/` están
implementados, con 96% overall coverage y 97% en `app.py`. Pendientes para siguientes
sprints: `risk/`, `execution/`, `portfolio/`, `paper/`, `observability/`, `storage/` (en
branch aparte). `backtesting/` F1 en rama `feature/tsk-104-backtest-engine`.

**Coverage actual** (post-merge PR #2):
- `src/trading_bot/app.py`: **97% module**
- overall project: **96%**
- Gate pinned en `pyproject.toml` i `.github/workflows/ci.yml`: `pytest --cov-fail-under=90`

**CI baseline** (TSK-008, ya en main):
- 4 jobs: `format-and-lint` (ruff check + ruff format), `type-check` (mypy strict),
  `pip-audit` (CVE scan), `tests-and-coverage` (pytest con markers `slow`+`market`
  excluidos en PR feedback < 5 min).
- Python anclado via `.python-version = 3.11`; `pyproject.toml::requires-python = ">=3.11"`.
- GitHub Actions: `ubuntu-latest`, `concurrency` con `cancel-in-progress`,
  `permissions: contents read`, gestor `uv` con `astral-sh/setup-uv@v3` y cache sobre
  `uv.lock`.

**Governance** (TSK-009, ya en main):
- `.github/CODEOWNERS` mapea los 9 agentes de AGENTS.md §2 a teams del org + dual-review
  para paths sensibles (`config/`, `risk/`, `execution/`, secrets, workflows).
- `.github/PULL_REQUEST_TEMPLATE.md` estructura el PR en 5 bloques (header + quality gates
  + 4 checklists colapsables por tipo de cambio + sign-off table + merge procedure).
- Branch protection rules (status checks required + bypass options + linear history) en
  `quality/release-gates.md` §6 con comandos `gh api` listos para bash + PowerShell.

## Cambios recientes

| Fecha       | Cambio                                                                   | Módulos afectados                   | Riesgos                                  | Mitigación                                              |
| ----------- | ------------------------------------------------------------------------ | ---------------------------------- | ---------------------------------------- | ------------------------------------------------------- |
| 2026-07-05  | Sqsh-merge PR #2 → main. Squash integra TSK-008 (CI), TSK-009 (Governance), TSK-103.5 F5 (BDD wiring), misc. | `scanner/`, `market_data/`, `app.py`, `tests/bdd/`, `tests/unit/scanner/`, `.github/`, `docs/`, `tasks/` | Regresiones scanner / BDD; coverage drop bajo 90%; CI no-verde por pip-audit strict. | Tests verde post-merge; coverage 96% overall; rip-audit strict (los CVEs transitivos que aparezcan se gestionan via ADR-firmada). |
| 2026-07-04  | TSK-103.5 F5 (BDD wiring sobre main en feature branch) | `bdd/features/market_scanner.feature`, `tests/bdd/conftest.py`, `tests/bdd/test_features.py`, `tests/unit/scanner/*`, `src/trading_bot/scanner/{exceptions,filters,mode_filters,protocols,registry,scanner,scoring,types}.py`, `src/trading_bot/market_data/{exchange_connector,fake,ohlcv_fetcher,types}.py`. | Regresión de contratos BDD; import cycle scanner×strategies×risk. | 23 BDD scenarios verdes; static-import lint pineado en conftest.py; `tests/unit/scanner/test_cross_layer.py` cubre interacción con settings/scanner/models. |

## Última actualización

2026-07-05 — context-engineer post-PR #2 sqsh-merge a `main` (merge_commit
`da0424a87d4ea685a54ccc8ee9c34f65fda38d74`) + branch delete de
`origin/feature/tsk-103-5-bdd-wiring`. Próximo refresh esperado: post-merge de TSK-102
(OHLCVStore en rama aparte) o de TSK-104 F2/F3 (backtesting commission refinement).
