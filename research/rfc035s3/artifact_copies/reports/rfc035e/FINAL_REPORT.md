# RFC-035E — INDEPENDENT EXTERNAL EFFECT REPRODUCTION

```text
RFC-035E STATUS      = EFFECT_NOT_REPRODUCED
COMMIT               = 7e21f7ca6dbf8816d83f2f8ab15aeb09310b878c (main; nothing committed, no commit was requested)

DATA SOURCES         = RF-01 Farside US spot BTC ETF daily net flow tables (703 sessions, 2024-01-11..2026-10-07)
                       RF-02 Binance BTCUSDT 1d klines (1042 rows)
                       raw bytes, retrieval timestamps and SHA-256s in research/rfc035e/raw_source_manifest.json
PIT STATUS           = UNKNOWN for exact per-record publication timestamps; conservative convention declared

SOURCE PERIOD        = 2024-01-11..2024-10-11 (197 in-window, 195 usable, 194 regression rows)

SOURCE REPLICATION RESULT
  ORIGINAL           F = 8.4767   p = 0.00406   lag-flow coefficient = 0.027 (source units, not comparable)
                     flow persistence = 0.533   correlation = 0.30   impulse response peak about +1.2% at days 3-4
  REPRODUCED         F = 4.0133   p = 0.04656   lag-flow coefficient = +2.343e-05 per USD m
                     flow persistence = 0.5724  correlation = 0.413 (contemporaneous Pearson)
                     overlapping 7-session flow gives F = 12.0473, p = 0.00065 (not HAC-corrected)
                     the source's NAMED transforms do not reproduce: normalised difference p = 0.2178 (daily),
                     0.4438 (7-session); 7-session aggregate p = 0.7443 / 0.9574
                     impulse response: impact only, then collapse; the delayed +1.2% drift does not appear

REVERSE CAUSALITY    price(t-1) -> flow(t): coefficient 1420.5733, p = 0.0010 (source window);
                     3278.2121, p = 0.0000 (OOS). The feedback direction is an order of magnitude stronger
                     than the forward one.

UPDATED OOS PERIOD   = 2024-10-12..2026-10-07 (506 in-window, 505 usable, 504 regression rows), frozen model,
                       no parameter change
UPDATED OOS RESULT   = raw daily flow keeps sign and gains significance (coefficient 8.720e-06, p = 0.0175);
                       normalised difference p = 0.4165, 7-session aggregate p = 0.4794
                       per-sub-period the daily-return specification is never significant
                       (EARLY p 0.342, MIDDLE p 0.152, LATE p 0.875, LATE coefficient negative)

ECONOMIC MAGNITUDE   1 SD flow shock (227.6 USD m) -> +53.3 bps next session (raw-flow VAR);
                     500 USD m shock -> +117.1 bps; post-publication IRF -7.0 bps (7-session aggregate)
                     and +10.4 bps (normalised difference, interval [+4.0, +16.2] bps)
COST FLOOR COMPARISON= project round-trip cost floor 23.791 bps. The variant above the floor is the one whose
                     coefficient flips sign under a trend control; the variants that survive falsification sit
                     at or below it. No profitability claim is made: there is no strategy here to make one about.

TEMPORAL STABILITY   three predeclared consecutive thirds of the source window: no sub-period significant at 5%
                     for the daily-return specification; the 7-session version keeps its sign but its inference
                     is not HAC-corrected
FALSIFICATION        realised_vol_20 p 0.0228, day_of_week p 0.0505 (borderline), winsorised p 0.0301,
                     exclude_first_20 p 0.0451 -> survive. degenerate by construction: same_day_return,
                     all_controls (R^2 = 1) and previous_return (collinear with the AR(1) term) -> not evidence.
                     POST-HOC trailing 5-session return control: coefficient SIGN FLIPS, p 0.1331;
                     trailing 20-session: p 0.3675. The effect is a trend proxy.

INDEPENDENT VERIFICATION = PASS, 107/107 checks, 0 mismatches, re-derived from the raw bytes
                     (scripts/rfc035e_verify.py -> reports/rfc035e/INDEPENDENT_VERIFICATION.{json,md})
                     tolerances: coefficient/statistic relative 1e-3, p-value absolute 1e-3, persistence absolute 5e-4
FALSE_SUCCESS        = 0 (checks that reported success without evidence)

OPP-0001 CLASSIFICATION = RESEARCH_HYPOTHESIS_P0 (corrected from REPLICATE_P0) -> REJECT
RFC-035 STATUS       = OPEN_NO_REPLICABLE_EXTERNAL_STRATEGY (its PASS clauses remain unsatisfied)
NEXT GATE            = CONTINUE_EXTERNAL_SEARCH   (RFC-036 is not opened)
```

