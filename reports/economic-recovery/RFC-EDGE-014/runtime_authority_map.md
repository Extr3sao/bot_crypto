# WP-EDGE-14A — runtime authority map

*What is authoritative, what is only reachable, and what exists without an entrypoint.*

| module | classification | present |
| --- | --- | --- |
| trading_bot.market_data | RUNTIME_REACHABLE | True |
| trading_bot.execution | RUNTIME_AUTHORITATIVE | True |
| trading_bot.paper | RUNTIME_REACHABLE | True |
| trading_bot.risk | RUNTIME_AUTHORITATIVE | True |
| trading_bot.backtesting | RESEARCH_ONLY | True |
| trading_bot.strategies | RUNTIME_REACHABLE | True |
| trading_bot.research | RESEARCH_ONLY | True |
| trading_bot.observability | RUNTIME_REACHABLE | True |
| trading_bot.portfolio | RUNTIME_REACHABLE | True |
| trading_bot.storage | RUNTIME_REACHABLE | True |

## Authority chain

Market Data → Signal → TradeProposal → StrategyRouter/Decision → Deterministic Risk → Paper Broker/Execution → Reconciliation → Evidence

an external engine is a hypothesis source or a benchmark; it cannot send an order and cannot replace Risk or Execution
