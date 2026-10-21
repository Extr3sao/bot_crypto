# FINAL REPORT — EXP-003P PAPER EXECUTION LIFECYCLE

- **PHASE**: `EXP-003P-PAPER-EXECUTION-001`
- **COMMITS**: the code is committed; the run binds `bdd96f4cf9eda379294d92282aa78707c669ffd5`, the commit that carries the implementation, the frozen 003K input and the scripts. The artifacts are carried by the evidence commit that follows it (`git log -1 --format=%H -- reports/ai-bots/EXP-003P-PAPER-EXECUTION-001`), because a file cannot contain the hash of the commit that adds it.
- **IMPLEMENTED**: typed lifecycle contracts, hash-chained event store, order state machine, idempotent fill ledger, provenance gate, offline venue double, reconciliation, broker instrumentation, 17 adversarial controls, separate verifier
- **TESTS**: `PASS` (see `evidence/TESTS.json` for exit codes)
- **RUNTIME_VALIDATION**: `PASS` (18/18 checks, 17/17 controls)
- **CLEAN_CHECKOUT_REPRODUCTION**: `PASS` (REPRODUCED)
- **PAPER_VALIDATION**: `BLOCKED_NOT_CONFIGURED` — no authorised paper provider exists in this workspace, so nothing here is observed paper execution; the minimum integration plan and its P1..P10 acceptance checks are in `design/PAPER_INTEGRATION_PLAN.md` and were not executed
- **FALSE_SUCCESS**: `0`
- **DEFECTS**: 8 found and fixed/declared during the phase
- **BLOCKERS**: 3
- **EVIDENCE**: `EXECUTION_TRACE.jsonl`, `SCENARIO_TRACE.jsonl`, `ORDER_LIFECYCLE.csv`, `RECONCILIATION.json`, `METRICS.json`, `NEGATIVE_CONTROLS.json`, `VERIFICATION.json`, `INDEPENDENCE_AUDIT.json`, `SHA256SUMS.txt`
- **ARCHITECTURE_STATUS**: the existing paper runtime is instrumented at its real execution boundary (`PaperBroker`); no second risk engine, broker or platform was added. The offline venue is a declared test double.
- **RFC_STATUS**: `ADOPT_P0` implemented for WP00-WP03 and WP05; WP04 `BLOCKED_NOT_CONFIGURED`; live, edge and promotion remain `REJECT`ed
- **NEXT_PHASE**: resolve the paper-provider blocker (`PAPER_VALIDATION`), or open an independent review of this trace — both are separate, authorised decisions

## Claims, sources and decisions

| CLAIM | SOURCE | EVIDENCE | DECISION |
| --- | --- | --- | --- |
| the paper execution boundary is instrumented, not re-implemented | `src/trading_bot/paper/broker.py (lifecycle hook)` | 8-event probe + 276-event rehearsal | `accepted` |
| a real broker fill produces CREATED→SUBMITTED→ACK→FILLED | `EXECUTION_TRACE.jsonl` | 69 runtime fills, 0 illegal transitions | `accepted` |
| ACK alone never moves quantity | `ORDER_LIFECYCLE.csv` | NEG-01, V6 | `accepted` |
| duplicate delivery books exactly once | `NEGATIVE_CONTROLS.json` | NEG-05 effective | `accepted` |
| timeouts leave an UNKNOWN order and block resend | `NEGATIVE_CONTROLS.json` | NEG-06 effective | `accepted` |
| reconciliation is PASS against the broker book and the venue snapshot | `RECONCILIATION.json` | runtime=PASS scenario=PASS | `accepted` |
| observed paper execution | `none` | no authorised provider is configured | `rejected` |
| economic edge | `none` | not evaluated by this phase | `rejected` |
| organisational independence | `INDEPENDENCE_AUDIT.json` | one author | `rejected` |

## Traceability REQ → ACC → WP → IMP → TEST → EXEC → EVID

