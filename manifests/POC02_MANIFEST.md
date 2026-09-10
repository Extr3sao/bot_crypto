# POC02_MANIFEST (DRAFT)

campaign_id: POC-02-alpha-discovery-01
start_date: TBD
end_date: TBD
duration_days: TBD
assets: []
market_data_provider: binanceusdm  # set explicitly before launch
execution_mode: PAPER
paper_execution_model: PaperBroker
strategies_eligible: []  # list of strategy_id/version allowed
risk_policy_hash: TBD
cost_model_hash: TBD
cadence: hourly
minimum_uptime_percent: 99.0
coverage_contract:
  expected_cycles_day: 24
  minimum_acceptable_coverage: 0.90
  outage_handling: record_outage_and_mark_partial
valid_day_definition: "COUNTED ∧ FINALIZED ∧ VALID (trade-independent)"
frequency_kpi: "target >=3 executed trades/day (not optimized/tuned)"
shadow_enabled: true
frontend_visibility: read-only
recovery_contract: resume_on_restart

notes:
- Provider authority and model MUST be set explicitly before launch.
- Confirmation window and frozen candidates must be pre-registered.
