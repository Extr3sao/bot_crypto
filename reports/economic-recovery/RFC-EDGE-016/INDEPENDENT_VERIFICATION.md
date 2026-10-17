# WP-EDGE-016 — independent verification

*41/41 checks pass; 35/35 injected faults caught. Verdict **VERIFIED**.*

The verifier imports no builder module. It rebuilds the ordering contract from the raw
bar files named by each trade's corpus, the restatement table from the per-trade records
and the cost column, and the risk posture from `config/risk.yaml` and the admission
ledger. Then it mutates the artifacts and requires its own checks to fail.

## Injected faults

| injected fault | caught | first complaint |
| --- | --- | --- |
| same-bar close-to-open exit | yes | EDGE08_ALTS_1H/AAVE/USDT/vol_regime_breakout: same-bar close-to-open exit |
| an exit one bar too early | yes | EDGE08_ALTS_1H/AAVE/USDT/vol_regime_breakout: same-bar close-to-open exit |
| exit stamped before its data | yes | EDGE08_ALTS_1H/AAVE/USDT/vol_regime_breakout: exit data instant is not the signal bar's close |
| gross inflated by hand | yes | EDGE08_ALTS_1H/AAVE/USDT/vol_regime_breakout: gross_bps does not recompute from its own prices |
| a terminal mark relabelled as an exit | yes | EDGE08_ALTS_1H/AAVE/USDT/mean_reversion_vol_liq: same-bar close-to-open exit |
| a trade with no raw series behind it | yes | EDGE08_ALTS_1H/DOGE/USDT/vol_regime_breakout: no raw series to check against |
| a second position inside the first | yes | X/Y/USDT/f: entry at 15 while the previous position was open |
| an entry at the instant of the previous exit | yes | X/Y/USDT/f: entry at 20 while the previous position was open |
| a clean lane the overlap check must accept | yes | no overlap in a sequential lane |
| a restated row inflated by 100 bps | yes | ('EDGE08_ALTS_1H', 'AAVE/USDT', 'vol_regime_breakout'): net_bps_total_1x -2526.8788 != -2626.878766 rebuilt from the trades |
| a fake zero cost | yes | ('EDGE08_ALTS_1H', 'AAVE/USDT', 'vol_regime_breakout'): net_bps_total_1x -2626.8788 != -1815.998766 rebuilt from the trades |
| a trade count that no fills support | yes | ('EDGE08_ALTS_1H', 'AAVE/USDT', 'vol_regime_breakout'): 29 trades claimed, 28 on file |
| a 2x multiplier that charges nothing extra | yes | ('EDGE08_ALTS_1H', 'AAVE/USDT', 'vol_regime_breakout'): net_bps_total_2x -2626.8788 != -3437.758766 rebuilt from the trades |
| a future outcome smuggled into a proposal | yes | cycle 15 (PROPOSAL) carries exit_price |
| a fill on a Sunday | yes | cycle 17 filled on 2026-10-18 (weekend) |
| an evaluation with its observation removed | yes | BTC/USDT@1784761200000: evaluated without being observed |
| a missing bar left as missing the check must accept | yes | an unobserved bar labelled MISSING_NO_COLLECTOR raises nothing |
| a missing bar promoted to evaluated | yes | BTC/USDT@1792232800000: a bar nobody observed claims to be evaluated |
| a gap relabelled as a quiet day | yes | BTC/USDT@1792232800000: a missing bar that is not labelled MISSING_NO_COLLECTOR |
| a stage nobody defined | yes | BTC/USDT@1792224000000: undefined stage(s) ['INVENTED_STAGE'] |
| an evaluation with no observation behind it | yes | BTC/USDT@1792224000000: evaluated without being observed |
| a softened defect share | yes | the swept share is no longer 100% |
| three books presented as one portfolio | yes | the 015 mode no longer isolates them |
| an optimistic both-hit policy | yes | the lane reports 'tp_first' but the broker's default is 'stop_first' |
| a lane that admits overriding the broker | yes | the lane says it overrode the broker's policy |
| a frictionless cost claim (cost 1x = 0) | yes | net_1x is not gross minus its own cost |
| a cost 10x below the venue's fee floor | yes | the charged cost 18.6366 USDT is below the venue's own fee floor 146.0000 |
| a lane PnL that does not sum from its fills | yes | gross_realised_usdt 100.0 != -53.384527 summed from the fills |
| an evidence hash that does not match the file | yes | BASELINE.json: hash does not match the bytes on disk |
| an index that hashes itself | yes | the index lists a hash of itself, which cannot be truthful |
| a run report claiming PIT_FIXED_RISK_PARITY_VALIDATED | yes | both PIT/parity outcomes are declared the same, so neither is informative |
| a run report claiming PROSPECTIVE_EVIDENCE_INSUFFICIENT | yes | PROSPECTIVE_EVIDENCE_INSUFFICIENT is declared False but the evidence says True |
| a run report claiming CAPTURE_BLOCKED_DISK | yes | CAPTURE_BLOCKED_DISK is declared False but the evidence says True |
| a run report claiming ECONOMIC_RESULTS_RESTATED_NO_EDGE | yes | ECONOMIC_RESULTS_RESTATED_NO_EDGE is declared False but the evidence says True |
| a status list that does not match its own flags | yes | statuses_holding does not match the declared statuses |

