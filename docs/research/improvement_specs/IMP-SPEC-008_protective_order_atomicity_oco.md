# IMP-SPEC-008 — Protective Order Atomicity Oco

## Source
SRC-MANUAL-002 pp.38-39

## Source Claim
Bracket orders pair an entry with protective stop and profit target, canceling the remaining exit after one fills.

## Problem
If entry succeeds while protective orders fail or diverge, authorized risk intent can be temporarily violated.

## Current Runtime
UNKNOWN. The supplied architecture documents are not proof of runtime reachability or implementation.

## Gap
Must be determined by later SOURCE-RUNTIME RECONCILIATION.

## Proposed Pattern
Audit runtime/broker semantics for atomic or compensating OCO protection. On failed protection, fail closed/cancel/flatten according to deterministic execution policy and emit trace evidence.

## Plane
EXECUTION / RISK / OBSERVABILITY

## Deterministic / Agentic
Deterministic contract/trace enforcement. Agents may propose/review evidence but cannot override the guard.

## Why
Prevents source interpretation and execution plumbing from creating false confidence or hidden risk.

## Measurable Hypothesis
The pattern should reduce hindsight contamination / ambiguous causal attribution / unprotected execution states without materially increasing false rejection or latency.

## Requirements
- REQ-008-001: Structured state with explicit provenance and timestamp.
- REQ-008-002: Fail closed on missing critical evidence.
- REQ-008-003: Record counter-evidence and failure reason.
- REQ-008-004: No automatic production promotion.

## Acceptance Criteria
- ACC-008-001: Adversarial test cannot bypass the invariant.
- ACC-008-002: Replay reconstructs inputs, rule version, result and evidence.
- ACC-008-003: Independent verifier can reproduce the decision.

## Architecture Impact
Fits existing research/observability/execution boundaries; no new RFC justified during ingestion.

## Runtime Reachability
UNKNOWN until code audit.

## Failure Modes
Silent fallback; stale state; post-hoc rewrite; source narrative treated as fact; broker partial failure; missing trace.

## Security / Safety
No LLM authority over Risk, sizing, accounting or execution constraints.

## Tests
UNIT / CONTRACT / INTEGRATION / RUNTIME / ADVERSARIAL / REGRESSION.

## Metrics
violation_count; untraceable_state_count; false_rejection_rate; replay_success_rate; latency where applicable.

## Rollback
Feature-gated implementation; restore previous deterministic contract while preserving audit evidence.

## Evidence Required
Tests + real reachable runtime execution evidence + independent verification.

## Adoption
ADOPT_P1
