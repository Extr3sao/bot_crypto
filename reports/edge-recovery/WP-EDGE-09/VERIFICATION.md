# WP-EDGE-09F — independent verification

*Run at `2026-10-15T05:28:27Z`. Result: **PASS** — 18/18 checks passed.*

| # | Check | Result |
| --- | --- | --- |
| C-1 | every authoritative input still carries the digest the audit recorded | PASS |
| C-2 | the panel hash recomputes from the bytes on disk | PASS |
| C-3 | panel rows re-derive from the raw segments through a second reader | PASS |
| C-4 | every row's decision clock lies inside its own second and moves forward | PASS |
| C-5 | every published horizon pairing has its partner at or after decision_time + h | PASS |
| C-6 | the barrier is the sum of its components, with the 1.5x margin | PASS |
| C-7 | the verifier's own thresholds still agree with the registration | PASS |
| C-8 | the published classification follows from the published numbers and the thresholds | PASS |
| C-9 | the negative control is not positive, so FALSE_SUCCESS stays at zero | PASS |
| C-10 | no measurement artifact claims readiness or profitability, and no order was sent; the verifier and the registered RFC name those states only to forbid them | PASS |
| C-11 | the measured universe shares no symbol with a holdout this project already spent | PASS |
| C-12 | the published capacity recomputes from the kept depth levels | PASS |
| C-13 | every registered hypothesis — including the rejected ones — appears once | PASS |
| C-14 | every registered venue scenario is priced, and the schedules are not all the same | PASS |
| C-15 | every measured stream is in the ledger as CONSULTED, no market window that the cost gate never opened is claimed as read, and no spent holdout is re-read | PASS |
| C-16 | the results matrix, the registry and the experiment ledger agree hypothesis by hypothesis, and every classification is registered vocabulary | PASS |
| C-17 | the pooled frequency carries the span it was extrapolated from, never counts more long-only opportunities than moves of either sign, and is classified by the rule that kills a book only when every measured horizon is below the target | PASS |
| C-18 | every derived deliverable still hashes to the digest its manifest declares | PASS |

## Sabotage self-test

Baseline PASS; 18/18 tampered inputs detected; result **PASS**.

| Check sabotaged | Detected |
| --- | :-: |
| C-1 | True |
| C-10 | True |
| C-11 | True |
| C-12 | True |
| C-13 | True |
| C-14 | True |
| C-15 | True |
| C-16 | True |
| C-17 | True |
| C-18 | True |
| C-2 | True |
| C-3 | True |
| C-4 | True |
| C-5 | True |
| C-6 | True |
| C-7 | True |
| C-8 | True |
| C-9 | True |