| REQ | ACC | WP | IMP | TEST | EVID |
| --- | --- | --- | --- | --- | --- |
| `REQ-003P-01` | runtime authority map + reachable PaperBroker | `WP-00` | `scripts/exp_003p_baseline.py; src/trading_bot/paper/lifecycle/recorder.py` | tests/unit/paper/test_execution_lifecycle.py::test_paper_broker_fill_is_recorded_as_an_envelope_with_its_own_provenance | BASELINE.md; runtime_authority_map.md; EXECUTION_TRACE.jsonl |
| `REQ-003P-02` | every event carries provenance, adapter, clock, correlation | `WP-01` | `src/trading_bot/paper/lifecycle/contracts.py` | test_provenance_cannot_be_promoted_by_relabelling; V2_provenance_completeness | EXECUTION_TRACE.jsonl; VERIFICATION.json |
| `REQ-003P-03` | data_time <= decision_time <= event_time | `WP-01` | `src/trading_bot/paper/lifecycle/contracts.py` | test_decision_after_the_event_it_produced_is_refused; V3_causality | VERIFICATION.json |
| `REQ-003P-04` | no submit without risk approval and policy identity | `WP-01` | `src/trading_bot/paper/lifecycle/engine.py` | test_submit_without_risk_approval_is_refused_before_transmission; NEG-15 | NEGATIVE_CONTROLS.json |
| `REQ-003P-05` | only legal transitions; ACK != FILL; terminal states hold | `WP-01` | `src/trading_bot/paper/lifecycle/store.py` | test_acknowledgement_is_not_a_fill; V4_state_machine; NEG-01/NEG-04 | ORDER_LIFECYCLE.csv; VERIFICATION.json |
| `REQ-003P-06` | one fill key books exactly once | `WP-01` | `src/trading_bot/paper/lifecycle/store.py` | test_duplicate_delivery_books_the_fill_once; NEG-05 | NEGATIVE_CONTROLS.json; ORDER_LIFECYCLE.csv |
| `REQ-003P-07` | quantities, cash, positions, fees and PnL rebuilt from events | `WP-01` | `src/trading_bot/paper/lifecycle/store.py` | test_partial_fill_then_full_fill_accumulates_quantity_and_fees; V5_ledger_rebuild | ORDER_LIFECYCLE.json; VERIFICATION.json |
| `REQ-003P-08` | reconciliation PASS/FAIL/INCOMPLETE, no simulated source | `WP-03` | `src/trading_bot/paper/lifecycle/reconcile.py` | test_reconciliation_without_a_primary_source_is_incomplete; NEG-12/NEG-16 | RECONCILIATION.json |
| `REQ-003P-09` | timeouts and unknowns produce no duplicate order or invented fill | `WP-01` | `src/trading_bot/paper/lifecycle/engine.py` | test_timeout_leaves_the_order_unknown_and_blocks_another_submit; NEG-06 | NEGATIVE_CONTROLS.json |
| `REQ-003P-10` | trace, metrics, per-provenance counts and a verifiable manifest | `WP-03` | `src/trading_bot/paper/lifecycle/store.py; scripts/exp_003p_rehearsal.py` | V1_chain_integrity; V8_determinism | EXECUTION_TRACE.jsonl; METRICS.json; SHA256SUMS.txt |
| `REQ-003P-11` | each control fails with its declared class | `WP-02` | `scripts/exp_003p_controls.py` | 17 controls, each with baseline_ok and the declared class | NEGATIVE_CONTROLS.json |
| `REQ-003P-12` | separate verification program; honest independence | `WP-05` | `scripts/exp_003p_verify.py` | INDEPENDENCE_AUDIT.json (program=True, organizational=False) | INDEPENDENCE_AUDIT.md; VERIFICATION.json |
| `REQ-003P-13` | LIVE unreachable, no secrets, config hashes preserved | `WP-01/WP-05` | `src/trading_bot/paper/lifecycle/contracts.py` | NEG-10/NEG-14; V7_live_disabled; V12_config_unchanged; V13_no_secrets | VERIFICATION.json |
| `REQ-003P-14` | two offline runs produce the same canonical digest | `WP-03` | `scripts/exp_003p_rehearsal.py` | V8_determinism (run 1 vs run 2) | DIGESTS.json; runs/run-2/DIGESTS.json |

## Defects

### DEF-003P-01 — the lane's recorder parameter was shadowed by an internal variable (`high`)

