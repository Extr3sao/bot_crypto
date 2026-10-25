# ARP-004 — ROBUSTNESS ANALYSIS (§14–§18)

| experiment | entered ROBUSTNESS? | result |
| --- | --- | --- |
| `EXP-ARP-007` | **No** | `NOT_REACHED` |
| `EXP-ARP-010` | **No** | `NOT_REACHED` |

§14: only DEV + COST + VALIDATION survivors are robustness-tested. Neither experiment
reached that point, so **no robustness perturbations were executed and no parameter
surface / regime / asset-slice claims are made** for a surviving candidate.

## Declared-before-results perturbations (frozen, not executed)

The driver declares its perturbation set *before* any result (so it is visible and
auditable), but it only runs them for a survivor:

* `EXP-ARP-007`: `stop_atr ∈ {0.75, 1.25}`, `atr_period ∈ {10, 20}`,
  `max_hold_days ∈ {2, 4}`, plus `execution_delay = 1 day` and `2.0×` cost.
* `EXP-ARP-010`: `vol_z_entry ∈ {1.75, 2.25}`, `vol_lookback_days ∈ {40, 80}`,
  `stop_atr ∈ {1.5, 2.5}`, `target_atr ∈ {0.75, 1.25}`, `ret_atr ∈ {0.75, 1.25}`,
  `max_hold_days ∈ {1, 3}`, plus `execution_delay = 1 day` and `2.0×` cost.

## Notes on what *would* have been reported

* **Regime analysis (§16)** is not computable on this corpus even for a survivor: the
  project's existing regime definition needs a trailing 720-day median, but DEV is only
  122 days. Any regime claim would have required a different, pre-registered definition.
* **Asset analysis (§17)** for `EXP-ARP-007` is still reported descriptively in the DEV
  artifact (BTC +9.96 · ETH +12.50 · SOL −19.36 bps gross). No asset was removed to
  manufacture a pass.

Because the experiments were rejected before ROBUSTNESS, `ROBUSTNESS.json` is absent
for both.
