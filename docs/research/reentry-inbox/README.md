# REENTRY INBOX

Drop candidate opportunities here before any evaluation. Each file
must declare every field below (RFC-044 §10):

1. OPPORTUNITY_ID
2. DATE
3. SOURCE
4. CLAIM
5. MECHANISM
6. MARKET
7. INSTRUMENT
8. CAPITAL_REQUIREMENT
9. EXPECTED_TURNOVER
10. KNOWN_COSTS
11. PRIMARY_BENCHMARK
12. COUNTER_EVIDENCE
13. TRIGGER_TYPE

Then run the checklist (docs/research/BUSINESS_REENTRY_CHECKLIST.md) and
record the outcome in REENTRY_DECISION_LEDGER. The inbox holds at most
10 pending opportunities; there is no daemon,
no crawler and no scheduled alpha search (§41-§42).

If nothing new is present, the correct result is NO_ACTION (§47).
