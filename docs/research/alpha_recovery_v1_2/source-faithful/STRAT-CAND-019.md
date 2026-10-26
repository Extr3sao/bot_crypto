# STRAT-CAND-019 — SOURCE RECONSTRUCTION (ARP-003 §5)

**Source-faithful status: `BLOCKED_NEEDS_SPEC`** — but the *closest* of the three
to resolvability, because the source names a standard pivot formula. The entry,
confirmation, stop, exit and horizon are still absent.

- Candidate id: `STRAT-CAND-019` (unrenumbered)
- Source: `SRC-MANUAL-002` "Escuela de Traders — Las 101 preguntas…"
- Source location: pp.32-33
- Source claim: *first contact with daily pivot support/resistance may support a
  quick countertrend mean-reversion trade*
- Registry hypothesis: `HYP-027`
- Experiment id: `EXP-028` (design-only; `NEEDS_SPEC`)
- Prior project implementation: `EXP-ARP-005` = **`PROJECT_DERIVED_VARIANT`** (not a
  source-faithful test)

## Rule table (every field classified)

| field | value from source | class |
| --- | --- | --- |
| market | futures / multi-asset, intraday | `SOURCE_EXPLICIT` |
| asset | "multi-asset" | `SOURCE_EXPLICIT` (unspecified which) |
| timeframe | intraday | `SOURCE_EXPLICIT` |
| pivot formula | **"standard pivot formulas"** | `SOURCE_EXPLICIT` (the source names "standard"; the classic floor-trader formula — `PP=(H+L+C)/3`, `R1=2·PP−L`, `S1=2·PP−H` — is `SOURCE_IMPLIED`) |
| data required | previous period's H/L/C | `SOURCE_IMPLIED` (daily pivots use the prior day's HLC) |
| availability timestamp | prior day close → available at next day open | `PROJECT_INTERPRETATION` (UTC alignment is a project choice) |
| entry condition | **"first contact"** with the pivot | `SOURCE_EXPLICIT` (concept) — the *definition of contact* is `UNKNOWN` |
| distance / tolerance | — | `UNKNOWN` |
| confirmation | — | `UNKNOWN` |
| stop | — | `UNKNOWN` |
| exit | **"close quickly"** | `SOURCE_EXPLICIT` (concept) — the *horizon* is `UNKNOWN` |
| target | — | `UNKNOWN` |
| session behavior | — | `UNKNOWN` |
| side | countertrend fade (so: fade from the level) | `SOURCE_EXPLICIT` (direction) |

## Future-bar leakage hazards (§5)

- **prior-day HLC must be closed** before it is used: the pivot for day *D* uses day
  *D−1*'s complete high/low/close. Reading day *D*'s own HLC is leakage.
- **"first contact"** must be evaluated on the bar that first touches the level, and
  the decision must be made from the closed bar (`data_time <= decision_time`).
- If a target is "the opposite pivot", that level may only be used if it was
  computable at the decision time (it is, if it is the same day's pivot set).

## Why the source-faithful experiment is blocked

Four critical rules are absent, and each would have to be invented:

1. **First contact** — no tolerance, so no way to decide when a touch begins.
2. **Confirmation** — none specified.
3. **Stop** — none specified.
4. **Profit horizon / target** — "close quickly" is not a number of bars or a level.

A deterministic test that supplies (touch = high/low crossing the pivot), a stop
(one volatility unit beyond the level) and a target (opposite pivot or session end)
is a `PROJECT_DERIVED_VARIANT` and may not be attributed to the source. The prior
`EXP-ARP-005` result (`REJECT_COSTS`; DEV n 287 gross +2.026 bps; VALIDATION gross
collapsed to −2.803) therefore **does not** refute the source claim.

**Consequence:** `SOURCE_FAITHFUL_EXPERIMENT = BLOCKED_NEEDS_SPEC`.

## Separation from the project variant (§6)

| identity | id | status |
| --- | --- | --- |
| source-faithful | `STRAT-CAND-019-SOURCE` | **BLOCKED_NEEDS_SPEC** (this file) |
| project variant | `STRAT-CAND-019-VARIANT-A` | earlier `EXP-ARP-005` (intraday 5m pivot fade) |
| new project variant | `STRAT-CAND-019-VARIANT-B` | pre-registered here as `EXP-ARP-007` (daily pivot fade, slower horizon) |

`STRAT-CAND-019-VARIANT-B` is the one place where a *slower project variant* is
explicitly allowed (§9: "A slower project-derived variant is allowed, but must be
labeled `PROJECT_DERIVED_VARIANT`"). It is still **not** source-faithful.
