# BUSINESS REENTRY POLICY (RFC-041)

> **EXCEPCION LIMITADA Y FECHADA — RFC-046 (aprobada 2026-10-08, ADR-0024)**
> El propietario aprueba la alternativa **5A**: una excepcion especifica de RFC-041 que activa
> RFC-046 **exclusivamente en investigacion offline** (Controlled Discovery). Esta excepcion:
> - **no** modifica `G_BUSINESS_REENTRY`, que permanece **distinto de PASS**;
> - **no** autoriza paper, live, ordenes reales ni despliegue de capital (`TRADES_AUTHORIZED = 0`);
> - **no** relaja `business_edge_requirement` ni los `reject_conditions` de este documento;
> - solo admite investigacion offline preregistrada bajo `docs/governance/DISCOVERY_ADMISSION_POLICY.md`
>   y `docs/governance/DISCOVERY_STOP_RULES.md`;
> - esta fechada, es revocable, y su alcance se agota con el stop rule de RFC-046.
> La unica puerta que abre es la de investigacion; todas las puertas de produccion siguen intactas.


```json
{
  "rfc": "RFC-041",
  "generated_at": "2026-10-05T23:11:22Z",
  "gate": "G_BUSINESS_REENTRY",
  "triggers": {
    "A": "new external evidence: independent publication/replication of persistent post-publication risk-adjusted excess return",
    "B": "new structural edge: institutional constraint, risk transfer, microstructure, forced flows, regulatory effect, structural carry or liquidity provision",
    "C": "capital change: available capital changes materially from 200 USDT (CAPITAL_CHANGE_REVIEW, no arbitrary fixed amount)",
    "D": "broker/instrument change: new fractional access, low-cost instrument, UCITS product, retail derivative or materially better cost structure",
    "E": "new data: only if it unlocks an already economically supported hypothesis (data alone is never enough)"
  },
  "structural_mechanisms": [
    "institutional_constraint",
    "risk_transfer",
    "market_microstructure",
    "forced_flows",
    "regulatory_effect",
    "structural_carry",
    "liquidity_provision"
  ],
  "reject_conditions": [
    "new RSI variation",
    "different moving average",
    "different threshold",
    "another crypto pair",
    "more LLM agents",
    "new sentiment source",
    "adding ML to old features",
    "parameter optimization",
    "same strategy with renamed rules"
  ],
  "scorecard_dimensions": [
    "external_evidence",
    "economic_mechanism",
    "post_publication_survival",
    "product_fit",
    "capital_fit",
    "data_feasibility",
    "tradability",
    "cost_headroom",
    "benchmark_adjusted_evidence",
    "implementation_cost"
  ],
  "critical_dimensions": [
    "external_evidence",
    "economic_mechanism",
    "product_fit",
    "capital_fit",
    "benchmark_adjusted_evidence"
  ],
  "minimum_evidence_sources": "strong enough to beat a passive alternative after costs",
  "budget": {
    "MAX_FAMILIES": 3,
    "MAX_FINALISTS": 2,
    "MAX_IMPLEMENTED": 1
  },
  "failure_rule": "PAUSE_AGAIN",
  "research_cycle": {
    "RESEARCH_CYCLE_ID": null,
    "CANDIDATES_TESTED_THIS_CYCLE": 0
  },
  "product_metrics": [
    "minimum_viable_capital",
    "expected_turnover",
    "expected_costs",
    "historical_cagr",
    "historical_sharpe",
    "max_drawdown",
    "benchmark_cagr",
    "benchmark_sharpe",
    "risk_matched_excess_return",
    "illustrative_pnl_at_reference_capital"
  ],
  "value_chain": [
    "EXTERNAL EVIDENCE",
    "PRODUCT FIT",
    "REPRODUCTION",
    "DISCOVERY",
    "VALIDATION",
    "BENCHMARK EDGE",
    "ROBUSTNESS",
    "PAPER CERTIFICATION",
    "FORWARD PAPER",
    "CANARY",
    "LIVE"
  ],
  "paper_admission": "requires BUSINESS_EDGE = PASS",
  "live_admission": [
    "PAPER_EXECUTION_PASS",
    "FORWARD_EVIDENCE",
    "RISK_APPROVAL",
    "HUMAN_CAPITAL_APPROVAL"
  ],
  "capital_principle": "STRATEGY MUST FIT CAPITAL",
  "no_profitability_by_test_count": "tests are engineering, not economic evidence",
  "engineering_freeze_allowances": [
    "bug",
    "security",
    "data integrity",
    "critical maintenance"
  ],
  "next_rfc_requires": "G_BUSINESS_REENTRY = PASS",
  "next_rfc_type_if_pass": "RFC-0XX BUSINESS-QUALIFIED STRATEGY REPRODUCTION"
}
```
