## Resumen

Cierra **TSK-013.10** como PR docs-only (cataloguing) sobre `main @ 41c4704` (post-5 baseline remediation tickets + ADR-0016 umbrella + ADR-0017 escalation per `tasks/decisions.md`).

2 commits atomicos en branch `feature/tsk-013.10-catalogue-only` (slim from `feature/tsk-013.10-latent-fixture-audit` @ `71046d1`):

- **A) `b74c2f2 docs(backlog+retrieval): TSK-013.10 latent fixture-invalidation audit catalog`** — abre el ticket en `tasks/backlog.md` entre TSK-013.9 y `## Tickets Fase 2` con la audit findings table (2 violaciones latentes + 4 sites `model_construct()` bypass + 1 NEGATIVE TEST site). Retrieval-log entry `[2026-07-07 14:00]` con sweep results verbatim. **0 src/ + 0 test src/ changes** (catalogacion, no fix).
- **B) `c3c30d3 docs(retrieval-log): TSK-013.10 re-sweep entry gated on upstream merge`** — honest re-sweep confirmando que las 2 violaciones latentes siguen activas en main HEAD porque `feature/tsk-013.8-013.9-test-fixes @ d6c9141` fue push-to-origin pero nunca mergeado (gh CLI sin auth bloqueo `gh pr create` en mi session). Documenta el stall para el operador. **0 src/ + 0 test src/ changes**.

**Audit gate wiring (commit `71046d1`)** se difiere a un PR separado posterior (`docs(commands+agents): TSK-013.10 audit gate co-located with fixture-audit catalog`) — la razon principal del slim split es que el audit gate requiere dual-file co-location per round-5 reviewer recommendation ("squash both files together; never cherry-pick 04-plan alone"), y preferimos reviewar el catalog solo primero.

**Validacion baseline**: 0 src/ + 0 test src/ changes. Mypy 6 baseline errors unchanged. Pytest 2 baseline fails unchanged (1 config failfast TSK-013.5 + 1 scanner universe_scanner cosmetico).

## Ticket / ADR

- **Ticket cerrado**: **TSK-013.10** (`tasks/backlog.md`) — Pri 6 = latent fixture drift, Risk L (no impact runtime).
- **ADR cross-link**:
  - **ADR-0016** (umbrella TSK-013.5..013.9 baseline remediation que origino el cataloguing).
  - **ADR-0017** (TSK-013.5 escalation con patron analog de latent drift en pydantic-settings v2.14.2 wrapper).
- **Ninguna nueva ADR requerida** — la decision cataloguing + slim split queda registrada en este PR body + 2 commit messages.
- **Cross-link upstream**: las 2 violations latentes originales (`rate_limit_ms=10 < ge=50` y `max_backoff_ms=50 < ge=100` en `tests/unit/market_data/test_ccxt_connector.py::fast_retry_exchange_cfg`) ya corregidas en `feature/tsk-013.8-013.9-test-fixes @ d6c9141`. Ese PR queda como upstream pre-requisito: cuando mergee, libera las 2 violations y deja el gate con 0 active violations + 4 catalogued `model_construct()` bypass sites como deuda potencial.
- **Cross-link downstream (follow-up PR)**: el audit gate wiring (`71046d1`) en `.ai/commands/04-plan.md` + `.ai/agents/context-engineer.md` sera un PR subsecuente en `feature/tsk-013.10-latent-fixture-audit` (branch original pre-split). Espera al merge de este catalogue PR + al merge de `feature/tsk-013.8-013.9-test-fixes @ d6c9141`.

## Convencion tipada + diff inventario

### Branch