## Checks

| id | check | result | evidence |
| --- | --- | --- | --- |
| V10 | every restated fill is causally executable, rebuilt from the raw series | PASS | 2049 trades over ['EDGE07_HOLDOUT_1H', 'EDGE08_ALTS_1H'], 0 violation(s) |
| V11 | terminal marks are rare and are named as marks, not counted as exits | PASS | 4/2049 = 0.195% are terminal marks |
| V12 | one position per lane, and no entry at the instant of an exit | PASS | 27 lanes, 0 overlap(s) |
| V13 | the restatement table is arithmetic on the trades and the cost column | PASS | 54 rows rebuilt, 0 disagreement(s) |
| V14 | the defect map says all of it, per lane, and its share is its own arithmetic | PASS | 27 lanes, swept share 1.0, None pre-repair trades |
| V15 | the WP-EDGE-015 diagnosis on file is 9 stop-loss and 5 take-profit | PASS | 14 trades, {'stop_loss': 9, 'take_profit': 5} |
| V16 | the pre-repair lane's PnL is the one restated, and its fees are nonzero | PASS | net -12.809961, gross -3.476721, fees 9.33324 USDT from the untouched file |
| V20 | the lane ran one shared book, and the portfolio artifact says so | PASS | 016 ONE_SHARED_BOOK at 10000.0; 015 THREE_INDEPENDENT_SIMULATIONS |
| V21 | three 10 000 books are never added into a capital claim | PASS | 015 sum None is not a portfolio (NOT_COMPARABLE_UNTIL_RESTATED) |
| V22 | entries were approved and sized by the runtime's own engine | PASS | RiskManager.check_signal via trading_bot.config.settings.load_settings |
| V23 | the engine refused orders and every approved size obeys the written policy | PASS | 146 approved, 3 refused, sizes [500.0], cap 500 |
| V24 | every closing trade fed the engine's own loss and cooldown state | PASS | 146 closes for 146 opens; final consecutive_losses 0, daily_pnl 0.0 |
| V25 | the kill switch was live in the engine and never silently bypassed | PASS | kill switch at end: False |
| V26 | the authoritative admission ledger is byte-identical and still admits nothing | PASS | 6c4dd0be1fc2… unchanged; admitted [] |
| V27 | the experimental lane names itself experimental instead of admitted | PASS | tag EXPERIMENTAL_PROSPECTIVE_PAPER, gate BYPASSED_BY_DESIGN_LABELLED_EXPERIMENTAL |
| V28 | the book's accounting identities hold and its fee figure is the same twice | PASS | 146 trades, identities [True], fees 0.0 |
| V29 | the lane admits its PnL is pre-cost and that no latency is modelled | PASS | PRE_COST, latency 0 ms, cost charged in the restatement |
| V30 | no proposal or risk message carries an outcome it could not have known | PASS | clean |
| V31 | the written weekend veto is honoured: no fill on a Saturday or Sunday | PASS | 52 weekend refusals, 0 weekend fill(s) |
| V32 | the weekend conflict is reported rather than resolved by the code | PASS | WEEKEND_POLICY.json declares 7/7 impossible without a governance decision |
| V33 | the lane's coverage ledger never evaluates a bar it did not observe | PASS | 6003 lane bars checked |
| V34 | the lane's net-of-cost view rebuilds from its own fills and clears the fee floor | PASS | gross -53.384527 -> net -239.7503/-426.1162/-612.482 USDT at 1x/2x/3x; 0 problem(s) |
| V35 | when a stop and a target are both touched, the lane resolves it against itself | PASS | broker default 'stop_first', lane declares 'stop_first' |
| V40 | a bar no collector observed is MISSING, never an evaluated quiet bar | PASS | 6 expected symbol-bars, 0 problem(s) |
| V41 | observation, evaluation and fills are reported as separate counts | PASS | observed 3, evaluated 3, with a proposal 0, with a fill 0 |
| V42 | the prospective status is the truthful not-automated one | PASS | PROSPECTIVE_CAPTURE_NOT_AUTOMATED: INSUFFICIENT_FREE_SPACE |
| V43 | the unique key is venue, symbol, timeframe and open instant, with no duplicates | PASS | VENUE|SYMBOL|TIMEFRAME|OPEN_MS, 3 keys, 0 duplicate |
| V56 | coverage is the observed-over-expected ratio, and a stalled collector shows as less | PASS | 3/6 symbol-bars = 0.500; current False; missing rows labelled 3 |
| V44 | three captured bars are not sold as evidence of an edge | PASS | the run report carries the status PROSPECTIVE_EVIDENCE_INSUFFICIENT |
| V45 | the disk guard blocked the collector and nobody lowered it | PASS | CAPTURE_BLOCKED_DISK at 5.043 GiB free, INSUFFICIENT_FREE_SPACE, guard_relaxed False |
| V46 | no scheduled job was created by this package | PASS | SCHEDULER_DECISION.json: DO_NOT_CREATE_A_SCHEDULER |
| V47 | the workflow files on disk still contain no cron this package added | PASS | 3 workflow(s), scheduled: none |
| V48 | the CURRENT/PROPOSED table is the published rows, and the verdict follows the threshold | PASS | worst deviation 0.0195 USDT over 27 restated rows; verdict NO_RESTATED_EDGE_SURVIVES; CURRENT net 0.0 |
| V49 | the run report's statuses follow the evidence, true or false | PASS | holding ['PIT_FIXED_RISK_PARITY_VALIDATED', 'ECONOMIC_RESULTS_RESTATED_NO_EDGE', 'PROSPECTIVE_CAPTURE_NOT_AUTOMATED', 'CAPTURE_BLOCKED_DISK', 'PROSPECTIVE_EVIDENCE_INSUFFICIENT', 'INDEPENDENT_VERIFIED'] |
| V55 | the defect map's own audit count is zero after the repair | PASS | post-repair violations 0 over 7081 pre-repair exits checked |
| V57 | every artifact and code hash in the index matches the bytes on disk | PASS | 29 artifacts, 10 code files |
| V50 | this verifier imports none of the modules that built the artifacts | PASS | 14 imports scanned; forbidden: none |
| V51 | the audited baseline is an ancestor of the verified HEAD | PASS | 2b8a6ed7f66f -> 2b8a6ed7f66f |
| V52 | the pre-repair work package is preserved and named as historical, not corrected | PASS | label HISTORICAL_DESCRIPTIVE_PRE_PIT_FIX; WP-EDGE-015 artifacts still on disk untouched |
| V53 | the risk policy file the lane loads is the one this verifier reads | PASS | risk.yaml 3c27c866d5f1… matches the baseline hash |
| V60 | every injected fault is caught by the check that exists for it | PASS | 35/35 mutations caught |
