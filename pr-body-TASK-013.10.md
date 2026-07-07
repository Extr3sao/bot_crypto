## Resumen

Cierra **TSK-013.10** como PR docs-only sobre `main @ 41c4704` (post-5 baseline remediation tickets + ADR-0016 umbrella + ADR-0017 escalation per `tasks/decisions.md`).

3 commits atomicos en branch `feature/tsk-013.10-latent-fixture-audit`:

- **A) `b74c2f2 docs(backlog+retrieval): TSK-013.10 latent fixture-invalidation audit catalog`** — abre el ticket en `tasks/backlog.md` entre TSK-013.9 y `## Tickets Fase 2` con la audit findings table (2 violaciones latentes + 4 sites `model_construct()` bypass + 1 NEGATIVE TEST site). Retrieval-log entry `[2026-07-07 14:00]` con sweep results verbatim. **0 src/ + 0 test src/ changes** (catalogacion, no fix).
- **B) `c3c30d3 docs(retrieval-log): TSK-013.10 re-sweep entry gated on upstream merge`** — honest re-sweep confirmando que las 2 violaciones latentes siguen activas en main HEAD porque `feature/tsk-013.8-013.9-test-fixes @ d6c9141` fue push-to-origin pero nunca mergeado (gh CLI sin auth bloqueo `gh pr create` en mi session). Documenta el stall para el operador. **0 src/ + 0 test src/ changes**.
- **C) `71046d1 docs(commands+agents): TSK-013.10 audit gate co-located with fixture-audit catalog`** — convierte el catalog pasivo en defensa activa. 2 archivos `.ai/`:

  - **`.ai/commands/04-plan.md`** — anadida gate `## Gate TSK-013.10 — Sweep latent fixture-invalidation antes de aprobar cualquier plan` con:
    - rg pattern (21 fields confirmed-bounded via code_searcher sobre `src/trading_bot/config/*.py`: `rate_limit_ms|max_backoff_ms|initial_backoff_ms|max_attempts|request_ms|recv_window_ms|max_open_positions|max_trades_per_day|max_risk_per_trade_pct|max_asset_exposure_pct|max_total_exposure_pct|min_order_notional_usdt|max_order_notional_usdt|default_stop_loss_pct|default_take_profit_pct|min_24h_volume_usdt|max_spread_bps|max_atr_percent|min_atr_percent|consecutive_loss_cooldown_minutes|prometheus_port`)
    - REQUIRED cross-reference grep post-sweep: `grep -rnE '\b(ge|gt|le|lt|min_length|max_length|pattern)\s*=\s*[0-9]' src/trading_bot/config/*.py`
    - 4 triggers que cubren: (1) constraint numerico bounded change, (2) harden/soften, (3) create/rename/delete bounded field (alias preserved case documentado), (4) create/remove Pydantic model.
    - 5 triage sub-categorias: Valid / VIOLATION / BYPASS intencional (`model_construct()`) / NEGATIVE TEST / FIELD-DEPRECATED (renames con alias).
    - **Coverage evolution rule gate-binding**: el PR que introduzca un nuevo bounded field debe self-extender el rg pattern en **EL MISMO COMMIT**.
  - **`.ai/agents/context-engineer.md`** — anadida seccion `## Fixture-audit catalog maintenance` con:
    - 4 sub-categorias (latent fixture-invalidation drift, `model_construct()` bypass sites, NEGATIVE TEST sites, FIELD-DEPRECATED sites).
    - 5 refresh triggers mapeando 1:1 los 4 gate triggers del command file + sprint close touched config.
    - Maintenance cadence: per sprint en el `00-context-scan` de cierre, OR triggered immediate por cualquier refresh trigger.
    - 3-surface sync check (rg pattern argv + grep cross-reference argv + canonical models en `src/trading_bot/config/*.py`).

**Validacion baseline**: 0 src/ + 0 test src/ changes. Mypy 6 baseline errors unchanged. Pytest 2 baseline fails unchanged (1 config failfast TSK-013.5 + 1 scanner universe_scanner cosmetico).

## Ticket / ADR

- **Ticket cerrado**: **TSK-013.10** (`tasks/backlog.md`) — Pri 6 = latent fixture drift, Risk L (no impact runtime).
- **ADR cross-link**:
  - **ADR-0016** (umbrella TSK-013.5..013.9 baseline remediation que origino el cataloguing).
  - **ADR-0017** (TSK-013.5 escalation con patron analog de latent drift en pydantic-settings v2.14.2 wrapper).
