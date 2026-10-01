# SOURCE REVIEW — SRC-NOTE-013

## Metadata

- Title: Rejected Ideas — Approaches Explicitly Discarded and Why
- File: `13_REJECTED_IDEAS.md`
- SHA-256: `42f19a2eb86c11711efa3e37dd7d9e08d0cba7ac85036c70f85e977a13465cc0`
- Type: OTHER / project research note
- Reliability: C (secondary synthesis / architecture evidence)
- Primary/secondary: secondary

## Coverage

- Lines total: 60
- Lines reviewed: 60
- Coverage: 100%
- Review status: SOURCE_REVIEW_COMPLETE for this supplied note.

## Thesis

This document is treated as project research/design evidence. It can establish intended architecture, priorities and prior research conclusions, but it cannot establish that runtime code is implemented, reachable, tested or executed.

## Relevant Claims

### CLAIM-N013-01
- Type: `GOVERNANCE_CLAIM`
- Location: `§1-9`
- SOURCE: Unconstrained chat, pure swarm decision paths, majority voting without evidence, builder self-verification, self-modifying critical risk and LLM-only sizing/execution are rejected.
- INTERPRETATION: Use as a constraint/reference when mapping new trading-source ideas so the ingestion does not duplicate already-designed architecture.
- CURRENT PROJECT: design-level evidence exists in supplied notes; runtime status is not inferable from this source.
- GAP: repository source code, runtime authority map and execution evidence were not supplied in this ingestion.
- HYPOTHESIS: none created solely from this internal note unless it is independently testable and not already represented.
- DECISION: KEEP as project-reference evidence.

### CLAIM-N013-02
- Type: `RESEARCH_CLAIM`
- Location: `§6`
- SOURCE: Additional agents require measurable improvement, not intuition that more agents are better.
- INTERPRETATION: Use as a constraint/reference when mapping new trading-source ideas so the ingestion does not duplicate already-designed architecture.
- CURRENT PROJECT: design-level evidence exists in supplied notes; runtime status is not inferable from this source.
- GAP: repository source code, runtime authority map and execution evidence were not supplied in this ingestion.
- HYPOTHESIS: none created solely from this internal note unless it is independently testable and not already represented.
- DECISION: KEEP as project-reference evidence.

## Quantitative Claims

Any numeric scores, star counts, failure percentages or priority labels in this note remain claims of the note; this ingestion does not independently re-verify them.

## Qualitative Claims

Used primarily for architecture boundaries, research governance and duplication checks.

## Strategy Ideas

No alpha strategy is promoted from this source.

## Risk Ideas

Where present, deterministic-risk boundaries are treated as project design constraints, not as proof of runtime implementation.

## Process Ideas

Keep structured evidence, independent verification, auditable flow and controlled promotion.

## Governance Ideas

Preserve deterministic critical-path authority and FALSE_SUCCESS=0.

## Failure Modes

Main ingestion risk: mistaking architecture intent for implemented runtime.

## Unsupported Claims

External claims embedded in the note were not independently re-sourced in this source-only ingestion phase.

## Project Mapping

Used as current architecture/RFC evidence only. Runtime reachability remains `UNVERIFIED`.

## Existing Capabilities

Architecture/design documents describe intended capabilities; no runtime implementation status is asserted.

## Gaps

- Runtime/source repository not supplied.
- No execution evidence supplied.

## Strategy Candidates

None from this note alone.

## Improvement Specs

No duplicate spec created when the mechanism is already represented by the VNext/RFC notes.

## Risk Specs

No new numeric risk policy derived from this note.

## Experiments Required

Implementation claims require later repository audit and execution evidence.

## Rejected Ideas

See source-specific rejected patterns where applicable; these are preserved as negative project knowledge.

## Adoption Decisions

KEEP_REFERENCE; do not promote design claims to runtime truth.

## Evidence References

- File hash `42f19a2eb86c11711efa3e37dd7d9e08d0cba7ac85036c70f85e977a13465cc0`.

## Final Assessment

Useful as project architecture context and duplication-control evidence. Not sufficient for `ALREADY_IMPLEMENTED` classification.