```
feature/tsk-013.10-catalogue-only
2 commits atomicos cherry-pickeados de feature/tsk-013.10-latent-fixture-audit:
  - b74c2f2  docs(backlog+retrieval): TSK-013.10 latent fixture-invalidation audit catalog
  - c3c30d3  docs(retrieval-log): TSK-013.10 re-sweep entry gated on upstream merge
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

## Independence invariant

Este PR es **completamente independiente** del upstream `feature/tsk-013.8-013.9-test-fixes @ d6c9141`:

- Este PR toca 0 archivos `tests/`, 0 archivos `src/`, 0 archivos `config/`.
- El upstream PR toca 2 archivos `tests/` (`tests/unit/market_data/test_ccxt_connector.py` + `tests/unit/scanner/test_universe_scanner.py`), 0 archivos `src/`, 0 archivos `config/`.
- No hay overlap de archivos modificados, no hay merge conflict surface.
- Cualquiera puede mergear primero sin bloquear al otro.

Este PR es **tambien independiente** del audit gate follow-up PR (commit `71046d1` en `feature/tsk-013.10-latent-fixture-audit` original):

- Este PR toca 0 archivos `.ai/`.
- El follow-up PR tocara 2 archivos `.ai/` (`.ai/commands/04-plan.md` + `.ai/agents/context-engineer.md`).
- Cero overlap, cero merge conflict surface.
- Orden sugerido (no obligatorio, basado en reviewer load + logica de desbloqueo): este PR (catalogue) → upstream `feature/tsk-013.8-013.9-test-fixes` → follow-up audit gate PR, porque catalogue es docs-only y revisa rapido, upstream arregla las violations, y audit gate depende de los 2 anteriores ya mergeados.

## Slim cherry-pick note

> **Por que esta seccion es mas corta que en `pr-body-TASK-013.10.md` (full scope)**: la version full incluye una seccion "Cherry-pick safety invariant" advirtiendo sobre co-location de `.ai/commands/04-plan.md` + `.ai/agents/context-engineer.md` (per round-5 reviewer recommendation). En esta slim version, ese invariant NO aplica porque el audit gate wiring (commit `71046d1`) esta diferido a un PR subsecuente. Los 2 commits de este PR (`b74c2f2` + `c3c30d3`) son individually cherry-pick-safe (1 file each, no cross-links).

## Repro audit trail

> **Post-merge verification path for reviewers**: this section documents the 3 reproducibility handles the operator commits after `git rebase origin/main` + `bash scripts/tsk-013.10-resweep.sh` succeeds on `feature/tsk-013.10-latent-fixture-audit`. All 3 land in the clean re-sweep entry in `context/retrieval-log.md` (see the "Slim cherry-pick note" above for the slim 2-commit scope rationale that motivates separating the catalogue from the clean re-sweep signal).

- **Sample output**: `/tmp/tsk-013.10-resweep-sample.txt` (produced by `tee` in the post-merge fire sequence per `fire-commands-TASK-013.10.md`; full script output: PASS 1 + PASS 2 + Drift invitation + manual triage reminder + SUMMARY + STATUS TILT).
- **Commit SHA**: `<paste REPO_SHA from the fire sequence; this is the local HEAD on `feature/tsk-013.10-latent-fixture-audit` AFTER `git rebase origin/main`>`
- **Date**: `<paste DATE from the fire sequence; ISO-8601 with timezone, e.g. `2026-07-15T10:42:31+02:00`>`

> **Operator fill-in source**: see `fire-commands-TASK-013.10.md` for the post-merge fire sequence + clean re-sweep entry template (line 77). The 3 placeholders in this pr-body map directly to the fire sequence output.

**How reviewers verify the clean state themselves**:

1. Read `/tmp/tsk-013.10-resweep-sample.txt` (full script output: PASS 1 rg sweep + PASS 2 grep + Drift invitation token list + manual triage reminder + SUMMARY + STATUS TILT verdict).
2. Spot-check PASS 1 hits against the 4 `model_construct()` sites catalogued in the **Audit findings table** of the **TSK-013.10** entry in `tasks/backlog.md` (commit `b74c2f2` in this PR). All hits should classify as `[VALID]` (value >= constraint floor) or `[BYPASS intencional]` (one of the 4 catalogued sites); no `[VIOLATION]` or `[FIELD-DEPRECATED]` hits expected.
3. Confirm the STATUS TILT line in the sample matches the post-merge expectation: `[STATUS: NEEDS-TRIAGE]` if PASS 1 `hit_count > 0` (manual triage applied), or `[STATUS: CROSS-CHECK-DRIFT-ONLY]` if `hit_count == 0` (positive signal that upstream constraint hardening removed the candidate surface).
4. Optionally re-fire the audit gate deterministically: `git checkout <REPO_SHA> && bash scripts/tsk-013.10-resweep.sh` (same input → same output; PASS 1 + PASS 2 + Drift invitation are reproducible).

**Cross-link**: the clean re-sweep entry in `context/retrieval-log.md` is the canonical reference for the audit trail. Commit `c3c30d3` in this PR is the gated-on-merge entry (intermediate status, 2 violations still active on main). The post-merge clean re-sweep entry is a follow-up commit on `feature/tsk-013.10-latent-fixture-audit` (NOT part of this slim 2-commit scope) — see "Cross-link downstream (follow-up PR)" under "Ticket / ADR" above for the full dependency chain.

## Precedentes firmados

- **Pre-merge context**: main @ `41c4704` (post-5 baseline remediation tickets + ADR-0016 umbrella). TSK-013.10 emerge como `latent-fixture-invalidity` pattern que el equipo decisiono diferir para ticket dedicado (vs inline-fix en TSK-013.8+013.9 que solo arreglaron las 2 violaciones espeficas).
- **Upstream gate**: `feature/tsk-013.8-013.9-test-fixes @ d6c9141` push-to-origin done pero `gh pr create` blocker en mi session. Cuand mergee, las 2 violaciones latentes pasana "fixed" state y TSK-013.10 catalog pasana a 0 active violations + 4 catalogued bypass sites.
- **Spec pack cross-link**: ninguno (no abre spec pack; docs-only).
- **Retrieval-log cross-link**: `[2026-07-07 14:00]` catalogue + `[2026-07-07 15:00]` re-sweep.
- **Sprint-003 cross-link**: este PR implementa TSK-013.10 catalogue, sin Pri asignada en `tasks/sprint-003.md` Foundations table por ser ticket living (no bloqueante para F3 sprints). Cross-ref sprint-003 Foundations table nota "TSK-013.10 = living documentation ticket, scheduler puede ejecutar anytime".

## Risk-level-of-change

- **Riesgo contractual**: BAJO. NO introduce logica nueva. NO toca `src/`. NO toca tests src/. Solo agrega documentation + retrieval-log entry.
- **Riesgo operacional**: NULO. NO toca runtime. NO toca `config/*.yaml`. NO toca `.env`.
- **Riesgo de regresion contratos existentes**: NINGUNO. Doc files no son callable por tests.

## Checklist (`.github/PULL_REQUEST_TEMPLATE.md` condensed)

### Tipo de cambio

- [ ] Nueva feature (NO)
- [ ] Breaking change (NO)
- [x] Bug fix (NO — esto es cataloguing, no fix)
- [ ] Config / YAML (NO; `src/trading_bot/config/*` no tocado)
- [x] Documentacion (SI: `tasks/backlog.md` + `context/retrieval-log.md`)
- [ ] Tests (NO; cero test src/ changes)

### Quality gates

- [x] `ruff check .` — pendiente squash-merge pre-flight check (los 2 files son markdown, ruff formatea markdown via `preview` flag que NO se usa en este repo per `.github/workflows/ci.yml`; rc esperado unchanged vs main baseline)
- [x] `ruff format --check .` — idem (no aplica a markdown)
- [x] `mypy strict src/trading_bot + tests/` — `type-check` job verde (zero `.py` changes en este PR; mypy rc unchanged vs main 6 baseline errors)
- [x] `pytest tests/unit/config/ tests/unit/scanner/` — VERDE all (1 baseline fail en test_failfast.py + 1 baseline fail en test_universe_scanner.py matching main exact baseline; cero nuevos failures)
- [ ] `safety check` — pendiente (post-merge scan; vacuously OK porque zero src changes)
- [ ] `pip-audit --ignore-vuln PYSEC-2026-597` — pendiente (ADR-0012 firmado; vacuously OK porque zero `pyproject.toml` changes)

### Riesgo

- [x] R-1: NO secrets (ningun `*.env*` tocado)
- [x] R-2: ADR-0012 firmado (CI gate-recovery precedents) — no aplica aqui porque zero src changes
- [x] R-3: NO live trading (cero runtime touched)
- [x] R-4: CODEOWNERS dual-review — `tasks/*` y `context/*` mapping per `.github/CODEOWNERS` (single-review sufficiente; review por `context-engineer` per ownership)
- [x] R-5: Independence confirmed contra `feature/tsk-013.8-013.9-test-fixes` y contra follow-up audit gate PR

## Sign-off table (per `.ai/AGENTS.md` section 2 mapping)

| Agente | Aplica? | Notas |
| --- | --- | --- |
| context-engineer | SI (autor) | Cataloguing + retrieval-log maintenance; cross-link maintenance |
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
   gh api orgs/<OWNER>/teams 2>&1 | head -50  # verify context-engineer team exists (sustituir <OWNER> por el org real del repo)
   ```

2. **Open PR con `--body-file`**:
   ```bash
   gh auth login
   gh pr create \
     --body-file pr-body-TASK-013.10-catalogue-only.md \
     --base main \
     --head feature/tsk-013.10-catalogue-only \
     --title "docs(backlog+retrieval): TSK-013.10 latent fixture-invalidation audit catalog"
   ```

3. **Esperar review**: single-review sufficiente per `.github/CODEOWNERS` (`tasks/*` y `context/*` no requieren dual-review path). Reviewer sugerido: `context-engineer` per ownership.

4. **Squash-merge con conventional**:
   ```bash
   gh pr merge --squash --delete-branch
   ```
   Squash preserva los 2 commits atomicos como 1 commit en main + sus SHAs separados en el body para historial. Post-squash los SHA refs en commit messages (b74c2f2, c3c30d3) quedan accesibles via `--verbose` en git log.

5. **Post-merge**:
   - Verificar main HEAD tiene el squash-commit con los 2 SHA refs preservados.
   - Iniciar el upstream PR (`feature/tsk-013.8-013.9-test-fixes @ d6c9141`) si no mergeado aun — la unblock condition del re-sweep.
   - Programar el follow-up audit gate PR (commit `71046d1` en `feature/tsk-013.10-latent-fixture-audit`) para despues de los dos anteriores.

## Quality gate references

- `quality/code-quality.md` — mypy + ruff baseline expectations (6 errors + ruff gate pendientes per TSK-008 + TSK-013.4 backfill).
- `quality/release-gates.md` Block 6 — branch-protection admin rules + required status checks (4 jobs en `.github/workflows/ci.yml` matching keys).
- `docs/architecture.md` — `## 13. Estado ADR` table (ADR-0016/0017 vigentes + tied al TSK-013.10 catalog).
- `tasks/decisions.md` — ADR-0016 (umbrella baseline remediation) + ADR-0017 (TSK-013.5 escalation).
- `.ai/methodology-hybrid.md` — flujo completo SDD/BDD/CDD/TDD; TSK-013.10 cae entre `02-bdd.md` y `03-specify.md` (cataloguing precediendo spec).
- `.ai/orchestration.md` — secuencia de invocacion de agentes; TSK-013.10 invoca `context-engineer` per `AGENTS.md` seccion 3.

## Cross-link summary

- **Tickets**: TSK-013.10 (target) + TSK-013.5 (escalation sibling) + TSK-013.4 (ruff backfill pendiente gate-enforcement) + TSK-013.8+013.9 (upstream fixes pendientes merge) + TSK-008 (CI baseline, prerequisite para ruff gate).
- **ADRs**: ADR-0016 (umbrella) + ADR-0017 (TSK-013.5 escalation patron analog).
- **Branches**:
  - `feature/tsk-013.10-catalogue-only` (este PR, slim 2 commits)
  - `feature/tsk-013.10-latent-fixture-audit @ 71046d1` (original, sera reusado para el follow-up audit gate PR)
  - `feature/tsk-013.8-013.9-test-fixes @ d6c9141` (upstream pendiente merge, independiente)
  - `feature/tsk-013.5-restore-live-validator @ d971d73` (TSK-013.5 escalation).
- **Commits en este PR**: `b74c2f2` + `c3c30d3`.
- **Commits diferidos a follow-up PR**: `71046d1` (audit gate wiring).
- **Cherry-pick safety**: ambos commits en este PR individually safe (1 file each, no cross-links).
