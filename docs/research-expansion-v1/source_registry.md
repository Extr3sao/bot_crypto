# RESEARCH-EXPANSION-V1 — Source Registry

Date: 2026-09-06 · Rule: nothing here enters POC01 runtime. `DISCOVERY_PLANE != TRADING_RUNTIME` holds. Licenses marked `verify` require a fresh check of the repo LICENSE file before any code adoption.

| SOURCE_ID | URL / Source | Project | License | Version/Commit | Pattern (what we'd take) | Evidence | Reliability | Decision | Layer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SRC-001 | github.com/freqtrade/freqtrade | Freqtrade | GPL-3.0 (verify) | current 2026 | hyperopt discipline, dry-run/wallet simulation, protections (stoplookback, cooldown) | wide community usage, long history | high (project maturity) | ADOPT_P1 (PATTERN only — GPL makes code adoption an authority risk) | PROJECT |
| SRC-002 | github.com/hummingbot/hummingbot | Hummingbot | Apache-2.0 (verify) | current 2026 | market-making/inventory patterns, order lifecycle idempotency | active; exchange-connectors depth | high | ADOPT_P2 | PROJECT |
| SRC-003 | github.com/jesse-ai/jesse | Jesse | Apache-2.0 (verify) | current 2026 | research-grade backtest API, clean strategy schema | 2026 comparisons rank it as research-grade | medium-high | ADOPT_P1 (PATTERN) | PROJECT |
| SRC-004 | github.com/nautechsystems/nautilus_trader | NautilusTrader | LGPL-3.0 (verify) | current 2026 | event-driven correctness, clock/PIT discipline, backtest-live parity | strongly aligned with our BUILDER/VERIFIER ethos | high | ADOPT_P1 (PATTERN: backtest-live parity gates) | PROJECT |
| SRC-005 | github.com/vnpy/vnpy | VeighNa (vn.py) | MIT (verify) | current 2026 | gateway abstraction, event engine | CN community scale | medium | DEFER | PROJECT |
| SRC-006 | github.com/microsoft/qlib | Qlib | MIT | current 2026 | walk-forward/rolling retrain evaluation workflows | established quant-research framework | high | ADOPT_P1 (PATTERN) | PROJECT |
| SRC-007 | github.com/microsoft/RD-Agent | RD-Agent | MIT (verify) | current 2026 | LLM-driven factor/strategy research loops with evidence gates | emerging 2025-2026 | medium | EXPERIMENT (research-plane only) | PROJECT |
| SRC-008 | polakowo/vectorbt (+ vectorbt PRO split) | vectorbt | Custom/Free-personal (verify) | current 2026 | vectorized parameter-robustness surfaces | widely used for sweeps | high | ADOPT_P2 — pattern only; sweeps are FORBIDDEN in our discovery plane (anti-overfit §ANTI-OVERFIT); never as authority | IMPLEMENTATION |
| SRC-009 | github.com/stefan-jansen/machine-learning-for-trading | ML4T notebooks | MIT-ish (verify) | stable | purged/embargoed CV patterns | book + repo longevity | high | ADOPT_P1 (PATTERN) | PATTERN |
| SRC-010 | papers: López de Prado (purged CV, triple-barrier); Armenteros/López de Prado crypto-ML studies | Academic patterns | n/a | n/a | meta-labeling, purged K-fold, embargo | peer-reviewed lineage | high | ADOPT_P0 (as evaluation patterns for our confirmation/holdout gates) | PATTERN |
| SRC-011 | yuosef/lean CLI & QuantConnect | Lean | Apache-2.0 (verify) | current 2026 | institutional-grade OOS discipline | 2026 landscape reviews | medium-high | DEFER | PROJECT |
| SRC-012 | Specialized crypto strategy repos (screened) | various | mixed | — | per-repo audit required before any adoption | low per-repo | low-medium | REJECT for now (authority risk; per-repo audit is a future checkpoint) | PROJECT |

## Screened-out risks (explicit)

- Copying whole frameworks is forbidden (spec §20): only PATTERNs cross into our contracts, re-implemented under our ADRs.
- Any GPL/AGPL-licensed code must not be copied — pattern-level inspiration only (SRC-001).
- vectorbt-style exhaustive sweeps (SRC-008) conflict with pre-registered discovery rules; usable only inside research plane with multi-variant correction and full registration.

## References consulted (current, 2026)

- pistack.xyz 2026-04-27 Freqtrade vs Jesse vs Hummingbot guide
- youngju.dev 2026-05-16 "Trading Bots & Quant Tools 2026 Deep Dive"
- klawtrade.com 2026-04-15 "Best Open-Source Python Trading Bots in 2026"
- trendrider.net 2026-04-02 Freqtrade vs Hummingbot vs CCXT
