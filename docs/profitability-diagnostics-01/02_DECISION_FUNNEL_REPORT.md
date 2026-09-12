# Decision funnel report

```json
{
  "authority": "EXECUTION_EVIDENCE",
  "claim_discipline": "No counterfactual outcome was calculated or synthesized.",
  "economic_status": "INSUFFICIENT_SAMPLE",
  "funnel": {
    "counts": {
      "AGENT_REVIEW": 45,
      "CLOSED_TRADE": 0,
      "CRITIC": "UNKNOWN",
      "DECISION_ENGINE": 45,
      "EXECUTION_INTENT": 3,
      "MARKET_WINDOWS": 45,
      "METARANKER": "UNKNOWN",
      "PAPER_ORDER": 6,
      "RAW_STRATEGY_SIGNAL": "UNKNOWN",
      "RISK": 39,
      "STRATEGY_ROUTER": "UNKNOWN",
      "TRADE_PROPOSAL": 90,
      "VERIFIER": 45
    },
    "rejection_reasons": {
      "AGENT_REJECT": 6,
      "MAX_POSITIONS": 11
    },
    "stages": [
      {
        "input_count": 45,
        "pass_count": 45,
        "pass_rate": "UNKNOWN",
        "reject_count": "UNKNOWN",
        "reject_rate": "UNKNOWN",
        "stage": "MARKET_WINDOWS",
        "transition_status": "UNKNOWN_UNCOMPARABLE_UNITS"
      },
      {
        "input_count": "UNKNOWN",
        "pass_count": "UNKNOWN",
        "pass_rate": "UNKNOWN",
        "reject_count": "UNKNOWN",
        "reject_rate": "UNKNOWN",
        "stage": "RAW_STRATEGY_SIGNAL"
      },
      {
        "input_count": 45,
        "pass_count": 90,
        "pass_rate": "UNKNOWN",
        "reject_count": "UNKNOWN",
        "reject_rate": "UNKNOWN",
        "stage": "TRADE_PROPOSAL",
        "transition_status": "UNKNOWN_UNCOMPARABLE_UNITS"
      },
      {
        "input_count": "UNKNOWN",
        "pass_count": "UNKNOWN",
        "pass_rate": "UNKNOWN",
        "reject_count": "UNKNOWN",
        "reject_rate": "UNKNOWN",
        "stage": "STRATEGY_ROUTER"
      },
      {
        "input_count": 90,
        "pass_count": 45,
        "pass_rate": 0.5,
        "reject_count": 45,
        "reject_rate": 0.5,
        "stage": "AGENT_REVIEW",
        "transition_status": "COMPARABLE"
      },
      {
        "input_count": "UNKNOWN",
        "pass_count": "UNKNOWN",
        "pass_rate": "UNKNOWN",
        "reject_count": "UNKNOWN",
        "reject_rate": "UNKNOWN",
        "stage": "CRITIC"
      },
      {
        "input_count": "UNKNOWN",
        "pass_count": "UNKNOWN",
        "pass_rate": "UNKNOWN",
        "reject_count": "UNKNOWN",
        "reject_rate": "UNKNOWN",
        "stage": "METARANKER"
      },
      {
        "input_count": 45,
        "pass_count": 45,
        "pass_rate": 1.0,
        "reject_count": 0,
        "reject_rate": 0.0,
        "stage": "DECISION_ENGINE",
        "transition_status": "COMPARABLE"
      },
      {
        "input_count": 45,
        "pass_count": 45,
        "pass_rate": 1.0,
        "reject_count": 0,
        "reject_rate": 0.0,
        "stage": "VERIFIER",
        "transition_status": "COMPARABLE"
      },
      {
        "input_count": 45,
        "pass_count": 39,
        "pass_rate": 0.8666666666666667,
        "reject_count": 6,
        "reject_rate": 0.13333333333333333,
        "stage": "RISK",
        "transition_status": "COMPARABLE"
      },
      {
        "input_count": 39,
        "pass_count": 3,
        "pass_rate": 0.07692307692307693,
        "reject_count": 36,
        "reject_rate": 0.9230769230769231,
        "stage": "EXECUTION_INTENT",
        "transition_status": "COMPARABLE"
      },
      {
        "input_count": 3,
        "pass_count": 6,
        "pass_rate": "UNKNOWN",
        "reject_count": "UNKNOWN",
        "reject_rate": "UNKNOWN",
        "stage": "PAPER_ORDER",
        "transition_status": "UNKNOWN_UNCOMPARABLE_UNITS"
      },
      {
        "input_count": 6,
        "pass_count": 0,
        "pass_rate": 0.0,
        "reject_count": 6,
        "reject_rate": 1.0,
        "stage": "CLOSED_TRADE",
        "transition_status": "COMPARABLE"
      }
    ],
    "telemetry_files": 14
  }
}
```
