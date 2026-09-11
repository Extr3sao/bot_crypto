# H6 MECHANISM EVIDENCE — OI-FULL-HISTORY-FREEZE-01 (Track M)

Researched **without inspecting any repository returns** (Track K still in force). Authority tiers used: `OFFICIAL_EXCHANGE_DOC` and credible market-microstructure literature. Social-media content is explicitly **not** used as authority.

## E-1 · CME Group — "Open Interest" (official exchange education, `OFFICIAL_EXCHANGE_DOC`)

> "Increasing open interest is typically a confirmation of the trend whereas decreasing open interest can be a signal that the trend is losing strength."

Source: cmegroup.com education course *Introduction to Futures — Open Interest* (retrieved 2026-09-11). Establishes, at official-exchange tier, the classic position-stock interpretation: OI change confirms or contradicts price movement. This is the ex-ante rationale for OI-conditioned decision rules.

## E-2 · Investopedia — "Open Interest" (credible reference, corroborating)

> "Open interest measures money flow into or out of a futures market. Increasing open interest represents new or additional money coming into the market."

Source: investopedia.com/terms/o/openinterest.asp (retrieved 2026-09-11). Consistent with E-1: OI expansion = new positioning entering; contraction = positioning leaving.

## E-3 · Shah (2026), *Perpetual Futures in Decentralised Finance: Mechanics, Risks, and Regulation* — MDPI Economies 14(7):178 (peer-reviewed)

Documents the distinctive role of leverage and liquidation cascades in perpetual futures: leveraged positioning (whose aggregate is exactly open interest) creates feedback dynamics absent from spot markets. Source: mdpi.com/2227-7072/14/7/178 (retrieved 2026-09-11). Supports ex-ante plausibility that the *level and change of aggregate positioning* carries state information in crypto perps beyond price/volume.

## Synthesis (ex-ante rationale, no profitability claim)

1. OI is a **position stock**: it accumulates when new positions are opened and decays when positions close — mechanically distinct from any flow variable (price, volume, taker imbalance, funding) used by the 12 failed families.
2. Official exchange education (CME) treats OI change as the canonical *confirmation/contradiction* signal for price movement.
3. Crypto perps add leverage-driven feedback (E-3), giving the position stock potential state information on 24/7 markets.
4. **No claim of profitability is made or implied.** Whether OI-conditioned rules clear costs and stability gates is precisely what the preregistered H6 experiment must measure (in a later checkpoint). If mechanism evidence were deemed insufficient, `H6_SELECTED=false / NO_JUSTIFIED_HYPOTHESIS` would be the honest outcome; here the evidence meets the ex-ante bar for exactly one hypothesis.

## Candidates considered against evidence

| Candidate | Mechanism anchor | Evidence tier | Ex-ante plausibility |
| --- | --- | --- | --- |
| OI expansion/contraction conditioning (M-B) | E-1 + E-2 + E-3 | OFFICIAL_EXCHANGE_DOC + peer-reviewed | defensible |
| Leverage build-up/unwind states | E-3 (partial — needs OI + funding interaction) | peer-reviewed, but requires funding conditioning (carry family #8 caution) | weaker as standalone |
| Trade-flow event imbalance (M-A) | H5 register entry #12 analysis | internal, HIGH collision | deferred |
