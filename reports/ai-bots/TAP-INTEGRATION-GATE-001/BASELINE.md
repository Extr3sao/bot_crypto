# BASELINE — TAP-INTEGRATION-GATE-001

Taken before any gate code was written, from the delivery the gate has to stand on.

## 1. Where the work starts

| Item | Value |
| --- | --- |
| Branch | `gate/integration-001`, cut from `integ/supervisor-002` |
| Worktree | `C:/Users/GVLLFR0035/Downloads/ff-wt-gate001` |
| Start commit | `7d18140c` — "Record the independent verification at the delivering commit" |
| Merge base with `main` | `e67194e7` (6 commits behind; `main` itself not moved) |
| Historical lane | `codepaper/supervisor-001` @ `3b758e22`, 301 commits, **not merged** |
| Predecessor delivery | `TAP-SUPERVISOR-INTEGRATION-002`, verdict `NOT_READY`, `false_success = 0` |

`git merge-base --is-ancestor e67194e7 HEAD` succeeded and `git rev-list --count
e67194e7..HEAD` returned `6`: the branch sits on `main` plus the 002 delivery, which is the
candidate surface the gate has to judge.

## 2. The four entrypoints and their exact commands

| Role | File | SHA-256 | Command used |
| --- | --- | --- | --- |
| Supervisor producer | `scripts/paper_supervisor_campaign.py` | `efc6c9d8ff137ff89c9f048092c6d7ad5cf77f989412c04a90a316618042a46e` | `run --out DIR --crashes N`; `scenarios --out DIR --source-session DIR/session` |
| Supervisor verifier | `scripts/paper_supervisor_verify.py` | `3ce89ea787ba6820b2dfc1af857001c92c4af59e6a9e9b5fcd1edae9cc725cc9` | `--campaign DIR --out FILE` |
| Lock producer | `scripts/paper_lock_campaign.py` | `16d8e0679603dc4339fd665b6423c28a8be8dbc3af98b3d125e304661f7f6c76` | `run --out DIR --modes … --race-iterations …` |
| Lock verifier | `scripts/paper_lock_campaign_verify.py` | `20304e19763813e770eb96f8cc329fa30014366e7f500b2b4fb883d06a8a1607` | `--campaign DIR --out FILE` |

Both producers record `commit` in `CAMPAIGN.json`; both verifiers record `verifier_commit` in
their report, and both exit `0` only on a `PASS` verdict. Nothing in the pair compares those
two commits with each other or with `HEAD`.

## 3. The contracts, as published by the 002 delivery

### Lock campaign

* six crash iterations, `--modes` default `after, after, before, after, after, after`, so the
  sixth is a `BEFORE_CYCLE` crash that persists no cycle;
* two of those iterations also race two independent reclaimers over the abandoned lock
  (`--race-iterations` default `[2, 5]`), and exactly one reclaimer must win;
* one `RECOVERY.json` per iteration, `exit_code == 0`, `locks_after == []`;
* reclaim fences advance from one reclaim to the next (`2, 5, 8, 11, 14, 17` in the published
  run), one fence per reclaim row;
* verifier: **32 checks**, **9 mutations**, `false_success == 0`.

### Supervisor campaign

* one crash episode, five cycles, one resume (`RECOVERED`);
* `supervisor` `STOP_COMPLETED`, `live_enabled: false`, `mode: PAPER`;
* verifier: **33 checks**, of which `corrupt_evidence_was_refused` and
  `budget_was_exhausted_not_exceeded` are `not_applicable` unless `scenarios/SCENARIOS.json`
  exists — the published supervisor run had **31 applicable** and **12 mutations**.

The published artifacts, hashed:

| Artifact | SHA-256 |
| --- | --- |
| `evidence/REAL_CAMPAIGN_VERIFICATION.json` | `a13f1f0675036a4b1dbf7d316f52e71d87c42d1c512b35c6b560da0f251b0336` |
| `evidence/LOCK_CAMPAIGN_VERIFICATION_FULL.json` | `7d49261cfc466f1232914fc8c7e5483a7afabc64c424207f5cec8968e7b7a90f` |
| `tools/independent_verify.py` | `2214f2af7e65a359a23dc2deae14e03b6b449c4680e2a0ae201901fc081ec8bb` |

## 4. What the 002 verification actually proves, and what it does not

`evidence/INDEPENDENT_VERIFICATION.json`: `verdict PASS`, 9 of 9 claims (`G1`, `R1`, `C1`,
`L1`, `V1`, `V2`, `S1`, `S2`, `T1`), `false_success 0`, recorded `head 7f53c75a`.

It does not, and was never meant to, do the following — these are the gaps this delivery
closes:

1. **It is tied to one workstation.** `independent_verify.py` hardcodes
   `C:/Users/GVLLFR0035/Downloads/ff-campaign-002` and `…/ff-campaign-002-controls`, and reads
   `evidence/LOCK_CAMPAIGN_FULL2`. On a clean checkout of the same commit those paths do not
   exist, so the claims cannot be re-derived there.
2. **It judges one delivery, not a candidate.** Its `R1`/`T1`/`G1` claims are about the 002
   report; nothing binds the campaigns to whatever commit a future integration selects.
3. **Nothing ran it automatically.** The three workflows present were `ci.yml` (four baseline
   status checks), `recovery-determinism.yml` and `cost-barrier-gate.yml`; none of them runs
   either PAPER campaign.
4. **Two supervisor checks were `not_applicable`** because the published campaign never ran
   the negative scenarios, so the corrupt-evidence and exhausted-budget behaviour of the
   supervisor is asserted only by unit tests.
5. **Evidence could not be told apart from a fixture.** No mechanism compared `CAMPAIGN.json
   .commit`, the verifier's `verifier_commit`, and `HEAD`; a report from an older tree would
   have looked exactly like a fresh one.

## 5. CI mechanism available

`ci.yml`, `recovery-determinism.yml` and `cost-barrier-gate.yml` run on `ubuntu-latest` with
`uv sync`, keep their evidence as build artifacts, and contain no `continue-on-error`. The
four required status checks named in `quality/release-gates.md` are the `ci.yml` jobs. So the
CI system can host a gate; what it cannot do from inside the repository is make one required.

`gh` is not installed in this environment and no API token is available, so the effective
branch-protection state of `Extr3sao/bot_crypto` cannot be read or changed from here. The
gate therefore reports `required_check: false` with state `GOVERNANCE_BLOCKED` instead of
claiming an enforcement nobody in this environment verified.

## 6. Runtime budget measured from the published runs

| Step | Wall clock in the 002 evidence |
| --- | --- |
| supervisor campaign (1 crash, 5 cycles) | `16:51:25Z → 16:56:32Z` ≈ 5 min |
| lock campaign (6 crashes, 2 races, 17 cycles) | `10:26:47Z → 10:43:23Z` ≈ 17 min |

The gate's timeouts are set from these with room to spare (45 min / 60 min per campaign,
30 min per verifier), and the CI job allows 75 minutes.
