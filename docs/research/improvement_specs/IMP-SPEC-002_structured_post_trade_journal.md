# IMP-SPEC-002 — Structured Post-Trade Journal

## Source
SRC-BOOK-001 printed p.151 (PDF p.152).

## Source Claim
Record asset, entry, stop, target, strategy modifications, reason, result and mistakes for each operation.

## Problem
Narrative memory alone is hard to audit, aggregate and test.

## Current Runtime
Architecture notes describe Decision/Evidence logs and Experience Memory. Runtime implementation is unverified.

## Gap
Need explicit source-to-existing-schema mapping before adding any journal feature.

## Proposed Pattern
Reuse DecisionTrace + Outcome + PostTrade + FailureMemory if present. Add fields only if evidence shows a real gap: pretrade intent, authorized modifications, outcome, conformance violations and post-trade lesson/hypothesis link.

## Plane
POST_TRADE / MEMORY / OBSERVABILITY

## Deterministic / Agentic
Raw event capture deterministic; agent commentary optional and non-authoritative.

## Measurable Hypothesis
Structured fields increase reproducibility and defect discovery versus free-text notes while avoiding duplicate state.

## Requirements
- REQ-JRN-001: No duplicate source of truth for PnL/risk/execution.
- REQ-JRN-002: Every modification links to rule_id and prior state.
- REQ-JRN-003: Lessons can create research hypotheses, never production changes.

## Acceptance Criteria
- ACC-JRN-001: A complete trade can be reconstructed without narrative memory.
- ACC-JRN-002: Missing required fields fail loudly.

## Architecture Impact
Prefer schema extension, not a new database/subsystem.

## Runtime Reachability
Unverified until source repository audit.

## Failure Modes
Duplicate ledgers, mutable history, narrative overriding numeric truth.

## Security / Safety
Immutable audit evidence; no secrets in memory.

## Tests
UNIT / CONTRACT / INTEGRATION / RUNTIME / ADVERSARIAL.

## Metrics
trace completeness; reconstruction success; duplicate-state defects; post-trade hypothesis yield.

## Rollback
Stop deriving journal views; preserve raw event evidence.

## Evidence Required
Schema audit + replay tests.

## Adoption
ADOPT_P1
