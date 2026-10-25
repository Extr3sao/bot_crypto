# RUN REPORT — TAP-INTEGRATION-GATE-001

**Branch:** `gate/integration-001`, worktree `C:/Users/GVLLFR0035/Downloads/ff-wt-gate001`
**Candidate commit:** `9a420ff18179c1f196221495aba5fdd2a81f5073`
**Base:** `integ/supervisor-002` @ `7d18140c`, on `main` @ `e67194e7` (unchanged)
**Verdict:** `IMPLEMENTED_VERIFIED` — gate `PASS` (15/15), review `PASS` (9/9 checks, 8/8
controls), `false_success = 0`
**Required check imposed:** **NO** — `GOVERNANCE_BLOCKED`

---

## 1. What this delivery adds

| File | Role |
| --- | --- |
| `scripts/tap_integration_gate.py` | the gate: captures the commit, refuses a dirty tree, runs both campaigns, judges both verifier reports, re-reads HEAD, writes the report and the manifest; `verify` re-derives a previous run; `preflight` is the fast, non-certifying check |
| `scripts/tap_gate_campaign_audit.py` | independent campaign audit: own chain re-hash, `C1`/`L1`/`S1`/`S2`/`V1`, imports nothing from `trading_bot` or from either verifier |
| `reports/ai-bots/TAP-INTEGRATION-GATE-001/tools/review_gate.py` | the reviewer: re-walks both campaigns with its own chain code, re-derives the verdict, and runs eight hermetic negative controls; imports nothing from the gate |
| `tests/unit/ops/test_tap_integration_gate.py` | 12 tests over the judging rules, the evidence-only commit rule (real git), and the chain re-derivation |
| `.github/workflows/integration-gate.yml` | preflight job + gate job + reviewer step; no `continue-on-error` |
| `.gitignore` | re-opens `reports/ai-bots/TAP-INTEGRATION-GATE-001/` so the evidence can be versioned |

No change to `src/`, `config/`, risk, sizing, execution or the admission ledger:
`git diff --stat 7d18140c..HEAD -- src config` is empty.

## 2. Commits

