# ARP-005 — OOS GATE (§12/§18/§19)

OOS (`W7_2026-09`, 24 d/symbol) opens **only** for a candidate that passes DEV, COST,
VALIDATION and ROBUSTNESS. Only then may a result become `PROMOTION_CANDIDATE`.

## Outcome

**OOS NOT OPENED — for every experiment.**

| experiment | DEV | COST | VALIDATION | ROBUSTNESS | OOS |
| --- | --- | --- | --- | --- | --- |
| EXP-ARP-009 | INSUFFICIENT_EVIDENCE | NOT_REACHED | NOT_REACHED | NOT_REACHED | **NOT_OPENED** |
| EXP-ARP-011 | INSUFFICIENT_EVIDENCE | NOT_REACHED | NOT_REACHED | NOT_REACHED | **NOT_OPENED** |
| EXP-ARP-012 | PASS | PASS | REJECT_VALIDATION | NOT_REACHED | **NOT_OPENED** |

- `OOS_GATE_ELIGIBLE candidates = 0`.
- `OOS opened = 0`.
- `PROMOTION_CANDIDATES = 0`.

The `W7` window remains unseen and available for a future, separately pre-registered
experiment. No OOS data influenced any upstream decision (adversarially asserted by
`test_split_firewall_never_opens_oos_when_validation_fails`).

## §19 — EXP-ARP-007 prohibition (restated and enforced)

`EXP-ARP-007` (`STRAT-CAND-019-VARIANT-B`, `REJECT_COSTS`) is **terminal** in its
current version. It MUST NOT advance to VALIDATION, ROBUSTNESS, OOS, PAPER, SHADOW or
CANARY. ARP-005 did not touch it and did not paper-shadow it. A materially different
mechanism from that family would be a **new strategy version + new hypothesis + new
manifest + new experiment id**.

## §21 — Independent verification

Independent verification triggers only at `OOS_GATE_ELIGIBLE` (or another critical
promotion boundary). **None was reached**, so no verifier effort was spent certifying
rejected candidates. `builder != verifier` remains satisfied trivially (no promotion
claim was made).

`FALSE_SUCCESS = 0`.
