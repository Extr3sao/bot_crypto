# ALPHA DATA EXPANSION PLAN

Checkpoint: H5-RESULT-INTEGRITY-RECONCILIATION-02 · Date: 2026-09-11
**SOURCE RESEARCH ONLY — no execution, no H6, no spec, no threshold.**
Context: H5 terminal DISCOVERY_FAIL (memory #12) + governance decision
**CURRENT_INFORMATION_SET = EXHAUSTED_FOR_NOW** (ADR-0033): every remaining OHLCV-family
transformation is exhausted; new alpha must come from genuinely new information families.

Evaluation assets carried forward: BTCUSDT, ETHUSDT, SOLUSDT (1h base timeframe;
1m/5m only where source depth supports it).

## Family evaluation (11 attributes each)

### 1. Open interest history

| Attribute | Assessment |
| --- | --- |
| Source authority | Binance official. REST `/futures/data/openInterestHist` (aggregate OI, 5m/15m/30m/1h/2h/4h/6h/12h/1d periods) — **only latest 30 days** (verified via Binance dev docs, change log). Deep history: `data.binance.vision` `data/futures/um/daily/bookDepth/` (snapshot book state incl. open interest fields at 1s grid, daily zips) and `data/futures/um/daily/metrics/` (OI + long-short + taker stats). |
| Historical depth | REST: 30 d. Vision archives: from ~2020-05 (per Tardis coverage cross-check of Binance collection; BTCUSDT/ETHUSDT from listing-adjacent dates). |
| Assets | All USDM perps incl. BTCUSDT, ETHUSDT, SOLUSDT. |
| Resolution | REST 5m–1d; vision bookDepth snapshots ~1s (usage as OI time series at 1m+). |
| PIT safety | HIGH — OI is exchange-reported state at timestamp; vision files are immutable point-in-time archives. No revision risk. |
| Cost | Free, public. Bulk-download bandwidth only (daily zips, ~MB-scale per symbol-day). |
| Rate limits | REST ~2 req IP-weight per call; vision is static HTTPS — effectively unlimited with courtesy pacing. |
| Licensing | Binance public data terms (attribution/non-redistribution caveats in ToU); internal research use consistent with current frozen klines usage. |
| Data quality | Good; known issues: vision snapshot gaps on low-liquidity days, REST 30-day rolling deletion. Requires gap/cadence validation per symbol (same pattern as funding-source proposal). |
| Expected mechanism | OI changes + price direction = positioning flow pressure (new money entering/leaving); OI-normalized volatility conditioning; squeeze detection (OI + adverse move). Orthogonal to momentum because it conditions on *positioning*, not price aggregation. |
| Expected frequency | 1h/4h events — compatible with n≥30 over 2020–2026 for BTC/ETH (thousands of bars), trades expected dozens-to-low-hundreds per hypothesis. |
| Storage | Daily zips per symbol: BTC/ETH/SOL × ~6 y ≈ 6.5k files, est. 2–6 GB decompressed at 1s grid; downsampling to 1m OI series → ~100 MB. |

### 2. Liquidation flow history

| Attribute | Assessment |
| --- | --- |
| Source authority | Binance official REST `/futures/data/forceOrders` requires **account credentials** (own liquidations only — useless for market-wide). Market-wide liquidations: NOT available as official archive; `data.binance.vision` has no liquidation archive (metrics has long/short but not liq events). Third-party: Tardis (commercial), Coinalyze/CoinGlass (aggregators, unverified methodology). |
| Historical depth | Official market-wide: none. Aggregators: ~2020+. |
| Assets | Aggregators cover majors. |
| Resolution | Event-level (aggregators), variable. |
| PIT safety | MEDIUM-LOW — aggregator captures are derived (websocket snapshots by the vendor); silent revision risk; methodology opaque. |
| Cost | Tardis is commercial (material subscription); aggregators freemium. |
| Rate limits | Vendor-dependent. |
| Licensing | Vendor ToU; redistribution restricted. |
| Data quality | Unverifiable without an independent capture program of our own. |
| Expected mechanism | Forced-flow continuation/reversal after liquidation cascades (cascade exhaustion). |
| Expected frequency | Episodic clusters — enough events only across full 6y window. |
| Storage | Event stream; small. |
| **Verdict** | No authoritative PIT-safe free source → REJECT for now (revisit only with a funded vendor contract or own capture). |

### 3. Order book / depth imbalance

| Attribute | Assessment |
| --- | --- |
| Source authority | Binance official `data.binance.vision` `bookDepth/` (daily files, top-N levels at 1s/10s aggregation) and `bookTicker/` (best bid/ask stream archives). REST depth is live-only (no history). |
| Historical depth | Vision bookDepth: from ~2022 (per collection layout; must verify per symbol). bookTicker from ~2020-01. |
| Assets | BTCUSDT, ETHUSDT, SOLUSDT available. |
| Resolution | 1s–10s snapshots (bookDepth); event-level (bookTicker). |
| PIT safety | HIGH for vision archives (immutable, exchange-published). |
| Cost | Free. |
| Rate limits | Static downloads. |
| Licensing | Binance public data terms. |
| Data quality | Good but LARGE; snapshot cadence gaps possible; top-N only (no full book). |
| Expected mechanism | Depth-imbalance (bid/ask size ratio) as short-horizon directional pressure — genuinely new information (unfilled demand/supply), not an OHLCV aggregate. Highest expected orthogonality of all families. |
| Expected frequency | High (per-bar signals) → cost hurdle dominates; must preregister coarse signals (e.g. 1h imbalance thresholds) with few/larger trades. |
| Storage | Very large at full resolution (multi-GB per symbol-month at 1s); requires downsampling policy defined BEFORE backfill. |
| **Verdict** | ADOPT_P0 candidate — but depth verification per symbol is step 1. |

### 4. Basis / futures curve

| Attribute | Assessment |
| --- | --- |
| Source authority | Constructible from official data already in repo: USDM perp klines (frozen) + spot klines (data.binance.vision `data/spot/`) or quarterly delivery contracts. No new vendor needed. |
| Historical depth | Spot: from 2017; perp: 2019-09+; delivery quarterlies per listing. |
| Assets | BTC/ETH/SOL full depth. |
| Resolution | Same as klines (1m–1d). |
| PIT safety | HIGH — derived from official immutable klines. |
| Cost | Free. |
| Rate limits | Static downloads. |
| Licensing | Same as current klines. |
| Data quality | Excellent; simple join. |
| Expected mechanism | Perp-spot basis and term-structure carry as positioning-pressure proxy; overlaps partially with funding (family 6) and with carry_funding memory #8 (basis alone failed) — must add conditioning variable per that lesson. |
| Expected frequency | Daily/4h. |
| Storage | Negligible (series, not archives). |
| **Verdict** | Partially redundant with #8 memory lesson; useful as *conditioning* input inside OI or funding hypotheses rather than standalone. DEFER. |

### 5. Cross-exchange prices / dislocations

| Attribute | Assessment |
| --- | --- |
| Source authority | Official per-exchange archives (Binance + Bybit/OKX vision equivalents) or vendors (Tardis). Multi-venue timestamp alignment is nontrivial (clock skew, different snapshot conventions). |
| Historical depth | Exchange-dependent; ~2019+ for majors on Bybit/OKX. |
| Assets | Majors. |
| Resolution | Trade/1s+ level. |
| PIT safety | MEDIUM — cross-venue alignment introduces look-ahead risk if timestamps not normalized with explicit per-venue latency bounds; PIT contract hard to enforce airtight. |
| Cost | Free (archives) / commercial (vendor). |
| Rate limits | Static downloads. |
| Licensing | Per-exchange terms. |
| Data quality | Clock-skew artifacts; venue outages create false dislocations. |
| Expected mechanism | Lead-lag price discovery (Binance leads; laggards follow) — but strategy only trades Binance per current architecture → dislocation mostly becomes an entry-timing overlay. |
| Expected frequency | High. |
| Storage | Multi-venue archives; large. |
| **Verdict** | REJECT for now — PIT contract cannot be made airtight without a dedicated timestamp-normalization research track; low orthogonality to a single-venue execution stack. |

### 6. Cross-exchange funding

| Attribute | Assessment |
| --- | --- |
| Source authority | Official per-venue funding history (Binance verified in FUNDING_HISTORY_SOURCE_PROPOSAL.md: `/fapi/v1/fundingRate` to 2019-09-10; Bybit/OKX official endpoints analogously). |
| Historical depth | Binance 2019-09 → present (~6,500 obs/symbol); Bybit/OKX similar for majors. |
| Assets | BTC/ETH/SOL on all venues. |
| Resolution | Settlement cadence (8h/1h/4h depending venue+era). |
| PIT safety | HIGH — settlement instants, exchange-reported. |
| Cost | Free. |
| Rate limits | Public REST, paginated; trivial. |
| Licensing | Per-exchange terms. |
| Data quality | Good; era-dependent cadence changes must be fingerprinted per venue. |
| Expected mechanism | Funding *differentials* across venues = relative positioning pressure → cross-venue carry/mean-reversion; extends memory #8's lesson (funding alone failed; differentials are a different mechanism). |
| Expected frequency | Low (8h cadence). |
| Storage | Tiny. |
| **Verdict** | EXPERIMENT — cheap to validate, mechanistically distinct, but low expected frequency means thin N; only viable with multi-venue perp execution someday. Second-priority. |

### 7. Higher-resolution trade flow

| Attribute | Assessment |
| --- | --- |
| Source authority | Official `data.binance.vision` `aggTrades/` and `trades/` (monthly + daily, full history from 2019-09/2020-01). |
| Historical depth | Complete for USDM perps since listing. |
| Assets | BTC/ETH/SOL full. |
| Resolution | Event-level (true trades). |
| PIT safety | HIGH — immutable official archives. |
| Cost | Free; bandwidth-heavy. |
| Rate limits | Static downloads. |
| Licensing | Binance public data terms. |
| Data quality | Excellent. |
| Expected mechanism | True order-flow imbalance (signed taker volume at trade granularity, OFI per Cont et al.) — the *correct* version of what H5 approximated with 1h takerBuy fields. Direct successor path to H5's mechanism on a genuinely finer information set. |
| Expected frequency | Very high raw; must preregister coarse aggregation (e.g. 1h signed-flow z) to control N and costs. |
| Storage | aggTrades BTCUSDT ~2019–2026: est. 10–30 GB compressed total; per-symbol-per-month ~100–300 MB. Requires ingestion pipeline + downsampled canonical features. |
| **Verdict** | ADOPT_P0 — highest mechanistic continuity with H5 and full official depth. |

### 8. Options IV / skew

| Attribute | Assessment |
| --- | --- |
| Source authority | Deribit official archives (BTC/ETH options; DVOL index; no SOL depth pre-2023). Binance options discontinued. No official Binance source for the frozen assets set. |
| Historical depth | Deribit from 2020+ (BTC/ETH). |
| Assets | BTC, ETH only (SOL effectively absent). |
| Resolution | Snapshot/vendor-dependent. |
| PIT safety | MEDIUM — vendor archives; Deribit does publish TBT but access tiered. |
| Cost | Commercial tiers for clean history (material cost → governance gate). |
| Rate limits | Vendor. |
| Licensing | Vendor ToU. |
| Data quality | Good on Deribit but thin OI in early years; SOL unusable. |
| Expected mechanism | IV/skew as forward-looking risk-premium state — genuinely orthogonal in principle. |
| Expected frequency | Daily. |
| Storage | Moderate. |
| **Verdict** | REJECT for now — asset coverage breaks the BTC/ETH/SOL comparability contract, and clean history is a paid external dependency. Revisit at a portfolio-level risk-premium hypothesis. |

## Ranking (DATA_AUTHORITY / ECONOMIC_VALUE / ORTHOGONALITY / HISTORICAL_DEPTH / PIT_SAFETY / COST)

| Rank | Family | Authority | Econ value | Orthogonality | Depth | PIT | Cost | Total /30 | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **7. Higher-resolution trade flow** | 5 | 4 | 4 | 5 | 5 | 4 (free, but pipeline effort) | **27** | **ADOPT_P0** |
| 2 | **1. Open interest history** | 4 | 4 | 5 | 4 | 5 | 5 | **27** | **ADOPT_P0** |
| 3 | 3. Order book depth imbalance | 4 | 4 | 5 | 3 (coverage verify) | 5 | 3 (storage) | 24 | ADOPT_P0 candidate — **only 2 allowed**; stands by as first substitute |
| 4 | 6. Cross-exchange funding | 5 | 2 | 3 | 4 | 5 | 5 | 24 | EXPERIMENT |
| 5 | 4. Basis / futures curve | 5 | 2 | 2 | 5 | 5 | 5 | 24 | DEFER (conditioning input only) |
| 6 | 8. Options IV/skew | 3 | 3 | 4 | 3 | 3 | 1 | 17 | REJECT |
| 7 | 5. Cross-exchange prices | 3 | 2 | 2 | 4 | 2 | 3 | 16 | REJECT |
| 8 | 2. Liquidation flow | 2 | 3 | 4 | 3 | 2 | 1 | 15 | REJECT |

## Selection (max 2) — binding for the next phase

1. **ADOPT_P0 → Trade flow (aggTrades, family 7)** — official, deep (2019-09+), PIT-clean,
   direct mechanistic successor to H5 with a correct order-flow implementation.
2. **ADOPT_P0 → Open interest (data.binance.vision metrics/bookDepth, family 1)** —
   official, PIT-clean, positioning information entirely absent from the current set.

**EXPERIMENT (not selected):** cross-exchange funding differentials (family 6) — small
validation spike may be run during source validation of the adopted families, but gets no
spec and no execution until the two adopted families resolve.
**STANDBY substitute:** order book depth (family 3) — replaces either adopted family only
if its per-symbol coverage validation fails.
**REJECTED:** liquidations, cross-exchange prices, options IV/skew.
**DEFERRED:** basis curve (as conditioning input inside adopted-family hypotheses).

## Hard preconditions (per family) before ANY hypothesis/spec exists

- [ ] Full-depth per-symbol backfill with per-file checksum + gap/cadence validation
- [ ] Dataset fingerprints under the frozen fingerprint_rule; no synthetic rows
- [ ] PIT contract: decision at t uses only records with event_time ≤ t (bar-completion rule)
- [ ] Cross-check overlap region against existing frozen klines-derived aggregates (no silent revision)
- [ ] Window/asset matrix preregistered BEFORE execution (same frozen protocol)
- [ ] Orthogonality gate computed with the CORRECTED Pearson implementation and checked
      BEFORE reading economics (memory #7 and DEF-H5-ORTHO-001 lesson)
- [ ] Cost model unchanged (frozen ExecutionCostModel semantics)

## Explicitly NOT done here

- No H6 created, no spec, no thresholds, no backfill executed, no vendor contacted,
  no cost incurred. This plan authorizes nothing by itself; each adopted family needs
  its own source-validation checkpoint before preregistration.
