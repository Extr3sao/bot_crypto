# CAMPAIGN_STATE_DETERMINISM_AUDIT — WP-8A / WP-8B / WP-8C

> Why the campaign state view could not be reconstructed anywhere but on the machine that
> wrote it, what was done about it, and what is now checked rather than asserted.

Evidence in this document is reproducible: every claim names the command or the artefact
that carries it.

---

## 1. WP-8A — the baseline, reconstructed before anything was touched

Starting state: `main` at `33512b5`, **dirty** — 26 modified tracked files and 44 untracked
entries belonging to other lanes (ST-6 scheduler, RFC-035e). Nothing in the shared tree was
cleaned, moved or stashed to make this work easier.

The failures were captured before a single test was edited, in three trees
(`data/recovery/wp8/evidence/BASELINE_REPRODUCTION.json`):

| tree | HEAD | result | missing external inputs |
| --- | --- | --- | --- |
| shared working tree (dirty by design) | `33512b5` | 1 failed, 25 passed | none — every input is on this machine |
| clean worktree of HEAD | `33512b5` | **3 failed**, 23 passed | all 8 |
| clean worktree of the pre-WP-7 baseline | `38b8e18` | **3 failed**, 23 passed | all 8 |

The three nodes:

1. `test_state_view_is_deterministic` — the committed view does not recompute.
2. `test_audit_is_deterministic_and_committed` — the committed audit does not recompute.
3. `test_audit_records_the_paper_lane_failure_honestly` — `paper_lane.present is False`.

Two facts that matter for attribution:

- the same three fail at `38b8e18`, i.e. **before** WP-7 touched anything: the defect is not
  a WP-7 regression;
- in the authoring tree only **one** of them fails, because that tree has every input. A
  suite that is green where it was written and red where it is checked out is exactly the
  shape of this bug.

