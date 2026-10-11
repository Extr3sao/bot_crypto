# COST_BARRIER_ADVERSARIAL_REPORT

- gate under test: **current working tree at a551fdc** (`sha256_lf 6ff2793aee81b88d...`, revision `a551fdc8dba7`)
- status: **EVALUATED** (substrate `reports/strategy-baseline/COST_BARRIER.json` present)
- attacks: **17/17 detected**, 0 evaded, 0 invalid, 0 leg(s) failed
- generated `2026-10-11T12:52:42Z` · python `3.11.15` · `win32`

Each attack runs against a throwaway sandbox built from the real files; the published artefacts and inputs are never touched. `DETECTED` means the gate's own published state flagged the run for that mode; a mutation that leaves the tree green is recorded as an escape rather than smoothed over.

| attack | requirement | input | expected | observed | detected |
| --- | --- | --- | --- | --- | --- |
| A01 alter a published number without touching its hash | 1 | `data/recovery/COST_BARRIER_EXPLORER.json` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A02 alter a published number and recompute its hash honestly | 2 | `data/recovery/COST_BARRIER_EXPLORER.json` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A03 alter the cost model | 3 | `src/trading_bot/research/microstructure/cost_model_v3.py` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A04 alter the admission ledger | 4 | `config/strategy_admission.json` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A05 substitute a pin for a valid one from another version | 5 | `data/recovery/COST_BARRIER_EXPLORER.json` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A06 remove a required input | 6 | `reports/strategy-baseline/COST_BARRIER.json` | full:BLOCKED, check:PARTIAL | full:BLOCKED_MISSING_INPUT, check:CHECK_ONLY_WITH_ADVISORIES | yes |
| A07 alter an unpinned producer | 7 | `scripts/cost_barrier.py` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A08 modify the builder and a published result together | 8 | `scripts/cost_barrier_explorer.py` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A09 modify a published verdict | 9 | `data/recovery/COST_BARRIER_EXPLORER.json` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A10 manipulate the negative-control results | 10 | `data/recovery/COST_BARRIER_VERIFICATION.json` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A11 introduce a legitimate CRLF/LF difference | 11 | `reports/strategy-baseline/COST_BARRIER.json` | full:CLEAN, check:PARTIAL | full:FULL_REPRODUCTION_PASS, check:CHECK_ONLY_PASS | yes |
| A12 combine a real content change with an end-of-line change | 12 | `reports/strategy-baseline/COST_BARRIER.json` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A13 disable the checks through configuration or environment | 13 | `environment + config files` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A14 alter dependency paths so CI stops activating | 14 | `src/trading_bot/research/microstructure/cost_model_v3.py` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A17 prune the CI path filters instead of the code | extra | `.github/workflows/cost-barrier-gate.yml` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |
| A15 make a check-only result satisfy a full gate | 15 | `the gate's own report` | full:CLEAN, check:PARTIAL | full:FULL_REPRODUCTION_PASS, check:CHECK_ONLY_PASS | yes |
| A16 alter a derived market-horizon number and recompute the hash honestly | extra | `data/recovery/COST_BARRIER_EXPLORER.json` | full:FLAGGED, check:FLAGGED | full:INTEGRITY_FAILURE, check:INTEGRITY_FAILURE | yes |

## Detail

### A01 — alter a published number without touching its hash

- **input**: `data/recovery/COST_BARRIER_EXPLORER.json`
- **mutation**: cells[0].zero_cost_gross_bps moved to 3.178; payload_sha256 left as published
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2)
- **detected**: yes
- **evidence**: [full] artifact:explorer_self_hash_and_checks: payload_sha256 da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6 != recomputed 792e03432572312ada17e9a569ae346867ef178fd84875eceaf6b284a1bbef8b; [check] artifact:explorer_self_hash_and_checks: payload_sha256 da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6 != recomputed 792e03432572312ada17e9a569ae346867ef178fd84875eceaf6b284a1bbef8b
- **why it should work**: the artefact's own self-hash no longer recomputes, so no re-run is needed to see it

### A02 — alter a published number and recompute its hash honestly

