# Profitability Diagnostics 01 requirements

## Context

The paper runtime has several deterministic multi-agent gates, but its persisted evidence is incomplete. This checkpoint must identify what actually ran, quantify only recorded funnel transitions, and prevent claims about profitability where counterfactual outcomes are unavailable.

## Goals

- **FR-001** Produce a runtime authority map distinguishing runtime paths from test, research, legacy, and orphan code.
- **FR-002** Produce deterministic, read-only funnel and rejection analyses from persisted R2 reports and Shadow artifacts.
- **FR-003** State counterfactual, risk, Critic, MetaRanker, agent-ablation, complexity, frequency, and time-to-falsify results with `UNKNOWN` or `INSUFFICIENT_SAMPLE` when authority is absent.
- **FR-004** Emit the requested Markdown/JSON report set and defect register outside the H6 namespace.
- **FR-005** Prove diagnostics do not modify protected runtime state.

## Non-goals

No H6/H5 economics, no trade execution, no risk/configuration changes, no Shadow resolution, no confirmation use, and no production runtime change.

## Constraints

- **CON-001** Work only in the isolated diagnostics worktree and allowed namespaces.
- **CON-002** Inputs are read-only and reports must use the authority order stated by the checkpoint.
- **CON-003** Economic claims require already-authoritative realized outcomes; counts alone do not establish overfiltering.

## Acceptance criteria

- **AC-001** All fifteen required report artifacts exist under `docs/profitability-diagnostics-01/`.
- **AC-002** Every unknown funnel stage is encoded as `UNKNOWN`, never invented as zero.
- **AC-003** Diagnostics unit tests demonstrate deterministic output and no input-state mutation.
- **AC-004** Focused diagnostics tests pass.
- **AC-005** A verification matrix maps each criterion to direct evidence.
