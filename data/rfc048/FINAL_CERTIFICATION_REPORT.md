# RFC-048V — Final Certification Report

- CURRENT_HEAD: `081201f1eeaf77985f55dc488ffec373939d8c02`
- RFC048_FINAL_STATUS: **RFC048_OFFLINE_CERTIFIED**
- FALSE_SUCCESS: 0

## Commits

- RFC-048 baseline: `19b1a0b`
- campaign: 081201f Falsify and recertify the futures risk plane independently (RFC-048V)

## Runtime reachability

- 31 recorded decisions through the real `DecisionEngine`
- approved simulated: 8
- any order authorised: False

## Deliverables

- `data/rfc048/ADVERSARIAL_FINDINGS.md` — sha256 `4666970b083eb51d…`
- `data/rfc048/ADVERSARIAL_FINDINGS.json` — sha256 `39d88cd8b47732bb…`
- `data/rfc048/RUNTIME_AUTHORITY_VERIFICATION.md` — sha256 `8d3397d452e68be6…`
- `data/rfc048/RUNTIME_AUTHORITY_VERIFICATION.json` — sha256 `25faa0f0cec1de2e…`
- `data/rfc048/INDEPENDENT_CERTIFICATION.md` — sha256 recorded in `DELIVERY_COMMIT_VERIFICATION.json` (self-referential)
- `data/rfc048/INDEPENDENT_CERTIFICATION.json` — sha256 recorded in `DELIVERY_COMMIT_VERIFICATION.json` (self-referential)
- `data/rfc048/FINAL_CERTIFICATION_REPORT.md` — sha256 recorded in `DELIVERY_COMMIT_VERIFICATION.json` (self-referential)
- `data/rfc048/FINAL_CERTIFICATION_REPORT.json` — sha256 recorded in `DELIVERY_COMMIT_VERIFICATION.json` (self-referential)

## False approvals

- pre-fix counterexamples replayed: 12
- post-fix false approvals: 0
- defect families: DEF-048V-01, DEF-048V-02, DEF-048V-03, DEF-048V-04, DEF-048V-05, DEF-048V-06, DEF-048V-07, DEF-048V-08

## Defects fixed

- `DEF-048V-01` (HIGH, FIXED, FuturesRiskEngine): non-finite numbers were not validated: NaN mark and NaN leverage reached approvals
- `DEF-048V-02` (HIGH, FIXED, FuturesRiskEngine): hostile numbers raised instead of refusing (NaN reached int())
- `DEF-048V-03` (MEDIUM, FIXED, FuturesRiskEngine): a repeated decision id reserved its margin twice
- `DEF-048V-04` (MEDIUM, FIXED, FuturesRiskEngine): the aggregate margin-utilization ceiling could be exceeded by concurrent decisions
- `DEF-048V-05` (MEDIUM, FIXED, FuturesRiskEngine): a non-finite reservation poisoned the ledger for every later decision
- `DEF-048V-06` (MEDIUM, FIXED, FuturesRiskEngine): an unmodelable stress scenario was silently treated as no stress
- `DEF-048V-07` (LOW, FIXED, FuturesRiskEngine): a non-finite funding observation could corrupt the funding term
- `DEF-048V-08` (MEDIUM, FIXED, FuturesRiskEngine): the closed-form liquidation solve extrapolated the maintenance amount below its zero floor
- `DEF-048V-09` (MEDIUM, FIXED, certification tooling): the certifier hashed its own certificate files into its manifest before rewriting them, so --verify-commit failed on a clean delivered tree

## Risk invariants

