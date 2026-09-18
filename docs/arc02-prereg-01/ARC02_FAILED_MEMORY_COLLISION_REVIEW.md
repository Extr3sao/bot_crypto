# ARC02_FAILED_MEMORY_COLLISION_REVIEW.md

> Explicit comparison of ARC-02 against every registered failure and against the two
> sibling ARC hypotheses, using the repository's own evidence. The purpose is to check
> whether ARC-02 has secretly become a hypothesis that already failed — and to document
> the collision, if any, rather than resolving it by tuning economics.

## 1. Registered failures (evidence basis)

| Id | Hypothesis | Recorded outcome | Evidence |
| --- | --- | --- | --- |
| H1 (#10) | regime-transition defense, 1h OHLCV | `DISCOVERY_FAIL` — gross expectancy ≈ 0 (−0.003 R), net −0.128 R, PF_net 0.833, halves/thirds uniformly negative; dominant loss mechanism `SHORT_ON_SHOCK` fading shocks in a secular uptrend | `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md`#10 (prereg `3ad054d`, execution `b9e2760`) |
| H3 (#11) | BTC↔ETH beta-neutral log-spread reversion, 1h | `DISCOVERY_FAIL` — the mean-reversion premise failed BEFORE costs (gross PF 0.492, gross expectancy −0.367 R); `|z|≥2.5` dislocations CONTINUED instead of reverting; neutrality gate failed (DEF-H3-NEUTRALITY-001) | `FAILED_RESEARCH_MEMORY.md`#11 (prereg `83b3acd`) |
| H5 (#12) | order-flow imbalance continuation, 1h taker flow | `DISCOVERY_FAIL — TERMINAL` — positive expectancy (+0.235 R, PF 1.350) but `P(Sharpe>0)=0.8285`, permutation `p=0.1838`, halves [1,−1]; trade-time overlap 0.916 with a momentum proxy | `FAILED_RESEARCH_MEMORY.md`#12 (prereg `c426b35`) |
| #8 | carry/funding basis | `DISCOVERY_FAIL` deep (N=769, PF 1.062, p=0.283) | `FAILED_RESEARCH_MEMORY.md`#8 |
| #6/#7 | vol-structure leads, cross-sectional | `DISCOVERY_FAIL` / redundant with momentum | `FAILED_RESEARCH_MEMORY.md`#6,#7 |
| H6 | OI-confirmed continuation | preregistered, **NOT EXECUTED** (no economics observed) | `H6-PREREG-V2`/`V4` commits; `NOT_EXECUTED` |
| ARC-01 | funding/crowding unwind after price rejection | `DISCOVERY_FAIL` — N=347; G3 ex-funding FAIL (−0.000298); PF 1.0498; Sharpe 0.1447; CI straddles zero; permutation p=0.3766; temporal stability FAIL | `docs/external-audit-01/arc01-primary-discovery-01/ARC01_PRIMARY_DISCOVERY_RESULT.md` (prereg `fa15fb4`) |
| ARC-03 | participation-shock reversal, 5m | `DISCOVERY_FAIL` — gross directional tilt existed but did not survive frozen 10 bps costs, the statistical gates, stability or the falsification controls | `research/arc03-primary-discovery-01` @ `8e3ebda` |

ARC-02 uses **none** of these outcomes to choose any parameter, direction, threshold,
lookback, ratio, holding period, asset or cost. The recorded values are cited only to check
for *structural* overlap.

## 2. Pairwise collision analysis

### H1 — regime-transition defense (`LOW`, per the ARU matrix)

* H1 traded a **state label** on 1h bars with no cross-asset input, and its dominant loss was
  `SHORT_ON_SHOCK` fading an up-move.
* ARC-02 trades a **cross-asset continuation** on 5m bars: it goes WITH the shock direction and
  requires a second asset's response to be incomplete.
* The sign relationship is opposite: H1's loss engine was fading shocks; ARC-02 is long the
  shock direction.
* **Collision: NOT MATERIAL.** No shared signal field, no shared direction logic.

### H3 — BTC↔ETH relative-value reversion (`MEDIUM`, the highest ARC-02 class)

This is the one class the ARU flags as `MEDIUM`, and the review must be explicit about it.

* H3 built a **beta-neutral log spread** between BTC and ETH, standardised it by a trailing z,
  and traded **AGAINST** the dislocation expecting reversion over 48 bars.
* H3's own evidence says the reversion premise failed and dislocations **continued**.
* ARC-02 does not build a spread, does not hedge, does not normalise one asset against the
  other, and does not trade against a dislocation. It trades the follower **with** the leader's
  direction, on 5m bars, over 1 bar.
* ARC-02 requires the follower to move in the SAME direction as the leader and to be
  *under*-reacting; H3 requires the two to have *diverged*.
* Structurally, ARC-02's signal can fire when the BTC↔ETH spread is unchanged (both move
  proportionally is excluded, but a same-direction underreaction is not a spread dislocation per
  se), and H3's signal can fire when ARC-02's cannot (opposite sign).
* **The interesting question is the converse:** H3's evidence (dislocations continue rather
  than revert) is *consistent in sign* with a continuation family, which is why ARC-02 is not a
  re-run of H3 but a different claim with the opposite directional logic.
* **Collision: PARTIALLY MATERIAL, ASSET OVERLAP ONLY.** Both read BTC and ETH prices. The
  directional logic is opposite, the construction differs (spread vs. response ratio), the
  cadence differs (1h vs 5m) and the horizon differs (48 bars vs 1 bar).
* **Consequence (frozen):** H3 is a MANDATORY orthogonality comparator at the later authorized
  promotion stage (daily-PnL correlation ≤ 0.5, trade-time Jaccard ≤ 0.5), and the collision is
  documented here rather than resolved by tuning. If ARC-02 ever became a spread claim, that
  would be a **NEW_HYPOTHESIS_ID**.
* **Non-remediation clause:** no ARC-02 parameter was chosen to make ARC-02 look less like H3.

### H5 — order-flow imbalance continuation (`LOW`)

* H5 read **taker-buy order-flow fields** aggregated over 1h bars and went WITH the flow.
* ARC-02's projection physically drops `tb`/`tq`/`n`/`qv`, so an order-flow input is not merely
  disallowed but unreachable.
* Direction is similar in spirit (continuation), the information family is entirely different.
* **Collision: NOT MATERIAL** (family separation is structural, enforced by the data authority).

### H6 — OI-confirmed continuation (`LOW`)

* H6 conditions continuation on **open interest**, which the ARC-02 projection does not carry
  and the ARC-02 authority forbids as a signal.
* H6 has no economics observed at all, so there is no outcome to collide with.
* **Collision: NOT MATERIAL.**

### ARC-01 — funding/crowding unwind (`LOW` per the ARU matrix; not scored for ARC-02 directly)

* ARC-01's mechanism is **funding/crowding**: who pays is a leveraged crowd being unwound after
  a rejection, and funding itself is the conditioning variable.
* ARC-02 reads **no funding as signal** (funding is a cashflow leg only), and its who-pays story
  is latency/segmentation on the follower, not crowding.
* ARC-01's dominant failure mode is entirely absent here: ARC-02 does not take an ex-funding
  negative leg by construction (G3 is a critical gate, so an ARC-02 result that only works via
  carry is a FAIL).
* **Collision: NOT MATERIAL.**

### ARC-03 — participation-shock reversal (`LOW`, same data family)

* ARC-03 requires a **volume record** exactly one day earlier at the same 5m slot, a range
  record, and exhaustion geometry — and then trades **AGAINST** the failing push.
* ARC-02 reads no volume, no range and no wick geometry, and trades **WITH** the leader shock.
* The two use the same reused 5m authority and the same 5m cadence — this is a **data** overlap,
  not a mechanism overlap, and it is exactly why reuse was safe: ARC-02 projects away every
  field ARC-03 depends on.
* Both hypotheses fail closed on missing reference history; their reference windows are
  computed differently (same-slot daily references vs. strictly trailing bars).
* **Collision: NOT MATERIAL.**
* ARC-03's outcome is deliberately NOT used to choose anything in ARC-02 (its 10 bps, 12-bar
  hold and 3-asset stability rule are not copied; the hold is 1 bar and the stability rule is
  2-of-2, both derived from ARC-02's own mechanism).

## 3. Summary table

| Comparator | ARU class | Structural collision | Material? | Consequence |
| --- | --- | --- | --- | --- |
| H1 regime transition | LOW | none (no state label, opposite direction) | No | none |
| H3 relative value | **MEDIUM** | shared assets, opposite directional logic, different construction/cadence/horizon | **Partially** (asset overlap only) | H3 frozen as mandatory orthogonality comparator at the later stage; documented, not resolved by tuning |
| H5 order flow | LOW | field family unreachable by construction | No | none |
| H6 OI continuation | LOW | field not admitted | No | none |
| ARC-01 funding/crowding | LOW | funding is never a signal; crowding story different | No | none |
| ARC-03 participation reversal | LOW | same data family, disjoint fields and opposite direction | No | none |

## 4. Standing prohibitions acknowledged

* No re-run of a registered hypothesis on the same spec.
* No promotion from failed/insufficient lines.
* `INSUFFICIENT ≠ refuted`: ARC-02 is a **new** hypothesis id with its own preregistration, so
  none of the above failures is being re-tested on the same spec.
* Any future sub-population that looks profitable while the primary fails is
  `POST_HOC_LEAD_ONLY` and requires a **NEW_HYPOTHESIS_ID**.

**Residual risk stated plainly:** ARC-02 is a continuation claim in the same two assets that
produced the repository's MEDIUM collision class (H3). If ARC-02 passes its gates, the H3
orthogonality check is the first thing the independent verifier should demand at the promotion
stage. No ARC-02 economics exist yet, so this cannot be pre-empted here.
