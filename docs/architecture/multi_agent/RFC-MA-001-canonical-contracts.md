# RFC-MA-001 — Canonical Multi-Agent Contracts

Status: **IMPLEMENTED_AND_VERIFIED** for MA-0A only.

## Scope

This RFC defines the neutral, deterministic contract layer for future
multi-agent intelligence. It is not wired into the paper trading runtime and
cannot select, size, approve, or execute trades.

## Decisions

- Contracts use Pydantic v2 with `frozen=True`, `extra="forbid"`, and
  `strict=True`.
- Timestamps are timezone-aware `datetime` values. A data timestamp cannot be
  later than the artifact creation timestamp.
- `TradeProposal` is the only canonical trading-proposal vocabulary. The
  existing research-side `Proposal` remains a research code-generation input;
  MA-0 does not create a second runtime trade proposal with the same meaning.
- `NO_TRADE` is an explicit `TradeProposal.direction`, never represented by a
  missing object, empty result, or exception.
- Capability declarations are separate from granted permissions. Capability
  policy is default-deny; explicit deny dominates grant.
- Production action, risk override, and direct broker access cannot be granted
  by MA-0 policy.
- Verification requires distinct builder and verifier identities whenever
  independent verification is requested.
- The contract package has no imports from paper, risk, execution, exchange,
  or runtime orchestration modules.

## Non-goals

MA-0 does not implement AgentBus, Blackboard, conversations, critics,
consensus, ranking, dynamic selection, execution integration, LLM providers,
or new runtime dependencies.

## Runtime authority

The package is a **FOUNDATION** and is not runtime-authoritative for trading.
It becomes runtime-reachable only when a later phase imports it through an
approved adapter and preserves the existing L5 paper boundary.
