# NEGATIVE KNOWLEDGE

| ID | SOURCE | DO NOT DO | WHY / FAILURE MODE | PROJECT ACTION |
|---|---|---|---|---|
| NEG-001 | SRC-BOOK-001 pp. 31-38 | Infer that because many traders lose, taking the opposite side yields the complement win rate. | Population profitability does not map to per-trade directional accuracy; source gives no valid derivation. | REJECT |
| NEG-002 | SRC-BOOK-001 p. 92 | Adopt a universal 3% breakout filter. | Asset/timeframe/volatility dependence; threshold may be nonstationary. | EXPERIMENT only |
| NEG-003 | SRC-BOOK-001 pp. 125-126 | Copy 1-5-15 / 1-15-45 exposure percentages into Risk. | External threshold is not project evidence; intraday expansion can dramatically increase risk. | REJECT as default; validate separately |
| NEG-004 | SRC-BOOK-001 pp. 117-122 | Treat 1/9, 3:1 R/R, Fibonacci 38/50 as universal truths. | No in-book robustness/OOS evidence. | Candidate parameters only |
| NEG-005 | SRC-BOOK-001 pp. 39-40 | Treat put/call 1.1 / 0.7 as timeless cutoffs. | Market structure and options activity change; absolute levels may drift. | Compare fixed vs normalized/quantile variants |
| NEG-006 | SRC-BOOK-001 pp. 111-113 | Treat “85%” MACD divergence outcome as validated. | No methodology/sample/costs/OOS shown. | Ignore claimed rate; independently test |
| NEG-007 | SRC-BOOK-001 pp. 128-129 | Assume an opposite derivative creates a perfect zero-risk hedge. | Basis risk, contract mismatch, funding, slippage, gaps and sizing error remain. | Formal hedge-risk spec |
| NEG-008 | SRC-BOOK-001 pp. 41-52 | Treat technical analysis as dogma or past-pattern repetition as guaranteed. | Source is opinion/teaching narrative, not empirical proof. | Require controlled evidence |
| NEG-009 | SRC-BOOK-001 pp. 133-150 | Learn from hindsight-perfect textbook charts without right-edge testing. | Selection/right-edge bias. | PIT-safe historical replay; blind evaluation |
| NEG-010 | SRC-BOOK-001 pp. 152-154 | Reward a winning trade that violated the authorized plan. | Outcome can positively reinforce unsafe process. | Separate process-quality from PnL |
| NEG-011 | SRC-NOTE-004 / 013 | Use unconstrained free-form multi-agent chat as the primary decision protocol. | Misalignment, loops, context pollution, groupthink. | REJECT |
| NEG-012 | SRC-NOTE-013 | Let builder be sole verifier. | False-success/self-certification. | REJECT |
| NEG-013 | SRC-NOTE-005 / 013 | Use majority vote without evidence/authority weighting. | Shared-model consensus is not independent evidence. | REJECT |
| NEG-014 | SRC-NOTE-010 / 013 | Let LLM own sizing, risk limits, accounting or execution. | Critical numeric safety must be deterministic/testable. | REJECT |
| NEG-015 | SRC-NOTE-006 / 013 | Auto-modify critical risk/verification rules from experience memory. | Unsafe self-modification. | REJECT |


## V2 Batch 2 additions

| NEG_ID | SOURCE | DO_NOT_DO | PROJECT_RULE |
|---|---|---|---|
| NEG-016 | SRC-BOOK-002 | Do not use rhetorical persuasion, looping, tone or rapport to raise agent decision confidence or overcome Risk/Verifier rejection. | Agent acceptance requires evidence and deterministic gates, not persuasion. |
| NEG-017 | SRC-MANUAL-001 | Do not treat “institutional stop hunting/manipulation” as measured causal truth when only OHLC patterns are observed. | Separate observable pattern from causal hypothesis. |
| NEG-018 | SRC-MANUAL-001 | Do not label Order Blocks/sweeps/regimes after seeing the reversal and then count them as predictions. | Freeze labels at decision_time and right-edge-test. |
| NEG-019 | SRC-MANUAL-001 | Do not adopt 61/79 Fibonacci, 5-pip entry, 10-pip stop, session windows, ADR multipliers or target percentages as defaults. | Every number remains SOURCE_THRESHOLD. |
| NEG-020 | SRC-MANUAL-001 | Do not claim source failure from a test whose entry/exit/regime rules materially differ from the source. | Use TESTED_CONFIGURATION_REJECTED vs SOURCE_HYPOTHESIS_UNRESOLVED. |
| NEG-021 | SRC-MANUAL-002 | Do not adopt 1%-3% daily loss, 2-point stops, Speed >3000, 6-10 point ranges, 25%-61% pullbacks or other book values into Risk/runtime without project evidence. | Threshold quarantine. |
| NEG-022 | SRC-MANUAL-002 | Do not implement volatility from chart-axis/display increments. | UI scale is not a portable market feature; derive point-in-time volatility from data. |
| NEG-023 | SRC-MANUAL-002 | Do not anthropomorphize agent “fear”, “ego”, “hope” or “discipline”. | Translate to stop modification, over-sizing, duplicate signals, horizon changes and conformance violations. |
| NEG-024 | SRC-MANUAL-002 | Do not treat unsupported claims such as 10% survival, 70% range time or other percentages as project evidence. | Record as unsupported source assertions. |
| NEG-025 | SRC-CHEATSHEET-001 | Do not infer missing E-1/E-2 semantics, stop, target, asset or setup conditions from a single diagram. | Candidate remains NEEDS_SPEC. |


