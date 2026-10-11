# FINAL REPORT — WP-8 / RECOVERY DETERMINISM, STATE AUTHORITY & CLEAN CHECKOUT CERTIFICATION

> Deliverables of this work package: this report, [RUN_REPORT.md](RUN_REPORT.md) + [.json](RUN_REPORT.json),
> [RECOVERY_RUNTIME_AUTHORITY_MAP.md](RECOVERY_RUNTIME_AUTHORITY_MAP.md),
> [CAMPAIGN_STATE_DETERMINISM_AUDIT.md](CAMPAIGN_STATE_DETERMINISM_AUDIT.md),
> [ACTIVE_RECOVERY_REPRODUCIBILITY.md](ACTIVE_RECOVERY_REPRODUCIBILITY.md),
> [CLEAN_CHECKOUT_REHEARSAL_REPORT.json](CLEAN_CHECKOUT_REHEARSAL_REPORT.json) + [.md](CLEAN_CHECKOUT_REHEARSAL_REPORT.md),
> and the verifier's own record [../INDEPENDENT_VERIFICATION.json](../INDEPENDENT_VERIFICATION.json).
> Builder ≠ verifier: the state view and the audit are two builders, a third program
> (`scripts/recovery_verify.py`) re-derives their numbers without importing either, and a
> fourth (`scripts/clean_checkout_rehearsal.py`) rebuilds everything in a detached worktree
> of the commit and asks the verifier to confirm it there.
>
> **Revision.** This report describes the sequence `e670d2a → 3f8d646 → 306939c → 9b9a4b8 →
> 6c3af00 → 4b32d97 → 66dc3de → 279d73f → 6cac3c6 → 272df9f → e07ce6c`, with the record
> commit that carries it (and the rehearsal report, the verifier's record, the sabotage
> proofs and the re-issued WP-7 certification) as its child. The clean-checkout rehearsal
> passed on `e07ce6c`; the verifier's record names that head; the certification names it too.

```
FALSE_SUCCESS = 0
BUILDER != VERIFIER
TEST_TARGET == RUNTIME_TARGET
LIVE_TRADING = DISABLED
PAPER_PROMOTION = NOT_AUTHORIZED
```

---

## Q1 — What was the real cause of the failures?

Not a flaky test and not a WP-7 regression: the lane's published artefacts were a function
of **the machine**, not of the commit. Two mechanisms, both measured
(`CAMPAIGN_STATE_DETERMINISM_AUDIT.md` §2, `evidence/BASELINE_REPRODUCTION.json`):

1. **Files that the repository does not carry.** The state view took three facts about the
   `ST6-FORWARD-REGIME` campaign from `data/st6/ST6_HEALTH_STATUS.json` — untracked, and
   rewritten by the ST-6 lane every few hours. The audit read four findings' worth of
   evidence from gitignored `reports/` outputs (`TIMEFRAME_AUDIT.json`, `REGIME_ANALYSIS.json`,
   `COST_BARRIER.json`, `STRATEGY_FAILURE_MATRIX.md`) and from an untracked
   `PAPER_DATA_24H_REPORT.json`. In a clean checkout those files do not exist, so the audit
   did not fail — it *degraded*: 7 gross-positive cells became 1, the best edge 8.912 bps
   became 1.4854 bps, the sample of ≥100-trade cells 23 became 6, and the paper lane's
   failure disappeared (`paper_lane.present = False`). A degraded audit that looks like a
   finding is worse than a crash.
2. **Digests taken over raw bytes.** Every pin was `sha256` of the bytes on disk, and this
   repository checks out with `core.autocrlf=true`: the same commit produced different
   digests in two checkouts, so the committed artefact could not recompute anywhere but on
   the machine that wrote it. This is the direct cause of
   `test_state_view_is_deterministic`.

The attribution matters: the same three nodes fail at `38b8e18`, the baseline *before* WP-7,
so WP-7 neither caused nor discovered it.

Two further defects of the same family were found by the rehearsal afterwards, in the order
it failed (`RUN_REPORT.md` §4): the coverage summaries embedded whether *this machine* held
the two gitignored price datasets, and the cost-barrier lane — a different work package —
pinned the audit's bytes, which no rebuild anywhere else could ever satisfy. Both are now
fixed, with the artefacts regenerated, the producer pins re-captured and the WP-7
certification re-issued.

