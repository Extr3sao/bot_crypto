# MA-0A + MA-0B Requirements and Verification Plan

Status: **IMPLEMENTED_AND_VERIFIED** after the recorded validation runs.

## Requirements

- Provide strict, immutable, versioned contracts for manifests, capability
  declarations, messages, evidence, trade proposals, and trace context.
- Reject unknown fields, invalid enum values, confidence outside `[0, 1]`,
  naive timestamps, temporal look-ahead, invalid SHA-256 hashes, identity
  collisions, and nested metadata mutation.
- Represent `NO_TRADE` explicitly.
- Provide versioned agent registration with deterministic lifecycle transitions.
- Provide default-deny capability authorization with explicit deny precedence.
- Keep production action, risk override, and direct broker access denied.
- Keep MA-0 independent from the trading runtime and add no dependencies.
- Produce reproducible validation evidence in Markdown and JSON.

## Acceptance criteria mapping

| Requirement | Acceptance criteria | Verification |
|---|---|---|
| Strict contracts | ACC-MA0A-001/003 | `test_manifest_is_strict_frozen_and_versioned` |
| Immutability | ACC-MA0A-002 | `test_manifest_is_strict_frozen_and_versioned` |
| Confidence validation | ACC-MA0A-004 | `test_message_validates_identity_confidence_and_point_in_time` |
| Time/PIT validation | ACC-MA0A-005/006 | message/evidence/proposal tests |
| Explicit NO_TRADE | ACC-MA0A-007 | `test_trade_proposal_supports_long_short_and_explicit_no_trade` |
| Capability restrictions | ACC-MA0A-008 | capability declaration and policy tests |
| No duplicate proposal vocabulary | ACC-MA0A-009 | RFC decision; existing research `Proposal` retained as a distinct code-generation input |
| No new dependency | ACC-MA0A-010 | `pyproject.toml` unchanged; imports use stdlib/Pydantic only |
| Exact agent versions | ACC-MA0B-001/005 | registry version-retention test |
| Lifecycle governance | ACC-MA0B-003/004 | lifecycle transition test |
| Default deny | ACC-MA0B-007/008/009 | capability registry tests |
| Deny precedence | ACC-MA0B-010 | `test_capability_registry_is_default_deny_and_deny_wins` |
| Permanent MA-0 restrictions | ACC-MA0B-011/012/013 | permanent grant/declaration tests |
| Builder/verifier separation | ACC-MA0B-014/015 | trace contract test and smoke |

## BDD-style scenarios

### Scenario: A valid offline agent is registered

```text
Given an immutable versioned strategy-agent manifest
When the manifest is registered and moved to probation
Then the exact version resolves and remains auditable
```

### Scenario: An agent cannot grant production authority

```text
Given a registered agent and a default-deny capability policy
When production action, risk override, or direct broker access is requested
Then authorization is denied and no runtime component is invoked
```

### Scenario: A future-dated claim is rejected

```text
Given an evidence, message, or proposal timestamped in the future
When its contract is validated
Then validation fails closed
```

### Scenario: NO_TRADE is explicit

```text
Given a valid proposal with direction NO_TRADE
When it is serialized and deserialized
Then the direction remains NO_TRADE and the proposal is not approved for risk review
```

## Non-goals

No bus, dialogue, blackboard, ranker, consensus, runtime integration, LLM,
execution, or live trading is part of this phase.
