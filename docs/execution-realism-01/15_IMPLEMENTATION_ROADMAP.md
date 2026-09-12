# 15 — IMPLEMENTATION ROADMAP — EXECUTION-REALISM-AND-COST-AUTHORITY-01

§27 (DO NOT MODIFY PAPERBROKER) + §36 priority matrix. Future integration only — design/prepare.

## Priority matrix

Score = `(EXPECTED_ECONOMIC_IMPACT × CONFIDENCE × FREQUENCY) / (IMPLEMENTATION_COST × COMPLEXITY × MERGE_RISK)`.

| Rank | Improvement | Impact | Conf/Freq | Cost/Complex/Merge | Score | Req |
|---|---|---|---|---|---|---|
| **1** | **funding deep ETH/SOL** — paginated `fundingRate?startTime=2019-09-10&limit=1000` until 6yr parity, 8h validation + fingerprint | HIGH (unlocks H6 3-asset gate) | MEDIUM | LOW/LOW/LOW | **HIGH** | **ADOPT_P0** |
| **2** | **bookTicker archiver** — `bid/ask` per cycle (KB/day), store + `spread_bps = (ask-bid)/mid*10000` | HIGH (unlocks spread+fills) | MEDIUM | LOW/LOW/LOW | **HIGH** | **ADOPT_P1** |
| **3** | **ask/bid-aware fills (PaperBroker feed-aware mode)** — `LONG@ask*(1+slip) SHORT@bid/(1+slip)` when bookTicker available, else keep `signal±slip` + mark `UNREALISTIC` | MEDIUM (0.5-1 bps SOL RT) | MEDIUM | LOW/LOW/MED | **MED** | P1 after 2 |
| **4** | **Venue-timed fills** — mount `ExecutionGateway( PaperVenue )` to measure `decision→fill ms` + `ExecutionJournal` append; keep PaperBroker DUAL until cutover | MEDIUM | LOW | MED/ MED / MED | **MED** | after 3 |
| **5** | **aggTrades sampled adverse** — extend admitted `TRADE_FLOW` sample to 250ms-5s `AdverseMoveHorizons` (`adverse_move.py`) | MEDIUM | MED | MED / MED / MED | **MED-LOW** | EXPERIMENT (sample first; full 100 GB COST_REVIEW) |
| **6** | **premiumIndex archiver** — `markPrice` alongside bookTicker | LOW-MED | LOW | LOW/LOW/LOW | LOW-MED | EXPERIMENT |
| **7** | **L2 depth (top 20)** | LOW for current size | LOW | HIGH/HIGH/HIGH | LOW | **DEFER** |

## Phased plan (no H6/Risk/live change)

### Phase 0 — Funding parity (ADOPT_P0, this or next checkpoint)

- Loop `fetchFundingRateHistory(symbol, since=2019-09-10, limit=1000, startTime cursor)` for ETH/SOL until `now`.
- Validate: monotonic `fundingTime`, 8h cadence, no gaps > 8h, dedupe `fundingTime`, fingerprint `sha256(symbol,fundingTime,rate)` sorted.
- Commit: `docs/external-audit-01/execution-realism-01/funding-deep/{ETH,SOL}USDT_FUNDING_DEEP.jsonl` + `*_FINGERPRINT.json`.

### Phase 1 — Spread truth (ADOPT_P1, after Phase 0)

- Add `BookTickerFetcher` (`fapi/v1/ticker/bookTicker?symbol=XYZ`) per asset per `PaperCycleEngine` tick; persist `bid/ask/mid/spread_bps/time`.
- Emit `09`-style spread distribution (`median/P75/P90/P95/P99` by asset, time-of-day, regime when sufficient).
- Upgrade `ExecutionRealismEstimate.spread_cost_bps` from `None→real` and populate `BASE/STRESSED`.

### Phase 2 — Fill realism (after Phase 1 evidence)

- Branch `PaperBroker` fill path: if `bookTicker[asset]` fresh (< kill-switch latency), use `ask`/`bid` else diagnostic mark `missing_components=["spread"]`, do not fabricate.
- Gate: `paper_cycle` test matrix for `execution/COST_REVIEW` after wiring — full hermetic must stay `0 failed`.

### Never

- No live trading, no leverage change, no Risk threshold change, no credentials, no H6 execution, no automatic merge.
