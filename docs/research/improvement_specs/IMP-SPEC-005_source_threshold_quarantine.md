# IMP-SPEC-005 — Source Threshold Quarantine

## Source
Triggered by multiple numeric prescriptions in SRC-BOOK-001 and by SOURCE-TO-SPEC governance requirements.

## Source Claim
The source supplies absolute thresholds such as 3% breakouts, put/call 1.1/0.7, 1-5-15 exposure, 1/9 filters, 3:1 R/R and 4% pair deviation.

## Problem
External numeric values can be copied into code as if they were validated project policy.

## Current Runtime
No runtime/research-ingestion implementation was supplied.

## Gap
Need a mechanical way to prevent external thresholds from becoming defaults without evidence.

## Proposed Pattern
Every external numeric threshold enters research as `SOURCE_THRESHOLD` with source/location/unit/context and is ineligible for Risk/production config until linked to project evidence and a promotion decision.

## Plane
RESEARCH / GOVERNANCE

## Deterministic / Agentic
Deterministic schema/validation gate.

## Measurable Hypothesis
Quarantine reduces untraceable parameter adoption and makes every threshold decision reproducible.

## Requirements
- REQ-THR-001: Store source threshold and units/context.
- REQ-THR-002: Default adoption state `HYPOTHESIS_TO_VALIDATE`.
- REQ-THR-003: Production config cannot reference unpromoted source threshold.
- REQ-THR-004: Project-derived normalized variants must be labeled separately.

## Acceptance Criteria
- ACC-THR-001: Attempt to promote raw source threshold without evidence fails.
- ACC-THR-002: Registry shows source->experiment->decision lineage.

## Architecture Impact
Research-governance contract only; no trading-runtime behavior in this phase.

## Runtime Reachability
Not applicable until implementation phase.

## Failure Modes
Threshold copied under another name; missing units; silent defaulting.

## Security / Safety
Prevents source authority escalation into capital controls.

## Tests
SCHEMA / CONTRACT / ADVERSARIAL / REGRESSION.

## Metrics
untraced_threshold_count (target 0); rejected promotion attempts; lineage completeness.

## Rollback
Registry-only feature can be disabled without touching trading runtime.

## Evidence Required
Tests proving production/risk config rejects unpromoted source thresholds.

## Adoption
ADOPT_P0
