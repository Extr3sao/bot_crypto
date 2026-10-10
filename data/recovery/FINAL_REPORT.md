# FINAL REPORT — POST RFC-049 / ACTIVE RECOVERY

> Deliverables of this work package: this report, [ACTIVE_RECOVERY_ROADMAP.md](ACTIVE_RECOVERY_ROADMAP.md),
> [ACTIVE_ECONOMIC_AUDIT.md](ACTIVE_ECONOMIC_AUDIT.md) + [.json](ACTIVE_ECONOMIC_AUDIT.json),
> [CAMPAIGN_STATE_VIEW_REPORT.md](CAMPAIGN_STATE_VIEW_REPORT.md) + [CAMPAIGN_STATE_VIEW.json](CAMPAIGN_STATE_VIEW.json),
> [RFC049_POST_CLOSURE_REPORT.md](RFC049_POST_CLOSURE_REPORT.md),
> [RUN_REPORT.md](RUN_REPORT.md) + [.json](RUN_REPORT.json), [INDEPENDENT_VERIFICATION.json](INDEPENDENT_VERIFICATION.json).
> Builder ≠ verifier: the audit and the view are produced by two scripts, and a third, independent
> script re-derives their numbers and their claims.

```text
PROFITABILITY_VERIFIED = FALSE
LIVE_TRADING = DISABLED
TRADES_AUTHORIZED = 0
PAPER_PROMOTION = NOT_AUTHORIZED
NEXT_CAMPAIGN = NOT_AUTHORIZED
FALSE_SUCCESS = 0
```

## 1. What was done

* **WP-1 — RFC-049 closure persisted.** HEAD `2d113a0` on `main`, 86 dirty entries of which 24 were
  this lane's. The closure (ADR-0025/ADR-0026, the closure record, the Discovery 2 artefacts, the four
  engine/verifier scripts, the contract tests and the verifier's `RFC049C-DEF-01` correction) was
  committed as **`108c44d`**, and only those files: the `data/st6/*`, `evidence/real_decisions/*`,
  `docs/source_registry.md`, root `RUN_REPORT.*`/`FINAL_REPORT.md` and other lanes' script changes were
  left untouched. The sealed OOS stays `CANCELLED_NOT_OPENED`; the frozen manifest was not edited.
* **WP-2 — campaign state view** (`scripts/campaign_state_view.py`): a read-only derived view of six
  campaigns with explicit precedence (latest ADR > campaign record > runtime ledger > frozen
  declaration), an ADR index built from inline `KEY = VALUE` facts, hash-pin verification (18 verified,
  1 append-only drift, 3 unresolvable pins), builder≠verifier and no-profitability-claim invariants,
  and a visible failure mode: an unresolved contradiction sets `status = CONTRADICTION` and exits 1.
* **WP-3 — ACTIVE economic audit** (`scripts/active_economic_audit.py`): all 24 registered strategies
  reconstructed field by field (identity, data, activation, sample, gross/net edge, fees, implied
  slippage, expectancy, robustness, rejection criteria, evidence, taxonomy), with the runtime cost
  plane re-derived from COST_MODEL_V3 (`23.353553391` bps reproduced) and the paper lane audited from
  its own reports.
* **WP-4 — recovery roadmap**: three measured causes, five evidence-derived candidate experiments, the
  sequencing gates, and the independent `R6 P2 QUALITY` lane recorded as operator-defined and unmapped.
* **WP-5 — reports + independent verification**, including negative controls.

## 2. The six answers

**1. Why did none of the 24 strategies reach paper?** Because none ever satisfied the pre-registered
admission criteria and the ledger is fail-closed. Statuses are 17 `NO_GROSS_EDGE` and 7 `COST_KILLED`;
`admitted_for_paper` is false for all 24; the runtime registry `StrategyRegistry.from_ledger` therefore
exposes zero paper-activatable entries on 5m/15m/1h and refuses every family naming its status. With no
proposal there is no authorization and no fill: 337 cycles, 0 trades, `NO_TRADE_STRATEGIC` every cycle.
The paper lane itself was healthy (0 runtime failures, 0 risk vetoes, 0 duplicate decisions,
`FALSE_SUCCESS = 0`), so the zero was correct, not broken. At 5m the mandatory failures are c2
(net > 0), c3 (PF > 1), c4 (OOS > 0) and c7 (2x cost survives) for all six families.

**2. How many have a positive net edge with a sufficient sample?** **Zero.** Zero of 24 have a positive
net expectancy after the research cost line, and zero after the runtime cost plane. Seven cells do have
a positive *gross* edge at zero cost (`volatility@30m` +8.912, `volatility@1h` +6.276,
`mean_reversion@30m` +5.472, `mean_reversion@5m` +1.485, `mean_reversion@15m` +2.714, `trend@30m`
+2.206, `trend@15m` +1.284 bps) and every one of them is below both cost lines, so none converts.
On sample size, 23 of 24 cells meet criterion c1 (≥100 total, ≥30 OOS) once the per-timeframe artefact
is used — the gap is *evidence provenance* (the ledger publishes `sample_trades = 0` for the 18
non-5m entries), not statistical power.

