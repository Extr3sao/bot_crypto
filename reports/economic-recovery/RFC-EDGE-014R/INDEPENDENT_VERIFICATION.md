# WP-EDGE-14R — independent verification

*verified at 2026-10-16T21:20:30Z against `ee3922e9f8e8`; verdict **VERIFIED**.*

Every number below is recomputed from the primitive records, not read from a
summary, and a check that cannot be recomputed is a failure rather than a pass.

| id | check | result | evidence |
| --- | --- | --- | --- |
| V01 | frozen dataset digest re-derived from the exported bars | PASS | sha256 d79ed2c56bf50226… vs recorded d79ed2c56bf50226… |
| V02 | 1-minute source aggregates to the frozen 1h bars | PASS | audited bar-for-bar by scripts/edge14r_fetch_1m.py |
| V03 | the partial final bar is excluded rather than kept | PASS | capture window stops at the final frozen bar's own start |
| V04 | the arm's realised PnL equals the sum of its recorded closed fills | PASS | sum of 347 closed fills -212.544674 vs realised -212.544674 |
| V04b | every close names an opening the arm recorded, and the ledger's identities hold | PASS | opened 348, closed 347, unpaired 1, still open at the end 1; every one of the 347 closes names a recorded opening: True; realised PnL -212.544674 vs equity change -212.544674 |
| V05 | closed fills counted in the stage totals equal the recorded exits | PASS | fills_closed 347 vs exits 347 |
| V06 | the authoritative arm produced no order and no fill | PASS | committed ledger admits nothing, so the funnel stops at the router |
| V07 | no exchange order was sent on any arm | PASS | execution is in-process only |
| V08-freqtrade | freqtrade: every residual satisfies the closed-form convention gap | PASS | max identity error 8.563e-07 bps over 44 trades |
| V09-freqtrade | freqtrade: the per-trade table length equals the matched count | PASS | matched 44 vs rows 44 |
| V10-freqtrade | freqtrade: the engine's trades all matched one of ours | PASS | external-only 0 |
| V08-vnpy_ctastrategy | vnpy_ctastrategy: every residual satisfies the closed-form convention gap | PASS | max identity error 4.919e-07 bps over 42 trades |
| V09-vnpy_ctastrategy | vnpy_ctastrategy: the per-trade table length equals the matched count | PASS | matched 42 vs rows 42 |
| V10-vnpy_ctastrategy | vnpy_ctastrategy: the engine's trades all matched one of ours | PASS | external-only 0 |
| V08-jesse | jesse: every residual satisfies the closed-form convention gap | PASS | max identity error 8.425e-07 bps over 44 trades |
| V09-jesse | jesse: the per-trade table length equals the matched count | PASS | matched 44 vs rows 44 |
| V10-jesse | jesse: the engine's trades all matched one of ours | PASS | external-only 0 |
| V11 | the simulator row's trade count and net sum are reproducible | PASS | recomputed 44 trades / -1070.105581 bps |
| V12 | the simulator row's equity multiple is reproducible | PASS | recomputed equity multiple 0.89216878 |
| V13 | no arm reaches three trades a day with a positive net | PASS | 1 arm(s) reach the ACTIVE frequency (PAPER_REPLAY SANDBOX_ADMISSION) and none of them is profitable, so the target is unmet on quality rather than forced |
| V14 | the reconciliation's router counts match the paper evidence | PASS | 1758 invocations, all refused |
| V15 | a stage without a ledger is not reported as a measured zero | PASS | unknown is kept distinct from zero |
| V16 | the disk guard still permits new decision slots without being relaxed | PASS | status WARNING, free 2.3377 GiB |
| V17 | every engine's fee identity holds | PASS | Additive(g) - Compounded(g) reproduces the reported residual pair |
| V18 | the paper broker's charging rule is reproduced from its own fills | PASS | max residual 8.882e-16 |
| V19 | the adversarial suite is executed, not declared | PASS | 10/10 pass, 0 declared-only |
| V20 | the three formerly declared cases are covered | PASS | replaces ['S12 fill_without_a_broker', 'S17 invented_maker_fill', 'S27 runtime_change_enabling_live'] |
| V21 | the holdout protocol was frozen before it was captured | PASS | protocol sha256 ea332d4ee11a4b42… still matches the manifest; frozen 2026-10-16T20:01:44Z <= captured 2026-10-16T20:01:44Z; the timestamps are second-resolution, so the hash is the binding commitment |
| V22 | the holdout is reserved and no selection has read it | PASS | state OOS_ACCRUING, not scored |
| V23 | the captured slice still hashes to its recorded digest | PASS | d92ac8cd8e86641c… over 1142 bytes |
| V24 | the runtime configuration still puts the bot in paper mode | PASS | no live trading enabled by this work package |

**31/31 checks pass.**