- **input**: `data/recovery/COST_BARRIER_EXPLORER.json`
- **mutation**: cells[0].zero_cost_gross_bps moved to 3.178 (+5 bps) with payload_sha256 recomputed honestly
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2)
- **detected**: yes
- **evidence**: [full] artifact:verification_attests_the_explorer: no control demonstrates a body mutation caught by recomputation; 12 control signal(s) do not form a pair around the committed hash 792e03432572312ada17e9a569ae346867ef178fd84875eceaf6b284a1bbef8b: [('da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6', '46f1f8d713ceac9bf90a32f23d9ba7a639d0e03695ced78745f5e6d0dd85cd63'), ('da4ab06129c927eb0d; [check] artifact:verification_attests_the_explorer: no control demonstrates a body mutation caught by recomputation; 12 control signal(s) do not form a pair around the committed hash 792e03432572312ada17e9a569ae346867ef178fd84875eceaf6b284a1bbef8b: [('da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6', '46f1f8d713ceac9bf90a32f23d9ba7a639d0e03695ced78745f5e6d0dd85cd63'), ('da4ab06129c927eb0d
- **why it should work**: self-consistency alone cannot help: the number has to survive re-derivation

### A03 — alter the cost model

- **input**: `src/trading_bot/research/microstructure/cost_model_v3.py`
- **mutation**: one fee literal in the executable cost model changed (5.0 -> 4.5)
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 3); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2)
- **detected**: yes
- **evidence**: [full] inputs:published_pins_match_the_declared_sources: 9/9 present; pinned: 4 exact, 0 line-ending-only, 1 drifted; src/trading_bot/research/microstructure/cost_model_v3.py content drift (pin bc7e27538b65b7f3...); [check] inputs:published_pins_match_the_declared_sources: 9/9 present; pinned: 4 exact, 0 line-ending-only, 1 drifted; src/trading_bot/research/microstructure/cost_model_v3.py content drift (pin bc7e27538b65b7f3...)
- **why it should work**: the artefact pins the executable module it evaluated, byte for byte

### A04 — alter the admission ledger

- **input**: `config/strategy_admission.json`
- **mutation**: the first admission-ledger entry is marked admitted_for_paper
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 1); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 1)
- **detected**: yes
- **evidence**: [full] inputs:published_pins_match_the_declared_sources: 9/9 present; pinned: 4 exact, 0 line-ending-only, 1 drifted; config/strategy_admission.json content drift (pin 6c4dd0be1fc2fff2...); [check] inputs:published_pins_match_the_declared_sources: 9/9 present; pinned: 4 exact, 0 line-ending-only, 1 drifted; config/strategy_admission.json content drift (pin 6c4dd0be1fc2fff2...)
- **why it should work**: same pin discipline as the cost model

### A05 — substitute a pin for a valid one from another version

- **input**: `data/recovery/COST_BARRIER_EXPLORER.json`
- **mutation**: the ledger's pin is replaced by a genuine digest belonging to another file (the WP-3 audit) - valid hash, wrong artefact
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 1); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 1)
- **detected**: yes
- **evidence**: [full] inputs:published_pins_match_the_declared_sources: 9/9 present; pinned: 4 exact, 0 line-ending-only, 1 drifted; config/strategy_admission.json content drift (pin 31fc6d4f57248bed...); [check] inputs:published_pins_match_the_declared_sources: 9/9 present; pinned: 4 exact, 0 line-ending-only, 1 drifted; config/strategy_admission.json content drift (pin 31fc6d4f57248bed...)
- **why it should work**: the pin is compared against the bytes of the file it cites, not against its shape

### A06 — remove a required input

- **input**: `reports/strategy-baseline/COST_BARRIER.json`
- **mutation**: reports/strategy-baseline/COST_BARRIER.json removed: the gitignored input the reproduction needs is deleted, so a full reproduction must become impossible
- **expected**: {'full': 'BLOCKED', 'check': 'PARTIAL'}
- **observed**: `full` → `BLOCKED_MISSING_INPUT` (exit 3, checks_failed 4); `check` → `CHECK_ONLY_WITH_ADVISORIES` (exit 2, checks_failed 0)
- **detected**: yes
- **evidence**: [full] full reproduction requires every declared input; absent: reports/strategy-baseline/COST_BARRIER.json. Materialize the generated inputs (the market-horizon report is produced locally from reports/strategy-baseline/data/) and re-run.; [check] status CHECK_ONLY_WITH_ADVISORIES (exit 2)
- **why it should work**: full mode refuses to claim a reproduction it cannot run; check mode says so and stays partial

### A07 — alter an unpinned producer

- **input**: `scripts/cost_barrier.py`
- **mutation**: scripts/cost_barrier.py (the market-horizon producer) edited: the BASE line 12.0 -> 11.0. No published artefact changes, so nothing but a producer pin can see it
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 1); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 1)
- **detected**: yes
- **evidence**: [full] producers:digests_match_the_pinned_manifest: scripts/cost_barrier.py drifted from the pinned producer digest; [check] producers:digests_match_the_pinned_manifest: scripts/cost_barrier.py drifted from the pinned producer digest
- **why it should work**: the producer digest manifest is what closes this; without it nothing in the tree changes

### A08 — modify the builder and a published result together

