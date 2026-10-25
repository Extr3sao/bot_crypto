# RFC048_FUTURES_RISK_FLOW

Two planes, one boundary. The trading runtime plane is deterministic and owns every
number; the agent intelligence plane may only propose.

```text
Agent Intelligence Plane (proposes; never sizes, never leverages, never authorises)
  └── RiskProposal{direction, entry, stop, requested_notional, requested_leverage, horizon}

                 │  (advisory input only)
                 ▼
Trading Runtime Plane — trading_bot.risk.futures.FuturesRiskEngine.decide()
  1  Instrument capability      InstrumentSpec.ensure_usable()      → UNSUPPORTED_INSTRUMENT
  2  Market-data validity       timestamps, mark price, ladder      → DATA_INVALID
  3  Cost completeness          FUTURES_COST_MODEL + PIT funding    → NO_TRADE (COST_UNKNOWN)
  4  Risk-bounded sizing        risk_bounded_sizing()               → NO_TRADE / RISK_VETO
  4b Economic feasibility       edge vs round-trip cost             → NO_TRADE
  5  Leverage cap               min(requested, policy, venue)       → effective leverage
  5b Portfolio gate             exposure, concentration, margin     → refuse or SHRINK
  6  Liquidation & margin       MarginModel.assess()                → RISK_VETO
  6a Loss inside margin         modelled loss <= isolated margin    → RISK_VETO
  6b Stress breach              stress path vs stress LP            → RISK_VETO
  7  Margin reservation         MarginLedger.try_reserve() atomically
  8  Verdict                    APPROVE_SIMULATION | REDUCE_SIMULATED_SIZE   (never an order)

                 │  RiskDecision (evidence + rejection_reasons, order_authorised = False)
                 ▼
Runtime integration (src/trading_bot/risk/futures/integration.py)
  to_risk_review()            RiskDecision → autonomous.contracts.RiskReview (advisory=True)
  build_decision_request()    real DecisionRequest with a RESEARCH_REQUIRED admission
  run_through_decision_engine() real DecisionEngine.decide()

                 ▼
  DecisionEngine ⇒ SHADOW_TRADE / NO_TRADE;  order_authorised = False
  A binding futures review would require an ADR, and the DecisionEngine itself refuses an
  advisory review on an order-authorising packet (pinned by test).
```

## Gate order is a contract

Each gate can only make the outcome more conservative, and no gate can widen a limit
another gate already applied. The order above is fixed in code; the executed catalogue
(`data/rfc048/RISK_SCENARIOS.json`) shows the first gate that fires for each of the 31
scenarios.

## Data flow

```text
venue raw payloads             derived fixtures                    engine inputs
data/rfc048/raw/*.json   →  INSTRUMENTS.json (spec + brackets)  →  InstrumentSpec
                             MARKET_SNAPSHOT.json (px, spread, depth)  mark / spread / depth
                             FUNDING_HISTORY.json (settlements)   →  FundingContext (PIT)
                             PROVENANCE.json (sha256 of each source)
```

Every derived field carries the sha256 of the payload it came from; the independent
verifier re-hashes the raw bracket payload and refuses a ladder that does not match.

## Margin and liquidation model

For an **isolated linear** position the venue's condition is
`wallet + unrealised_pnl − adverse_terms = maintenance_margin`, with
`maintenance_margin = notional × bracket_rate − cumulative_amount` taken from the venue's
own ladder. Solving for the mark price yields the closed forms the engine uses:

```text
LONG :  LP = (qty·entry − WB + A − cum) / (qty · (1 − rate))
SHORT:  LP = (qty·entry + WB − A + cum) / (qty · (1 + rate))
```

where `A` is funding owed plus the venue liquidation fee, charged **before** solving, and
`WB` is the isolated wallet balance. The bracket is taken as the worst one touched between
entry and stress notional, so a notional that can cross the ladder is charged the higher
rate. If the ladder, the mark price or the liquidation fee is missing the assessment is
`LIQUIDATION_RISK_UNKNOWN` and no approval may rest on it.

The verifier does not trust the algebra: it re-solves the same condition numerically over
the raw ladder and additionally simulates the position bar by bar over the venue's real
5-minute closes.

## Cost model

`SPOT_COST_MODEL` and `FUTURES_COST_MODEL` are separate objects. The futures model charges
commission (two sides), measured spread (two sides), assumed slippage, measured book-depth
impact (entry side and exit side), point-in-time funding over the horizon, and reports the
venue liquidation fee as a catastrophe term. Three honest states — `COST_KNOWN`,
`COST_ESTIMATED`, `COST_UNKNOWN` — and an unknown component is always refused, never zeroed.
Funding is zero only when the venue's own funding interval proves no settlement falls inside
the horizon.

## Portfolio and concurrency

`MarginLedger.try_reserve` is the only way to consume margin. It is atomic, so eight
concurrent decisions either reserve disjoint margin or are refused; the executed probe
(`RUNTIME_EXECUTION_REPORT.json → concurrency`) shows the invariant holding with real
threads.
