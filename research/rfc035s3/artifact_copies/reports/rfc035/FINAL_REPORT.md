# RFC-035 — EXTERNAL PROFITABLE OPPORTUNITY DISCOVERY

```text
RFC-035 STATUS          = OPEN_NO_REPLICABLE_EXTERNAL_STRATEGY  (RFC-035E returned EFFECT_NOT_REPRODUCED)
PHASE                   = DISCOVERY_AND_SELECTION   (no backtest, no implementation)
ACTIVE_RFC              = RFC-035
SOURCE COMMIT           = 7e21f7ca6dbf8816d83f2f8ab15aeb09310b878c
BASELINE                = reports/rfc035/BASELINE.{md,json}
GOVERNANCE              = docs/governance/PROFITABILITY_FIRST_FREEZE.md (ACTIVE)
SOURCES REVIEWED        = 20 (research/profitability/source_registry.{md,json})
OPPORTUNITIES IDENTIFIED= 9  (research/profitability/opportunities/OPP-0001..0009)
OPPORTUNITIES REJECTED  = 7  (5 REJECT, 1 INSUFFICIENT_EVIDENCE, 1 WATCH)
SELECTED CANDIDATE      = OPP-0001 (RESEARCH_HYPOTHESIS_P0 since RFC-035E; was REPLICATE_P0), frozen before any backtest
INDEPENDENT VERIFICATION= reports/rfc035/RFC035_VERIFICATION.json
FALSE_SUCCESS           = 0 (reported by the verifier)
EDGE CLAIMED            = NONE. This RFC claims an opportunity worth replicating, nothing more.
RFC-035E VALIDATION     = EFFECT_NOT_REPRODUCED  ->  OPP-0001 = REJECT
NEXT_GATE               = CONTINUE_EXTERNAL_SEARCH
```

## 1. What was asked and what was done

The mission was not to build anything: it was to find out whether an **external** opportunity exists that
is defined and evidenced well enough to deserve an exact replication inside this project. No strategy was
written, no backtest was run, no parameter was searched, no asset or timeframe was swept. RFC-035 answers
one question only: *is there something here worth reproducing exactly?*

## 2. Baseline

CAP-004C = STORAGE_STABILIZED (verifier PASS 169/169), CAP-004B = RUNNING (verifier PASS 36/36, 4/4 real
decisions settled, evaluated and verified, scheduler armed), chain INTACT, drift NO_DRIFT, disk HEALTHY at
24.16 GiB free, `G_AGENTIC_EDGE = NOT_TESTED`, `TRADES_AUTHORIZED = 0`, `FALSE_SUCCESS = 0`. Repo gates at
baseline: pytest 2745 passed, ruff clean, mypy clean over 687 files, `git diff --check` clean.

Two findings are recorded rather than smoothed over:

- an earlier CAP-004C verification run under an interpreter that lacked the project dependencies wrote
  `assessment = storage_not_verified`; the verifier now fails closed (`ENVIRONMENT_UNVERIFIED`, exit 2) so an
  environment artefact can never be published as a storage verdict again;
- CAP-004B's last four cycles (20:00-20:45Z) ended `MISSED_DECISION_SLOT` (exit 3). No decision was lost
  (4/4 settled, 0 pending), but "campaign RUNNING" must not be read as "campaign sealing on cadence".

