# RFC Candidates — Source Ingestion V1

No new RFC is created from the supplied book in this phase.

Reason: the high-value mechanisms map onto architecture already described in supplied project notes (deterministic Risk, Decision/Evidence trace, Strategy/Regime routing, PostTrade/Memory, independent verification). Creating another RFC now would risk duplicating architecture without a repository/runtime gap audit.

Possible RFC gate later: if the actual repository lacks a versioned `TradeIntent / RuleProvenance` persistent contract and adding it changes a critical runtime interface, promote IMP-SPEC-004 to an RFC candidate after runtime authority mapping.


## V2 Batch 2 RFC Gate

No new RFC candidate was created from SRC-BOOK-002, SRC-MANUAL-001, SRC-MANUAL-002 or SRC-CHEATSHEET-001. IMP-SPEC-006/007/008 and RISK-SPEC-005/006 fit existing research, observability, execution and deterministic-Risk boundaries. An RFC is justified only if later runtime reconciliation proves a new authority boundary, persistent-state contract or critical subsystem is required.