The WP-7 commits under examination: `749bf4c`, `a551fdc`, `3e60112`, `081ee7a`, `7ed61f7`,
`33512b5`. `3e60112` is the commit that contains the cost-barrier **code** certified by the
record; `7ed61f7` and `33512b5` are the commit that carries the **certification record** for
it (re-issued after the record's fingerprint check was added). WP-8 changes neither lane's
conclusions; it changes one artefact (`ACTIVE_ECONOMIC_AUDIT.json`) that the WP-7 record
lists as an input, and that record is re-issued in this work package (see
`ACTIVE_RECOVERY_REPRODUCIBILITY.md` §5).

## 2. WP-8B — the four demonstrated causes

Each cause was measured, not inferred. The diagnostic compared the committed artefact with a
fresh build leaf by leaf (`campaign_state_view.build()` vs the committed JSON, and the same
for the audit).

### C1 — the state view read a file that is not in the repository

`campaigns[5]` (`ST6-FORWARD-REGIME`) took its three facts from `data/st6/ST6_HEALTH_STATUS.json`,
which is **untracked** and rewritten by the ST-6 lane every few hours. In a clean checkout the
file does not exist, so the campaign lost `LANE_STATE`, `NEXT_CAMPAIGN` and `LIVE_TRADING`, and
the advisory set changed. The committed view asserted those values; nothing in a clean checkout
could reproduce them.

### C2 — the audit read a whole research baseline that is not in the repository

`reports/*` is gitignored by design (`reports/*` in `.gitignore`). Four inputs the audit needs
live there:

```
reports/strategy-baseline/TIMEFRAME_AUDIT.json          109 211 bytes
reports/strategy-baseline/REGIME_ANALYSIS.json            3 670 bytes
reports/strategy-baseline/COST_BARRIER.json               3 822 bytes
reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md      3 501 bytes
```

With them absent, the audit did not fail: it degraded. `sufficient_sample_count` fell from
23 to 6, `zero_cost_gross_positive` from 7 cells to 1, and the best gross edge from 8.912 bps
to 1.4854 bps. The published artefact described a state no clean checkout could reach.

### C3 — every digest was taken over raw bytes

`sha256_file(path.read_bytes())`. This repository runs with `core.autocrlf=true`, so a fresh
checkout writes CRLF where the authoring tree held LF: in the clean worktree 13 of the 14
append-only document attestations graded `DRIFTED` for a difference no edit caused, and the
two dataset pins graded `MISSING`. The gate in the cost-barrier lane had already learned this
(`sha256_lf`/`sha256_crlf`, WP-7E); the recovery lane had not.

### C4 — a pin with no path graded as "missing", and a pin with no path was dropped

The RFC-049 manifest records digests for nine `signal_series` inputs **without a path**. The
old code skipped them silently; the two `price_series` entries (gitignored datasets) were
graded `MISSING` when absent, which failed invariant `I1` and turned a clean checkout into
`status = CONTRADICTION`. A contradiction in the state view is not a cosmetic matter: it is
the view saying the repository disagrees with itself.

Two smaller causes of the same family were found and fixed:

- **RFC occupancy came from the filesystem** (`(ROOT / "data").iterdir()`), so any untracked
  `data/rfcNNN/` directory moved a certified number, and `local_observations` did not exist to
  record it;
- **`I5_governance_mirrors_agree` passed on an empty comparison**: with the mirror absent,
  `shared = []` and *no disagreements* read as PASS. A check that could not see its input
  reported success — the failure mode this whole work package is about.

## 3. WP-8C — the deterministic reconstruction

### 3.1 What the view now does

| rule | before | after |
| --- | --- | --- |
| committed sources | `ROOT / path` (working tree) | `git show HEAD:<path>` — the commit is the state |
| external sources | the local file if it exists | the evidence copy or dated snapshot the commit carries; the local file is an observation |
| digests | raw bytes | content digests, `sha256_lf` authoritative, EOL tolerant |
| pins on gitignored inputs | graded, and fatal when absent | declared with their authority digest; graded as an observation |
| a pin with no path | dropped | published as `UNRESOLVED` with the reason |
| RFC occupancy | `data/*` directory listing | committed tree (`git ls-tree HEAD data/`) |
| invariant that cannot see its input | PASS | `NOT_CHECKED` + advisory `A6` |
| reproducibility | not modelled | invariant `I7_inputs_are_reproducible` over all 8 declared inputs |

### 3.2 Precedence, snapshots and current state (unchanged, and now enforced)

The resolution rules are the ones RFC-049 discovery closed with, and WP-8 changed none of
them:

- the **latest** ADR that names a campaign decides (`P1`), earlier values are recorded as
  superseded rather than rewritten: for `RFC-049-DISCOVERY-2`, `ADR-0025`'s
  `NEXT_CAMPAIGN = AUTHORIZED` remains visible while `ADR-0026`'s `NOT_AUTHORIZED` governs;
- two records at the same level with different values remain an unresolved contradiction;
- a **frozen declaration** (`P4`) is historical: it is never current unless nothing above it
  speaks;
- a **snapshot** (the forward lane's dated capture) is labelled as one and is never presented
  as live state; the live file's current values are published as an observation.

### 3.3 What the published view says now

`data/recovery/CAMPAIGN_STATE_VIEW.json` — identity `e7bee5d8b710640c…`, `status =
CONSISTENT_WITH_ADVISORIES`, seven invariants PASS:

```
I1_frozen_pins_verify              PASS  16 verified, 0 failed, 0 missing
I2_builder_is_not_verifier         PASS
I3_no_profitability_claim          PASS  no profitability flag is true anywhere
I4_sealed_window_never_read        PASS  no sealed-OOS flag is true anywhere
I5_governance_mirrors_agree        PASS  4 shared flags agree (coverage FULL)
I6_campaign_numbers_are_consistent PASS  declared [46, 48, 49]
I7_inputs_are_reproducible         PASS  8 declared inputs resolve from the repository
```

Advisories: `A1` (registry stale vs the committed tree), `A2` (next free number derived),
`A3`, `A4` (append-only drift on one attested document). No contradictions, no failed
invariants, `sources_unchanged: true`.

Everything governance-relevant is unchanged from the pre-WP-8 view: the effective state of
every campaign is identical, including

- `RFC-049-DISCOVERY-2`: `TERMINAL_STATE = DISCOVERY_CAMPAIGN_FAILED`,
  `SEALED_OOS = CANCELLED_NOT_OPENED`, `NEXT_CAMPAIGN = NOT_AUTHORIZED`,
  `PAPER_PROMOTION = NOT_AUTHORIZED`, governing ADR `ADR-0026`;
- `ACTIVE-PAPER`: 24 strategies registered, 0 admitted for paper,
  `PAPER_RUN_STATE = PAPER_24H_DATA_FAILED`;
- `ST6-FORWARD-REGIME`: `HEALTHY`, `NOT_AUTHORIZED`, `DISABLED`.

One published value *did* change, and it is a strengthening: `A3_unresolved_pins` now names
**12** unchecked pins instead of 3, because the nine `signal_series` digests that used to be
dropped silently are declared. Nine pins that proved nothing are now visible as pins that
prove nothing.

No new authorization is created anywhere. The view adds no flag that grants anything; the two
authorization fields it reports (`NEXT_CAMPAIGN`, `PAPER_PROMOTION`) still say
`NOT_AUTHORIZED`.

## 4. What is checked now (WP-8F)

`tests/unit/research/test_active_recovery_wp.py` (26 tests, all passing) holds the two
artefacts to their content. `tests/unit/research/test_recovery_determinism.py` adds the
regressions for the causes above:

| test | the defect it would catch |
| --- | --- |
| a later ADR supersedes without rewriting / a governed disagreement resolves and an ungoverned one does not | precedence silently changing, or a later ADR rewriting history |
| a CRLF checkout is the same content, a content change is drift | a raw-byte digest (cause C3) coming back |
| every evidence copy reproduces the published authority | an evidence copy drifting from the artefact's own pin |
| the observations are outside the identity | per-machine state leaking into a certified identity |
| an uncommitted edit to a committed document cannot move the identity | cause C1's cousin: a working-tree read |
| an untracked `data/rfc050/` cannot move the certified occupancy | the filesystem-derived RFC numbering |
| repeated reproduction is byte-identical | nondeterminism from ordering or formatting |
| the published artefacts report the reproducibility invariants | `I7` or `I5` coverage being dropped |
| no source of either artefact came from the working tree | a `WORKTREE_FALLBACK` read |
| the clean-checkout rehearsal passes on this commit | the whole sequence |
| a sabotaged evidence copy / a sabotaged committed input is detected | a rehearsal that cannot fail |

## 4b. WP-8H — what the rehearsal found that the identity hash did not

The rehearsal failed three times before it passed, and each failure was a real defect. Two of
them belong to this view:

1. **The coverage summary embedded the machine.** `I7_inputs_are_reproducible` published
   `resolved_from` over every declared input, and the two gitignored price datasets resolved to
   `LOCAL_MATERIALIZATION` where they exist and `ABSENT` where they do not — inside a field that
   is *not* volatile, so the committed view encoded which machine built it. The origin now names
   the route (`LOCAL_MATERIALIZATION`, always) with the presence reported next to it, and the
   per-machine observations stay in `local_observations`, which is outside the identity
   (`6c3af00`). This is the defect the raw-byte pin would have produced one level up: the
   identity was clean, the *reported* state was not.
2. **The rendered report carried the same fact.** `CAMPAIGN_STATE_VIEW_REPORT.md` renders the
   observation table, so its bytes differed between two checkouts of one commit. The rehearsal
   now declares that section volatile next to the moment line and compares the report on what
   it asserts (`4b32d97`).

A third failure was in the rehearsal itself, not the view: its sabotage proofs expected the
input bundle step and the artefact comparison to notice a mutation made *inside* the checkout,
and neither can — both read from HEAD, which is the property this work package established. The
rehearsal now guards that only the artefacts it reproduces and its own run records may change,
and both sabotage targets are detected by that guard, with the mutation path named in the report
(`272df9f`; artefacts under `evidence/SABOTAGE_*.json`).

What the rehearsal therefore proves, as a file a reader can open rather than a claim:

| claim | evidence |
| --- | --- |
| a clean checkout of the commit rebuilds the view and its report to the same state | `CLEAN_CHECKOUT_REHEARSAL_REPORT.json`, 4/4 identical on state digests |
| no input is modified by the run | `inputs_modified_in_the_checkout: []` |
| a mutation of an input is detected | `evidence/SABOTAGE_EVIDENCE_COPY.json`, `evidence/SABOTAGE_COMMITTED_INPUT.json` |
| the run reports who ran it | `runner: LOCAL` here, `GITHUB_ACTIONS` in CI (`recovery-determinism.yml`) |

## 5. Limitations

- The rehearsal and these tests were executed on **Windows** only. The cross-platform claim
  rests on the content digests (LF-normalised), not on a run on a second operating system.
- The input authority is a **digest chain anchored in the commit**, not a signature: a party
  able to rewrite an artefact, its evidence copy and the checker together defeats it.
- `A1`/`A2` (the RFC registry is stale against the committed tree) are reported, not fixed:
  reconciling the registry is a governance act, not a repair.
- The one append-only drift (`tasks/decisions.md` against the RFC-046 activation attestation)
  is recorded, not silenced: the attested digest predates later ADRs by design.
