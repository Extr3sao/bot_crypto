# Sprint 003 - F5 close-out + backtest/paper + indicators

> Sprint abierto el `<F5_MERGE_DATE>` tras cierre de TSK-103.5 (F5) via PR F5
> squash-merge + tag `v0.5.0-rc.1`. Apertura formal tras aplicacion de las
> Phase 7.4 manual bookkeeping (backlog.md flip + sprint-002.md log entry +
> decisions.md ADR-0014 opcional).

> **Estado real del worktree (sprint-003 abierto via ADR-0015 post-PR #2 merge)**: TSK-008/TSK-009 governance cerradas en sprint-002 via **PR #2** (commit `da0424a`) — ya no son arrastre. TSK-099/101/102/103.x mergeados en main; TSK-103.5 cerrado en `<F5_PR_URL>`; 7/7 quality gates verdes per `docs/ci.md sec 3` (incluido Gate 7 BDD fixture injection contract per round-24..27 review chain).

---

## Duracion

- **Inicio**: `<F5_MERGE_DATE>` (post-Phase 6 squash-merge de PR F5).
- **Fin blando**: `<F5_MERGE_DATE + 2 weeks>`.
- **Trigger de fin anticipado**: DoD de `TSK-104` + `TSK-105` verde con
  paper trading reproduciendo al menos 1 sesion real de scanner.

## Objetivo

Cerrar el arrastre de governance (`TSK-008` + `TSK-009`) que llevan 2 sprints
en `in_progress`; anclar el baseline de backtesting (`TSK-104`) que habilita
el walk-forward obligatorio per ADR-0007; y arrancar la Fase 2 (indicators)
como bloque de valor incremental sobre el scanner F1-F5 ya operativo.

## Tickets en curso

### Foundations (CI/calidad + governance carryover)

| ID | Titulo | Tam | Fase | Risk | Estado | Pri |
| --- | --- | --- | --- | --- | --- | --- |
| TSK-008 | Baseline CI: ruff + mypy + pytest markers + pip-audit + workflow GHA | S | 1 | M | done | - |
| TSK-009 | CODEOWNERS + PR template + branch-protection admin rules | S | 0 | M | done | - |
| TSK-013.4 | Backfill ruff format + ruff check drift on main (deferred from TSK-013.3 sweep) | M | 0 | M | todo | 1 |

### Fase 1 (backtest + paper trading ahora desbloqueados)

| ID | Titulo | Tam | Fase | Risk | Estado | Pri |
| --- | --- | --- | --- | --- | --- | --- |
| TSK-104 | Backtest engine minimal + comisiones + slippage | L | 1 | M | in_progress | 3 |
| TSK-105 | Paper trading harness + reporter | M | 1 | M | in_progress | 4 |

### Fase 2 (indicators)

| ID | Titulo | Tam | Fase | Risk | Estado | Pri |
| --- | --- | --- | --- | --- | --- | --- |
| TSK-200 | Motor de indicadores (interface, registro, cache) | M | 2 | M | todo | 5 |
| TSK-201 | EMA, RSI, MACD, ATR, BB | M | 2 | L | todo | 6 |
| TSK-202 | VWAP, volume_relative, spread, volatilidad, momentum | M | 2 | M | todo | 7 |
| TSK-203 | Order book imbalance (detras de un feature flag) | S | 2 | M | todo | 8 |
| TSK-204 | Property tests sobre series sinteticas | S | 2 | L | todo | 9 |

### Secondary (carry from sprint-002 si no cerrado)

| ID | Titulo | Tam | Fase | Risk | Estado | Pri |
| --- | --- | --- | --- | --- | --- | --- |
| TSK-100 | Storage layer (SQLite + migraciones minimas) | S | 1 | L | todo | 10 |

### TSK-103 sub-tickets (solo si ADR-0014 surgio de F5 close-out)

| ID | Titulo | Tam | Risk | Estado |
| - | - | - | - | - |
| TSK-103.6 | Post-F5 follow-up (per ADR-0014 scope changes) | TBD | TBD | todo |

> Si el merge de F5 fue limpio (sin scope changes en reviewer chain o
> dual-team discussion), la fila `TSK-103.6` queda como placeholder y no
> se materializa. ADR-0014 documenta la decision en su defecto.

## Estado real por ticket

- `TSK-008`: **done** via **PR #2** (commit `da0424a`) cerrado al
  cierre de sprint-002 (per `ADR-0015`). CI baseline operativo con
  `.github/workflows/ci.yml` (4 jobs pineados a status-checks
  required en `quality/release-gates.md` Bloque 6) +
  `.python-version = 3.11` + ajustes `pyproject.toml`. Cross-link
  ADR-0012 cubre numpy<2.1 + app.py omit + PYSEC-2026-597.
- `TSK-009`: **done** via **PR #2** (commit `da0424a`, mismo PR que
  TSK-008). Cerrado al cierre de sprint-002 (per `ADR-0015`).
  CODEOWNERS con mapping 9-agent + dual-review para paths sensibles
  + PULL_REQUEST_TEMPLATE 5 bloques con collapsibles `<details>` +
  branch-protection rules documentadas en `quality/release-gates.md`
  Bloque 6.