- `I1_APPROVED_RISK_LE_BUDGET`: HELD
- `I2_MARGIN_LE_AVAILABLE`: HELD
- `I3_NOTIONAL_LE_MAX_ALLOWED`: HELD
- `I4_DATA_ORDER`: HELD
- `I5_UNKNOWN_CRITICAL_INPUT`: HELD
- `I6_UNSUPPORTED_CONTRACT`: HELD
- `I7_LIQUIDATION_KNOWN_AND_SAFE`: HELD
- `I8_LIVE_ROUTE_BLOCKED`: HELD
- `I9_NO_ORDER_AUTHORISED`: HELD
- `I10_ROUNDING_REDUCES`: HELD

## Verification-tooling defects

The verification is held to the standard it applies to the engine.

### DEF-048V-09 — the certifier hashed its own certificate files into its manifest before rewriting them, so --verify-commit failed on a clean delivered tree

- severity: MEDIUM · status: FIXED
- detected by: scripts/rfc048v_certify.py --verify-commit, run against the delivery commit after the certificates had been committed
- counterexample: on a clean tree at the delivery commit, --verify-commit returned exit 1 with 4 blob mismatches: FINAL_CERTIFICATION_REPORT.json e26e59df739f -> 2880b83b7306, FINAL_CERTIFICATION_REPORT.md 567ec006838f -> 82ba8429df9b, INDEPENDENT_CERTIFICATION.json 4a40b1ff2584 -> 93ba4810ed00, INDEPENDENT_CERTIFICATION.md 378b662ce5c7 -> e31a101617a3
- root cause: manifest() was evaluated as an argument before write_reports() rewrote the four certificate files, so their recorded blobs were the previous generation's bytes; a document cannot contain the hash of its own final content
- behaviour before: the manifest and the report's DELIVERABLES hashes were stale by one generation for the certificate files, and the delivery gate could never pass
- behaviour after: the manifest excludes the certifier's own outputs and says why; DELIVERY_COMMIT_VERIFICATION.{json,md} carries their sha256 and git blob after they are written, and --verify-commit returns 0 on the delivered tree
- regression test: `uv run python scripts/rfc048v_certify.py --verify-commit` on the delivered commit (exit 0, 0 mismatches); `--record-delivery-commit` re-hashes the six excluded files and fails if any delivered blob moved
- fixed in: the RFC-048V delivery commit; its exact hash is the `delivery_commit` field of data/rfc048/DELIVERY_COMMIT_VERIFICATION.json


## Quality gates

- ruff check: All checks passed! (exit 0)
- ruff format --check: 22 files already formatted (exit 0)
- mypy strict: Success: no issues found in 22 source files (exit 0)
- risk suite: 119 passed in 6.23s
- unit suite: 3163 passed in 270.21s (0:04:30)
- repo-wide suite: PASS — 3210 passed, 78 warnings in 268.08s (0:04:28)
- reports/ hermeticity probe: 0 files changed with no local test running

## Limitations

- none recorded by the certification pass

## Economic integrity

- checks: 41 (failed: none)
- leverage creates alpha: False

## Next economic gate

can a second economic research campaign start? Not yet. The runtime is ready to size and bound a futures position; it has nothing with a measured edge to size, and it cannot place orders by construction.

- a strategy hypothesis with a PIT-measured edge (the RFC-046 campaign failed and no candidate is admitted; RFC-048 explicitly does not create one)
- a measured futures cost model verified against a real account schedule (fees are currently a published assumption, spread/impact measured once)
- jurisdiction/venue eligibility verified for the operator (BLK-048-02: still PRODUCT_ELIGIBILITY_UNKNOWN)
- partial-liquidation rules obtained in verifiable form (BLK-048-03: refused rather than modelled)
- cross-margin dependencies validated before any cross usage (BLK-048-04)
- a binding futures review path plus admission-ledger integration if futures PAPER is ever to place simulated orders (today the review is advisory and no order is authorised)

opening that campaign, changing governance flags, or treating an engineering pass as economic evidence

Offline certification of the supported contracts. It means the risk arithmetic, the refusals and the runtime boundary survived independent rebuilding and adversarial search. It does not mean profitability, eligibility or production readiness.
