# WP-EDGE-08 — run report

*Run `EDGE08-REPORT-20261014T214244Z` at `2026-10-14T21:42:44Z`, branch `agent/edge-recovery/WP-EDGE-00-baseline`, head `5c34cc718ff3`. Verdict: **CLOSED_WITH_OPEN_ITEMS** — the cross-section was read once, every arm the screen let through is rejected on it, the gate status is published, the verification passes with its sabotage self-test, and the open items are the ones the numbers point at*

## 1. Acceptance, row by row

| # | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| B-1 | identify strategies with positive net expectancy after costs, sufficient statistical robustness and a viable frequency | **ANSWERED: CLOSED_WITH_OPEN_ITEMS** | on the known universe the best arm is edge08_quality_breakout_daily with 924.1688 USDT at DEV; on the unread cross-section every arm read is rejected ({'edge08_quality_breakout_daily': 'REJECT', 'edge08_active_daybreak_1h': 'REJECT', 'edge08_active_multiday_range_1h': 'REJECT'}). The cross-section is where the answer counts. |
| B-2 | statistical robustness, measured rather than asserted | **PASS** | every read arm carries its trade count against the registered floor of 30, a 90 % block-bootstrap interval, three time blocks, leave-out-largest, per-asset and per-market-context breakdowns and a serial-dependence pair |
| B-3 | viable frequency | **MEASURED** | ACTIVE target 3.0/day: measured {'edge08_quality_breakout_daily': 0.0461, 'edge08_active_daybreak_1h': 0.1581, 'edge08_active_multiday_range_1h': 0.1965}; QUALITY floor 0.05/day: measured on the cross-section per the verdict rows. No trade was forced to reach a target |
| B-4 | ACTIVE and QUALITY kept apart | **PASS** | two registered tracks, two artefacts (quality/ and active/), two criterion sets (F2 for QUALITY, F1 for ACTIVE) and two frequency targets; no blended reading |
| B-5 | no spent holdout reused | **PASS** | the decisive window is read on six symbols whose history no committed artefact had measured; the WP-EDGE-07 window is not part of any criterion here, and the known universe is used only as the screening ground |
| B-6 | real campaigns, not fixtures | **PASS** | the screen, the matrix and the validation run the frozen simulator over the real corpora; the cross-section validation ran over 304158 fetched bars with digest fb32470f5bc6329e... |
| B-7 | independent verification | **PASS** | 14/14 checks, sabotage self-test PASS (14/14 tampered inputs detected) |
| B-8 | economic matrix and results per strategy | **PASS** | economics/ECONOMIC_MATRIX.{json,md} carries 9 arms x 3 windows x 3 scenarios with their robustness readings; every arm's own numbers are section 3 of that document |
| B-9 | gate status published | **PASS** | validation/GATE_STATUS.{json,md}: 9 arms with their registered verdict beside the frozen gate's own reading |
| B-10 | no PASS, PAPER_READY or profitability declared without evidence | **PASS** | promotion: NONE, order_sent: False; every verdict is computed from the registered criteria and the artefacts carry the numbers they rest on |
| B-11 | no real trading, no risk limit modified | **PASS** | config/risk.yaml is read, never written, by this package; its digest is 3c27c866d5f11afe... and the last commit that touched it is 10cdee2 chore: initial Phase 0 scaffolding for crypto-scalping-agentic-bot |
| B-12 | isolated commits and safe push | **PASS** | branch agent/edge-recovery/WP-EDGE-00-baseline, head 5c34cc7, remote refs/heads/agent/edge-recovery/WP-EDGE-00-baseline, tip read back 5c34cc718ff3, range at last push 5c34cc7..5c34cc7 (+0 ahead), force push used: False, unpushed commits 0 |
| B-13 | executive report in Spanish | **PASS** | INFORME_EJECUTIVO.md, rendered from the same dictionary as this document |
| B-14 | owned tests, lint, format and types | **PASS** | owned: exit 0 (26 passed in 1.33s); lint: exit 0 (All checks passed!); format: exit 0 (21 files already formatted); types: exit 0 (Success: no issues found in 12 source files) |