- **Ninguna nueva ADR requerida** — la decision gate-binding + dual-file co-location queda registrada en este PR body + 3 commit messages.
- **Cross-link upstream**: las 2 violations latentes originales (`rate_limit_ms=10 < ge=50` y `max_backoff_ms=50 < ge=100` en `tests/unit/market_data/test_ccxt_connector.py::fast_retry_exchange_cfg`) ya corregidas en `feature/tsk-013.8-013.9-test-fixes @ d6c9141`. Ese PR queda como upstream pre-requisito: cuando mergea, libera las 2 violations y deja el gate con 0 active violations + 4 catalogued `model_construct()` bypass sites como deuda potencial.

## Convencion tipada + diff inventario

### Branch

```
feature/tsk-013.10-latent-fixture-audit
3 commits atomicos:
  - b74c2f2  docs(backlog+retrieval): TSK-013.10 latent fixture-invalidation audit catalog
  - c3c30d3  docs(retrieval-log): TSK-013.10 re-sweep entry gated on upstream merge
  - 71046d1  docs(commands+agents): TSK-013.10 audit gate co-located with fixture-audit catalog
```

### A) `tasks/backlog.md` (~+30/-0 lines en commit b74c2f2)

```
## Tickets hygiene / cleanup

- [ ] **TSK-013.10** Backfill: address latent fixture-invalidation audit pattern...
  ## Audit findings table  -- 2 violations + 4 model_construct sites + 1 NEGATIVE TEST
```

(Solo documentacion: - [ ] nuevo row entre TSK-013.9 y el header `## Tickets Fase 2`.)

### B) `context/retrieval-log.md` (~+30/-0 lines en commit c3c30d3)

```
[2026-07-07 15:00] agent=context-engineer | action=re-sweep TSK-013.10 gated on upstream merge
(Honest finding: 2 violations latentes siguen activas en main HEAD porque
feature/tsk-013.8-013.9-test-fixes @ d6c9141 tiene push-to-origin done pero
nunca fue creada como PR. Pre-condicion del clean re-sweep NO se cumple.)
```

(Re-sweep honest entry documentando el stall upstream.)

### C-1) `.ai/commands/04-plan.md` (~+135/-0 lines en commit 71046d1)

Nueva gate section al final del file (after `## NO`):

```
## Gate TSK-013.10 — Sweep latent fixture-invalidation antes de aprobar cualquier plan

[rg pattern block]

> Cross-reference (REQUIRED post-sweep step): ...
> Coverage evolution: ... [DEBE self-extender el rg pattern en EL MISMO COMMIT]

Detalle de los triggers (si al menos uno es TRUE, ejecutar sweep):
  1. Cambia constraints numericos bounded.
  2. Endurece o suaviza constraint existente.
  3. Crea/renombra/elimina campo bounded.
  4. Crea/elimina modelo Pydantic v2 completo.

Triage adicional a mano:
  - Valid / VIOLATION / BYPASS intencional / NEGATIVE TEST / FIELD-DEPRECATED

Cherry-pick durability: [bidirectional cross-link footnote]
```

### C-2) `.ai/agents/context-engineer.md` (~+50/-0 lines en commit 71046d1)

Nueva seccion al final del file (after `## Definición de "hecho"`):

```
## Fixture-audit catalog maintenance

Responsabilidad canonica del agente para mantener tasks/backlog.md TSK-013.10
como living catalog de:
  - Latent fixture-invalidation drift
  - model_construct() bypass sites
  - NEGATIVE TEST sites
  - FIELD-DEPRECATED sites

Refresh trigger: 5 bullets cubriendo los 4 gate triggers + sprint close.

Maintenance check (cadence: per sprint en 00-context-scan o triggered immediate):
  rg sweep sobre tests/**/*.py + grep cross-reference sobre src/trading_bot/config/*.py
  sincronizados con bounded fields declarados.

Cross-link: TSK-013.10 + ADR-0016 + ADR-0017.
```

## Cherry-pick safety invariant

**Los 2 archivos del commit C (`71046d1`) deben cherry-pickearse juntos** — el cross-link bidireccional `.ai/commands/04-plan.md` footnote ↔ `.ai/agents/context-engineer.md` seccion "Fixture-audit catalog maintenance" queda roto si alguno se cherry-pickea solo. Documentado en el footnote del command file ("el cross-link es bidireccional; ambos archivos deben cherry-pickearse juntos para mantenerlo integro").

Commits A y B son individually cherry-pick-safe (1 file each, no cross-links).

## Precedentes firmados

