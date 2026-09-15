# ARC-01 FAILED-MEMORY COLLISION REVIEW

**Hypothesis:** `ARC-01-FUNDING-CROWDING-UNWIND-01` · **Checkpoint:** `ARC01-PREREG-001`
**Register read in full:** `docs/external-audit-01/FAILED_RESEARCH_MEMORY.md` (12 terminal entries), plus
`docs/alpha-research-universe-01/04_FAILED_MEMORY_COLLISION_MATRIX.json` (frozen at `e7f470d`).
**Computed:** before any economic observation (`ARC01_BACKTESTS = 0`, `ARC01_EXECUTIONS = 0`).
**Verdict:** `ARC01_FAILED_MEMORY_COLLISION_REVIEW = PASS_WITH_ONE_REGISTERED_MEDIUM_COLLISION`

---

## 1. Headline collision assessment (ARU frozen matrix)

`ARC-01: {H1: LOW, H3: LOW, H5: LOW, H6: MEDIUM}` — the registered MEDIUM collision is **H6**, and it is
the OI axis, not the direction axis (section 3).

## 2. Entry-by-entry review

| # | Failed family | ARC-01 collision | Why ARC-01 is not a re-roll |
| --- | --- | --- | --- |
| 1 | Legacy momentum (5m/1h) | **NONE** | ARC-01 contains no momentum/trend input. Its only price reads are the entry and exit bar opens; direction comes from the sign of extreme funding. |
| 2 | Legacy trend (5m/1h) | **NONE** | as #1; ARC-01 is explicitly contrarian to the crowded side, i.e. its direction is not the direction of prior price movement. |
| 3 | Legacy breakout | **NONE** | no level, range or breakout construction exists in the frozen spec. |
| 4 | Legacy mean_reversion | **LOW–MEDIUM — addressed** | ARC-01 is a mean-reversion-*like* claim, but its conditioning variable is derivatives positioning (funding + OI stock), which is absent from #4's price-only family. This is precisely the "different mechanism" requirement: #4's lesson is that MR needs a *different* conditioning variable, not a re-parameterization — and funding × crowding is that different variable. Registered residual: if ARC-01 passes only in low-volatility regimes, that must be disclosed as an MR-family proximity, not claimed as a new mechanism. |
| 5 | Legacy volatility | **NONE** | no volatility estimator is used. |
| 6 | volatility_structure | **NONE** | different variable family, and ARC-01 has no single-asset lead structure. |
| 7 | cross_sectional | **NONE** | ARC-01 is not a cross-sectional rank strategy; each asset is decided independently from its own funding/OI state. Orthogonality to momentum is nevertheless evaluated (section 4). |
| 8 | **carry_funding (Batch 02 + CARRY-FUNDING-DEEP-01)** | **MEDIUM — REGISTERED, DIRECT** | #8 is the closest ancestor: funding basis alone, N=769, PF 1.062, p=0.283, halves/thirds INCONSISTENT, with the recorded lesson *"any basis hypothesis must add a conditioning variable and show halves/thirds consistency"*. ARC-01's answer: (a) it adds the OI position-stock conditioning leg (`OI_CONTROL` tests that it is load-bearing); (b) it is not a carry strategy — the direction is contrarian to the funding sign and the carry is a byproduct, which is why `G3_NET_EXPECTANCY_EX_FUNDING > 0` is a critical gate; (c) halves **and** quartiles consistency are critical gates. ARC-01 does not re-roll #8's mechanism (harvesting basis), and cannot be reconciled to it. |
| 9 | session_time / liquidity_flow | **LOW** | funding settles on a sessioned schedule, but ARC-01 makes no intraday-timing claim; the `TIMING_CONTROL` (±8h) exists specifically to falsify a session artefact reading. |
| 10 | H1 regime-transition defence | **LOW–MEDIUM — addressed** | #10 failed by fading shocks inside a structural uptrend (`SHORT_ON_SHOCK`). ARC-01's SHORT leg is structurally similar (it fades a crowded long side during an uptrend). Registered mitigations: the entry condition requires an *extreme* funding event plus position-stock expansion rather than a transition label; frequency is ~1–2 orders of magnitude lower (settlement-driven, 72h holds), so the cost drag that destroyed #10 cannot apply; and both direction and timing controls are critical. This residual asymmetry risk is stated openly: if ARC-01's LONG leg carries the result and the SHORT leg is negative, that is a mechanism mismatch and must be reported, not averaged away. |
| 11 | H3 relative-value spread reversion | **LOW** | no spread, no beta, no two-leg neutrality; ARC-01 has no neutrality claim (it is deliberately directional per asset). |
| 12 | H5 order-flow imbalance continuation | **LOW** | H5 used taker-flow aggregates over 1h bars — the same OHLCV family it was built from. ARC-01 uses no OHLCV-derived feature. H5's recorded requirement (a) "use a genuinely new information family (depth/trade-flow/**open-interest**)" is satisfied by the funding + OI construction; requirement (b) "generate enough independent events" is addressed by the frozen minimum-N and the event-budget argument in `ARC01_SELECTION_RATIONALE.md` §3; requirement (c) "enforce the orthogonality gate BEFORE reading economics" is honoured — the orthogonality plan is frozen here and will be executed under its own authorized checkpoint before any interpretation of ARC-01's economics. |

