# CERT-MA4-002 — MA-4 Evidence-Based Decision Engine Certification (post DEF-MA4-003 repair)

```text
CERTIFICATION_ID: CERT-MA4-002
STATUS: MA4_EVIDENCE_BASED_DECISION_ENGINE_CERTIFIED_VNEXT
CERTIFIED_ON: 2026-09-06
REPAIR_COMMIT (certified): 15e7048582d7057622c67c55ca712877cf365b03
   branch feat/poc01-setup (chain 11e76cc -> 57f300f -> 15e7048)
CERTIFICATION_CHECKOUT: .worktrees/cert-ma4-002 (detached @ 15e7048, fresh)
PREDECESSOR: CERT-MA4-001 lineage (CP-MA-004, CP-MA-004.1/2/3) — NOT overwritten
SUPERSEDED_DEFECT: DEF-MA4-003 NATURAL_AGREEMENT_EVIDENCE_AUTHORITY_MISMATCH
AUTHORITY_DECISION: ADR-MA-0009, MODEL A (docs/ma4/ADR-MA-0009-NATURAL-AGREEMENT-EVIDENCE.md)
```

## Scope of the certified change

One deviation from the previously certified MA-4 behavior, resolved by
ADR-MA-0009 MODEL A: `DecisionEngine` (builder) no longer unions
debate-derived supporting refs into `DecisionCandidate.supporting_evidence_refs`.
The candidate's supporting evidence authority is the terminal
`TradeProposal.evidence_refs` set (ADR-MA-0007), unchanged in
`DecisionPackageVerifier` (`decision-package-verifier-v3` — semantics unchanged,
so no v4 bump was required). Debate corroboration remains available in the
`DebateReport` and the candidate's debate provenance fields
(`debate_id`, `debate_outcome`, `material_dissent`, `challenged_by`).
Builder (`decision-engine`) != verifier (`decision-package-verifier`) preserved.

On single-proposal paths the union was already equal to the proposal set, so
the repair is semantically a no-op there: the certified demo fixture E2E
reproduces the certified realized PnL 242.82705154 exactly (§14 record).

## Certification gates (fresh detached checkout @ 15e7048)

| Gate | Result | Evidence |
| --- | --- | --- |
| HEAD exact + worktree clean | PASS | `git rev-parse` = 15e7048582…; `git status` empty |
| `uv sync --frozen` | PASS | lockfile-exact env |
| Original 23 MA-4 gates | PASS | `tests/unit/multi_agent` 186 passed, 1 skip (inapplicable partial-strip variant; full-strip covers it): contracts, terminal resolution, eligibility, scoring provenance, unresolved matrix, revision winner, NO_TRADE matrix, order independence, replay, verifier, cross-run isolation, selected-evidence binding, authoritative debate blockers, boundary/temporal |
| Historical defect gates (DEF-MA4-001/002, RETRY-001 binding, RETRY-2 blockers) | PASS | `TestCrossRunIsolation`, `TestSelectedEvidenceBinding`, `TestAuthoritativeDebateBlockers` + validator checks `run_authority_*`, `selected_evidence_binding`, `authoritative_debate_blocker_rederivation` |
| Natural agreement positive gate | PASS | validator `natural_multi_proposal_agreement_verified`: Momentum LONG + Trend LONG, real MA-3 debate (SUPPORTED, cross-support), engine SELECTED, candidate authority == terminal proposal set, verifier VERIFIED; unit matrix `tests/unit/multi_agent/test_cp_ma4_003_agreement_evidence.py` (11 passed, 1 skip) |
| Agreement evidence adversarial gate | PASS | validator `unauthorized_agreement_evidence_rejected` (unrelated-registered, foreign-run, cross-proposal promotion all REJECTED); unit negatives: unrelated addition, foreign-run addition, counter-promotion, strip, partial strip, swap (order-insensitive set semantics), duplicate ref |
| Single-proposal control | PASS | `test_single_proposal_semantics_unchanged` + demo fixture E2E PnL equality |
| UNRESOLVED control | PASS | engine fail-closed (no selection) AND verifier re-derives blocker from authoritative report → forged-ELIGIBLE package REJECTED |
| INSUFFICIENT_EVIDENCE control | PASS | same two-sided proof as UNRESOLVED |
| TAMPER matrix (T1–T16 classes) | PASS | strip/partial/swap/add/duplicate/unknown/foreign-run/foreign-trace/future/strong-forgery covered in binding/blocker/cross-run test classes |
| Independent validator | 21/21 PASS | `scripts/validate_ma4_decision_engine.py` (19 historical checks unweakened + 2 new CP-MA4-POSTCERT-001 checks) |
| Deterministic replay | PASS | validator `check_replay_determinism` + replay tests (repeated decide() identical) |
| Trace reconstruction | PASS | verifier `trace_complete` + `trace` on every artifact; DemoRecord reconstruction |
| Dependency closure (MA-4 scope) | PASS | all 24 `trading_bot.multi_agent` modules import from the checkout; editable install points at this checkout's own `src`; no `.worktrees` references in source |
| Ruff / Mypy (scoped) | PASS | `src/trading_bot/multi_agent`, validator, tests: 0 findings; mypy clean |
| Full regression (host `EXCHANGE_ID` override neutralized — classified pre-existing env baseline) | PASS | 812 passed, 1 skipped, 0 failed |
| RISK_CALLS from agents | 0 | validator `execution_capability_zero` + `dynamic_execution_boundary` |
| BROKER_CALLS from agents | 0 | same |
| LIVE_CALLS | 0 | same |
| FALSE_SUCCESS | 0 | no fabricated packages (positive scenario runs MA2→MA3→MA4→verifier for real); fixture/public separation respected |

## Verifier version decision

`selected_evidence_binding` semantics did not change — the builder was brought
into conformance with the already-authoritative binding. Per existing version
conventions (v2→v3 bumps accompanied verifier semantic changes), the verifier
remains `decision-package-verifier-v3`.
