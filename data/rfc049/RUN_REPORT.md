# RFC-049 RUN REPORT — PHASE A (PREPARATION)

- generated_at_utc: 2026-10-10T11:26:20Z
- checks: 39 total / 0 failed
- exit status: **PASS**
- economic evaluations executed: **none (by construction of the activation gate)**

## Checks

| check | result | detail |
| --- | --- | --- |
| `vendor:defillama_stablecoin_supply_all.json` | PASS | 3238 rows, 2017-11-29..2026-10-10 |
| `vendor:blockchain_info_hashrate_8y.json` | PASS | 2917 rows, 2018-10-12..2026-10-09 |
| `vendor:blockchain_info_miners_revenue_all.json` | PASS | 1619 rows, 2009-01-17..2026-10-07 |
| `vendor:fred_WALCL.csv` | PASS | 1243 rows, 2002-12-18..2026-10-07 |
| `vendor:fred_RRPONTSYD.csv` | PASS | 6176 rows, 2003-02-07..2026-10-09 |
| `vendor:fred_WTREGEN.csv` | PASS | 1243 rows, 2002-12-18..2026-10-07 |
| `vendor:fred_DFII10.csv` | PASS | 6201 rows, 2003-01-02..2026-10-08 |
| `vendor:fred_DTWEXBGS.csv` | PASS | 5415 rows, 2006-01-02..2026-10-02 |
| `vendor:fred_DFF.csv` | PASS | 26398 rows, 1954-07-01..2026-10-08 |
| `baseline:rfc_number_collision` | PASS | tracked mentions before this RFC: ['scripts/rfc048v_certify.py'] |
| `baseline:rfc048v_status` | PASS | RFC048_FINAL_STATUS=RFC048_OFFLINE_CERTIFIED |
| `baseline:governance` | PASS | {"DISCOVERY_CAMPAIGN_FAILED": true, "LIVE_TRADING": "DISABLED", "NEXT_CAMPAIGN": "NOT_AUTHORIZED", "PROFITABILITY_VERIFIED": false, "TRADES_AUTHORIZED": 0} |
| `baseline:cost_model` | PASS | 200 USDT=23.353553391 bps, 1000 USDT=23.790569415 bps |
| `baseline:protected:config` | PASS | protected path present; this RFC must not modify it |
| `baseline:protected:docs/COST_MODEL_V3.json` | PASS | protected path present; this RFC must not modify it |
| `baseline:protected:data/st6` | PASS | protected path present; this RFC must not modify it |
| `baseline:protected:scripts/st6_scheduler_witness.py` | PASS | protected path present; this RFC must not modify it |
| `baseline:protected:src/trading_bot/risk/futures` | PASS | protected path present; this RFC must not modify it |
| `baseline:closed_line:perpetual funding carry (long spot / short perpe` | PASS | evidence paths present |
| `baseline:closed_line:spot-BTC ETF net-flow continuation` | PASS | evidence paths present |
| `baseline:closed_line:time-series momentum / trend following (spot and` | PASS | evidence paths present |
| `baseline:closed_line:cross-sectional momentum / reversal / low volati` | PASS | evidence paths present |
| `baseline:closed_line:funding capitulation / settlement dip / weekend ` | PASS | evidence paths present |
| `baseline:closed_line:derivatives positioning confirmation (OI / long-` | PASS | evidence paths present |
| `baseline:closed_line:cross-asset lead-lag (daily and intraday), relat` | PASS | evidence paths present |
| `baseline:closed_line:intraday seasonality / clock-boundary / overnigh` | PASS | evidence paths present |
| `baseline:closed_line:order-flow imbalance / microstructure families` | PASS | evidence paths present |
| `baseline:closed_line:token unlock / vesting supply events` | PASS | evidence paths present |
| `baseline:closed_line:liquidation-cascade reversal` | PASS | evidence paths present |
| `baseline:closed_line:stablecoin exchange-flow prediction (OPP-0003 co` | PASS | evidence paths present |
| `spec:H-049-001:fields` | PASS | all required fields present |
| `spec:H-049-002:fields` | PASS | all required fields present |
| `spec:H-049-003:fields` | PASS | all required fields present |
| `prereg:H-049-001:thresholds` | PASS | RFC-049 §16 minimum contract present |
| `prereg:H-049-001:pf_min` | PASS | PF_min=1.1 |
| `prereg:H-049-002:thresholds` | PASS | RFC-049 §16 minimum contract present |
| `prereg:H-049-002:pf_min` | PASS | PF_min=1.1 |
| `gate:next_campaign` | PASS | NEXT_CAMPAIGN=NOT_AUTHORIZED -> Phase A stops |
| `final:deliverables` | PASS | all present |

## Notes

Phase A executes no economic evaluation: no signal, no return, no PnL, no trade is computed anywhere in this run
