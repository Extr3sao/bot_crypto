# ARP-005 — COST-COMPATIBLE ALPHA DISCOVERY & RESEARCH-INFRASTRUCTURE RECOVERY — FINAL

```
ARP-005 — FINAL

START_SHA:  eae4c27e8254303c30ddf42abebb4ddaecf10716   (ARP-004 final)
END_SHA:    <ARP-005_END_SHA>                          (stamped after the code+evidence commit)
COMMITS:    <ARP-005_COMMITS>

PRIMARY OBJECTIVE: discover whether a strategy candidate exists whose signal
magnitude can survive realistic trading costs. NOT more trades, NOT paper execution.
FALSE_SUCCESS = 0.
```

## Per-candidate results

| strategy | version | hypothesis | dataset | sample | gross bps | cost bps | net bps | gross/cost | DEV | COST | VALIDATION | ROBUSTNESS | OOS | final |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `STRAT-CAND-019-VARIANT-B` | v1 | level reaction | baseline | 153 | +0.776 | 23.559 | −22.783 | 0.03 | PASS | REJECT_COSTS | NOT_REACHED | NOT_REACHED | NOT_OPENED | **REJECT_COSTS** *(ARP-004, unchanged)* |
| `H-VOLSPIKE-MR-001` | v1 | vol-spike reversion | baseline | 6 | −75.059 | — | −98.619 | — | INSUFFICIENT | NOT_REACHED | NOT_REACHED | NOT_REACHED | NOT_OPENED | **INSUFFICIENT_EVIDENCE** *(ARP-004, unchanged)* |
| `H-XSEC-RELSTR-001` | arp005 | cross-sectional momentum | baseline | 17 | −100.114 | 23.559 | −123.673 | — | INSUFFICIENT | NOT_REACHED | NOT_REACHED | NOT_REACHED | NOT_OPENED | **INSUFFICIENT_EVIDENCE** |
| `H-VOLEXP-BREAK-001` | arp005 | breakout / vol expansion | baseline | 2 | −63.301 | 23.559 | −86.861 | — | INSUFFICIENT | NOT_REACHED | NOT_REACHED | NOT_REACHED | NOT_OPENED | **INSUFFICIENT_EVIDENCE** |
| `STRAT-CAND-016-VARIANT-B` | arp005-ext | liquidity reversal | extended | 62 | +27.610 | 23.559 | +4.051 | 1.17 | **PASS** | **PASS** | **REJECT_VALIDATION** | NOT_REACHED | NOT_OPENED | **REJECT_VALIDATION** |

`REJECT_NO_EDGE 0 · REJECT_COSTS 1 (ARP-004) · REJECT_VALIDATION 1 · REJECT_FRAGILE 0
· INSUFFICIENT_EVIDENCE 3 · INFRASTRUCTURE_BLOCKED 0`

## Dataset coverage

- Baseline corpus: 21 × 5m files, fingerprint `9d51385d…` (unchanged), DEV 122 /
  VALIDATION 62 / OOS 24 days/symbol.
- Extended corpus (NEW, isolated): 18 × 5m files in `reports/alpha-recovery-v1-4/data/`,
  digest `d3669d28…`, six windows WX1_2025-09 … WX6_2026-02. DEV **303** days/symbol
  (inside the ARP-004 adequacy band). Baseline digest provably untouched.

## Backlog statuses

- **EXP-ARP-006** — EXECUTED AS `EXP-ARP-012` (same rules, extended corpus). Status:
  `REJECT_VALIDATION`.
- **EXP-ARP-008** (`H-DAILY-TSMOM-001`, 20-day holds) — **still
  `DATA_SHORT_FOR_HORIZON`**: needs ≈830–1230 DEV days; the extension reaches 303. Not
  executed (a shorter sub-horizon would be a different experiment).
- **EXP-ARP-009** — EXECUTED (PATH B unblocked). Status: `INSUFFICIENT_EVIDENCE`
  (17 rotations < frozen 20).
- **EXP-ARP-010** — unchanged (`INSUFFICIENT_EVIDENCE`); frozen `vol_z_entry=2.0` not
  lowered.

## Cross-sectional engine status

`CrossSectionalEngine` classified **`ORPHAN`** (no callers, no-op rank assignment, no
asset-sync guard, no tests). Decision **`REIMPLEMENT_MINIMAL_PATTERN`**: a new minimal,
tested, PIT-safe ranker (`research/alpha_recovery/xsec.py`) with synchronization,
staleness rejection, PIT ranking, deterministic ties, contiguity rejection and
contract tests. The legacy engine was left untouched.

## Counts

- hypotheses evaluated (frozen experiments): **3** (plus 2 carried over from ARP-004).
- rejected pre-experiment (deferred): **2** (EXP-ARP-006→012 superseded; EXP-ARP-008
  data-short).
- reaching DEV: **3**.
- DEV survivors: **1** (EXP-ARP-012).
- COST survivors: **1** (EXP-ARP-012).
- VALIDATION survivors: **0**.
- ROBUSTNESS survivors: **0**.
- OOS opened: **0**.
- PROMOTION candidates: **0**.

## Quality gates

- `pytest`: **1525 passed / 0 failed / 0 skipped** (123 s).
- `ruff check .`: **clean**.
- `mypy . --exclude "reports"`: **Success: no issues found in 420 source files**.
- `git diff --check`: **clean**.
- determinism: two ARP-005 driver runs **byte-identical** (excluding the corpus dir).

## Independent verification

NOT TRIGGERED — no experiment reached `OOS_GATE_ELIGIBLE` / `PROMOTION_CANDIDATE`.
`builder != verifier` trivially satisfied (no promotion claim).

## §19 prohibition

`EXP-ARP-007` remains `REJECT_COSTS` and was **not** advanced to
VALIDATION/ROBUSTNESS/OOS/PAPER/SHADOW/CANARY. It was not paper-shadowed.

## Verdict

**ARP-005 = COMPLETE. `PROMOTION_CANDIDATES = 0` — correctly so.**

The demonstrated bottleneck (cost-compatible net edge) is unresolved because no
candidate has a gross edge comfortably above the canonical cost:
- EXP-ARP-009/011 are trigger-starved even after considering the pre-filter head-room
  and cannot reach their frozen minimum samples without loosening thresholds.
- EXP-ARP-012 produced a **razor-thin** DEV edge (break-even 27.6 bps vs 23.6 bps cost;
  fails at 1.25×) that **collapsed out of sample** (−374.8 bps gross in VALIDATION).

Closing the data gap (PATH A) and repairing the infrastructure (PATH B) were both
completed — and both merely enabled *honest rejection*. No threshold was relaxed, no
rejected experiment was promoted, and OOS `W7` remains unseen.

`FALSE_SUCCESS = 0`.
