# RFC-MA-003 — Deterministic Communication Runtime

Status: **IMPLEMENTED_AND_VERIFIED** for MA-1.

## Scope

MA-1 provides an in-process typed communication plane for registered fixture
agents. It is intentionally not a network broker and has no trading authority.
The runtime is composed of:

```text
AgentMessage → AgentBus → AgentRegistry/CapabilityRegistry → Blackboard
                     ↓
                 CommunicationSession
```

## Decisions

- `AgentBus` accepts only the existing immutable `AgentMessage` contract.
- Sender identity must resolve to an enabled registered version and have
  `WRITE`; direct receivers must resolve to an enabled version and have
  `READ`. Topic subscriptions also require `READ`.
- Message type selects one canonical blackboard topic. A caller cannot publish
  a message under an unrelated topic.
- Evidence-requiring message types must reference evidence registered for the
  same run and trace and available at message time.
- Accepted messages are FIFO, immutable, and duplicate-safe. Reusing an ID
  with identical content is idempotent; reusing it with different content is
  rejected.
- Blackboard history is append-only. Returned values are deep copies so a
  mutable fixture payload cannot corrupt stored history.
- Sessions advance one round per accepted message and terminate with
  `COMPLETED`, `FAILED`, `TIMEOUT`, or `MAX_ROUNDS`. No unbounded loop is
  available in the API.
- Replay consumes the same ordered accepted messages and reconstructs the same
  session state. Trading modules are not imported by the MA-1 package.

## Non-goals

No Redis, Kafka, network broker, LLM provider, specialist agent, consensus,
ranker, RiskManager, PaperBroker, strategy runtime, or live execution is part
of MA-1.

## Fail-closed matrix

| Invalid condition | Result | Side effects |
|---|---|---|
| Unknown sender/receiver | reject | no bus/blackboard append |
| Missing capability/topic/evidence | reject | no trading side effects |
| Invalid, expired, future, or trace-mismatched message | reject | no append |
| Duplicate identical message | idempotent no-op | no duplicate append/delivery |
| Duplicate conflicting message | reject | original state retained |
| Timeout/max rounds | terminal session state | no further communication |
| Blackboard external mutation | isolated by copy | history remains intact |

## Certification evidence

- `tests/unit/multi_agent/test_communication.py`
- `tests/unit/multi_agent/test_fixture_e2e.py`
- `tests/unit/multi_agent/test_architecture.py`
- `reports/multi_agent/ma1/TRACEABILITY_MATRIX.md`
- `reports/multi_agent/ma1/RUN_REPORT.md`
