# WP-EDGE-015 — independent verification

*32/32 checks pass. Verdict **VERIFIED**.*

The verifier imports none of the modules that built these artefacts: the cost model is recomputed from its published parameters, one family's held-out trade list is rebuilt from the raw bars by a second implementation, the verdicts are re-derived from the matrix and the frozen thresholds, and the repositioned Jesse residual is recomputed from the published rows.

| id | check | result | detail |
| --- | --- | --- | --- |
| V01 | the v2 freeze and its capture manifest exist (the v1 evidence could not order them) | PASS | OOS_PREREGISTRATION_V2.json=True OOS_CAPTURE_MANIFEST_V2.json=True |
| V02 | every clause of the order check is true (not a sentence containing False) | PASS | verdict ORDER_VERIFIED; freeze_precedes_capture=True, prereg_file_matches_committed_blob=True, commit_precedes_capture=True, protocol_digest_matches=True, all_prospective_bars_open_after_freeze=True |
| V03 | the ordering is reconstructed from the recorded integers | PASS | freeze 1792221328939466200 -> capture 1792221621701637600 (+292762171400 ns) |
| V04 | the frozen file still hashes to the blob of the commit that added it | PASS | commit b4ff58892263 blob cea0be89347d219b… |
| V05 | that commit is an ancestor of HEAD (the freeze was not rewritten) | PASS | git merge-base --is-ancestor -> 0 |
| V06 | the protocol digest recomputes from the frozen protocol block | PASS | protocol sha256 3a88f70da2f10d0e… |
| V07 | every bar in the prospective slice opens after the freeze instant | PASS | 0 prospective bar(s); digest matches the manifest |
| V08 | the 14R slice is preserved and labelled descriptive | PASS | d92ac8cd8e86641c… DESCRIPTIVE_FOR_THESE_HYPOTHESES |
| V09 | the holdout is reserved: no selection read it and nothing scored it | PASS | state OOS_ACCRUING, selection_has_read_any_slice=False |
| V10 | every row's cost per round trip recomputes from the published cost model | PASS | worst deviation 0.000e+00 bps over 60 rows |
| V11 | the sensitivity columns are the same trades priced at 1x, 2x and 3x | PASS | worst identity error 2.183e-11 bps; monotone True |
| V12 | the decisive family's entries satisfy their own gate on past bars only | PASS | 119 published trades re-derived; worst z overshoot 0.000e+00; worst price mismatch 0.000e+00 |
| V13 | every published verdict is re-derived from the matrix and the frozen thresholds | PASS | published {'cross_sectional_rotation': 'REJECT', 'mean_reversion_vol_liq': 'EXPERIMENT_COST_FRAGILE', 'trend_pullback': 'REJECT', 'vol_regime_breakout': 'REJECT_OUTLIER_DRIVEN'} vs recomputed {'mean_reversion_vol_liq': 'EXPERIMENT_COST_FRAGILE', 'cross_sectional_rotation': 'REJECT', 'trend_pullback': 'REJECT', 'vol_regime_breakout': 'REJECT_OUTLIER_DRIVEN'} |
| V14 | no family is reported as adoptable | PASS | ADOPT requires prospective data, which has not accrued |
| V15 | the maker family is declared untested rather than given a fabricated fill model | PASS | no queue model exists in the tree, so no maker backtest was run |
| V16 | NO_ECONOMIC_EDGE_FOUND agrees with the verdicts | PASS | rejected families: ['cross_sectional_rotation', 'trend_pullback', 'vol_regime_breakout'] |
| V17 | the registered candidates are disabled in the runtime's own vocabulary | PASS | 15 candidates, paper_candidates=[] |
| V18 | the authoritative admission ledger still admits nothing | PASS | 24 entries, none admitted |
| V19 | the lane is labelled experimental and cannot count as an admitted operation | PASS | ledger sha256 6c4dd0be1fc2fff2… unchanged |
| V20 | every lane trade carries broker-minted identities, all distinct | PASS | 14 trades, 56 identifiers, 56 distinct |
| V21 | net PnL decomposes into gross minus both commission legs | PASS | worst residual 0.000e+00 USDT over 14 trades |
| V22 | realised PnL equals the sum of the closed trades | PASS | report -12.809961 vs recomputed -12.809961 |
| V23 | the accounting identities hold in every book | PASS | {'cash_equals_initial_plus_realised': True, 'closed_trade_pnl_rebuilds': True, 'equity_equals_cash_plus_net_unrealised': True, 'ledger_equity_equals_initial_plus_realised': True} |
| V24 | positions that share a wall-clock instant still have distinct identities | PASS | 4 (symbol, opened_at) group(s) shared by more than one position; identities remain distinct |
| V25 | rejected families were refused, not traded, and no signal was forced | PASS | 160 refused cycles, 14 fills, 210 cycles total |
| V26 | no exchange order was sent and the risk limits were not changed | PASS | 14 simulated orders, none sent |
| V27 | the Jesse residual is the sum of its three terms, recomputed independently | PASS | worst error 1.210e-07 bps over 2 material trades |
| V28 | every other trade agrees within the preregistered tolerance | PASS | worst 0.080318 bps over 42 trades (tolerance 1.0) |
| V29 | the two unmatched VeighNa trades are the last two entries of the rule | PASS | unmatched [1792094400000, 1792094400000], last two [1792094400000] |
| V30 | both divergences are reported as resolved | PASS | jesse RESOLVED, vnpy RESOLVED |
| V31 | this verifier imports no builder module | PASS | imports scanned: 14; forbidden found: [] |
| V32 | the 14R verifier no longer imports the module that built its artefacts | PASS | its 11 imports contain no builder module |
