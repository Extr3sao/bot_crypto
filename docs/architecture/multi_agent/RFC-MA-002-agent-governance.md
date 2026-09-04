# RFC-MA-002 — Agent Governance

Status: **IMPLEMENTED_AND_VERIFIED** for MA-0B only.

## Scope

MA-0B provides deterministic registries for immutable agent manifests and
capability policies. It does not dispatch agents, execute actions, or modify
the trading runtime.

## Agent lifecycle

The canonical lifecycle is:

```text
DRAFT → PROBATION → ENABLED → DISABLED → RETIRED
              ↘ DISABLED
              ↘ RETIRED
DISABLED → PROBATION
```

Versions are keyed by `(agent_id, agent_version)` and are never overwritten or
deleted. Invalid transitions fail loudly.

## Capability policy

- Unknown agents and capabilities are denied.
- No policy means deny.
- Explicit deny wins over grant.
- `PRODUCTION_ACTION`, `RISK_OVERRIDE`, and `DIRECT_BROKER_ACCESS` remain
  denied in MA-0 and cannot be granted through the normal API.
- Declared manifest capabilities do not imply effective permissions.

## Verification governance

`VerificationMetadata` records the builder, verifier, artifact, and whether
independent verification is required. When required, builder and verifier
identities must differ. The metadata is immutable and serializable.

## Runtime authority

Registries are **FOUNDATION** components, not trading-authoritative runtime
components. No registry imports or calls `PaperBroker`, `RiskManager`, live
connectors, credentials, or external action providers.