## 1. The correction that had to come first

RFC-035 classified OPP-0001 as `REPLICATE_P0` — and, the corrected verifier found, OPP-0002 as
`REPLICATE_P1` — while their own records said the entry rule, exit rule and thresholds were
`UNKNOWN`. A replication rank asserts `REPLICABLE_ENTRY_EXIT_LOGIC`; neither candidate had it, so
both classifications were wrong. They are now corrected in the RFC-035 artifacts:

```text
PREVIOUS_CLASSIFICATION  = REPLICATE_P0 (OPP-0001), REPLICATE_P1 (OPP-0002)
CORRECTED_CLASSIFICATION = RESEARCH_HYPOTHESIS_P0 (OPP-0001), RESEARCH_HYPOTHESIS_P1 (OPP-0002)
REASON                   = the sources do not define a complete trading strategy
RFC-035 FINAL STATUS     = OPEN_NO_REPLICABLE_EXTERNAL_STRATEGY (was PASS under the wrong contract)
RFC-035 VERIFIER         = scripts/rfc035_discovery_verify.py PASS 214/214 after the correction
```

Nothing earlier was erased: the superseded ranks live on in `rank_history`, in
`classification_correction`, in `selected_opportunity.rank_before_correction` and in the frozen
selection with both of its hashes intact. The registry document also still quoted the pre-re-freeze
`SOURCE_BUNDLE_HASH`; it now carries the current one, and the RFC-035 verifier checks hashes quoted
in prose instead of trusting them.

## 2. What was actually tested

The published claim (S-01, FalconX 2024-10-11): Granger F 8.4767, p 0.00406, previous-day flow
coefficient 0.027 on today's price change, flow persistence 0.533, correlation 0.30, and a positive
impulse response peaking near +1.2% at days 3-4.

Reproduction: raw data fetched and hashed (`research/rfc035e/raw_source_manifest.json`), a frozen
specification written and digested before any statistic (`FALCONX_REPLICATION_SPEC.json`), six
declared variable combinations estimated over the source window and then over the unseen period with
no parameter change, plus a predeclared falsification battery.

## 3. Original versus reproduced (source window)

| quantity | source | reproduced (daily return + daily flow) |
| --- | --- | --- |
| Granger F | 8.4767 | **4.0133** |
| Granger p | 0.00406 | **0.04656** |
| lagged-flow coefficient | 0.027 (source units) | **+2.343e-05 per USD m** (units not comparable) |
| flow persistence | 0.533 | **0.5724** |
| correlation | 0.30 | **0.413** (contemporaneous Pearson) |
| impulse response | +1.2% peaking days 3-4 | **not reproduced** (see section 5) |

With overlapping 7-session returns the daily-flow F rises to 12.0473 (p 0.00065), in the same order
as the source — but that specification has serially correlated errors and the frozen spec has no HAC
correction, so it is reported and discounted.

**The transform the source names does not reproduce.** The normalised-difference transform gives
p 0.2178 (daily return) and p 0.4438 (7-session); the 7-session flow aggregate gives p 0.7443 and
p 0.9574. Only the raw daily flow carries the effect.

## 4. Reverse causality

```text
price -> flow (source window)   coefficient 1420.5733   p 0.0010
price -> flow (OOS)             coefficient 3278.2121   p 0.0000
```

The feedback direction is an order of magnitude more significant than the forward one. Most of the
co-movement is flows following price, exactly as the external literature warns.

## 5. Out-of-sample, stability, and the falsification that decides it

Out of sample the raw-flow variant keeps its sign and gains significance (coefficient 8.720e-06,
p 0.0175; 7-session version F 22.1387). Per sub-period, however, the daily-return specification is
never significant (EARLY p 0.342, MIDDLE p 0.152, LATE p 0.875; the LATE coefficient is negative).

The predeclared battery: 20-session realised volatility survives (p 0.0228), day-of-week is
borderline (0.0505), winsorising survives (0.0301), excluding the first 20 sessions survives (0.0451).

