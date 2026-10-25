# IMP-SPEC-007 — Observable Pattern Vs Causal Narrative

## Source
SRC-MANUAL-001, especially pp.2-16 and pp.70-72

## Source Claim
The source mixes observable price structures with causal claims about institutional manipulation/stop hunting.

## Problem
A plausible story can be mistaken for measured mechanism and leak into feature/agent confidence.

## Current Runtime
UNKNOWN. The supplied architecture documents are not proof of runtime reachability or implementation.

## Gap
Must be determined by later SOURCE-RUNTIME RECONCILIATION.

## Proposed Pattern
Store `OBSERVED_PATTERN` separately from `CAUSAL_HYPOTHESIS`; strategy tests may rely on observable data without requiring the causal claim to be true.

## Plane
RESEARCH / GOVERNANCE / MARKET_INTELLIGENCE

## Deterministic / Agentic
Deterministic contract/trace enforcement. Agents may propose/review evidence but cannot override the guard.

## Why
Prevents source interpretation and execution plumbing from creating false confidence or hidden risk.

## Measurable Hypothesis
The pattern should reduce hindsight contamination / ambiguous causal attribution / unprotected execution states without materially increasing false rejection or latency.

## Requirements
- REQ-007-001: Structured state with explicit provenance and timestamp.
- REQ-007-002: Fail closed on missing critical evidence.
- REQ-007-003: Record counter-evidence and failure reason.
- REQ-007-004: No automatic production promotion.

## Acceptance Criteria
- ACC-007-001: Adversarial test cannot bypass the invariant.
- ACC-007-002: Replay reconstructs inputs, rule version, result and evidence.
- ACC-007-003: Independent verifier can reproduce the decision.

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
ADOPT_P0
