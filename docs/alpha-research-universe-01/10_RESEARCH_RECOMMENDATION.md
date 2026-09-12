# Research recommendation

Adopt ARC-02 first: it uses already available OHLCV, has a distinct cross-asset information-transmission mechanism, is PIT-simple, and is cheaply falsifiable. Admit timestamped funding as P0 only after authority and availability audits; then test ARC-01 separately from H6's OI-continuation mechanism. Reject full L2, full aggTrades backfill, historical liquidation claims without an official archive, and latency arbitrage: their storage, synchronization, or execution demands exceed current evidence value.
