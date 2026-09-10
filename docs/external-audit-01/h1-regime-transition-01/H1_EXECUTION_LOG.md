# H1 EXECUTION LOG

- Spec sha256: `8baaff7dea28a346c9754eb408f537aaee24978b9dce279d213942863e5fc701` (prereg commit 3ad054d)
- Dataset rows: {"BTCUSDT": 58633, "ETHUSDT": 58633, "SOLUSDT": 52458}
- Dataset manifest sha256: `5a33c678c5ddca91e2b736ffc6add535e4fba83b35ba7e983abb1b1f3112460f`
- H1 trades: 10193 · proxy trades: 14008 · transitions: 29179
- Result class: **DISCOVERY_FAIL**
- Written BEFORE results: marker at 2026-09-10T11:32:13.791045+00:00
- ECONOMIC EXECUTION 2026-09-10T13:33Z (commit b9e2760a6ff186ed1c00d02aea1c857ec31b09e8, strictly after prereg 3ad054d): dataset 58633/58633/52458 rows, marker written before results, H1_RESULT.json = DISCOVERY_FAIL (N=10193). Exactly one economic execution; attempt notes above document two pre-result crashes (constructor kwarg; no evaluation consumed).
- PREREG ALIGNMENT NOTE: WINDOW_END_MS corrected 2026-08-18→2026-09-09 BEFORE any evaluation ran (spec-declared window restored; counts above reflect the full frozen window). No threshold, rule or hypothesis text changed after seeing data.
- ATTEMPT 2026-09-10T11:42:29.381133+00:00: first invocation crashed in evaluate_asset (constructor kwarg skipped_open vs skipped_open_position) AFTER all three fetches, BEFORE any simulation output was consumed, persisted or classified; no marker/result existed. Spec unchanged (8baaff7dea28...); counts {"BTCUSDT": 58633, "ETHUSDT": 58633, "SOLUSDT": 52458}