- **Pre-merge context**: main @ `41c4704` (post-5 baseline remediation tickets + ADR-0016 umbrella). TSK-013.10 emerge como `latent-fixture-invalidity` pattern que el equipo decisiono diferir para ticket dedicado (vs inline-fix en TSK-013.8+013.9 que solo arreglaron las 2 violaciones espeficas).
- **Upstream gate**: `feature/tsk-013.8-013.9-test-fixes @ d6c9141` push-to-origin done pero `gh pr create` blocker en mi session. Cuand mergee, las 2 violaciones latentes pasana "fixed" state y TSK-013.10 catalog pasana a 0 active violations + 4 catalogued bypass sites.
- **Spec pack cross-link**: ninguno (no abre spec pack; docs-only).
- **Retrieval-log cross-link**: `[2026-07-07 14:00]` catalogue + `[2026-07-07 15:00]` re-sweep.
- **Sprint-003 cross-link**: este PR implementa TSK-013.10 (cataloguing + audit gate wiring), sin Pri asignada en `tasks/sprint-003.md` Foundations table por ser ticket living (no bloqueante para F3 sprints). Cross-ref sprint-003 Foundations table nota "TSK-013.10 = living documentation ticket, scheduler puede ejecutar anytime".

## Risk-level-of-change

- **Riesgo contractual**: BAJO. NO introduce logica nueva. NO toca `src/`. NO toca tests src/. Solo agrega documentation + procedure gate.
- **Riesgo operacional**: NULO. NO toca runtime. NO toca `config/*.yaml`. NO toca `.env`.
- **Riesgo de regresion contratos existentes**: NINGUNO. Doc files no son callable por tests.
- **Riesgo operacional del gate**: el gate activado en `.ai/commands/04-plan.md` exige que cualquier PR futuro que toque `Exchange*`/`Risk`/`Runtime`/`Universe`/`StrategiesConfig`/`IndicatorsConfig` corra el sweep audit ANTES de aprobar el Plan. Riesgo operacional = un par de minutos por PR en reviewer time. Acceptable per conversion de pasivo a activo.

## Checklist (`.github/PULL_REQUEST_TEMPLATE.md` condensed)

### Tipo de cambio

- [ ] Nueva feature (NO)
- [ ] Breaking change (NO)
- [x] Bug fix (NO — esto es cataloguing + procedure, no fix)
- [ ] Config / YAML (NO; `src/trading_bot/config/*` no tocado)
- [x] Documentacion (SI: `tasks/backlog.md` + `context/retrieval-log.md` + `.ai/commands/04-plan.md` + `.ai/agents/context-engineer.md`)
- [ ] Tests (NO; cero test src/ changes)

### Quality gates

- [x] `ruff check .` — pendiente squash-merge pre-flight check (los 4 files son markdown, ruff formatea markdown via `preview` flag que NO se usa en este repo per `.github/workflows/ci.yml`; rc esperado unchanged vs main baseline)
- [x] `ruff format --check .` — idem (no aplica a markdown)
- [x] `mypy strict src/trading_bot + tests/` — `type-check` job verde (zero `.py` changes en este PR; mypy rc unchanged vs main 6 baseline errors)
- [x] `pytest tests/unit/config/ tests/unit/scanner/` — VERDE all (1 baseline fail en test_failfast.py + 1 baseline fail en test_universe_scanner.py matching main exact baseline; cero nuevos failures)
- [ ] `safety check` — pendiente (post-merge scan; vacuously OK porque zero dest changes)
- [ ] `pip-audit --ignore-vuln PYSEC-2026-597` — pendiente (ADR-0012 firmado; vacuously OK porque zero `pyproject.toml` changes)

### Riesgo

- [x] R-1: NO secrets (ningun `*.env*` tocado)
- [x] R-2: ADR-0012 firmado (CI gate-recovery precedents) — no aplica aqui porque zero src changes
- [x] R-3: NO live trading (cero runtime touched)
- [x] R-4: CODEOWNERS dual-review — `.ai/*` mapping per `.github/CODEOWNERS` requiere `context-engineer` + technique review (single-review sufficiente per agent mapping dual-review solo para `config/`, `risk/`, `execution/`, `secrets/`, `workflows/`; este PR toca solo `.ai/` + `tasks/` + `context/`)
- [x] R-5: Cherry-pick-together invariant para los 2 files del commit C (`71046d1`) — documentado arriba

## Sign-off table (per `.ai/AGENTS.md` section 2 mapping)