VisionLane.__init__ assigns ``lifecycle = str(opinion_lifecycle)``; the new parameter of the same name was therefore a string when it reached PaperBroker, and every observation raised AttributeError. The broker logged a warning per fill and the trace stayed empty rather than failing loudly.

**Treatment:** parameter renamed to lifecycle_recorder; the broker now logs the exception message, and the rehearsal asserts a non-zero event count

### DEF-003P-02 — a duplicate accounting_snapshot was shadowed by the existing one (`medium`)

003P added a second accounting_snapshot to PaperBroker; Python silently kept the later definition, so reconciliation compared against a shape nobody returned. The class already carried a richer book snapshot.

**Treatment:** the added method was removed; reconciliation reads the existing shape

### DEF-003P-03 — a tampered persisted row was reported as PROVENANCE_MISMATCH (`high`)

the loader validated the payload digest before the hash chain, so NEG-09 (quantity altered on disk) produced a provenance class instead of an integrity one. Naming the wrong defect is how a control passes for the wrong reason.

**Treatment:** the chain is verified over the bytes as written before any semantic check

### DEF-003P-04 — the venue double counted a duplicated delivery in its own snapshot (`medium`)

the re-delivered fill was refused by the event store (correct) but counted twice in the venue's tally, so a correct ledger failed reconciliation.

**Treatment:** the venue book applies each fill identity once

### DEF-003P-05 — realised PnL was compared while the book still held a position (`low`)

the ledger books an open leg's entry fee at the fill and the broker books it at the close, so the two realised numbers differ by that fee until flat.

**Treatment:** the comparison is deferred and declared (realised_pnl_comparison=DEFERRED_OPEN_POSITION) instead of being forced

### DEF-003P-06 — the protocol was re-rendered once before the first rehearsal (`low`)

NEG-14's expected class was corrected to LIVE_MODE_FORBIDDEN after the contract began refusing a LIVE environment as a live-mode violation. The correction happened before any trace existed; the protocol hash recorded by the rehearsal matches the file on disk.

**Treatment:** declared here; the protocol carries no result-dependent content

### DEF-003P-07 — the checkout gate could compare a run against itself and call it a reproduction (`high`)

run_checkout_check derived the worktree path from ``REPO.parent``. Executed from inside the checkout that path *is* the checkout, so the rehearsal would rewrite the published artifacts and the digest comparison would compare a file with itself: a green verdict for an operation that reproduced nothing. Found while running this phase's own reproduction, before any verdict was published.

**Treatment:** the gate refuses to run when the worktree path resolves to the repository it is executing from, and the reproduction verdict is now produced by a separate comparison script (exp_003p_checkout_compare.py) that reads two directories

### DEF-003P-08 — the independence audit reported a false negative from a substring scan (`medium`)

`program_independence` was decided by searching the verifier's text for each producer module stem. Those stems ("store", "engine", "venue", "reconcile", "recorder", "contracts") also occur as ordinary words in its prose, so the audit published `program_independence=false` for a verifier that imports no `trading_bot` module at all. An audit that understates its own separation is still wrong: the claim has to match the code.

**Treatment:** the scan parses the verifier with `ast` and collects its real imports; the markdown heading follows the measured value instead of asserting it

## Blockers

- PAPER_VALIDATION=BLOCKED_NOT_CONFIGURED: no authorised paper/testnet provider, endpoint or account is configured in this workspace, so no fill of this cycle was observed at a venue. The offline book is not a substitute.
- organizational_independence=false: producer, verifier and controls were written by one agent. The separation is between programs.
- Prospective status does not rest on a commit that predates the run: the artifacts are committed by the evidence commit, which follows the code commit the run binds. The preregistration is a frozen document (`PROTOCOL_FROZEN_UTC`), its digest is recorded in every run, and a clean checkout re-derives the identical file from the frozen constants.

## Declared limits

