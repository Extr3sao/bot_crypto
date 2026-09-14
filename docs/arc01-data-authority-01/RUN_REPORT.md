# RUN_REPORT — ARC-01 FUNDING / CROWDING DATA AUTHORITY 01

Generated: 2026-09-14T17:07:12.359962Z
Base: `e7f470d`  HEAD: `e7f470d8ea07`  Branch: `research/arc01-data-authority-01`
Verdict: **PASS**  Economics: `ARC01_BACKTESTS=0` `ARC01_EXECUTIONS=0` `PERFORMANCE_OBSERVED=false`

## Funding source (official only)
- data.binance.vision:fundingRate/monthly (official archive, .CHECKSUM verified)
- binanceusdm:/fapi/v1/fundingRate (official REST, tail after 2026-08-31 16:00 UTC)

Raw: Vision 232 zips (.CHECKSUM verified) + REST tail 126 rows
Dataset SHA: `5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec`  Canonical rows SHA: `34f736b1efdaebcf81c2e7824f776706385f27aee1c564f3dc39f8d1fe993452`  Rows: 21346

- **BTCUSDT**: 7347 `2020-01-01T00:00:00Z` -> `2026-09-14T16:00:00Z` `sha=700b0c4c7e5f` class=VALID
- **ETHUSDT**: 7347 `2020-01-01T00:00:00Z` -> `2026-09-14T16:00:00Z` `sha=2edf501ea698` class=VALID
- **SOLUSDT**: 6652 `2020-09-13T16:00:00.004000Z` -> `2026-09-14T16:00:00Z` `sha=6b16d13f5115` class=VALID

Quality: **PASS**  PIT: **PASS**  `data_time <= decision_time`  availability==settlement
OI reuse: **REUSABLE** (`16779b7d2eff`)  Price reuse: **REUSABLE** (`e1c2462a6aa9`)
Common causal window (funding superset, intersect with OI): funding `2020-09-13T16:00:00.004000Z` -> `2026-09-14T16:00:00Z` (SOL from 2020-09-13); OI/price H6 common `2021-12-01 -> 2026-09-10`

## Artifacts
- `docs/arc01-data-authority-01/ARC01_DATA_INVENTORY.json`
- `docs/arc01-data-authority-01/ARC01_FUNDING_MANIFEST.json`
- `docs/arc01-data-authority-01/ARC01_FUNDING_DATA_AUTHORITY.json`
- `docs/arc01-data-authority-01/ARC01_DATASET_FINGERPRINT.json`
- `docs/arc01-data-authority-01/ARC01_DATA_DETERMINISM.json`
- `docs/arc01-data-authority-01/ARC01_MUTATION_SENSITIVITY.json`
- `docs/arc01-data-authority-01/ARC01_PIT_AUTHORITY.json`
- `docs/arc01-data-authority-01/ARC01_OI_REUSE_ASSESSMENT.json`
- `docs/arc01-data-authority-01/ARC01_PRICE_REUSE_ASSESSMENT.json`
- `docs/arc01-data-authority-01/ARC01_COMMON_CAUSAL_WINDOW.json`
- `docs/arc01-data-authority-01/ARC01_SOURCE_REGISTRY.md`
- `docs/arc01-data-authority-01/ARC01_CANDIDATE_DESIGN.md`
- `docs/arc01-data-authority-01/ARC01_RESUME_STATE.json`
- `docs/arc01-data-authority-01/RUN_REPORT.json`

