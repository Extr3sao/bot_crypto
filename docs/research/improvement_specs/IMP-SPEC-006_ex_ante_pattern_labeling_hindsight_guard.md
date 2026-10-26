# IMP-SPEC-006 — Ex Ante Pattern Labeling Hindsight Guard

## Source
SRC-MANUAL-001 pp.70-72

## Source Claim
Pattern labels that are changed after seeing the outcome invalidate predictive evaluation.

## Problem
Research artifacts can silently classify “Order Block”, swing, regime or setup after future bars are visible.

## Current Runtime
UNKNOWN. The supplied architecture documents are not proof of runtime reachability or implementation.

## Gap
Must be determined by later SOURCE-RUNTIME RECONCILIATION.

## Proposed Pattern
Freeze every material pattern/regime label at `decision_time` with detector version, inputs and evidence refs. Later outcome may evaluate the label, never rewrite it.

## Plane
RESEARCH / OBSERVABILITY / GOVERNANCE

## Deterministic / Agentic
Deterministic contract/trace enforcement. Agents may propose/review evidence but cannot override the guard.

## Why
Prevents source interpretation and execution plumbing from creating false confidence or hidden risk.

## Measurable Hypothesis
The pattern should reduce hindsight contamination / ambiguous causal attribution / unprotected execution states without materially increasing false rejection or latency.

## Requirements
- REQ-006-001: Structured state with explicit provenance and timestamp.
- REQ-006-002: Fail closed on missing critical evidence.
- REQ-006-003: Record counter-evidence and failure reason.
- REQ-006-004: No automatic production promotion.

## Acceptance Criteria
- ACC-006-001: Adversarial test cannot bypass the invariant.
- ACC-006-002: Replay reconstructs inputs, rule version, result and evidence.
- ACC-006-003: Independent verifier can reproduce the decision.

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