## Q2 — Which dependencies were contaminating the reconstruction?

Eight external inputs, mapped and classified in `RECOVERY_RUNTIME_AUTHORITY_MAP.md`:

| contaminating dependency | class before WP-8 | what it did |
| --- | --- | --- |
| `data/st6/ST6_HEALTH_STATUS.json` | another lane's live state, untracked, rewritten hourly | silently changed the ST-6 campaign's state and the advisory set |
| `reports/strategy-baseline/TIMEFRAME_AUDIT.json` | gitignored local output | the audit's per-cell numbers |
| `reports/strategy-baseline/REGIME_ANALYSIS.json` | gitignored local output | regime context for the cells |
| `reports/strategy-baseline/COST_BARRIER.json` | gitignored local output | the cost-plane corroboration |
| `reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md` | gitignored local output | the failure taxonomy |
| `PAPER_DATA_24H_REPORT.json` | untracked output of the paper lane | the paper lane's failure record |
| `data/raw/alpha001/BTC-USDT_1d.json`, `ETH-USDT_1d.json` | gitignored datasets | pins that no checkout could satisfy |
| `data/rfcNNN/` directories | the working tree itself | RFC-number occupancy read from the directory listing, so an untracked `data/rfc050/` could move a certified number |

Two further vectors were removed rather than classified: the moment (`generated_at_utc`,
`head`, `branch`) and per-machine facts are now **outside** the identity hash, and the
occupancy count is read from the committed tree.

## Q3 — Do the results now reproduce from a clean checkout?

Yes, for the recovery lane's artefacts, and the claim is checked rather than asserted:

- `scripts/recovery_input_evidence.py --verify` → `VERIFIED`, 0 failures;
- `data/recovery/CAMPAIGN_STATE_VIEW.json` re-derives with the published `payload_sha256`
  (`--check` → PASS), from 14 sources that all resolve from `HEAD` or an evidence copy;
- `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` does the same, from 17 sources, and publishes
  the check `inputs:every_external_input_resolves_from_the_commit` → PASS;
- `scripts/clean_checkout_rehearsal.py --scope full` rebuilds both artefacts in a detached
  worktree of the commit and compares them byte for byte (content digests, so a CRLF
  checkout is not a difference), then runs the independent verifier inside that worktree —
  the report is `CLEAN_CHECKOUT_REHEARSAL_REPORT.json`, and its `sabotage` block records the
  two deliberate mutations that must be detected (`evidence_copy`, `committed_input`);
- the same script is wired into CI (`.github/workflows/recovery-determinism.yml`), where it
  reports `runner: GITHUB_ACTIONS` instead of `LOCAL`.

The economics did not move while the provenance did:
`evidence/ECONOMIC_INVARIANCE.json` → `verdict: IDENTICAL`, all 24 strategy records and all
aggregates byte-identical to the pre-repair publication, `admitted_for_paper: 0 → 0`,
`net_positive_count: 0 → 0`; the single declared change is the state view's `advisories`
list, which the repair alters on purpose.

## Q4 — Which tests and validations were executed?

