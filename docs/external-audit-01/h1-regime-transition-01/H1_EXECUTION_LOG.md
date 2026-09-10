# H1 EXECUTION LOG

- Spec sha256: `8baaff7dea28a346c9754eb408f537aaee24978b9dce279d213942863e5fc701` (prereg commit 3ad054d)
- Dataset rows: {"BTCUSDT": 58633, "ETHUSDT": 58633, "SOLUSDT": 52458}
- Dataset manifest sha256: `5a33c678c5ddca91e2b736ffc6add535e4fba83b35ba7e983abb1b1f3112460f`
- H1 trades: 10193 · proxy trades: 14008 · transitions: 29179
- Result class: **DISCOVERY_FAIL**
- Written BEFORE results: marker at 2026-09-10T11:32:13.791045+00:00
- ECONOMIC EXECUTION 2026-09-10T11:16Z→11:32Z (code state at execution = b9e2760a6ff186ed1c00d02aea1c857ec31b09e8, frozen core; execution_commit b9ddc35504b45e2e779e568c593625c0964628fc contains the artifacts and is strictly later than prereg 3ad054d): dataset 58633/58633/52458 rows, marker written before results, H1_RESULT.json = DISCOVERY_FAIL (N=10193). Exactly one economic execution; attempt notes above document two pre-result crashes (constructor kwarg; no evaluation consumed).
- PREREG ALIGNMENT NOTE: WINDOW_END_MS corrected 2026-08-18→2026-09-09 BEFORE any evaluation ran (spec-declared window restored; counts above reflect the full frozen window). No threshold, rule or hypothesis text changed after seeing data.
- POST-RUN FILL 2026-09-10T12:20Z: execution_commit filled into H1_RESULT.json (was POST_RUN_FILL) and this line added; no metric, threshold or dataset field changed at any point. Forensic note: RESULT mtime 11:32:13Z precedes MARKER mtime 11:42:29Z because a later --replay invocation (b9e2760 code) reproduced the identical result byte-for-byte but its replay path erroneously re-wrote the exactly-once marker and re-appended the crash attempt note; both side effects are governance-fixed in execution_commit b9ddc35 and can never recur. This replay is deterministic verification (flagged technical_replay=false in RESULT because the fill run produced the original economic file), NOT a second economic experiment; the single economic simulation is the 11:16Z→11:32Z run.