## 2. What was measured, and where the evidence lives

- Cross-section: ['AAVEUSDT', 'UNIUSDT', 'KSMUSDT', 'SNXUSDT', 'CRVUSDT', 'SUSHIUSDT'], corpus digest `fb32470f5bc6329e…`, 304158 bars (15687107 bytes). Claim: HOLDOUT_CLAIM_HOLDS.
- Read on it: ['edge08_quality_breakout_daily', 'edge08_active_daybreak_1h', 'edge08_active_multiday_range_1h']; stopped by the gross screen before it: ['edge08_quality_pullback_daily', 'edge08_quality_reversion_daily', 'edge08_active_stretch_revert_1h'].
- Arms in the economic matrix: 9; gate-status rows: 9; multiplicity declared: {'current_comparison': 3, 'note': 'every arm is reported; no book is re-parameterised after seeing a result, and a book that fails the gross screen is not read on the cross-section at all', 'proposed': 6, 'total': 9}.

## 3. Every arm, at a glance

| Arm | Track | Clock | Known DEV | Known OOS | Cross OOS | Cross trades/day | Cross trades | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `edge08_quality_breakout_daily` | QUALITY | 1d | 924.1688 | -57.8012 | -166.6146 | 0.0461 | 30 | REJECT |
| `edge08_quality_pullback_daily` | QUALITY | 1d | -378.976 | 27.5484 | not read | — | — | REJECT_NO_GROSS_EDGE |
| `edge08_quality_reversion_daily` | QUALITY | 1d | 0 | 0 | not read | — | — | REJECT_NO_GROSS_EDGE |
| `edge08_active_daybreak_1h` | ACTIVE | 1h | 18.9021 | -314.8222 | -474.0861 | 0.1581 | 103 | REJECT |
| `edge08_active_multiday_range_1h` | ACTIVE | 1h | 238.7233 | -23.6598 | -494.7063 | 0.1965 | 128 | REJECT |
| `edge08_active_stretch_revert_1h` | ACTIVE | 1h | -314.0392 | -526.1891 | not read | — | — | REJECT_NO_GROSS_EDGE |
| `edge06_trend_fixed` | CURRENT | 4h | 470.1555 | 230.0174 | -415.825 | 0.2211 | 144 | NOT_APPLICABLE |
| `edge07_active_thrust` | CURRENT | 1h | -440.9027 | -488.0181 | -350.7431 | 0.3009 | 196 | NOT_APPLICABLE |
| `edge_trend_01_4h` | CURRENT | 4h | 572.9393 | 152.9961 | -215.8994 | 0.1934 | 126 | NOT_APPLICABLE |

The known-universe columns come from the screens (proposed books) or the matrix (CURRENT books); the cross-section columns come from `validation/VALIDATION.json` and say 'not read' where the gross screen stopped the book before the cross-section was touched. The verdict is the registered one.

## 4. Verification, tests and digests

- Independent verifier: **PASS** (14/14), sabotage self-test PASS (14/14).
- `owned`: exit `0` — 26 passed in 1.33s
- `lint`: exit `0` — All checks passed!
- `format`: exit `0` — 21 files already formatted
- `types`: exit `0` — Success: no issues found in 12 source files

