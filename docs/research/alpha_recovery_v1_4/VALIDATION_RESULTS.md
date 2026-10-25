# ARP-005 — VALIDATION RESULTS (§12)

VALIDATION (W5_2026-07 … W6_2026-08, 62 d/symbol) is read **only** after DEV PASS and
COST PASS. Only `EXP-ARP-012` qualifies. The split-firewall test proves programmatically
that `EXP-ARP-011` (DEV fail) and `EXP-ARP-012` (OOS never) touch the forbidden splits.

## EXP-ARP-012 — VALIDATION

| metric | DEV | VALIDATION |
| --- | --- | --- |
| trades | 62 | **9** |
| gross bps | +27.610 | **−374.824** |
| net bps | +4.051 | **−398.383** |
| win rate | 0.468 | 0.222 |
| profit factor | 1.014 | **0.039** |
| max drawdown bps | 4136.8 | 3585.4 |

Frozen validation checks:

- `val_gross_positive` → **false**
- `no_material_collapse` (val ≥ 0.5× dev) → **false**
- `val_net_positive` → **false**

**Result: `REJECT_VALIDATION`.** The DEV edge did not generalise — the opposite
occurred: 9 VALIDATION trades produced a −374.8 bps gross expectancy, and the DEV
result was already known to be ETH/SOL-carried with BTC negative.

## Not reached

- `EXP-ARP-009` — VALIDATION NOT_REACHED.
- `EXP-ARP-011` — VALIDATION NOT_REACHED.

## Interpretation

This is exactly the failure mode the staged pipeline is designed to catch: a
razor-thin DEV edge (net +4.05 bps, break-even 27.6 bps) that survives canonical cost
by 1.17× but collapses out of sample. No threshold was relaxed to rescue it, and the
OOS window `W7` remains **unopened**.

`VALIDATION survivors = 0`.
