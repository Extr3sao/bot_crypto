# IMP-SPEC-004 — Entry/Exit Rule Provenance & Conformance

## Source
SRC-BOOK-001 printed pp.96-97 and pp.139-141.

## Source Claim
A position entered by one system should not be managed opportunistically by another; respect the authorized stop/system until its rule says otherwise.

## Problem
Mid-trade strategy switching can make the original risk/expectancy assumptions invalid and hide process drift.

## Current Runtime
TradeProposal/DecisionTrace are part of project target architecture, but runtime schemas are not supplied here.

## Gap
Need an explicit immutable link from an authorized trade to strategy version and allowed exit/stop modification rules.

## Proposed Pattern
`TradeIntent = strategy_id + strategy_version + entry_rule_id + exit_rule_id + risk_plan + allowed_modification_rule_ids + evidence_refs` bound before execution.

## Plane
TRADING_RUNTIME / GOVERNANCE / OBSERVABILITY

## Deterministic / Agentic
Deterministic authorization and conformance. Agents may propose changes only as new research, not mutate an open trade outside allowed rules.

## Measurable Hypothesis
Rule provenance eliminates silent strategy switching and reduces irreproducible exits.

## Requirements
- REQ-PROV-001: Bind strategy/rules before Risk authorization.
- REQ-PROV-002: Every post-entry action references an allowed rule_id.
- REQ-PROV-003: Unknown rule_id -> reject/fail closed.

## Acceptance Criteria
- ACC-PROV-001: Unauthorized exit/stop strategy change is blocked and logged.
- ACC-PROV-002: Replay reconstructs exactly which rule changed the position.

## Architecture Impact
Potential TradeProposal/DecisionTrace contract extension; may require RFC only if current schemas cannot support versioned rule provenance.

## Runtime Reachability
Unverified.

## Failure Modes
Mutable strategy version, implicit/manual overrides, missing rule identifiers.

## Security / Safety
Fail closed on unknown modification rule.

## Tests
CONTRACT / INTEGRATION / RUNTIME / REPLAY / ADVERSARIAL.

## Metrics
unauthorized_action_rate; trace completeness; replay equality.

## Rollback
Versioned schema/config rollback while preserving audit log.

## Evidence Required
Real runtime replay + independent verifier.

## Adoption
ADOPT_P0
