# RFC-049 POST-CLOSURE REPORT (WP-1 / WP-5)

> What RFC-049 Discovery 2 left behind, now that the closure is committed. Read-only summary:
> the campaign's own artefacts remain the authority for the campaign; this report records the
> state a reader must assume *today*, after ADR-0026.

## 1. Terminal state

```text
RFC_049_DISCOVERY2        = CLOSED
CAMPAIGN_STATE            = DISCOVERY_CAMPAIGN_FAILED   (ST-2, evaluated on ECONOMIC_RESULTS.json)
HYPOTHESIS_001            = CLOSED_REJECTED_DEV_VAL
HYPOTHESIS_002            = CLOSED_REJECTED_DEV_VAL
HYPOTHESIS_BUDGET         = EXHAUSTED_NO_REFILL
SEALED_OOS                = CANCELLED_NOT_OPENED
OOS_OPENED                = FALSE
NEXT_CAMPAIGN             = NOT_AUTHORIZED
PAPER_PROMOTION           = NOT_AUTHORIZED
LIVE_TRADING              = DISABLED
TRADES_AUTHORIZED         = 0
PROFITABILITY_VERIFIED    = FALSE
FALSE_SUCCESS             = 0
```

Both frozen candidates produced a large net on the 2019–2023 development partition and decayed to
non-confirmatory in 2024–2026: the bootstrap LCB turns negative (−619.9 / −293.6 bps), drawdown
breaches the frozen 25 % limit (27.9 % / 35.2 %), neither beats buy-and-hold (−9,788 / −9,281 bps)
or the 200-day trend baseline (−761 / −254 bps), and the ETH replication turns negative in
validation. Technical validity was never the issue: PIT violations 0, counts reproduced exactly
(14/9/23 and 26/22/48), independent verification PASS 37/37 with 8/8 negative controls and
`FALSE_SUCCESS = 0`.

## 2. What the closure did and did not do

| did | did not |
| --- | --- |
| closed the campaign in the terminal state its own stop rule dictates | re-tune, re-open or re-label any candidate |
| retired the single licensed sealed-OOS inspection unused (`1 licensed, 0 used, 1 retired`) | read the sealed window, delete it, or spend the inspection |
| registered the closure as ADR-0026 and as a machine-readable closure record | edit the frozen Phase A declaration (`PREREGISTRATION_MANIFEST.json` is byte-identical) |
| reproduced the RFC-049B verification (66/0) and corrected its two stale hashes | change any threshold, cost model or partition |
| left `NEXT_CAMPAIGN = NOT_AUTHORIZED` | create any new hypothesis, budget or authorization |

The frozen manifest still says `gate.authorized: false` with
`reason: "NEXT_CAMPAIGN = NOT_AUTHORIZED"`. That text is a *Phase A historical record*: it was true
at the freeze and it is superseded forward — but the effective authorization is the same today
(`NOT_AUTHORIZED`), because ADR-0026 consumed the ADR-0025 scope and created no new one. The
campaign-state view resolves exactly this case and shows the supersession trail
(`data/recovery/CAMPAIGN_STATE_VIEW_REPORT.md`).

## 3. Defects still open at closure

| id | severity | state | impact |
| --- | --- | --- | --- |
| `RFC049B-DEF-01` | documentation | open | none (provenance wording; the frozen rule is not edited) |
| `RFC049B-DEF-03` | units | open | none for Phase B (it ingested the frozen snapshot only) |
| `RFC049B-DEF-04` | data revision | open, bounded | bounded (vendor revision, immaterial at this cadence) |
| `RFC049B-DEF-05` | source direction | open | none (no rule changed) |
| `RFC049B-DEF-06` | citation | open | none (registry citation error) |
| `RFC049B-DEF-07` | vendor semantics | open | none at this cadence (2026-10-10 vendor row never consumed) |
| `RFC049B-DEF-08` | signal attribution | open | none for the recorded result; relevant to any future re-specification |
| `RFC049B-DEF-09` | power | **confirmed and kept** | the 20-trip floor is unreachable inside the 24-month sealed window at the measured turnover |
| `RFC049C-DEF-01` | bookkeeping | **corrected** by the verifier re-run | none |
| `DEF-ACT-01/02/03` | evidence provenance | open (WP-3 audit) | block promotion, not measurement |

## 4. What would reopen the question

The entry condition is recorded in the closure and repeated here without amendment: a **new
hypothesis** whose turnover-adjusted gross edge is expected to clear the frozen 23.353553391 bps per
round trip at its own cadence, registered with a new id, a new experimental budget and an explicit
operator authorization. A new campaign brings its **own** freeze timestamp and its own sealed
forward window; it may not claim the 2026-10-11 window, which was defined for H-049-001/H-049-002
and retired with them. A reversal of ADR-0026 could re-arm the gate as a data-collection schedule,
but it cannot resurrect a closed candidate: a restatement of those rules is a new hypothesis.

The hypotheses are *closed on their computable criteria*, not disproved forward. That question stays
deliberately unanswered, and no future reader may cite the frozen gate text as evidence that an
opening is still pending.

```text
PROFITABILITY_VERIFIED = FALSE
```
