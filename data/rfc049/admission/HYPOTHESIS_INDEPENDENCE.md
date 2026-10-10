# RFC-049B — HYPOTHESIS INDEPENDENCE

Question: do H-049-001 and H-049-002 carry economically different information, or are they two names for one liquidity idea?

## Mechanisms

- **H-049-001** — crypto-native: aggregate USD-pegged stablecoin circulating supply (daily, vendor); primary-market issuance/redemption changes the dollar float available to crypto venues
- **H-049-002** — off-crypto policy accounts: Federal Reserve total assets, ON RRP, Treasury General Account; net dollar liquidity in the banking system moves the market price of risk
- shared label: both sit in a 'dollar liquidity -> risk appetite' family; the information sets and the transmission channels differ, and the frozen cross-incremental test is the control

## Measured structural overlap (research-exposed inputs; no returns computed)

- common weekly grid: 2019-01-06 to 2026-10-04 (405 weeks)
- active weeks — both 93, H-049-001 only 85, H-049-002 only 120, neither 107
- state agreement rate: 0.49382716049382713
- Jaccard on active weeks: 0.31208053691275167
- Spearman rank correlation of the drivers (30-day supply-growth margin versus 4-week net-liquidity change): 0.08748981630511161

## Reading

the two candidates do not trade the same clock: different inputs, different sampling frequency and different transmission channels. The measured state overlap is reported above; it is a structural measure, not an economic one, and the frozen cross-incremental test remains the decisive control (if either candidate is indistinguishable from the other's state, the frozen test rejects it).

## What would falsify independence

The frozen cross-incremental test (c): each candidate's net result must survive conditioning on the other candidate's state. A high measured overlap does not by itself condemn either candidate, but it makes that control decisive rather than decorative — if either candidate adds nothing on top of the other, it is rejected as a re-description rather than kept as a second discovery.