## 3. The registered MEDIUM collision with H6 (OI continuation) — explicit disambiguation

| Axis | H6 (`H6-OI-CONFIRMED-CONTINUATION-02`) | ARC-01 |
| --- | --- | --- |
| Information used | OI (position stock) + 1h price direction | funding rate (new authority) + OI (position stock) |
| Direction source | **price** direction of the completed hour | **sign of extreme funding** |
| Direction semantics | **continuation** (trade *with* the move) | **contrarian unwind** (trade *against* the crowded side) |
| Conditioning | OI expansion confirms price direction | OI expansion confirms the crowded side implied by funding |
| Cadence / hold | every completed asset-hour, 1h hold | funding settlement instants, 72h hold |
| Overlap | — | shares the OI dataset and field only |

**Why this is not a parameter re-roll of H6:** the two hypotheses disagree on the *sign of the predicted
direction* for the same OI-expansion state; they share one input series but not the mechanism, the trigger,
the cadence or the direction. If both were run, ARC-01 and H6 would be expected to be *anti-correlated*
on any overlapping signal instants.

**Mandatory handling:** the collision is closed by the frozen orthogonality plan
(`max |daily PnL correlation| ≤ 0.5`, `max trade-time Jaccard ≤ 0.5`) evaluated in a later authorized
experiment. If the H6 comparison cannot be computed from persisted evidence (H6's daily PnL arrays were
never persisted — see `FAILED_RESEARCH_MEMORY` #12 / H6 orthogonality note), the comparison is recorded as
`NOT_EVALUABLE_FROM_PERSISTED_EVIDENCE` and H6 is **not** regenerated.

## 4. Deviation from the ARU candidate sketch — registered, not silent

The ARU sketch (`05_ALPHA_MECHANISM_CANDIDATES.json`) names ARC-01 *"Funding crowding unwind **after price
rejection**"* and its data line mentions 5m OHLCV. This preregistration freezes `PRICE_CONTEXT = NONE`
(no price-rejection leg), for the reasons in `ARC01_SELECTION_RATIONALE.md` §5: a price leg would import
the OHLCV family already refuted by #1/#3/#4/#10/#12, would convert the hypothesis into a
momentum/mean-reversion hybrid, and would re-test a refuted family under a new name.

This is a **deliberate narrowing decided before any economic observation**, consistent with the candidate
design document's own table, which left the price-rejection shape `UNFROZEN_PENDING_PREREG_DESIGN`. It is
recorded here so that no later reader can discover it as an undocumented change.

## 5. Standing prohibitions carried over

- No re-run of any registered hypothesis on the same spec — ARC-01 is a **new** hypothesis id.
- If ARC-01 fails, no threshold/lookback/holding retune, no dropping of losing assets, no second attempt
  under this id; any price-conditioned or contraction-conditioned successor needs a `NEW_HYPOTHESIS_ID`
  and a `NEW_PREREGISTRATION`.
- No PAPER promotion from a FAIL/INSUFFICIENT outcome.
- Post-hoc sub-cells are `POST_HOC_LEAD_ONLY · INSUFFICIENT_SAMPLE · DO_NOT_RETEST_WITHOUT_NEW_EX_ANTE_HYPOTHESIS`.

## 6. Verdict

`ARC01_FAILED_MEMORY_COLLISION_REVIEW = PASS_WITH_ONE_REGISTERED_MEDIUM_COLLISION`

- No failed family's mechanism, information set or parameterization is repeated.
- #8 (funding-only) is directly confronted and answered with a load-bearing second leg plus a mandatory
  ex-funding-cashflow gate; #10's trend-asymmetry risk is explicitly registered.
- #12's H6/OI MEDIUM collision is disambiguated axis-by-axis and closed by a frozen orthogonality plan.
- The sole deviation from the ARU sketch (price leg removed) is documented with its justification.