| what | command | result |
| --- | --- | --- |
| lane contract tests | `pytest tests/unit/research/test_active_recovery_wp.py -q` | 28 passed (26 before WP-8) |
| determinism regressions | `pytest tests/unit/research/test_recovery_determinism.py -q` | 15 tests: CRLF/LF, later ADR, dirty input, missing input, contradictory sources, hash change, occupancy, repeated reproduction, invariance, rehearsal + 2 sabotages |
| CI parity contract | `pytest tests/unit/research/test_recovery_ci_parity.py -q` | 8 passed |
| cost-barrier lane tests | `pytest tests/unit/research/test_cost_barrier_{explorer,gate,adversarial,ci_parity}.py -q` | 93 passed |
| cost-barrier gate and sweep | `scripts/cost_barrier_gate.py`, `scripts/cost_barrier_adversarial.py` | `FULL_REPRODUCTION_PASS`, 0 controls missed; 17 attacks, 0 evaded |
| global suite | `pytest -m "not slow and not market" -q` | **3390 passed, 3 deselected** (the slow rehearsal tests) |
| rehearsal + sabotages | `pytest tests/unit/research/test_recovery_determinism.py -m slow` and `scripts/clean_checkout_rehearsal.py --scope full` | **PASS** on `e07ce6c`, 4/4 artefacts state-identical, no input modified; both sabotages `SABOTAGE_DETECTED`, kept as `evidence/SABOTAGE_*.json` |
| independent verification | `scripts/recovery_verify.py` | `../INDEPENDENT_VERIFICATION.json`: C1–C17 + 12 negative controls, each shown to fire |
| lint / types | `ruff check`, `mypy` on the touched files | clean |
| economic invariance | `scripts/recovery_economic_invariance.py --check` | `STABLE`, `IDENTICAL` |
| cost-barrier chain | `scripts/cost_barrier_certify.py`, `scripts/cost_barrier_gate.py`, adversarial sweep | `CERTIFIED` on the record's own head, gate `FULL_REPRODUCTION_PASS`, 0 escapes |

No assertion was weakened to obtain a pass: the three nodes that were red at the baseline are
red-then-green because the inputs became committed and the digests became content digests.

## Q5 — Which commits contain the implementation?

| commit | subject | what it carries |
| --- | --- | --- |
| `e670d2a` | Give the ACTIVE recovery lane's external inputs a committed, pinned authority | the input bundle (`wp8/evidence/inputs/` + sidecar + `.gitattributes -text`) and the baseline evidence; it also commits `PAPER_DATA_24H_REPORT.json`/`.md`, an audit input that was untracked (the paper lane's bytes, unmodified) |
| `3f8d646` | Make the recovery lane's state and audit a function of the commit, not the machine | `recovery_input_evidence.py`, the state view and audit repairs, `clean_checkout_rehearsal.py`, the regression suite, the regenerated artefacts |
| `306939c` | Follow the regenerated audit through the cost-barrier chain instead of failing on it | the cost-barrier chain re-pinned to the regenerated audit digest (+2 adversarial attacks) |
| `9b9a4b8` | Make the recovery lane's reproducibility a claim anyone can re-run | the WP-8 authority, determinism, reproducibility and run reports, `recovery_economic_invariance.py`, the CI workflow, the CI parity tests |
| `6c3af00` | Stop publishing which machine built the artefacts, and compare the state | the dataset-route fix, the state-digest comparison, the regenerated artefacts |
| `4b32d97` | Compare the rendered reports on their state too, not on this machine | the volatile-section rule for the rendered reports |
| `66dc3de`, `279d73f` | the cost-barrier chain follows the regenerated audit, twice | the re-pinned chain and, at `279d73f`, the state pin that replaces the byte pin over the audit |
| `6cac3c6` | Judge a declared-only dataset on its authority instead of demanding bytes | the C14 correction and control N13 |
| `272df9f` | Detect a mutated input the only way a HEAD-reading lane can: by the checkout | the input guard and the two sabotage detectors |
| `e07ce6c` | Keep the two sabotage proofs as artefacts instead of test output | `evidence/SABOTAGE_*.json` |
| record commit (child of `e07ce6c`) | | the rehearsal report, the verifier's record, the re-issued WP-7 certification and the lane-level report updates |

`33512b5` (WP-7) is **not** part of this list: it re-issued the cost-barrier certification
record after that record's fingerprint check was added. WP-8 re-issues that record once more,
because the audit artefact it fingerprints was regenerated (see Q6).

## Q6 — Which certification has authority over which commit?

- **Implementation**: commits `e670d2a` → `3f8d646` → `306939c` → `C` → `R` on `main`.
- **Recovery lane**: `R` carries `INDEPENDENT_VERIFICATION.json`, whose `head` names the
  commit the verifier ran on, and the rehearsal report, whose `rehearsed_commit` names the
  commit the rehearsal tested (`C`). A reader has both: what was tested, and where it was
  verified.