**3. Which component limits profitability most?** The cost plane, on top of a weak entry, and the
order matters. First the entry: five of six families have a negative gross edge even at zero cost, and
ARP-001's forward-drift measurement shows the entry is on average on the wrong side of the next move at
+1/+3/+6/+12/+24 bars in every family — that is a NO_ALPHA failure that no exit policy repairs. Then
the cost plane: the best gross edge anywhere in the registry is 8.912 bps against a 12 bps research
barrier and a 23.353553391 bps admission floor; 0 of 24 cells clear either. Because frequency multiplies
the per-trip cost (three operations a day at 23.353553391 bps is 255.7 % of the stake per year in
costs), raising cadence is not a fix. The largest single lever in the whole model is the venue/order-type
plane itself: 13.79 bps for USD-M perpetual vs 23.79 bps for spot standard at the same size.

**4. Which strategies or families justify new experiments?** Only as *new* preregistered hypotheses,
never as a retune of a closed one. The evidence justifies, in order: (a) the **measured cost plane**
(E-1) — the difference between the two modelled venues exceeds the best gross edge in the registry, and
the maker path is explicitly modelled-not-measured; (b) the **30m horizon with a forward-drift entry
screen** (E-2) — gross edge peaks there and turnover falls, and the drift metric is a property of the
entry rather than a parameter; (c) **funding/basis carry** (E-3) — the only mechanism whose per-trip
cost shrinks with holding time, currently blocked by collection history; (d) the **microstructure family**
(E-4) — the only information set not already consumed, blocked by the M-03/M-07 gates; and, recorded but
not recommended first, (e) an exit-asymmetry test for `trend` (55.4 % win rate, payoff 0.58), which
ARP-001 explicitly notes is not currently supported by evidence. Nothing supports looking for a better
window on the same rules: 17 of 24 cells already show a sign flip between partitions.

**5. What exactly is missing to run verifiable paper?** Four things, in dependency order:
1. ≥1 strategy that clears c1..c9 net of the runtime cost plane — everything else is untestable until
   this exists;
2. a per-timeframe admission verdict and the missing metrics (max drawdown, observed spread) so the
   ledger is complete instead of partly unproven (`DEF-ACT-02`, `DEF-ACT-01`);
3. runtime enablement *behind* admission: a router able to carry N eligible strategies, a deterministic
   portfolio policy for simultaneous signals, and the `DEF-206` precompute fix — each only worth doing
   once (1) exists;
4. paper-gate prerequisites: a clean continuous 24 h window (last attempt 4.16 h usable, 17.33 %
   coverage, collector stopped on its own disk budget with ~4.6 GB/day projected, M-03 and M-07
   `NOT_READY`), plus the explicit operator authorization (`PAPER_PROMOTION = NOT_AUTHORIZED`).

**6. What is the next justified RFC or work package?** One work package is justified by the evidence,
and it is not a strategy: a **cost-and-entry research campaign**, to be registered as **RFC-050** and
to remain unauthorized until the operator amends governance. The campaign-state view derives 050 as the
next free number from tree + registry occupancy (the registry itself is stale: it lists up to 047 and
declares 048 as next free while the tree already occupies 048 and 049 — advisory `A1`, step 0 of the
roadmap). Its first deliverable is the *measured* cost plane (E-1), because the evidence says the cost
plane is what kills the edge; its second is a single entry-quality candidate (E-2). Everything else
waits for the two collection gates.

## 3. Verification

* `scripts/campaign_state_view.py` → `CONSISTENT_WITH_ADVISORIES` (6 invariants pass, 4 advisories), 0
  contradictions, 18 strict pins verified (3 unresolvable, 1 append-only drift), `sources_unchanged: true`,
  `--check` deterministic (same `payload_sha256` on re-run).
* `scripts/active_economic_audit.py` → 18/18 internal checks pass, 0 failed, `--check` deterministic.
* `scripts/recovery_verify.py` → PASS, 12/12 checks, 8/8 negative controls detected, 0 missed,
  `FALSE_SUCCESS = 0`: independent re-derivation of the audit and the view from the primary artefacts (a
  different implementation that does not import either builder); see
  [INDEPENDENT_VERIFICATION.json](INDEPENDENT_VERIFICATION.json).
* Unit/contract tests: [tests/unit/research/test_active_recovery_wp.py](../../tests/unit/research/test_active_recovery_wp.py)
  plus the full `tests/unit/research` suite; results and exit codes in [RUN_REPORT.json](RUN_REPORT.json).

## 4. Limitations and open defects

* The audit reconstructs what the artefacts publish. Where they publish nothing, the field is `null`
  and named in `missing_metrics` — no drawdown and no observed spread exists for any strategy, so the
  c6/c8 checks remain unverifiable rather than passed.
* Three RFC-046 spec pins cannot be resolved (the pinned artefacts are not in the tree); they are
  reported as `UNRESOLVED` advisory pins, which proves nothing about them either way.
* The 5m admission matrix publishes DEV and OOS slices only, so 5m partition comparison uses
  BASE-after-slippage and a DEV↔OOS pair while 15m/30m/1h use zero-cost DEV↔VAL.
* `breakout@5m`'s published gross edge disagrees with the same artefact's own gross_usd and trades by
  0.026 bps; it is registered as `DEF-ACT-03` with a materiality bound instead of being smoothed away.
* `DEF-206` is verified present in the legacy runner; whether the canonical entrypoint starves families
  of indicators is *not* established here and is recorded as an open question.
* The campaign-state view reads one artefact owned by another lane in flight (`data/st6/*`); if that
  lane writes during a run, the view's hashes move with it, which is why the view re-hashes before and
  after and reports `sources_unchanged`.
* Nothing here was promoted: no campaign was launched, no threshold or cost model changed, no frozen
  artefact was modified, and no trading of any kind occurred.

```text
PROFITABILITY_VERIFIED = FALSE
```
