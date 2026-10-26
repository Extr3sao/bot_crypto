# WP-EDGE-06 — independent verification: VERIFY_PASS

*Read at `2026-10-14T08:14:31Z` (`EDGE06-VERIFY-20261014T081431Z`). 7/7 checks, 8 sabotages, 8 detected.*

| Check | Result | Figures | Detail |
| --- | --- | --- | --- |
| `audit:the_decomposition_re_sums_from_the_trades` | **PASS** | 45 | — |
| `audit:every_figure_equals_the_campaign_artefact` | **PASS** | 225 | — |
| `program:one_family_re_runs_to_the_published_metrics` | **PASS** | 24 | — |
| `storage:every_removed_path_passed_the_three_checks` | **PASS** | 175 | — |
| `freeze:no_strategy_or_risk_path_moved_since_the_freeze` | **PASS** | ['config/risk.yaml', 'src/trading_bot/risk', 'src/trading_bot/strategies', 'src/trading_bot/research/edge01/candidates.py', 'src/trading_bot/research/edge01/campaign.py'] | — |
| `registration:the_hypotheses_commit_precedes_the_results_commit` | **PASS** |  | — |
| `repair:the_derived_view_agrees_with_a_fresh_build_of_head` | **PASS** |  | — |

## Sabotage matrix

Each mutation below is applied to an in-memory copy of the inputs and must make its
check fail. A verification that survives its own sabotage is not verifying anything.

| Check | Mutation | Detected |
| --- | --- | --- |
| `audit_re_sums_from_the_trades` | one gross figure moves by 1 USDT | yes |
| `audit_re_sums_from_the_trades` | the net is stated as zero | yes |
| `audit_re_sums_from_the_trades` | fees erased from the trade rows | yes |
| `audit_equals_the_campaign_artefact` | the audit disagrees with the campaign | yes |
| `family_re_runs` | the published OOS net moves by 1 USDT | yes |
| `family_re_runs` | the published trade count moves | yes |
| `reclaim_rule` | a removed path is claimed as tracked by git | yes |
| `reclaim_rule` | the reclaimed total stops matching its rows | yes |