- **input**: `scripts/cost_barrier_explorer.py`
- **mutation**: the builder is edited (OPS_PER_DAY 3.0 -> 4.0) and then re-run so the published artefact and its verification document are regenerated from it: builder and result agree with each other, so only a producer pin can object
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 1); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 1)
- **detected**: yes
- **evidence**: [full] producers:digests_match_the_pinned_manifest: scripts/cost_barrier_explorer.py drifted from the pinned producer digest; [check] producers:digests_match_the_pinned_manifest: scripts/cost_barrier_explorer.py drifted from the pinned producer digest
- **why it should work**: a coherent lie passes every self-consistency check; the producer pin is the only witness

### A09 — modify a published verdict

- **input**: `data/recovery/COST_BARRIER_EXPLORER.json`
- **mutation**: the published horizon verdict is rewritten from HORIZON_INVARIANT_AT_ZERO_FUNDING to HORIZON_DEPENDENT_AT_ZERO_FUNDING with the self-hash recomputed
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2)
- **detected**: yes
- **evidence**: [full] artifact:verification_attests_the_explorer: no control demonstrates a body mutation caught by recomputation; no control demonstrates a self-hash tamper caught by recomputation; 13 control signal(s) do not form a pair around the committed hash dfd8461f5f82d8b8a1300ea50a043a340b85cf6660d7473b7134ea807e8d3d93: [('da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6', '792e03432572312ada17; [check] artifact:verification_attests_the_explorer: no control demonstrates a body mutation caught by recomputation; no control demonstrates a self-hash tamper caught by recomputation; 13 control signal(s) do not form a pair around the committed hash dfd8461f5f82d8b8a1300ea50a043a340b85cf6660d7473b7134ea807e8d3d93: [('da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6', '792e03432572312ada17
- **why it should work**: verdicts are re-derived from the audit and the cost model by the independent verifier

### A10 — manipulate the negative-control results

- **input**: `data/recovery/COST_BARRIER_VERIFICATION.json`
- **mutation**: every negative control in the verification document rewritten to claim detection with a fabricated signal
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2)
- **detected**: yes
- **evidence**: [full] artifact:verification_attests_the_explorer: no control demonstrates a self-hash tamper caught by recomputation; [check] artifact:verification_attests_the_explorer: no control demonstrates a self-hash tamper caught by recomputation
- **why it should work**: the gate re-runs the verifier, and a control ledger that no longer matches the fresh one is document drift

### A11 — introduce a legitimate CRLF/LF difference

- **input**: `reports/strategy-baseline/COST_BARRIER.json`
- **mutation**: the pinned market-horizon input re-encoded with LF line endings only (legitimate checkout difference)
- **expected**: {'full': 'CLEAN', 'check': 'PARTIAL'}
- **observed**: `full` → `FULL_REPRODUCTION_PASS` (exit 0, checks_failed 0); `check` → `CHECK_ONLY_PASS` (exit 2, checks_failed 0)
- **detected**: yes
- **evidence**: [full] status FULL_REPRODUCTION_PASS (exit 0); [check] status CHECK_ONLY_PASS (exit 2)
- **why it should work**: positive control: a checkout convention is not drift, and must not be reported as one

### A12 — combine a real content change with an end-of-line change

- **input**: `reports/strategy-baseline/COST_BARRIER.json`
- **mutation**: one published median moved (27.51 -> 27.52) and the file re-encoded to LF in the same edit
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 4); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2)
- **detected**: yes
- **evidence**: [full] inputs:published_pins_match_the_declared_sources: 9/9 present; pinned: 4 exact, 0 line-ending-only, 1 drifted; reports/strategy-baseline/COST_BARRIER.json content drift (pin 2437f446051d97ec...); [check] inputs:published_pins_match_the_declared_sources: 9/9 present; pinned: 4 exact, 0 line-ending-only, 1 drifted; reports/strategy-baseline/COST_BARRIER.json content drift (pin 2437f446051d97ec...)
- **why it should work**: end-of-line tolerance must not become a laundering service for content

### A13 — disable the checks through configuration or environment

