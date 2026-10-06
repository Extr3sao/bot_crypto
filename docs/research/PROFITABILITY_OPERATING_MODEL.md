# PROFITABILITY OPERATING MODEL

- **rfc**: RFC-043
- **generated_at**: 2026-10-06T07:13:27Z
- **title**: PROFITABILITY OPERATING MODEL
- **reference_capital_usdt**: 200.0
- **role_of_200_usdt**: FUTURE_CANARY_CAPITAL
- **current_milestone**: M0
- **capital_scale_authorized**: False
- **answers**:
  - **what_can_200_usdt_prove**: It can prove real order, fill, fee, spread, quantity rounding, reconciliation and PnL behaviour of a strategy that already cleared the business-edge gate. It cannot prove statistical alpha.
  - **what_can_200_usdt_earn**: A small absolute amount: at a 20% net annual return it is 40 USDT/year, i.e. about 3.33 USDT/month. These are scenarios, never forecasts.
  - **how_much_capital_for_targets**: Dividing the target by the net return: e.g. 1,000 USDT/year needs 10,000 USDT at a 10% net return but 5,000 USDT at a 20% net return.
  - **when_can_capital_scale**: Only after G_CAPITAL_SCALE = PASS and a positive realized trading PnL, with evidence and explicit human approval - never automatically.
  - **when_must_capital_not_scale**: Whenever the business edge is unproven, paper execution has not passed, or realized costs do not match assumptions - which is the case today.
  - **what_counts_as_real_trading_profit**: REALIZED_TRADING_PNL after real costs, excluding any external deposit; ending_equity = starting + contributions + trading_pnl - withdrawals.
- **canary_purpose**: 200 USDT exists to check actual order, fill, fee, spread, quantity rounding, reconciliation and PnL of an already-validated edge; never to prove statistical alpha.
- **benchmark_alternative**: Any future strategy must also be compared against DO_NOT_TRADE / a passive alternative, because capital deployed in trading carries an opportunity cost.
- **business_edge_requirement**: RFC-041 requirement stands unchanged: NET POSITIVE + BENCHMARK-ADJUSTED VALUE + EXECUTABLE + ROBUST. It is never relaxed to trade sooner.
- **trigger_c_capital_change**: A material capital change (trigger C) only opens a PRODUCT_FIT_REVIEW for archived candidates; it never approves a strategy by itself.
- **next_action_policy**:
  - **trigger**: ONLY a NEW QUALIFIED OPPORTUNITY or a MATERIAL CAPITAL / INSTRUMENT CHANGE reopens evaluation
  - **no_periodic_rfc**: No RFC-044/RFC-045 merely because time passes
  - **opportunity_watch**: human process: NEW EVIDENCE -> BUSINESS_REENTRY_CHECKLIST (no daemon, no new infrastructure)
- **profitability_definition**: PROFITABILITY = NET_RETURN + CAPITAL + TIME + RISK + COST
- **real_profit_equation**: REAL_PROFIT = VALIDATED_BUSINESS_EDGE x DEPLOYED_CAPITAL x TIME (subject to drawdown, cost, execution and regime uncertainty)
- **capital_tiers**:
  - **tier**: TIER_0
    **capital_usdt**: 200.0
    **label**: CANARY
  - **tier**: TIER_1
    **capital_usdt**: 500.0
    **label**: FIRST_SCALE_REVIEW
  - **tier**: TIER_2
    **capital_usdt**: 1000.0
    **label**: SMALL
  - **tier**: TIER_3
    **capital_usdt**: 2500.0
    **label**: SMALL_PLUS
  - **tier**: TIER_4
    **capital_usdt**: 5000.0
    **label**: MEDIUM
  - **tier**: TIER_5
    **capital_usdt**: 10000.0
    **label**: MEDIUM_PLUS_AND_ABOVE
- **any_tier_authorized**: False
- **capital_scale_gate_conditions**:
  - business_edge_still_valid
  - paper_execution_pass
  - forward_evidence_acceptable
  - actual_costs_consistent
  - no_major_reconciliation_defect
  - drawdown_within_expected_envelope
  - human_approval
- **milestones**:
  - **milestone**: M0
    **meaning**: BUSINESS_EDGE = 0
  - **milestone**: M1
    **meaning**: BUSINESS_EDGE = 1
  - **milestone**: M2
    **meaning**: PAPER_EXECUTION = PASS
  - **milestone**: M3
    **meaning**: FORWARD_EVIDENCE = PASS
  - **milestone**: M4
    **meaning**: CANARY_DEPLOYED
  - **milestone**: M5
    **meaning**: REALIZED_NET_PNL > 0
  - **milestone**: M6
    **meaning**: CAPITAL_SCALE_1
  - **milestone**: M7
    **meaning**: REPEATED_PROFITABILITY
  - **milestone**: M8
    **meaning**: ECONOMICALLY_MEANINGFUL_PNL
- **profit_levels**:
  - **LEVEL_A_PROOF_OF_PROFITABILITY**: REALIZED_NET_PNL > 0 after real costs
  - **LEVEL_B_ECONOMICALLY_NOTICEABLE**: annual profit materially above execution and operational costs
  - **LEVEL_C_MEANINGFUL_INCOME_CONTRIBUTION**: requires significantly larger capital; the 'meaningful' threshold is the owner's to set and is never invented here
- **leverage_policy**: LEVERAGE_IS_NOT_A_CAPITAL_SUBSTITUTE
- **priority_order**:
  - FIND BUSINESS EDGE
  - VERIFY PAPER EXECUTION
  - DEPLOY 200 USDT CANARY
  - VERIFY REAL PNL
  - SCALE CAPITAL
- **official_sequence**:
  - BUSINESS EDGE
  - PAPER
  - FORWARD
  - 200 USDT CANARY
  - REALIZED NET PROFIT
  - CAPITAL SCALE
  - MEANINGFUL ABSOLUTE PROFIT
- **operating_questions**:
  - DO WE HAVE EDGE?
  - HOW MUCH CAPITAL CAN USE IT?
  - HOW MUCH MONEY CAN IT REALISTICALLY PRODUCE?
  - WHAT RISK DOES THAT REQUIRE?
  - WHEN CAN WE SAFELY SCALE?
- **next**: WAIT FOR BUSINESS EDGE
