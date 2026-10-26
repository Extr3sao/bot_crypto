# FINAL REPORT — TAP-INTEGRATION-GATE-001

**Verdict: `IMPLEMENTED_VERIFIED`**
Candidate commit `9a420ff18179c1f196221495aba5fdd2a81f5073`, branch `gate/integration-001`.
Gate `PASS` (15/15 steps), independent review `PASS` (9/9 checks, 8/8 negative controls),
`false_success = 0`. **Required status check imposed: NO — `GOVERNANCE_BLOCKED`.**

---

## 1. What changed for integration

Before this delivery, a `PASS` on the supervisor and lock campaigns was something a person
asserted. The two campaigns were run by hand, their verifiers were run by hand, and the claim
that the evidence belonged to a commit rested on the person remembering which commit it was.
The 002 delivery even shipped a verifier that hardcoded `C:/Users/…/ff-campaign-002`, so its
claims could not be re-derived anywhere else.

Now there is one command:

```
python scripts/tap_integration_gate.py run --out <dir outside the repository>
```

It refuses a dirty tree, captures the commit, runs the supervisor campaign with its crash and
its two negative scenarios, runs the lock campaign with its six crash sites and its two
reclaim races, runs both campaign verifiers, runs an independent audit that re-derives both
campaigns from their own bytes, judges every report against its published floors instead of
its own verdict, re-reads `HEAD` after the work, and writes one report plus a SHA-256
manifest. `verify` re-derives a previous run, so evidence from another commit, another
contract, or an edited report is refused rather than trusted.

## 2. The evidence, in the order it was produced

| Step | Result |
| --- | --- |
| Gate run on `9a420ff1` | `PASS`, 15/15 steps, 258 files hashed, 21.5 min |
| Supervisor campaign | 5 cycles, 1 reclaim, 13 rows, `RECOVERED`, 2 scenarios, 0 locks, 0 live orders |
| Lock campaign | 6 iterations, 17 cycles, 64 rows, reclaim fences `2, 5, 8, 11, 14, 17`, 2 races with one winner each, 0 locks, 0 live orders |
| Supervisor verifier | 33 checks, all applicable, 12/12 mutations detected, `false_success 0` |
| Lock verifier | 32 checks, 9/9 mutations detected, `false_success 0` |
| Independent audit | `C1`, `L1`, `S1`, `S2`, `V1` all `PASS` |
| Reviewer | 9/9 checks; 8/8 controls rejected old evidence, a moved commit, a missing recovery, edited evidence, a shortened campaign, a weakened report and a single failing verifier |
| `verify` at the candidate commit | `PASS`, 258 manifest files, all five re-derived judgements `PASS` |

## 3. What this does *not* say

* **It is not a required check.** The workflow `.github/workflows/integration-gate.yml` exists
  and can be selected as one, but `gh` is not installed here and no API token is available, so
  the branch-protection state of `Extr3sao/bot_crypto` was neither read nor changed. The gate
  records `required_check: false` rather than claiming enforcement.
* **It has not run on a GitHub runner.** The wiring is checked statically
  (`R10_CI_WIRING`); the gate executed locally on Windows from a clean tree. A Linux run is
  the obvious next data point, because the supervisor entrypoint's process killing is the most
  platform-sensitive part.
* **It is not profitability, and it is not an admission.** `PAPER_ADMISSION` stays `NO_GO`.
  A green gate means the campaigns ran, recovered, left nothing behind and were judged
  honestly — nothing about making money.
* **`G1` stays `OPEN_SIGNOFF`.** The weekly loss veto now rolls at UTC Monday 00:00; the gate
  does not sign that loosening, and signing it is not a verification task.
* **The full unit suite was not run** in this worktree. The new tests (12) and the static
  checks were.

## 4. Two runs that did not count, kept on purpose

Run 001 was aborted: the gate wrote the scenario record to the campaign root instead of
`<campaign>/scenarios/`, so the verifier left two checks `not_applicable` while every exit
code was 0. That is exactly the shape of a false success, and the gate's contract judgement
would have caught it; the log showed it first.

Run 002 returned `PASS` and the reviewer **refused it**: the runner's own shell log had been
written inside the evidence directory and appended to after the manifest was computed, so
`R2_MANIFEST` reported `changed=['GATE_STDOUT.log', 'RUN_STARTED.txt']`. Both are recorded in
[RUN_REPORT.md](RUN_REPORT.md) §5. Keeping them is the point: the machinery is only worth
something if it can refuse the run that produced it.

## 5. Where to look

* [BASELINE.md](BASELINE.md) — what existed before, with hashes and the five gaps.
* [GATE_MATRIX.md](GATE_MATRIX.md) — the fifteen steps, the contract numbers, the controls,
  and the seven acceptance criteria of the mission.
* [RUN_REPORT.md](RUN_REPORT.md) / [RUN_REPORT.json](RUN_REPORT.json) — commands, durations,
  exit codes, rework, blockers.
* [REVIEW.json](REVIEW.json) — the independent review, including the eight controls.
* `evidence/` — the gate report, the campaign audit, both verifier reports, both campaigns,
  every step log, and `EVIDENCE_MANIFEST.json` over 258 files.
* `scripts/tap_integration_gate.py`, `scripts/tap_gate_campaign_audit.py`,
  `tools/review_gate.py` — builder, independent auditor, independent reviewer; none imports
  another.
