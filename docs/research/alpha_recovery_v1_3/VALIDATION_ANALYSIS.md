# ARP-004 — VALIDATION ANALYSIS (§11–§13)

| experiment | entered VALIDATION? | result |
| --- | --- | --- |
| `EXP-ARP-007` | **No** | `NOT_REACHED` (stopped at the COST gate) |
| `EXP-ARP-010` | **No** | `NOT_REACHED` (stopped at the DEV gate) |

## Why no validation was run

§11: *only DEV + COST survivors enter VALIDATION.* Neither experiment survived to the
validation gate:

* `EXP-ARP-007` cleared DEV (§7/§8: gross > 0, 153 trades, not single-trade
  concentrated) but failed the COST gate (`REJECT_COSTS`), so VALIDATION was never
  evaluated.
* `EXP-ARP-010` failed the DEV sample gate (`INSUFFICIENT_EVIDENCE`), so neither COST
  nor VALIDATION was evaluated.

## Discipline

* **No parameter change.** Nothing was re-run; no threshold, horizon, asset, exit or
  volatility-window was altered to make anything pass.
* The VALIDATION split was **not used for any decision**, and the decision rules were
  frozen before results (see the driver's `ROBUSTNESS` / kill-criteria declarations and
  the ARP-003 frozen manifests).
* The OOS window `W7_2026-09` was **never read** by the ARP-004 driver.

Consequently `VALIDATION.json` and `OOS.json` are absent for both experiments, as
required when a gate fails earlier.