- `TSK-104`: ahora `in_progress` (desbloqueado por F5 close-out). DoD
  per `docs/backtesting-methodology.md` + `quality/risk-quality-gates.md`:
  engine con OHLCVStore replay + commissions + slippage parametrizables
  + walk-forward ready (per ADR-0007) + reproducibility (seed-pinned).
- `TSK-105`: ahora `in_progress` (desbloqueado por F5 + TSK-104). DoD per
  `docs/paper-trading-methodology.md`: harness ejecutando `UniverseScanner`
  con `MarketDataSourceProtocol` (F2 protocol) sobre `paper` mode con
  fills simulados, reporter PineStructlog-based, retention de snapshots.
- `TSK-200..TSK-204`: tickets de Fase 2. Arrancan en este sprint con
  TSK-200 (interface + registro) primero; los demas quedan bloqueados
  hasta TSK-200 cerrado.
- `TSK-100`: arrastre desde sprint-002. Bajo prioridad; OHLCVStore
  minimal ya cubre Fase 1 (TSK-102). Migracion completa queda para
  Fase 9+.

## DoD resumida

### TSK-008

- `ruff`, `mypy`, `pytest`, `pip-audit` y workflow GHA operativos.
- `.python-version = 3.11` (o 3.14 per pin post-ADR-0012).
- `coverage fail_under = 90`.
- `docs/ci.md` como runbook oficial.

### TSK-009

- `CODEOWNERS` con `/src/trading_bot/scanner/` + `/tests/bdd/` + `/tests/unit/scanner/`
  pineados a dual-review `strategy-team + security-team` (F5 PR ya anadio scanner paths).
- `PULL_REQUEST_TEMPLATE.md`.
- branch protection documentada.

### TSK-104

- engine replay sobre OHLCVStore SQLite (TSK-102 foundation).
- commissions + slippage parametrizables.
- walk-forward obligatoriedad cross-cutting (per ADR-0007).
- min_trades_for_promotion gate per `config/strategies.yaml`.
- PineStructlog-based reporter consistente con F5 spec section 10.

### TSK-105

- harness ejecutando `UniverseScanner` en `paper` mode.
- `MarketDataSourceProtocol` (TSK-103.2 protocol) para feeds en vivo vs
  OHLCVStore replay indistintamente.
- reporter: dashboard CSV/JSON + structlog events.
- retention policy: snapshots persistidos en SQLite con TTL.

### TSK-200..TSK-204 (Fase 2)

- TSK-200: interface `Indicator` Protocol + `IndicatorRegistry` extensible
  (mirror de `FilterRegistry` F2 design pattern).
- TSK-201 + TSK-202: indicators concretos segun `config/indicators.yaml`
  (catalogo enchufable per F1).
- TSK-203: order book imbalance detras de `feature_flag_ob_imbalance`
  (Fase 1 sentinel sin feed real).
- TSK-204: hypothesis property tests sobre series sinteticas (invariantes
  + monotonicidad + determinismo; mirror de F3 pattern).

## Criterio de salida del sprint

- `TSK-008` + `TSK-009` cerrados (governance arrastre FIN).
- `TSK-104` cerrado con backtest engine verde.
- `TSK-105` cerrado con paper trading reproduciendo scanner F5.
- Al menos `TSK-200` cerrado (interface) + `TSK-201` arrancado.

## Riesgos detectados

1. **TSK-008 + TSK-009 arrastre**: 2 sprints en `in_progress`. Riesgo de
   deuda de governance cronica. Mitigacion: Pri 1+2 al inicio del sprint
   para forzar cierre.
2. **TSK-104 walk-forward**: ADR-0007 pineado obliga walk-forward como
   pre-condicion de TSK-105 promotion. Si backtest engine no soporta
   walk-forward nativo, paper trading queda bloqueado.
3. **TSK-105 paper mode coupling**: el harness debe usar `runtime.mode=paper`
   end-to-end (config + scanner + execution); cualquier regresion de
   `mode` mapping en scanner (F1 regression guard `test_mode_shadow_live_*`)
   bloquea Fase 1+.
4. **Fase 2 indicators vs scanner coupling**: los indicators se computan
   sobre OHLCV (TSK-102) + live feeds (TSK-101). Cross-layer enforcement
   via AST pine contract: scanner no importa indicators/ directo; los
   indicators se exponen via protocol (mirror de F2 protocol design).
5. **TSK-103.6 follow-up (conditional)**: solo si ADR-0014 detecto scope
   changes. Mantener la fila como placeholder; poblar tras F5 review.

## Log

```
[<F5_MERGE_DATE> HH:MM] agent=context-engineer | action=open sprint-003 via F5 close-out | artifacts=tasks/sprint-003.md, tasks/{backlog,sprint-002,decisions}.md (Phase 7.4 bookkeeping ya aplicado), context/retrieval-log.md | summary=Apertura formal de sprint-003 tras merge de TSK-103.5 (F5) en <F5_PR_URL> con tag v0.5.0-rc.1. F5 unblock TSK-104 (backtest engine) + TSK-105 (paper trading harness) que pasan de blocked a in_progress. Governance arrastre TSK-008 + TSK-009 sube a Pri 1+2 para forzar cierre del arrastre de 2 sprints. Fase 2 indicators arranca con TSK-200 (interface) como Pri 5. TSK-103.6 queda como placeholder conditional: solo se materializa si ADR-0014 detecto scope changes durante F5 review chain; en caso contrario la fila se mantiene vacia y el ticket queda descartado.
```