| Commit | Content |
| --- | --- |
| `591fbe6b` | the gate, the auditor, the reviewer, 12 tests, the workflow, the `.gitignore` re-open |
| `9a420ff1` | scenario record written to `<campaign>/scenarios/` (the verifier's path); reviewer stops treating YAML comments as steps |
| *this delivery* | `BASELINE.md`, `GATE_MATRIX.md`, `RUN_REPORT.*`, `FINAL_REPORT.md`, `REVIEW.json`, `evidence/` (258 files) |

`git rev-list --merges 7d18140c..HEAD` is empty: nothing was merged, and the 301-commit lane
was not touched.

## 3. Exact commands and their exit codes

| Command | Exit | Duration |
| --- | ---: | ---: |
| `python scripts/tap_integration_gate.py run --out <evidence>` | **0** | **1290.8 s of steps** |
| `python reports/…/tools/review_gate.py --evidence <evidence> --out REVIEW.json` | **0** | 8.16 s |
| `python scripts/tap_integration_gate.py verify --evidence <evidence>` | 0 | 0.46 s |
| `python scripts/tap_integration_gate.py preflight` (clean tree) | 0 | see `POST_DELIVERY_VERIFY.json` |
| `python scripts/tap_integration_gate.py preflight` (dirty tree, uncommitted evidence) | **1** | 1.27 s — refused the dirty tree, as designed |
| `pytest tests/unit/ops/test_tap_integration_gate.py -q` | 0 | 1.2 s (12 passed) |
| `ruff check` / `ruff format --check` on the new files | 0 | – |
| `mypy` on the three new modules | 0 | – |

The gate's own step durations, in seconds: supervisor campaign 266.9, scenarios 13.6,
supervisor verifier 5.6, lock campaign 999.8, lock verifier 4.4, audit 0.6.

### Static checks, and their pre-existing red state

`ruff check .` reports **136** errors and `ruff format --check .` would reformat **484** files
at `9a420ff1`; the same ruff 0.15.20 binary reports **130** and **444** on `main`
(`e67194e7`). The four files this delivery adds pass both checks individually and account for
**none** of those findings. `mypy .` reports **338** errors in 46 files, and none is in the new
code (`grep` over the log: 0 matches). The repo-wide gates were already red on `main`; this
delivery neither inherited nor fixed that, and does not claim CI is green because of it.

## 4. Results

* Gate verdict `PASS`, `certifies: true`, 15 of 15 steps `PASS`, no `NOT_TESTED`, no
  `BLOCKED`, `false_success: 0`. Manifest: **258 files**.
* Both campaigns ran on `9a420ff1`: `CAMPAIGN.json.commit`, both `verifier_commit` fields and
  `HEAD` are the same SHA (`J4_CANDIDATE_BINDING` PASS).
* Lock campaign: 6 iterations, 17 cycles, 6 reclaims at fences `2, 5, 8, 11, 14, 17`,
  64 stream rows, 12 starts, 2 races with exactly one winner each, 0 locks, 0 live orders.
* Supervisor campaign: 5 cycles, 1 reclaim, 1 resumed start, 13 rows, `RECOVERED`,
  `STOP_COMPLETED`, scenarios present, **0 not-applicable checks**.
* Verifiers: supervisor 33 checks / 12 mutations, lock 32 checks / 9 mutations, all detected,
  no invalid mutation, `false_success 0`.
* Audit: `C1`, `L1`, `S1`, `S2`, `V1` all `PASS`.
* Reviewer: 9 of 9 checks, 8 of 8 controls rejected what they must reject, `false_success 0`.
* Commit stability: one commit observed for the whole run (`9a420ff1`), tree clean at both
  ends.

Full matrix: [GATE_MATRIX.md](GATE_MATRIX.md). Raw: `evidence/GATE_REPORT.json`,
`evidence/CAMPAIGN_AUDIT.json`, `REVIEW.json`.

## 5. Rework, and the two runs that did not count

Both were caught by the machinery this delivery adds, not by inspection.

1. **Run 001 (12:35Z → 12:43Z, aborted).** The gate passed `--out <campaign>` to the
   supervisor's `scenarios` command. The campaign wrote `SCENARIOS.json` at the campaign root;
   the verifier reads `<campaign>/scenarios/SCENARIOS.json`, so its two scenario checks stayed
   `not_applicable` while every exit code was 0. The gate's own contract judgement would have
   failed the run (`not_applicable` must be empty), but it was aborted as soon as the log
   showed it. Fix: commit `9a420ff1`.
2. **Run 002 (12:44Z → 13:08Z, rejected).** The gate returned `PASS`, but the runner's shell
   log and a start marker had been written **inside** the evidence directory and then
   appended to after the manifest was computed. The reviewer refused it:
   `MANIFEST_MISMATCH … changed=['GATE_STDOUT.log', 'RUN_STARTED.txt']`. That is the correct
   behaviour — evidence is immutable once hashed — and the mistake was in how the run was
   driven, not in the gate. Run 003 kept every log outside the evidence directory.

Keeping run 002's rejection is deliberate: it is the proof that the manifest is load-bearing,
and that a `PASS` from the gate is not accepted by the reviewer on its own word.

## 6. Reproducibility between runs

Runs 002 and 003 produced the same shape on the same commit:

| Quantity | Run 002 | Run 003 |
| --- | ---: | ---: |
| Lock iterations / cycles / rows | 6 / 17 / 64 | 6 / 17 / 64 |
| Lock reclaim fences | 2, 5, 8, 11, 14, 17 | 2, 5, 8, 11, 14, 17 |
| Supervisor cycles / rows | 5 / 13 | 5 / 13 |
| Supervisor checks / lock checks | 33 / 32 | 33 / 32 |
| Supervisor campaign duration | 317.5 s | 266.9 s |

The hashes differ (PIDs, timestamps, tokens are inside the streams); the facts the contract
asserts are identical.

## 7. Blockers and limitations

* **`GOVERNANCE_BLOCKED`** — the workflow can be invoked and can be selected as a required
  status check, but it is **not** imposed today. `gh` is not installed here and no API token
  is available, so the branch-protection state of `Extr3sao/bot_crypto` could not be read or
  changed. The gate reports `required_check: false` rather than claiming enforcement.
* **No GitHub runner executed the workflow.** CI wiring is static and checked by
  `R10_CI_WIRING`; the gate was executed locally, on Windows, from a clean tree.
* **`G1` stays `OPEN_SIGNOFF`.** The gate does not sign the weekly-loss-veto change; that
  signature is still the 002 blocker.
* **`PAPER_ADMISSION = NO_GO`.** Nothing here admits a strategy, and a green gate is not
  profitability.
* The audit and verifier reports embed absolute paths of the host that produced them
  (`campaigns.*`); every hash and every chain is relative, so verification does not depend on
  those paths, but the JSON is not byte-identical across hosts.
* The full `pytest tests/unit` suite was not run in this worktree (subsets alone take 27+
  minutes on this machine).

## 8. Next work

1. A repository administrator turns `Integration gate (campaigns on this commit)` into a
   required status check, and the report's `imposition.state` moves from `GOVERNANCE_BLOCKED`
   to `ENFORCED` with the settings page quoted as evidence.
2. One run of the same workflow on `ubuntu-latest` to confirm the campaigns behave the same on
   Linux (the supervisor entrypoint's kill/`taskkill` split is the part most likely to differ).
3. `G1`: the risk-manager signs, or the weekly-veto roll is reverted, and 002 can move from
   `NOT_READY` to `READY`.
