# PIT contract

Bars use UTC open timestamps. At decision time T only aligned BTC and follower bars ending at T are admitted; entry is the following bar open. Missing, duplicate, out-of-order, or conflicting bars produce `NO_SIGNAL`. Future BTC or follower data cannot change an earlier decision.