- The 69 runtime fills are `OFFLINE_SIMULATED`: they prove what the code does with a frozen bar and never that a venue accepted an order.
- Partial fills, cancels, rejects and timeouts are exercised through the declared offline venue double, not through the broker, whose fills are all-or-nothing.
- Broker-observed envelopes stamp the decision instant with the booking instant (`decision_time_source=PAPER_BROKER_BOOKING_INSTANT`) and record the broker's notional guard as the risk gate (`risk_evaluation_source=PAPERBROKER_NOTIONAL_GUARD`).
- `signal → intent` latency is `NOT_AVAILABLE`; the broker publishes no decision clock.
- Spread and slippage against an external quote are `NOT_AVAILABLE`; the closed-trade cost decomposition of the broker is reported instead.
- Depends on `EXP-003O=PASS_PARTIAL_INCOMPLETE_REAL_DATA`; 003P does not repair that coverage or its independence.
- `tests/unit/reports` belongs to another experiment and is not part of this gate. Observed while reproducing: it passes in the shared tree (201 tests) and is red in a clean checkout (2 failed, 40 errors) because it reads artifacts under `reports/ai-bots` that are git-ignored and therefore absent from a checkout. That is a pre-existing defect of that suite, declared here and not counted as green.
- The clean-checkout reproduction needs the 003K frozen dataset, which the code commit publishes under `reports/ai-bots/EXP-003K-CANDIDATE-001/dataset` (3.9 MB) so the checkout is self-contained; the three SHA-256 digests are the ones `BASELINE.json` recorded.
- Dependencies are installed from the committed `uv.lock`. `uv sync --locked` refuses this repository because that lock predates the current `pyproject.toml` (it does not know `matplotlib`) — a pre-existing repository defect, not a 003P one. The clean checkout therefore installs the baseline's exact versions with `uv pip sync` from a frozen freeze file, declared with its command in `evidence/CLEAN_CHECKOUT_REPRODUCTION.json`.

## Clean-checkout reproduction

