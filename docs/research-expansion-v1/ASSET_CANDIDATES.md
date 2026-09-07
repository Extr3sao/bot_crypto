# RESEARCH-EXPANSION-V1 — Asset Candidates (§22)

POC01 universe stays BTC/ETH/SOL (frozen during the 7-day window). Candidates below are
`ASSET_CANDIDATE` records only. Metrics marked UNVERIFIED require a fresh-data quality
pass (same harness as FRESH-DATA-001-R1) before they can enter any future campaign —
none were downloaded in this checkpoint.

| Candidate | Exchange pair | Liquidity | Spread | Volatility character | Data quality (5m) | Correlation vs BTC | Diversity hypothesis | Preliminary decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ASSET_CANDIDATE-01 | BNB/USDT:USDT | high | low | mid, event-driven spikes | good (Binance native) | mid | exchange-native regime, distinct from majors | ADOPT_P1 pending fresh validation |
| ASSET_CANDIDATE-02 | XRP/USDT:USDT | high | low | news/regulatory-driven bursts | good | mid-low | event-regime diversity | ADOPT_P2 |
| ASSET_CANDIDATE-03 | DOGE/USDT:USDT | high | low-mid | retail-momentum, fat tails | good | mid | momentum-regime contrast | EXPERIMENT (tail-risk review first) |
| ASSET_CANDIDATE-04 | AVAX/USDT:USDT | mid-high | mid | high-beta alt | good | high | beta within L1 cluster | DEFER (redundant vs ETH/SOL) |
| ASSET_CANDIDATE-05 | LINK/USDT:USDT | mid-high | mid | oracle-sector cycles | good | mid-high | sector-rotation signal | ADOPT_P2 |
| ASSET_CANDIDATE-06 | ADA/USDT:USDT | mid-high | low-mid | slow-trend, low volatility-of-vol | good | mid | low-regime contrast | DEFER |

Objective criteria scoring (liquidity/spread/volume/volatility/data-quality/availability/slippage/correlation/diversity/strategy-compatibility) will be computed from fresh 5m data in a future checkpoint — recorded here as UNVERIFIED by design. Do NOT add any of these to a running campaign.

---

## ASSET-VALIDATION-001 — fresh measurement (2026-09-07)

Executed `scripts/validate_asset_candidates.py`: public ccxt binanceusdm
(credentials empty by construction), 20-day 5m window (2026-08-18 ..
2026-09-07T06:01Z, 5760 candles/symbol, 0 gaps, 0 duplicates), 400-day 1d
depth. Acceptance criteria were pre-registered in the script docstring
BEFORE any data was fetched. Evidence: `reports/research-expansion-v1/ASSET_VALIDATION.json`
(sha256 4fe93e377027191e...). Runtime artifacts are gitignored by design;
the summary below is the committed record.

| Candidate | Decision | Median 5m quote vol | Ann. vol | max\|corr\| vs BTC/ETH/SOL | Slippage proxy (half-spread) | Depth 1d |
| --- | --- | --- | --- | --- | --- | --- |
| ASSET_CANDIDATE-01 BNB | ADOPT_P2 | $896,604 | 47.0% | 0.743 (BTC) | 0.00070 | 400d |
| ASSET_CANDIDATE-02 XRP | ADOPT_P1 | $3,327,936 | 105.7% | 0.714 (SOL) | 0.00145 | 400d |
| ASSET_CANDIDATE-05 LINK | ADOPT_P2 | $389,357 | 82.6% | 0.736 (ETH) | 0.00136 | 400d |
| ASSET_CANDIDATE-03 DOGE | ADOPT_P1 | $1,229,594 | 91.9% | 0.767 (SOL) | 0.00127 | 400d |

Baselines measured with the same harness (BTC 44.5% vol / $25.3M med5m,
ETH 61.2% / $19.7M, SOL 78.1% / $5.4M) — all candidates show meaningful
opportunity diversity (diversity index 0.267–0.317, higher = more
independent opportunity).

**Revisions vs the preliminary table above (data overruled priors):**

- XRP: ADOPT_P2 → **ADOPT_P1** (highest liquidity of the four, clean data).
- DOGE: EXPERIMENT → **ADOPT_P1** (vol 91.9% inside band, corr 0.767 < 0.85,
  liquidity > $1M). The tail-risk concern was not confirmed by 5m data.
- BNB: ADOPT_P1 pending → **ADOPT_P2** (median 5m quote volume $896k is
  below the $1M P1 bar; everything else passes).
- LINK: ADOPT_P2 → **ADOPT_P2** (unchanged; liquidity $389k keeps it below P1).
- AVAX/ADA: not re-measured this pass (remained DEFER candidates); no data
  downloaded for them, no decision change.

Still `ASSET_CANDIDATE` records only — **nothing enters POC01**, whose
universe BTC/ETH/SOL stays frozen. Entry of any candidate into a future
campaign requires a new checkpoint with the full FRESH-DATA quality harness
(PIT/no-lookahead included), not this market-structure measurement.