Two specifications are degenerate by construction and are marked as evidence-free: `same_day_return`
and `all_controls` (the dependent variable becomes its own regressor, R² = 1). A third one turned out
to be degenerate too, and that is a defect in the frozen battery rather than in the result:
`previous_return` is the previous 1-session return, which **is** the AR(1) term already in the price
equation of every reported combination, so the control duplicates a column (condition number > 1e10)
and its p 0.0471 is not evidence of anything. The momentum alternative is therefore tested by the
AR(1) term of the baseline model itself — where it does not rescue the flow coefficient — and the
degeneracy flags are now derived from the recorded R² and condition number instead of a hardcoded
list, which is exactly how the collision surfaced.

Then the controls the flow's own persistence demanded, labelled **post-hoc**:

```text
trailing 5-session return control   coefficient -1.777e-05   p 0.1331   SIGN FLIPS
trailing 20-session return control  coefficient +1.214e-05   p 0.3675   significance vanishes
```

Once a multi-session price trend is controlled for, the information attributed to lagged flow is not
identified. That is the falsification the battery exists to perform, and it fails.

The impulse response is the same story from another angle: the response is concentrated at impact
(the same session as the flow, before the number is public) — +113.9 bps for a 292 USD m shock to the
7-session aggregate, and about +33 bps for the normalised difference with an interval that already
crosses zero — and then collapses. The post-publication response is approximately **-7.0 bps** at the
first step for the aggregate and **+10.4 bps** for the normalised difference with a 95% interval of
[+4.0, +16.2] bps. The source's delayed +1.2% drift does not appear.

## 6. Economic magnitude versus the cost floor

```text
1 SD flow shock (227.6 USD m) -> +53.3 bps on the next session (via the raw-flow VAR)
500 USD m shock               -> +117.1 bps on the next session
post-publication IRF          -> -7.0 bps (aggregate) / +10.4 bps (normalised difference)
project round-trip cost floor ->  23.791 bps
```

Read together: the variant whose next-session response exceeds the cost floor (raw daily flow) is
precisely the one whose coefficient flips sign under a trend control, while the variants that survive
falsification land at or below the floor. The large numbers therefore belong to the specification the
battery rejects, not to the one it accepts. **No profitability claim is made** — there is no strategy here to make
one about, and this step is only a scale check.

## 7. Independent verification

`scripts/rfc035e_verify.py` does not import the estimator and does not read the derived dataset: it
re-parses the raw Farside HTML and the raw Binance klines from the bytes recorded in the manifest,
rebuilds the series, re-estimates the reference model, and compares with declared tolerances
(coefficient and statistics relative 1e-3, p-values absolute 1e-3, persistence absolute 5e-4). It also
checks the spec digest, the dataset hash, the OOS no-change declaration, the PIT convention, and that
no artifact asserts a forbidden verdict. Result: **PASS 107/107, 0 mismatches, `FALSE_SUCCESS` = 0**, in
`reports/rfc035e/INDEPENDENT_VERIFICATION.json`. The verifier's own two outputs are checked *after*
they are written, so a clean first run cannot pass on evidence it has not produced yet. Four real
defects were found and fixed this way, and they are listed in the JSON rather than quietly patched:

1. the artifact's `sessions` field and the verifier's meant different things (usable rows vs rows in
   the equations), which showed up as an off-by-one of 1 in both windows; both counts are now
   declared separately and the verifier re-derives all three;
2. the per-control `degenerate` flags contradicted the artifact's own declared list, which is how the
   collinear `previous_return` control was found;
3. the verifier required its own markdown to pre-exist, making a first run fail on a file it had not
   written yet;
4. the RFC-035 registry document quoted a stale `SOURCE_BUNDLE_HASH`; prose hashes are now checked.

## 8. Verdict, and what would change it

```text
EFFECT_NOT_REPRODUCED
OPP-0001 = REJECT
```

The effect is not reproduced **as claimed**: the named transform fails, the surviving variant is a
trend proxy by the battery's own test, stability is absent within sub-periods, and the delayed drift
does not exist. What remains is a same-session comovement between flows and prices with flows
following prices more strongly than the reverse.

A different verdict would need concrete things, not a re-run: HAC inference for the overlapping
specifications, a point-in-time flow series with verified publication timestamps, an instrument or
natural experiment for flow shocks, or a venue where creation demand is less anticipated.

RFC-035 now carries its corrected status `OPEN_NO_REPLICABLE_EXTERNAL_STRATEGY` with no replicable
external strategy on record, and its own verifier passes 214/214 under that contract; RFC-036 is not
opened; the RFC-041 freeze is untouched.
