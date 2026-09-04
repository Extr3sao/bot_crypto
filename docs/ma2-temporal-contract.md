# MA-2 Temporal Contract (CP-MA-002.1)

> Canonical reference for every temporal comparison on the MA-2 decision path.
> Scope: `src/trading_bot/multi_agent/` (MA-2-owned modules only). Established by
> checkpoint **CP-MA-002.1** in response to defect **DEF-MA2-003**.

## 1. Canonical clock source

Exactly one temporal authority exists per MA-2 evaluation pass:

```text
Run Clock (injected into AgentBus at construction)
   │  AgentBus.now() is the only decision-time accessor
   ├── AgentBus            → message expiry / future-dating / evidence availability
   ├── SpecialistSwarm     → all message created_at, proposal expires_at
   ├── TradeProposal       → timestamps derived from the same run clock
   ├── OpportunityBoard    → admission/expire_stale/rank `now`
   └── MetaRanker          → freshness via proposal fields (relative, clock-free)
```

- `AgentBus.__init__(..., clock=...)` is a **required keyword** — no default, no
  wall-clock fallback (DEF-MA2-001). Constructing without `clock=` raises `TypeError`.
- `AgentBus.now()` exposes the injected clock as the single public decision-time accessor.
- `SpecialistSwarm.evaluate()` derives `decision_time = bus.now()` at pass start;
  there is **no** evaluate-level time override (`run_time=` was removed as a
  second authority).
- `OpportunityBoard(run_id=..., now=...)` takes the run time explicitly; swarm
  callers pass the same value that was injected into the bus clock.

## 2. Temporal invariants

```text
decision_time = canonical run time          (AgentBus.now())

data_time    <= decision_time               (no future data)
created_at   <= decision_time               (no future-dated artifacts)
proposal currently valid  iff
    proposal.created_at <= decision_time < proposal.expires_at
```

Fail-closed behavior:

| Condition                                   | Verdict                              | Raised by |
| ------------------------------------------- | ------------------------------------ | --------- |
| `expires_at is not None and now >= expires_at` | `ExpiredMessageError` (bus) / admission rejected (board) | `AgentBus._validate`, `OpportunityBoard.add` |
| `created_at > now`                          | fail-closed (`ExpiredMessageError` "future-dated" / "future proposal") | `AgentBus._validate`, `OpportunityBoard.add` |
| `data_time > created_at`                    | schema invalid (proposal never constructible) | `TradeProposal` model validator |

## 3. Deterministic replay law

```text
same inputs + same run clock = same temporal validity
```

For identical fixture inputs and an identical injected run clock, every replay
must produce structurally equal `AssetAssessment`s, `TradeProposal`s, accepted
`AgentMessage`s, `OpportunityBoard` snapshot (opportunities and conflicts),
and `MetaRanker` output. Enforced by `test_t4_deterministic_replay` and
`test_deterministic_replay`.

## 4. Wall-clock classification policy

Occurrences of `datetime.now` / `datetime.utcnow` / `date.today` / `time.time`
in MA-2-owned code are classified:

| Class                 | Rule |
| --------------------- | ---- |
| `DECISION_TIME`       | Forbidden. Must use the injected run clock. Audited by `test_no_datetime_now_in_*` (AST). |
| `OPERATIONAL_LOG_TIME`| Allowed only outside the decision path, clearly separated. |
| `TEST_ONLY`           | Allowed in tests, never imported by decision code. |

Current inventory:

| Location | Use | Class |
| -------- | --- | ----- |
| `multi_agent/bus.py` | none — clock is injected | — |
| `multi_agent/swarm.py` | none — derives from `bus.now()` | — |
| `multi_agent/opportunity.py` | none — `now` injected/explicit | — |
| `multi_agent/specialists.py` | none — timestamps derive from data timestamps | — |
| `multi_agent/session.py` | `datetime.now(UTC)` only when a real deadline exists (live-session timeout) | `OPERATIONAL_LOG_TIME` (non-decision) |
| `multi_agent/blackboard.py` | none found | — |

## 5. Regression guardrails

- `test_bus_requires_explicit_clock` — fails if the bus silently regains a wall-clock default.
- `test_bus_rejects_message_when_wall_clock_is_far_ahead` — reproduces the original
  2026-01 vs 2026-09 defect at bus level; passes only with an injected run clock.
- `test_swarm_derives_all_timestamps_from_bus_clock` — fails if any MA-2 timestamp
  source drifts from the bus clock or if a `run_time=` override reappears.
- `test_no_datetime_now_in_{swarm,opportunity,bus,specialists}` — AST audit, fails
  on any wall-clock call in MA-2 decision code.