RFC-035 also collides in number with the older `reports/RFC035_FINAL_REPORT.*` (2026-10-05, "STRATEGIC
PROFITABILITY PLAN V2"). That is a different task; this run is namespaced under `reports/rfc035/`.

## 3. Sources reviewed (20)

Registry: [source_registry.md](../../research/profitability/source_registry.md). Types: peer-reviewed journal
articles, arXiv/SSRN working papers, a Federal Reserve note, a conference paper, buy-side research, vendor
research, an index-provider page and one news report. Every entry records how much was actually read
(`full_text` vs `abstract_snippet`); nothing was upgraded to "read" that was not, and no field was filled in
by inference - the schema uses `UNKNOWN`.

Most-cited for the selection: S-01 FalconX (ETF flow statistics), S-02/S-03/S-04 peer-reviewed ETF price
discovery and return/volatility work. Counter-evidence for the same line: S-01's own declared limitations.

## 4. Opportunities identified (9) and why the others were rejected

| OPPORTUNITY | family | rank | score | reason |
| --- | --- | --- | ---: | --- |
| OPP-0001 | spot-BTC ETF net-flow continuation | RESEARCH_HYPOTHESIS_P0 | 19/50 | only candidate passing every filter clause |
| OPP-0002 | token unlock / vesting forced supply | RESEARCH_HYPOTHESIS_P1 | 22/50 | thousands of events, but the effect is negative and the runtime is long/cash: replicable content is avoidance, not edge |
| OPP-0003 | on-chain USDT net inflow | WATCH | 17/50 | blocked at the data layer (labelled flows are commercial) and a 1-2h effect against a 23.791 bps cost floor |
| OPP-0004 | liquidation-cascade reversal | INSUFFICIENT_EVIDENCE | 13/50 | venues throttled their own liquidation feeds (S-13); events are rare; risks being the closed vol-spike family renamed |
| OPP-0005 | quarter-hour clock-boundary | REJECT | 23/50 | best-evidenced source in the registry; the documented object is a 10-second return far below the cost floor, and its 4-12h channel is order flow (internally COST_KILLED) |
| OPP-0006 | turn-of-the-candle | REJECT | 19/50 | ~0.58 bps per minute gross against a 23.791 bps round trip |
| OPP-0007 | external order-flow imbalance | REJECT | 22/50 | already tested internally with our own cost model: A-01..A-06 gross +0.03..+0.61 bps, all COST_KILLED |
| OPP-0008 | perpetual funding carry | REJECT | 27/50 | highest-scoring rejection: needs perpetual shorts, two-venue collateral and 25M-50M USD minimum capital by the project's own prior review |
| OPP-0009 | intraday/overnight seasonality | REJECT | 17/50 | ~7 bps for a mined hour-of-day window: below cost and textbook multiple testing |

The pattern is consistent and worth stating plainly: **nothing was rejected for being uninteresting. Every
rejection is arithmetic (cost floor), instrument fit (no derivatives, long/cash only), data fidelity, or the
policy's ban on re-entering a closed family under a new name.**

## 5. Selected opportunity

**OPP-0001 - spot-BTC ETF net-flow continuation (structural creation demand).**

`research/profitability/opportunities/OPP-0001.{md,json}`

- **Why this one.** It is the only registered opportunity that satisfies every clause of the minimum-evidence
  filter at once, and the only one that is simultaneously (a) not a closed internal family, (b) expressible in
  a long/cash spot runtime and (c) larger per trade than the 23.791 bps round-trip cost floor.
- **What exactly is claimed.** ETF creations are mechanical spot demand executed by authorised participants.
  S-01 estimates that previous-day net inflows have a positive coefficient (0.027) on today's BTC return
  (Granger p = 0.00406), that flows are persistent (0.533), and that a positive flow shock produces a
  persistent non-negative impulse response peaking near **+1.2% around days 3-4**. S-02/S-03/S-04 establish,
  in peer-reviewed work, that the ETF channel is materially connected to spot price formation and volatility.
- **Evidence supporting it.** One industry statistical study with numbers (S-01) plus three peer-reviewed
  papers on the ETF-spot linkage (S-02, S-03, S-04). Evidence class: `AUTHOR_BACKTEST` for the tradable claim,
  `ACADEMIC_PAPER` for the mechanism. No forward test, no live track record, no external code.
- **Counter-evidence (recorded, not buried).** Correlation is only 0.30 (< 10% of variance); the relation is
  unstable (rolling 60-day 0.10-0.50); a price-to-flow feedback loop means part of the signal is already
  realised; the sample is 10 months at publication; flows are published after the US close, so the tradable
  part is the residual; and the source is buy-side research with no cost model while our floor is 23.791 bps.
- **Evidence score.** 19/50 (SAMPLE_SIZE 1, OOS_EVIDENCE 2, no cost model in the source, CODE_AVAILABILITY 1).
- **Ambiguities.** No entry/exit rule, threshold, lookback, aggregation or sizing is defined by any source; the
  PIT publication timestamp per day is vendor-specific; whether the signal is better used as a level, a change
  or a sign is unresolved. These are assigned to RFC-036 and must be frozen there before any data is touched.
- **Freeze (selection precedes results).** `SELECTION_TIMESTAMP = 2026-10-07T21:20:00Z`,
  `RULE_HASH = afb82b7079143ade...`, `SOURCE_BUNDLE_HASH = 34ea7e3866f582fb...` (full values in the
  opportunity JSON and the registry). No project backtest artifact for this line exists at selection time.

## 6. Replication risks carried into RFC-036

1. **Power.** About 21 months of ETF history and few independent flow shocks: RFC-036 may legitimately end in
   `INSUFFICIENT_SAMPLE`. That is a result, not a failure.
2. **Reverse causality.** Flows may follow price. A replication must separate the residual predictive part
   from the contemporaneous part, or it will measure the price move twice.
3. **PIT fidelity.** One publication timestamp per day, fixed in advance, or the study becomes lookahead.
4. **Rule invention.** The rules are ours, not the source's; they must be frozen and hashed before any
   measurement, exactly as the reentry policy requires.
5. **Cost realism.** 23.791 bps round trip on a low-turnover daily signal is manageable, but the claim must
   survive it net.

## 7. Independent verification and false success

`scripts/rfc035_discovery_verify.py` re-reads the artifacts, re-derives the two frozen hashes from the stored data,
re-checks schema, ranks, score arithmetic, rules honesty, counter-evidence, the closed-family registration,
the baseline and the governance freeze, and audits every source URL over the network. It writes
[RFC035_VERIFICATION.json](RFC035_VERIFICATION.json) and [RFC035_VERIFICATION.md](RFC035_VERIFICATION.md).
Result: see `status` in that artifact. `FALSE_SUCCESS` counts checks that reported success while their
evidence was absent; the target is 0 and any non-zero value invalidates this PASS.

## 8. Honest limits of this verdict

RFC-035 demonstrates `EXTERNAL_OPPORTUNITY_WORTH_REPLICATING` for one candidate and nothing else. It does not
demonstrate, imply or approach `EDGE_CONFIRMED`, `PROFITABLE` or `READY_FOR_LIVE`; `G_AGENTIC_EDGE` stays
`NOT_TESTED`, `TRADES_AUTHORIZED` stays 0 and the RFC-041 freeze stays in force. The selection is a
*pre-commitment*: at 19/50 it is a claim about what deserves work, not about what works.

NEXT_GATE = `RFC-036_IMMUTABLE_STRATEGY_REPLICATION_SPEC` (candidate frozen; no implementation authorized).

## 9. Note on the shared working tree

The gates in this report were measured at the baseline commit on a working tree shared with other threads.
Every RFC-035 artifact is clean under `ruff` and `mypy`. At the time of writing, the repository as a whole
still reports findings in another thread's in-flight files (`scripts/cap004d_*.py`,
`tests/unit/research/test_campaign_health.py`); those are not RFC-035 files, were not modified here, and are
recorded so a reader is not surprised by a non-zero repo-wide exit code. Full suite at the same moment:
**2794 passed** (the baseline's 2745 plus the concurrent additions and the 8 RFC-035 tests).

## RFC-035 artifact-name collision (declared)

`scripts/rfc035_verify.py` already exists in this repository: it is the tracked independent verifier of the
**older** RFC-035 ("admit external multi-asset strategy candidates", commit 17d4777), which verifies
`reports/profitability-v2/`. Overwriting it would have destroyed another RFC's ability to verify itself, so
this run's verifier was created as **`scripts/rfc035_discovery_verify.py`** and the older file was left
byte-identical to its committed state. The verification artifact of this run is
`reports/rfc035/RFC035_VERIFICATION.json`; the older one stays at `reports/profitability-v2/RFC035_VERIFICATION.json`.

## Classification correction required by RFC-035E (nothing erased)

RFC-035 classified OPP-0001 as `REPLICATE_P0` and OPP-0002 as `REPLICATE_P1` while their own records said the entry rule, exit rule,
threshold, lookback, aggregation and position size were all `UNKNOWN`. `REPLICATE_P0` requires
`REPLICABLE_ENTRY_EXIT_LOGIC`, so there was no external strategy to replicate exactly and the
classification was wrong. It has been corrected in place:

```text
PREVIOUS_CLASSIFICATION  = REPLICATE_P0 (OPP-0001), REPLICATE_P1 (OPP-0002)
CORRECTED_CLASSIFICATION = RESEARCH_HYPOTHESIS_P0 (OPP-0001), RESEARCH_HYPOTHESIS_P1 (OPP-0002)
REASON                   = the source does not define a complete trading strategy;
                           entry/exit/threshold/lookback/aggregation/size are UNKNOWN
CORRECTED_BY             = RFC-035E
VALIDATION RESULT        = EFFECT_NOT_REPRODUCED -> OPP-0001 = REJECT
```

Consequences, stated plainly:

- **RFC-035 is not PASS.** Its own contract reaches PASS only through (A) a true externally
  specified strategy with replicable entry/exit logic, or (B) a hypothesis that passes RFC-035E and
  is promoted into Strategy Discovery as a `STRATEGY_CANDIDATE`. Neither happened: no such strategy
  exists among the 20 sources, and RFC-035E found the statistical effect did not reproduce.
- The original rank is preserved, not deleted: `research/profitability/opportunities/OPP-0001.json`
  keeps it in `rank_history` and `classification_correction`, and this report keeps it in
  `selected_opportunity.rank_before_correction`.
- The frozen selection and both hashes are unchanged. Reclassification is not permission to rewrite
  evidence, and the RFC-035E result is recorded in the registry as `validation_evidence`.
- `CONTINUE_EXTERNAL_SEARCH` replaces `RFC-036_IMMUTABLE_STRATEGY_REPLICATION_SPEC` as the next
  gate: there is no reproduced effect to freeze into a specification. RFC-036 stays unopened.