- **Cost-barrier lane (WP-7)**: `data/recovery/wp7/COST_BARRIER_CERTIFICATION.json` is
  `CERTIFIED` on head `e07ce6c` with `dirty_watched_paths: []`, fingerprint `0cfdb13e…`, 93
  lane tests passed, gate `FULL_REPRODUCTION_PASS`, adversarial `EVALUATED` 17/17 — and it
  carries a `supersession` block naming the record it replaced (`bd607266…` on `081ee7a`,
  previous status `CERTIFIED`, plus a digest of that record's evidence table) and the reason:
  the audit artefact it fingerprints was regenerated by WP-8D, and a reproducibility defect in
  its own pins was closed by WP-8H. The previous record was **replaced, not rewritten**, so the
  chain `3e60112` (certified code) → `7ed61f7`/`33512b5` (records) → this re-issue stays
  auditable. The record was re-issued twice while the chain was being fixed; the intermediate
  attempt never left the working tree, and only this one is committed.
- **What has no authority**: nothing in this work package authorizes a strategy, a campaign
  or a paper promotion. `RFC-049-DISCOVERY-2` remains `DISCOVERY_CAMPAIGN_FAILED`, the sealed
  OOS remains `CANCELLED_NOT_OPENED`, `NEXT_CAMPAIGN` and `PAPER_PROMOTION` remain
  `NOT_AUTHORIZED`, and `admitted_for_paper` is 0 before and after.

## Q7 — Which defects remain?

1. **The frozen price series are still gitignored** (`data/raw/alpha001/*`). They are declared,
   graded against the RFC-049 manifest digest when present, and their absence is a
   materialization note — not a contradiction — because no published finding rests on them.
   A future work package that *does* rest a finding on them will need their materialization
   route recorded, not their bytes committed.
2. **The rehearsal ran on one operating system.** The cross-platform claim rests on the
   content digests and on CI (`runner: GITHUB_ACTIONS`); a Linux-originated local run has not
   been recorded, and the CI workflow has not yet executed on a GitHub runner from this
   machine.
3. **Other lanes keep writing into this repository.** `data/st6/*` is rewritten hourly and
   several uncommitted paths belong to other work packages; the lane no longer reads them,
   but a tree-level audit of the whole repository would still be noisy.
4. **The paper lane's own reports are inputs now.** `PAPER_DATA_24H_REPORT.json` is committed
   and pinned; if that lane republishes it, the audit's pin must be re-attested in a new
   commit rather than edited in place — the check `inputs:every_external_input_resolves_from_the_commit`
   will fail loudly if it is.
5. **WP-8 does not re-open discovery.** The economic question (RFC-049) is closed as failed;
   this work package changed no criterion, no cost assumption and no admission rule.
6. **The CI workflow has not run on GitHub.** `.github/workflows/recovery-determinism.yml` is
   committed and its activation and content are held by parity tests, but from this machine the
   honest state is "rehearsed locally", not "verified in CI".
7. **The cost-barrier lane now carries two pins for the audit** (a byte pin and a state pin).
   That is deliberate — the byte pin still catches any change, the state pin is what survives a
   rebuild — but a reader comparing the two artefacts will see both, and only the state pin is
   satisfiable away from this machine.

## Q8 — What is still missing before the ACTIVE economic recovery can continue?

The lane's own audit answers this and WP-8 changes none of it: no strategy has a net-positive
expectancy after costs, `admitted_for_paper = 0`, and a paper promotion is
`NOT_AUTHORIZED`. Concretely, before that can move:

1. an operator authorization for paper promotion (the flag is `NOT_AUTHORIZED`, and this work
   package deliberately leaves it there);
2. a clean continuous 24 h paper-data window — the last attempt reached 4.16 h and stopped on
   its own disk budget (`paper_lane.final_status = PAPER_24H_DATA_FAILED`);
3. the M-03 / M-07 history their gates require;
4. a cost-and-entry research campaign registered as its own RFC (the next free number is
   derived from the committed registry, not from a directory listing) and left unauthorized
   until the operator amends the registry — because the measured cost plane, not the signal
   inventory, is what kills the edge.

Until then the honest states remain: `PROFITABILITY_VERIFIED = FALSE`,
`LIVE_TRADING = DISABLED`, `TRADES_AUTHORIZED = 0`.
