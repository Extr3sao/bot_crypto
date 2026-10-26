# IMP-SPEC-001 — Decision / Process Quality Score

## Source
SRC-BOOK-001, especially printed pp. 131-154 (exam + final advice); supported by project observability/verification notes SRC-NOTE-005/007/010.

## Source Claim
A trade can make money despite violating the plan, while a losing trade can still have followed the plan correctly.

## Problem
PnL alone cannot tell whether the decision process was compliant and reproducible.

## Current Runtime
Supplied project notes describe Decision Engine, Evidence, verifier and PostTrade/Experience concepts, but no runtime/source code was supplied. Runtime reachability is `UNVERIFIED`.

## Gap
No supplied evidence of an explicit `PROCESS_COMPLIANT` / conformance metric separated from outcome quality.

## Proposed Pattern
Persist an immutable expected-plan contract with each TradeProposal/DecisionTrace and compute a deterministic rule-conformance result after execution/outcome.

## Plane
OBSERVABILITY / POST_TRADE / GOVERNANCE

## Deterministic / Agentic
Conformance calculation deterministic. Agent may explain failure causes but cannot overwrite the score.

## Why
Prevents lucky violations from being learned as good behavior and enables research on decision quality independent of realized return.

## Measurable Hypothesis
Runs with explicit conformance scoring reduce undetected plan violations and improve post-trade defect attribution without changing trading decisions.

## Requirements
- REQ-PQ-001: Bind proposal strategy_id/version, entry_rule_id, exit_rule_id, risk_rule_ids and evidence hashes before authorization.
- REQ-PQ-002: Record deviations with timestamp, rule_id, old/new state and authorizing deterministic rule.
- REQ-PQ-003: Compute `process_compliant` independently of PnL.
- REQ-PQ-004: Winning but non-compliant trades must be classified as process failures, not positive lessons.

## Acceptance Criteria
- ACC-PQ-001: Same DecisionTrace yields same conformance result.
- ACC-PQ-002: Injected unauthorized stop/exit/strategy change is detected.
- ACC-PQ-003: PnL sign does not alter conformance result.

## Architecture Impact
Extension to DecisionTrace/PostTrade schema; likely no new subsystem if these contracts already exist.

## Runtime Reachability
Must be verified against actual runtime in implementation phase.

## Failure Modes
Missing rule IDs, mutable traces, retrospective plan rewriting, agent override of deterministic score.

## Security / Safety
Append-only evidence; builder != verifier for critical conformance checks.

## Tests
UNIT: rule matcher. CONTRACT: immutable trace schema. INTEGRATION: proposal->risk->execution->post-trade. RUNTIME: injected compliant/non-compliant runs. ADVERSARIAL: winning unauthorized trade.

## Metrics
conformance_violation_rate; undetected_violation_rate; false-positive rate; attribution completeness.

## Rollback
Disable derived score without deleting raw trace fields.

## Evidence Required
Runtime traces + injected violation tests + independent verifier report.

## Adoption
ADOPT_P0
