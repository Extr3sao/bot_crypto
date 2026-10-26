# ARP-003 — CANONICAL REGISTRY RECONCILIATION (§1/§2)

Evidence sources audited (read-only, no candidate is edited or renumbered):

- `docs/research/strategy_specs/` — 21 `STRAT-CAND-001..021` specs
- `docs/research/experiment_specs/` — 20 `EXP-*` design specs
- `docs/research/hypotheses/HYPOTHESIS_REGISTRY.md` — 34 registered hypotheses
- `docs/research/claims/` — `CLAIM_REGISTRY_V2_BATCH2`, `SOURCE_THRESHOLD_REGISTRY_V2_BATCH2`,
  `CONFLICT_REGISTRY_V2_BATCH2`
- `docs/research/source_reviews/` — 17 reviews (8 sources × review+mapping)
- `docs/research/source_registry.md` — 19 registered source ids
- `docs/research/runtime_reconciliation/` — `STRATEGY_CANDIDATE_MATRIX`,
  `VERIFIED_CANDIDATE_MATRIX`, `SOURCE_TO_RUNTIME_MATRIX`
- `docs/research/work_packages/`, `improvement_specs/`, `risk_specs/`, `insights/`
- `docs/STRATEGY_DISCOVERY_V3_*`, `reports/strategy-baseline/DISCOVERY_CANDIDATES.json`
- `reports/alpha-recovery-v1*/`
- `config/strategy_admission.json` (six runtime families)
- untracked: `src/trading_bot/research/experimental/`, `scripts/source_candidate_experiment.py`

## Counts

| metric | value | note |
| --- | --- | --- |
| `CANONICAL_CANDIDATES` | **21** | `STRAT-CAND-001..021`, no gaps, no duplicates |
| `SOURCE_INGESTION_CANDIDATES` | **34** | `HYP-001..034` registered hypotheses |
| `UNMERGED_CANDIDATES` | **3** | `D-02_vol_z_rev`, `D-03_squeeze_breakout`, `D-04_rel_momo` (see below) |
| `DUPLICATES` | **0** | no new byte-identical candidate; every HYP alpha hypothesis already maps to a canonical id |
| `VARIANTS` | **4 canonical + 3 project** | canonical variants 002, 005, 015, 020; project variants 016/012/019 |
| `CONFLICTS` | **6** | `CONFLICT-001..006` (unchanged, preserved) |

The mission's a-priori "≈ 001..047" is **stale** (ARP-001 already corrected it). The
registry is 21 candidates and is **complete** for the alpha universe.

## Canonical candidate classification (§2)

`Class` is one primary reconciliation class. `SF` is the source-faithfulness status
established in §3–§5.

| id | candidate | family | class | SF status |
| --- | --- | --- | --- | --- |
| 001 | MA20/40/200 pullback | trend | `CANONICAL` | source-faithful (resolvable) |
| 002 | multi-timeframe alignment | trend filter | `VARIANT` (of 001) | source-faithful (resolvable) |
| 003 | MACD regime crossover | momentum | `SEMANTIC_DUPLICATE` (runtime `momentum`) | source-faithful (resolvable) |
| 004 | MACD divergence + break | reversal | `CANONICAL` (NEEDS_SPEC) | needs spec |
| 005 | candle pullback 1/9 3:1 | trend | `VARIANT` (of 001) | needs spec (source thresholds) |
| 006 | S/R + Fibonacci pullback | level | `CANONICAL` (NEEDS_SPEC) | needs spec |
| 007 | range + RSI/Stoch/CCI | mean reversion | `CANONICAL` (NEEDS_SPEC) | needs spec |
| 008 | head & shoulders | geometry | `CANONICAL` (NEEDS_SPEC) | needs spec |
| 009 | put/call contrarian | sentiment | `DATA_BLOCKED` | data blocked |
| 010 | pair spread mean reversion | relative value | `INFRASTRUCTURE_BLOCKED` | infra blocked |
| 011 | order-block OTE (FX) | continuation | `CANONICAL` (NEEDS_SPEC) | needs spec + asset mismatch |
| 012 | SMT relative strength | cross-instrument | `CANONICAL` | **BLOCKED_NEEDS_SPEC** (§4) |
| 013 | Juda swing stop-hunt | liquidity reversal | `CANONICAL` (NEEDS_SPEC) | needs spec |
| 014 | Asian-range killzone sweep | session liquidity | `CANONICAL` (NEEDS_SPEC) | needs spec |
| 015 | fair-value range MR | mean reversion | `VARIANT` (of 007) | needs spec |
| 016 | liquidity-void retest | rebalancing reversal | `CANONICAL` | **BLOCKED_NEEDS_SPEC** (§3) |
| 017 | mini-SPX S1 false break | index intraday | `DATA_BLOCKED` | data blocked (no index) |
| 018 | mini-SPX S2 pullback | index intraday | `DATA_BLOCKED` | data blocked (no index) |
| 019 | pivot level fade | level reaction | `CANONICAL` | **BLOCKED_NEEDS_SPEC** (§5) |
| 020 | pivot breakout continuation | continuation | `VARIANT` (of 001/005) | needs spec |
| 021 | micro S/R entry family | level entry | `CANONICAL` (NEEDS_SPEC) | source is visual-only |

Tally: `VARIANT` 4 · `SEMANTIC_DUPLICATE` 1 · `DATA_BLOCKED` 3 ·
`INFRASTRUCTURE_BLOCKED` 1 · `CANONICAL` (other) 12 · `UNMERGED_NEW` 3 (below) ·
`SUPERSEDED` 0 · `CONFLICT` 6. **No id was renumbered and no canonical spec was
overwritten.**

## Unmerged candidates (§1)

Three alpha candidates exist in the corpus **outside** the canonical registry. They
come from the STRATEGY-DISCOVERY-V3 phase
(`scripts/discovery_candidates.py`, `docs/STRATEGY_DISCOVERY_V3_EXPERIMENTS.md`),
not from source ingestion. All three were tested and none has edge:

| unmerged candidate | timeframe | ZERO-cost gross | outcome | reconciliation class |
| --- | --- | --- | --- | --- |
| `D-02_vol_z_rev` | 15m | −11.51 $ / −0.3714 bps, n 31 | REJECT | `REJECTED` (kept unmerged; no id assigned) |
| `D-03_squeeze_breakout` | 30m | 0 signals on the whole dataset | INTESTABLE | `DATA_BLOCKED` (spec too strict; no post-hoc re-tuning allowed) |
| `D-04_rel_momo` | 1h | −12.12 $ / −0.0635 bps, n 191 | REJECT | `REJECTED` |

**Decision: merge none.** They are pre-registered-enough to be *named*, but they are
rejected, transitive and 5m/15m/30m/1h high-turnover. Assigning a `STRAT-CAND` id
would imply a canonical status they do not have. They are recorded here so a future
phase cannot silently re-discover them.

`D-04_rel_momo` is a *semantic neighbour* of the cross-sectional idea but is
time-series relative momentum on a single instrument pair, not a cross-sectional
ranking — so it is not a duplicate of `H-XSEC-RELSTR-001` either.

## Conflicts preserved (§2)

`CONFLICT-001..006` are carried forward unchanged (Order-Block promotion vs its own
counter-evidence; 61-79 vs 25-61 retracement zones; manipulation narrative vs
observable geometry; 1-3 % daily loss vs evidence-based thresholds; cheatsheet
visual semantics; persuasion vs evidence authority). None is resolved by authority.
