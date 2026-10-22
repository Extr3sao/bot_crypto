# RFC-049 SOURCE REGISTRY

- campaign: **RFC-049 DISCOVERY 2 — Phase A**
- rule: every hypothesis carries `CLAIM + SOURCE + EVIDENCE + DECISION`; negative and
  contradictory sources are recorded with the same weight as supporting ones
- evidence classes (RFC-035 hierarchy, unchanged):
  `REAL_EXECUTION > FORWARD_PAPER > INDEPENDENT_REPLICATION > REPRODUCIBLE_CODE > ACADEMIC_PAPER > AUTHOR_BACKTEST > UNVERIFIED_CLAIM`
- **read level** is declared per source and is deliberately conservative: Phase A read
  abstracts, vendor metadata and search-level bibliographic records.  A Phase B claim
  that leans on a source must first raise its read level to full text.

| id | source | class | read level in Phase A | what it supports | counter/limits |
| --- | --- | --- | --- | --- | --- |
| SRC-049-001 | DefiLlama API `stablecoins.llama.fi/stablecoincharts/all` (series stored and hashed in `data/rfc049/vendor/`) | REPRODUCIBLE_CODE | API responses retrieved, coverage-audited | the signal series for H-049-001 (`totalCirculatingUSD.peggedUSD`) | vendor revisions; PIT semantics are a declared convention, not a vendor timestamp |
| SRC-049-002 | Chi, Chu & Hao (2024, rev. 2025-09-01). *Return and Volatility Forecasting Using On-Chain Flows in Cryptocurrency Markets*. arXiv:2411.06327v2 | ACADEMIC_PAPER | abstract read in full | USDT net inflows **into exchanges** positively predict BTC and ETH returns at 1–6h intervals; ETH net inflows negatively predict ETH returns | the finding is exchange-flow at intraday horizons, **not** aggregate supply growth at daily horizons; this is an extrapolation our mechanism must earn on data |
| SRC-049-003 | Watsky, Allen, Daud, Demuth, Little, Rodden & Seira (2024-02-23). *Primary and Secondary Markets for Stablecoins*. FEDS Notes | ACADEMIC_PAPER (central-bank note) | introduction/background read; full note not read | primary vs secondary market mechanics: mints/redemptions are primary-market events that change supply, secondary-market prices are where depegs appear | the note is a crisis anatomy (March 2023), not a return-prediction study |
| SRC-049-004 | Federal Reserve Bank of Philadelphia WP 26-24 (2026), *Evaluating Stablecoin's Role …* (event study on USDT and systemic liquidity in ETH/BTC markets) | ACADEMIC_PAPER | bibliographic record + abstract snippet only | independent event-study evidence that USDT interactions carry information for BTC/ETH market liquidity | unread in full; result direction not verified in Phase A |
| SRC-049-005 | Boido et al. (2026). *The Predictive Relationship Between Stablecoin and Cryptocurrency …*. MDPI JRFM 5(3):68 (preprint version also exists) | ACADEMIC_PAPER | bibliographic record + snippet only | **counter-evidence**: forward predictability from stablecoin events is weak/non-systematic when depegging is accounted for | unread in full; recorded as the principal adversarial source for H-049-001 |
| SRC-049-006 | *Does monetary liquidity affect Bitcoin price?* SSRN working paper 4904716 (2024) | ACADEMIC_PAPER (working paper) | bibliographic record + snippet only | a practitioner USD monetary-liquidity measure has a significant impact on the BTC price | single working paper, practitioner-constructed measure; unread in full |
| SRC-049-007 | Eickmeier, Gambacorta & Hofmann (2013). *Understanding Global Liquidity*. BIS Working Paper 402 | ACADEMIC_PAPER | bibliographic record + snippet only | the framework: global liquidity as a priced factor in risk assets | macro-level, not crypto-specific |
| SRC-049-008 | FRED series `WALCL`, `RRPONTSYD`, `WTREGEN`, `DFII10`, `DTWEXBGS`, `DFF` (data retrieved and hashed); H.4.1 / DTS release practice | REPRODUCIBLE_CODE + official statistics | series data retrieved; release-lag table declared from standard publication practice | the signal inputs for H-049-002 and its comparators | release-lag table must be re-verified against actual publication timestamps in the Phase B PIT audit |
| SRC-049-009 | blockchain.com charts API: `hash-rate`, `miners-revenue` | REPRODUCIBLE_CODE | data retrieved and hashed (daily hashrate from 2018-10-12) | H-049-003 signal series (deferred) and comparator | the `timespan=all` variant is 4-day sampled; only the `sampled=false` daily series is admissible |
| SRC-049-010 | Kubal & Kristoufek (2022). *Exploring the relationship between Bitcoin price and network hashrate within endogenous system*. International Review of Financial Analysis | ACADEMIC_PAPER | bibliographic record + snippet only | hashrate and price are jointly determined — the mechanism behind miner supply stress | endogeneity cuts both ways: it also warns the signal may echo price |
| SRC-049-011 | Fantazzini, Kolodin, Parshakov & Smirnov (2020). *Does the Hashrate Affect the Bitcoin Price?* JRFM 13(11):263 | ACADEMIC_PAPER | bibliographic record + snippet only | hashrate carries information about price beyond a pure cost channel | unread in full |
| SRC-049-012 | Edwards / Adamant Capital (2019), *Hash ribbons*; industry coverage (CoinDesk 2026-02-25, Bitcoin Magazine 2022-03-23, TradingView/NewsBTC 2026-01-06) | AUTHOR_BACKTEST + UNVERIFIED_CLAIM | snippets only | the exact rule family registered for the deferred H-049-003 | publish-or-perish: widely followed since 2019; no source located with net-of-cost OOS attribution |

## Negative and contradictory record

- **SRC-049-005** is the declared counter-evidence for H-049-001.
- The project's own `research/profitability/opportunities/OPP-0003.md` records that
  the 1–2h stablecoin-flow effect collides with the cost floor and that labelled
  exchange-flow data is commercial — the reason H-049-001 was specified on a free
  aggregate series at a weekly cadence instead.
- The project's own `OPP-0001` / RFC-035E falsification is the precedent that a
  flow-continuation story can collapse into a trend proxy; H-049-001 carries the
  trend baseline as a frozen control for exactly that failure mode.
- For H-049-002, no located source establishes a stable BTC-liquidity relationship
  across regimes; the registered spec treats regime instability as an acceptance
  risk, not a footnote.

## What Phase A did not verify

- Full texts of SRC-049-004..007 and 010..012 were not read; their records here are
  bibliographic plus snippet level.
- No source is a complete trading strategy; the rules in the specs are ours, derived
  from the mechanism, and they are frozen before measurement.
- No source provides a net-of-cost out-of-sample attribution at our size, venue and
  cadence; that is what the campaign exists to produce.