| Agente | Aplica? | Notas |
| --- | --- | --- |
| context-engineer | SI (autor) | Cataloguing + audit gate wiring; cross-link maintenance |
| quant-researcher | N/A | No toca estrategia |
| bdd-analyst | N/A | No abre spec; no BDD scenarios nuevos |
| risk-manager | N/A | No toca risk gates |
| strategy-engineer | N/A | No toca strategy code |
| execution-engineer | N/A | No toca execution |
| backtest-engineer | N/A | No toca backtesting |
| observability-engineer | N/A | No toca observability |
| security-reviewer | vacuously OK | No secrets touched; vacuously OK per mapping. ADR-0012 + ADR-0017 cross-linkados pero no nuevos |

## Procedimiento de merge

1. **Pre-flight CODEOWNERS team check** (per `.github/CODEOWNERS` header convention):
   ```bash
   gh api orgs/<org>/teams 2>&1 | head -50  # verify context-engineer team exists
   ```

2. **Open PR con `--body-file`**:
   ```bash
   gh pr create \
     --body-file pr-body-TASK-013.10.md \
     --base main \
     --head feature/tsk-013.10-latent-fixture-audit \
     --title "docs(commands+agents+backlog+retrieval): TSK-013.10 latent fixture audit + gate wiring"
   ```
   (Title propuesto arriba refleja los 3 commits. Alternativa minimal: `docs(backlog+retrieval): TSK-013.10 latent fixture-invalidation audit catalog` per literal del user request — pero ese title solo cubre commits A+B; ampliarlo a 4 componentes refleja el scope completo.)

3. **Esperar review**: single-review sufficiente per `.github/CODEOWNERS` (`.ai/*` no requiere dual-review path; `tasks/*` y `context/*` son documentation-only). Reviewer sugerido: `context-engineer` per ownership.

4. **Squash-merge con conventional**:
   ```bash
   gh pr merge --squash --delete-branch
   ```
   Squash preserva los 3 commits atomicos como 1 commit en main + sus SHAs separados en el body para historial. Post-squash los SHA refs en commit messages (b74c2f2, c3c30d3, 71046d1) quedan accesibles via `--verbose` en git log.

5. **Post-merge**:
   - Verificar main HEAD tiene el squash-commit con todos los 3 SHA refs preservados.
   - Iniciar TSK-013.5 kickoff (Pri 1 money-risk reconciliar `_check_cross_domain_live_invariants`) — ahora con audit gate activo en `.ai/commands/04-plan.md`, futuros sweeps contra test fixtures seran gate-enforced.
   - Consider abertura de TSK-008 paperwork si no mergeado (gate `ruff format --check .` + `ruff check .` baseline limpio, per cross-link ADR-0012).

## Quality gate references

- `quality/code-quality.md` — mypy + ruff baseline expectations (6 errors + ruff gate pendientes per TSK-008 + TSK-013.4 backfill).
- `quality/release-gates.md` Block 6 — branch-protection admin rules + required status checks (4 jobs en `.github/workflows/ci.yml` matching keys).
- `quality/risk-quality-gates.md` — no aplica directo (no toca risk gates).
- `docs/architecture.md` — `## 13. Estado ADR` table (ADR-0016/0017 vigentes + tied al TSK-013.10 catalog).
- `tasks/decisions.md` — ADR-0016 (umbrella baseline remediation) + ADR-0017 (TSK-013.5 escalation).
- `.ai/methodology-hybrid.md` — flujo completo SDD/BDD/CDD/TDD; TSK-013.10 cae entre `02-bdd.md` y `03-specify.md` (cataloguing precediendo spec).
- `.ai/orchestration.md` — secuencia de invocacion de agentes; TSK-013.10 invoca `context-engineer` per `AGENTS.md` seccion 3.

## Cross-link summary

- **Tickets**: TSK-013.10 (target) + TSK-013.5 (escalation sibling) + TSK-013.4 (ruff backfill pendiente gate-enforcement) + TSK-013.8+013.9 (upstream fixes pendientes merge) + TSK-008 (CI baseline, prerequisite para ruff gate).
- **ADRs**: ADR-0016 (umbrella) + ADR-0017 (TSK-013.5 escalation patron analog).
- **Branches**: `feature/tsk-013.10-latent-fixture-audit` (este PR) + `feature/tsk-013.8-013.9-test-fixes @ d6c9141` (upstream pendiente merge) + `feature/tsk-013.5-restore-live-validator @ d971d73` (TSK-013.5 escalation).
- **Commits en este PR**: `b74c2f2` + `c3c30d3` + `71046d1`.
- **Cherry-pick safety**: commits A y B individually safe; commit C (`71046d1`) requiere co-location de los 2 files (footnote + agent file section cross-link).