## V3 — ARP-005 cost-compatible discovery additions

| NEG_ID | SOURCE | DO_NOT_DO | WHY / FAILURE MODE | PROJECT ACTION |
|---|---|---|---|---|
| NEG-026 | ARP-005 / EXP-ARP-009 | Treat a cross-sectional top-1 selection over a fixed 3-asset universe as an adequate test on a ≈4-month daily corpus. | 17 DEV rotations < frozen minimum 20; the frozen `lookback_days=30` was not shortened to grow the sample. | INSUFFICIENT_EVIDENCE |
| NEG-027 | ARP-005 / EXP-ARP-011 | Relax a Donchian/ATR-expansion gate to manufacture trades. | Only 2 DEV trades in ~122 days; the gates are trigger-starved, not mis-specified. | INSUFFICIENT_EVIDENCE |
| NEG-028 | ARP-005 / EXP-ARP-012 | Advance a mechanism whose gross/cost ratio is ≈1.17 (break-even 27.6 bps vs 23.6 bps cost). | DEV net +4.05 bps but negative at 1.25× cost; VALIDATION collapsed to −374.8 bps gross over 9 trades. | REJECT_VALIDATION |
| NEG-029 | ARP-005 PATH A | Assume that closing a data gap creates an edge. | Extending DEV 122 → 303 days/symbol (adequacy band) only improved the quality of the rejection. | Reinforced |
| NEG-030 | ARP-005 PATH B | Repair/adopt an unevaluated orphan infra module to unblock an experiment. | The minimal tested replacement unblocked EXP-ARP-009, which then failed on economics, not infrastructure. | REIMPLEMENT_MINIMAL_PATTERN |
| NEG-031 | ARP-005 §29 / §19 | Paper-shadow a `REJECT_COSTS` experiment (EXP-ARP-007) to compensate for a lack of net edge. | REJECT_COSTS is terminal; a shadow campaign is not positive expectancy. | REJECT |

## ARP-005 alpha-expansion additions

| NEG_ID | SOURCE | DO_NOT_DO | WHY / FAILURE MODE | PROJECT ACTION |
|---|---|---|---|---|
| NEG-032 | ARP-005 / EXP-ARP-013 | Treat a long multi-regime gross edge as real without checking single-trade concentration. | 31 DEV episodes, gross +1258 bps, but the SOL Aug-2021 rally is >50 % (0.5049) of positive net. | REJECT_FRAGILE |
| NEG-033 | ARP-005 / EXP-ARP-014 | Assume clearing DEV + COST proves an edge. | Weekly cross-sectional reversal: DEV net +11.75 bps, break-even 35.31 bps, yet VALIDATION net −1.91 bps over 84 episodes. | REJECT_VALIDATION |
| NEG-034 | ARP-005 / EXP-ARP-015 | Shorten a frozen ranking window to manufacture a sample for a slow factor. | 60d window + 30d hold over a 3-asset, ~5-year corpus yields only 11 episodes (< 15). | INSUFFICIENT_EVIDENCE |
| NEG-035 | ARP-005 §2 | Treat "N years downloaded" as data adequacy. | Adequacy is timestamp-correct, gap-audited, duplicate-free, PIT-compatible and fingerprinted history. | Measure per split |
| NEG-036 | ARP-005 §10/§11 | Rank assets with mismatched/stale bars or let a caller supply unsynchronized series. | A stale or future bar silently changes the cross-sectional rank; every such case must FAIL CLOSED. | Reject at the snapshot contract |
| NEG-037 | ARP-005 §13/§14 | Canonicalize a candidate because its source count looks incomplete. | The registry is 21 canonical; the 3 unmerged candidates are rejected/blocked and are not new mechanisms. | NO_IMPORT |
| NEG-038 | ARP-005 §5 | Derive HTF bars from incomplete/partial buckets or interpolate missing hours. | A partial bucket reads a future constituent; an interpolated hour fabricates data. | Drop the bucket |
