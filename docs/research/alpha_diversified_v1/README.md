# ARP-006 — DIVERSIFIED ALPHA SEARCH (tracked canonical evidence)

PIT dynamic crypto universe + ready slow-horizon experiments + broader-universe
cross-sectional factors. Research-only; touches no runtime authority, Risk,
lifecycle or promotion state. `FALSE_SUCCESS = 0`.

## What this program did

1. **§0** Captured the baseline and corrected the ARP-005 VALIDATION/OOS terminology
   (`EXP-ARP-014`'s result is a **VALIDATION** result, not out-of-sample, because
   `OOS_OPENED = NO`).
2. **§1** Froze the ARP-001…ARP-015 negative knowledge; nothing is re-run.
3. **§2-§9** Fetched a broader native **1d** corpus (130 USDT markets) and built the
   research-only, fail-closed `DynamicAssetUniverse` / `UniverseSnapshot` with PIT
   listing, liquidity, data-quality and synchronization gates and explicit
   `SURVIVORSHIP_DATA_LIMITATION`.
4. **§10-§13** Executed the two READY experiments (`EXP-ARP-006`, `EXP-ARP-008`) on
   the expanded multi-regime corpus with their frozen parameters.
5. **§14-§18** Pre-registered and executed three NEW broader-universe cross-sectional
   factors (`EXP-ARP-016/017/018`) with concentration and breadth gates.
6. **§19-§25** Ran DEV → COST → VALIDATION → ROBUSTNESS with temporal and regime
   decomposition. **§26** OOS stayed sealed. **§27** a verifier was provisioned when
   a survivor appeared.

## Experiments

| id | strategy_id | mechanism | universe | status |
| --- | --- | --- | --- | --- |
| `EXP-ARP-006` | `STRAT-CAND-016-VARIANT-B` | daily liquidity-reversal | 3 frozen assets | see `FINAL_REPORT.md` |
| `EXP-ARP-008` | `H-DAILY-TSMOM-001` | daily time-series momentum | 3 frozen assets | see `FINAL_REPORT.md` |
| `EXP-ARP-016` | `H-XSEC-MOM-LONG-002` | xsec momentum (broad) | PIT dynamic | see `FINAL_REPORT.md` |
| `EXP-ARP-017` | `H-XSEC-REV-002` | xsec reversal (broad) | PIT dynamic | see `FINAL_REPORT.md` |
| `EXP-ARP-018` | `H-XSEC-LOWVOL-002` | xsec low-volatility (broad) | PIT dynamic | see `FINAL_REPORT.md` |

`EXP-ARP-016/017/018` are **NEW** experiment ids: the previous `EXP-ARP-013/014/015`
configurations are frozen negative knowledge and may not be re-run on the same data.

## Artifacts

* `experiments/EXP-ARP-0{16,17,18}/` — frozen `SPEC.md` + `MANIFEST.json`.
* `HYPOTHESIS_REGISTRY.md`, `NEGATIVE_KNOWLEDGE.md`, `EXPERIMENT_REGISTRY.jsonl`.
* Non-tracked run outputs and reports: `reports/alpha-diversified-v1/` (gitignored).

## Corpus fingerprints

| corpus | sha256 |
| --- | --- |
| diversified 1d (new) | see `reports/alpha-diversified-v1/RESULTS.json` (`universe.corpus_digest`) |
| ARP-005 expansion 1h (untouched) | `2ce6e6b5ff1c84d6b365934ab9fbcb0b2ee987a4f041354c454ec6aca952e04a` |
| baseline 5m (untouched) | `9d51385d570b8ff4ba1af22c3d4491f78c36111ec7383173e7d0351d5ee21658` |