- **input**: `environment + config files`
- **mutation**: a config file and a skip marker asking the gate to stand down with each hostile environment variable set, on a tree whose published number was already moved
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 2)
- **detected**: yes
- **evidence**: [full] artifact:verification_attests_the_explorer: no control demonstrates a body mutation caught by recomputation; 12 control signal(s) do not form a pair around the committed hash 792e03432572312ada17e9a569ae346867ef178fd84875eceaf6b284a1bbef8b: [('da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6', '46f1f8d713ceac9bf90a32f23d9ba7a639d0e03695ced78745f5e6d0dd85cd63'), ('da4ab06129c927eb0d; [check] artifact:verification_attests_the_explorer: no control demonstrates a body mutation caught by recomputation; 12 control signal(s) do not form a pair around the committed hash 792e03432572312ada17e9a569ae346867ef178fd84875eceaf6b284a1bbef8b: [('da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6', '46f1f8d713ceac9bf90a32f23d9ba7a639d0e03695ced78745f5e6d0dd85cd63'), ('da4ab06129c927eb0d
- **leg `environment_and_config_change_no_verdict_in_either_direction`**: clean+hostile FULL_REPRODUCTION_PASS/exit 0; defective plain INTEGRITY_FAILURE/exit 5 vs hostile INTEGRITY_FAILURE/exit 5
- **why it should work**: the tree also carries a moved number, so a run that stands down is visible; the hostile environment is applied to a mutation that is already flagged

### A14 — alter dependency paths so CI stops activating

- **input**: `src/trading_bot/research/microstructure/cost_model_v3.py`
- **mutation**: the executable cost model is moved to src/trading_bot/research/microstructure/costs/cost_model_v3.py and everything that cites it is rewired (explorer, verifier, the gate's declared inputs, the artefact's pin and the producer manifest) - but the workflow's path filters are not
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 5); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 3)
- **detected**: yes
- **evidence**: [full] producers:digests_match_the_pinned_manifest: scripts/cost_barrier_verify.py drifted from the pinned producer digest; [check] producers:digests_match_the_pinned_manifest: scripts/cost_barrier_verify.py drifted from the pinned producer digest
- **why it should work**: the gate checks that its activation contract still covers every declared input, and the relocated path is not in the filters

### A17 — prune the CI path filters instead of the code

- **input**: `.github/workflows/cost-barrier-gate.yml`
- **mutation**: src/trading_bot/research/microstructure/cost_model_v3.py removed from both path filters, so a change to the executable cost model would no longer activate the workflow that is supposed to catch it
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 1); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 1)
- **detected**: yes
- **evidence**: [full] ci:activation_contract_covers_every_declared_input: a change to ['src/trading_bot/research/microstructure/cost_model_v3.py'] would not activate the workflow on push; a change to ['src/trading_bot/research/microstructure/cost_model_v3.py'] would not activate the workflow on pull_request; [check] ci:activation_contract_covers_every_declared_input: a change to ['src/trading_bot/research/microstructure/cost_model_v3.py'] would not activate the workflow on push; a change to ['src/trading_bot/research/microstructure/cost_model_v3.py'] would not activate the workflow on pull_request
- **why it should work**: same activation contract, attacked from the workflow side

### A15 — make a check-only result satisfy a full gate

- **input**: `the gate's own report`
- **mutation**: a check-only report (mode=check, no builder run) rewritten to say FULL_REPRODUCTION_PASS with the certification flag flipped
- **expected**: {'full': 'CLEAN', 'check': 'PARTIAL'}
- **observed**: `full` → `FULL_REPRODUCTION_PASS` (exit 0, checks_failed 0); `check` → `CHECK_ONLY_PASS` (exit 2, checks_failed 0)
- **detected**: yes
- **evidence**: [full] status FULL_REPRODUCTION_PASS (exit 0); [check] status CHECK_ONLY_PASS (exit 2)
- **leg `the_certifier_refuses_a_partial_run_dressed_as_full`**: certifier verdict FAILED for a mode=check report claiming FULL_REPRODUCTION_PASS: ['the evidence bundle was not verified for this candidate, so the inputs the reproduction consumed are not accounted for', "a FULL_REPRODUCTION_PASS report claims mode 'check'"]
- **why it should work**: the undressed run is partial by contract; the dressed one is kept as evidence and handed to the certifier, which must refuse it

### A16 — alter a derived market-horizon number and recompute the hash honestly

- **input**: `data/recovery/COST_BARRIER_EXPLORER.json`
- **mutation**: horizon.market_horizon.rows[1h/SOL].hours_to_BASE -> 99.0 with payload_sha256 recomputed honestly (the independent verifier never reads that source)
- **expected**: {'full': 'FLAGGED', 'check': 'FLAGGED'}
- **observed**: `full` → `INTEGRITY_FAILURE` (exit 5, checks_failed 3); `check` → `INTEGRITY_FAILURE` (exit 5, checks_failed 3)
- **detected**: yes
- **evidence**: [full] artifact:verification_attests_the_explorer: no control demonstrates a body mutation caught by recomputation; no control demonstrates a self-hash tamper caught by recomputation; 13 control signal(s) do not form a pair around the committed hash dd3abc392e430125c9a29c35464f69bfa7c4311b402c26f60c2d990b47acb6a1: [('da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6', '792e03432572312ada17; [check] artifact:verification_attests_the_explorer: no control demonstrates a body mutation caught by recomputation; no control demonstrates a self-hash tamper caught by recomputation; 13 control signal(s) do not form a pair around the committed hash dd3abc392e430125c9a29c35464f69bfa7c4311b402c26f60c2d990b47acb6a1: [('da4ab06129c927eb0dfccf820bc0db2673321b031cef77e0317594bb82c19fc6', '792e03432572312ada17
- **why it should work**: the section the independent verifier never reads is re-derived by the gate from the pinned source
