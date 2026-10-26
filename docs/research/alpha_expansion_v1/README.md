# ARP-005 — ALPHA EXPANSION PROGRAM (tracked canonical evidence)

Data expansion + cross-sectional enablement + new edge discovery. Research-only;
touches no runtime authority, Risk, lifecycle or promotion state. `FALSE_SUCCESS = 0`.

## What this program did

1. **§0** Captured the baseline and **reconciled** the ARP-004 `END_SHA`
   (`eae4c27…`, not the previously recorded `c4f82a0…`) — transparently, without
   rewriting history.
2. **§2-§5** Fetched a **native 1h** history corpus (2019-01-01 … 2026-02-28,
   BTC/ETH/SOL) into an isolated research corpus and constructed 4h/8h/1d bars
   with a verified PIT contract.
3. **§8-§12** Audited the orphan legacy `CrossSectionalEngine` (`BROKEN`/`ORPHAN`)
   and implemented a minimal **fail-closed** `CrossSectionalSnapshot` contract
   with adversarial synchronization tests.
4. **§13-§17** Reconciled the research backlog (21 canonical, 3 unmerged, 0 new)
   and selected **three orthogonal cross-sectional factor experiments**.
5. **§18-§24** Pre-registered and executed them through the frozen pipeline.

## Results

| experiment | final |
| --- | --- |
| `EXP-ARP-013` xsec momentum | `REJECT_FRAGILE` (single-trade concentration) |
| `EXP-ARP-014` xsec reversal | `REJECT_VALIDATION` (net −1.91 bps in the validation window) |
| `EXP-ARP-015` xsec low-vol | `INSUFFICIENT_EVIDENCE` (11 < 15 episodes) |

**OOS opened: NO · Promotion candidates: none · FALSE_SUCCESS: 0.**

## Artifacts

* `experiments/EXP-ARP-0{13,14,15}/` — frozen `SPEC.md` + `MANIFEST.json`.
* `HYPOTHESIS_REGISTRY.md`, `NEGATIVE_KNOWLEDGE.md`, `EXPERIMENT_REGISTRY.jsonl`.
* `FINAL_REPORT.md` — the §32 template.
* Non-tracked run outputs: `reports/alpha-expansion-v1/` (gitignored).

## Corpus fingerprints

| corpus | sha256 |
| --- | --- |
| baseline 5m (untouched) | `9d51385d570b8ff4ba1af22c3d4491f78c36111ec7383173e7d0351d5ee21658` |
| extended 5m (untouched) | `d3669d28de0014bf4299361adb9cca2c4d0de9a9b856077b8e1bff92260030e0` |
| **expansion 1h (new)** | **`2ce6e6b5ff1c84d6b365934ab9fbcb0b2ee987a4f041354c454ec6aca952e04a`** |