- result: `REPRODUCED`
- detail: every content digest, trace row, verifier outcome, control class and reconciliation verdict matched
- commit reproduced: `bdd96f4cf9eda379294d92282aa78707c669ffd5`
- comparisons: {"commit_bound:execution_trace_sha256": {"byte_identical": true, "published": "f0264348e3823c2fd2cfd95b5a4643496f34a95bacfcd914fce3dcf25b52429e", "reproduced": "f0264348e3823c2fd2cfd95b5a4643496f34a95bacfcd914fce3dcf25b52429e"}, "commit_bound:run_digest": {"byte_identical": true, "published": "sha256:433a819e7537d73aa484fda414b21c63b4efba4afc164d6f7b3fce0ba7a3f95c", "reproduced": "sha256:433a819e7537d73aa484fda414b21c63b4efba4afc164d6f7b3fce0ba7a3f95c"}, "commit_bound:scenario_trace_sha256": {"byte_identical": true, "published": "a97955f89591225e5f8a7216eab780bb8c86574e9bdc96b1743f21aa3a62a385", "reproduced": "a97955f89591225e5f8a7216eab780bb8c86574e9bdc96b1743f21aa3a62a385"}, "commit_bound:store_digest_runtime": {"byte_identical": true, "published": "sha256:2b417f11b3cc4bfde2e80a31d9a630a09b258d0c3396ab4f9da69ed462d37e79", "reproduced": "sha256:2b417f11b3cc4bfde2e80a31d9a630a09b258d0c3396ab4f9da69ed462d37e79"}, "commit_bound:store_digest_scenario": {"byte_identical": true, "published": "sha256:ebd26e2e7c7f6947ee0ce60cd6aa4b027f6fd490471af532d109ea292ef000ea", "reproduced": "sha256:ebd26e2e7c7f6947ee0ce60cd6aa4b027f6fd490471af532d109ea292ef000ea"}, "controls": {"effective_published": 17, "effective_reproduced": 17, "identical_classes": true}, "dataset": {"digests_match": true, "files": 3}, "digest:config_digest": {"identical": true, "published": "sha256:4f93519d8fc6b4040e82df6f6c495671ae5f510fe47ee246937a4400baa071fa", "reproduced": "sha256:4f93519d8fc6b4040e82df6f6c495671ae5f510fe47ee246937a4400baa071fa"}, "digest:ledger_digest_runtime": {"identical": true, "published": "sha256:6c6dc8d2c271a0186dfcf08706a16a97a5161aa5f57cd7d307b0ef9d7e407be1", "reproduced": "sha256:6c6dc8d2c271a0186dfcf08706a16a97a5161aa5f57cd7d307b0ef9d7e407be1"}, "digest:ledger_digest_scenario": {"identical": true, "published": "sha256:97d2766cbbcf5e048f77e052c7e3b69f2cfb39bf585b15a3a1abd444f5fd1a5c", "reproduced": "sha256:97d2766cbbcf5e048f77e052c7e3b69f2cfb39bf585b15a3a1abd444f5fd1a5c"}, "digest:lifecycle_csv_sha256": {"identical": true, "published": "f4b5004960b2aa3f7b35f2325e7f6823bee909d4fc65f8cea7d78078ad1a5090", "reproduced": "f4b5004960b2aa3f7b35f2325e7f6823bee909d4fc65f8cea7d78078ad1a5090"}, "digest:protocol_sha256": {"identical": true, "published": "9f349bda6f2dbbfea5aed8b27418ffd9d92d59cdf26068172fad5ba841d00c9a", "reproduced": "9f349bda6f2dbbfea5aed8b27418ffd9d92d59cdf26068172fad5ba841d00c9a"}, "file:METRICS.json": {"identical": true, "published": "11552b64225f001b2b47f77d3a71a632f8e5fa387eb4afa35496e82c26dcc90a", "reproduced": "11552b64225f001b2b47f77d3a71a632f8e5fa387eb4afa35496e82c26dcc90a"}, "file:ORDER_LIFECYCLE.csv": {"identical": true, "published": "f4b5004960b2aa3f7b35f2325e7f6823bee909d4fc65f8cea7d78078ad1a5090", "reproduced": "f4b5004960b2aa3f7b35f2325e7f6823bee909d4fc65f8cea7d78078ad1a5090"}, "file:ORDER_LIFECYCLE.json": {"identical": true, "published": "f6938b7409c7998e99cb53ca47fde2e81a3d42555c6ecdfaf1a5bbf6d6016322", "reproduced": "f6938b7409c7998e99cb53ca47fde2e81a3d42555c6ecdfaf1a5bbf6d6016322"}, "reconciliation": {"identical": true, "published": "PASS", "reproduced": "PASS"}, "tests": {"exit_codes": {"mypy": 0, "pytest_autonomous": 0, "pytest_integration": 0, "pytest_paper": 0, "ruff": 0}, "identical_exit_codes": true, "state_published": "PASS", "state_reproduced": "PASS"}, "trace:EXECUTION_TRACE.jsonl": {"byte_identical": true, "identical_after_commit_normalisation": true, "rows_published": 276, "rows_reproduced": 276}, "trace:SCENARIO_TRACE.jsonl": {"byte_identical": true, "identical_after_commit_normalisation": true, "rows_published": 32, "rows_reproduced": 32}, "verification": {"checks": 17, "identical_outcomes": true, "passed": ["V10_protocol_frozen", "V11_protocol_integrity", "V12_config_unchanged", "V13_no_secrets", "V14_scenario_states", "V15_reconciliation", "V16_paper_blocked", "V1_chain_integrity", "V1_scenario_chain", "V2_provenance_completeness", "V3_causality", "V4_state_machine", "V5_ledger_rebuild", "V6_ack_is_not_fill", "V7_live_disabled", "V8_determinism", "V9_negative_controls"]}}
- method: git worktree add --detach <commit>; dependencies installed from the committed uv.lock; the 003K dataset read from the checkout itself; every phase re-run there; the two directories then compared by this program

## Measurements (uninterpreted)

- runtime fills: `69`; scenario fills: `7`
- broker cost decomposition (closed trades): `9.27514543` execution, `42.275145` commissions
- positions open at end: `3`; mark: `final frozen bar close per symbol`
- These numbers are bookkeeping of an offline replay. They are not a profitability claim and were not used to select anything.

**FINAL STATUS: PARTIAL** — `TECHNICAL_EXECUTION_VALIDATION=PASS`, `PAPER_VALIDATION=BLOCKED_NOT_CONFIGURED`, `ECONOMIC_EDGE=NOT_EVALUATED`, `STRATEGY_PROMOTION=DENIED`, `LIVE=DISABLED`, `HOLDOUT=CLOSED`, `FALSE_SUCCESS=0`.