| Artefact | Bytes | SHA-256 |
| --- | --- | --- |
| `data/edge08/universe-1h/_FETCH_MANIFEST.json` | 10514 | `3346b54b1ddafae3…` |
| `reports/edge-recovery/WP-EDGE-08/PREREGISTRATION.json` | 12325 | `66a8c60d330e5dd9…` |
| `reports/edge-recovery/WP-EDGE-08/UNIVERSE.json` | 24263 | `e322eb1f9453bea6…` |
| `reports/edge-recovery/WP-EDGE-08/VERIFICATION.json` | 24310 | `0e53817db836c956…` |
| `reports/edge-recovery/WP-EDGE-08/active/ACTIVE_SCREEN.json` | 28505 | `5e81919fa60bd85b…` |
| `reports/edge-recovery/WP-EDGE-08/active/ACTIVE_TRADES.csv` | 405466 | `0827a45a28cb308e…` |
| `reports/edge-recovery/WP-EDGE-08/economics/ECONOMIC_MATRIX.json` | 448349 | `b96881550bb0a14d…` |
| `reports/edge-recovery/WP-EDGE-08/economics/ECONOMIC_TRADES.csv` | 911204 | `bb568b0a8f725316…` |
| `reports/edge-recovery/WP-EDGE-08/quality/QUALITY_SCREEN.json` | 25085 | `1b97551efec9dd8d…` |
| `reports/edge-recovery/WP-EDGE-08/quality/QUALITY_TRADES.csv` | 113374 | `a02b4826ace519f4…` |
| `reports/edge-recovery/WP-EDGE-08/validation/GATE_STATUS.json` | 3332 | `b71962954288ed2a…` |
| `reports/edge-recovery/WP-EDGE-08/validation/HOLDOUT_TRADES.csv` | 426168 | `a2a18a149f69bdf9…` |
| `reports/edge-recovery/WP-EDGE-08/validation/VALIDATION.json` | 247850 | `c312269dc307d058…` |

The four documents this script writes are excluded from the table by name, together with `GITHUB_STATE.json`: hashing a file before rewriting it is how a digest table ends up describing a version of itself that no longer exists.

## 5. Git

- Branch `agent/edge-recovery/WP-EDGE-00-baseline`, head `5c34cc718ff3d6b8a6e7b82062d26be3c1be3140`, remote `refs/heads/agent/edge-recovery/WP-EDGE-00-baseline`.
- Pushed range at the last push: `5c34cc7..5c34cc7 (+0 ahead)`; remote tip read back: `5c34cc718ff3d6b8a6e7b82062d26be3c1be3140`; matches head: `True`; force push used: `False`.
- Package files still uncommitted at this reading: none.

## 6. Defects found by running, and fixed

### `DEF-EDGE08-01`

- **Symptom.** two registered QUALITY books produced no trades at all on the screening ground: edge08_quality_pullback_daily and edge08_quality_reversion_daily could not fire, the second of them on any bar of a three-year corpus.
- **Cause.** the frozen cost_gate applies max(min_rr, cost_margin) as its reward/risk floor, so a book whose registered min_rr (1.2 and 0.5) sits below its declared cost_margin (1.5) carries a requirement that is unsatisfiable by construction — the same defect class DEF-EDGE01-01 recorded for the frozen campaign, where a candidate printed signals and never traded one of them.
- **Fix.** the reward/risk of both books was made satisfiable by design rather than by weakening a gate: Q-2 moved to a 2.0 ATR stop against a 3.0 ATR objective (R:R 1.5) and Q-3 to an ATR-denominated dislocation (entry at least 3.0 ATR below the 20-day mean, 2.0 ATR stop, objective the mean), both with min_rr = cost_margin = 1.5, so the gate judges each setup instead of refusing the book.
- **Found.** by running the screen, before the registration was committed and before any bar of the cross-section was aggregated or measured.
- **Published by.** QUALITY and ACTIVE — one entry, however many artefacts carry it.

## 7. What this run does not establish

- the cost plane is venue-level: no per-symbol spread or book depth is modelled, and the ADVERSE scenario is the only sensitivity that speaks to thinner names
- the bars are one venue's public REST feed at 1h, aggregated upwards into complete buckets only; gaps are left absent and counted (42 missing hours across six symbols)
- the decisive window carries 651 daily bars per symbol, which is what makes a 30-trade floor reachable for the ACTIVE books and marginal for the QUALITY one
- windows are the same calendar spans on both universes: on the known universe they have been read before, which is exactly why it is the screening ground and not the evidence

`promotion: NONE`, `order_sent: False`.
