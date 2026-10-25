# WP-EDGE-016 — weekend policy conflict

`config/risk.yaml` declares `blocks.weekend_trading: false`, i.e. **no trading on Saturday or
Sunday**. The 7/7 ACTIVE goal in the campaign brief needs the opposite.

## What the code does about it

Searching `src/` and `scripts/` for the flag returns: scripts/edge15_paper_lane.py, scripts/edge16_artifacts.py, scripts/edge16_paper_lane.py, scripts/edge16_reports.py.
The canonical risk engine does not consult it (see `RISK_PARITY_MATRIX.json`), the paper cycle
does not consult it, and the runtime does not consult it. The only code that has ever read it
is the experimental lane written for this work package, which honours it: weekend entries are
refused and recorded as `WEEKEND_VETO_POLICY`.

## Consequence

* A 7/7 goal cannot be met under the policy as written, and it is not blocked by an enforced
  rule either: the conflict is between a declared intention and an unimplemented one.
* This package does **not** change the flag, does not enable weekend trading and does not
  amend the runtime to read it.
* Unblocking it needs an explicit risk/governance decision with its own RFC/ADR — either a
  changed flag plus the code that enforces it, or a written statement that weekends are out of
  scope for ACTIVE.

Weekend refusals recorded by the lane: **52**.
