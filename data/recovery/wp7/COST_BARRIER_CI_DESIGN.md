# COST_BARRIER_CI_DESIGN — WP-7B / 7C / 7E / 7F

> How a clean checkout, and a CI runner, can run a **full reproduction** of the
> published cost-barrier artefacts; how a partial run is prevented from being
> read as a certification; and what the resulting record does and does not
> authorize. Baseline `38b8e18`.

## 1. The problem, measured

`reports/strategy-baseline/COST_BARRIER.json` is a declared input (it carries the
market-horizon medians the explorer publishes) and:

* it is **not committed** — `.gitignore` line 55 is `reports/*`, deliberately:
  `reports/` holds generated outputs;
* its **own inputs are not committed either** — `reports/strategy-baseline/data/*.json`
  are the cached bar datasets, also under `reports/*`, also generated;
* the only way to regenerate it is `scripts/cost_barrier.py`, which needs those
  datasets; producing them needs network access to the venues.

So a clean checkout cannot run the builder. WP-6 handled that honestly by running
`--check` and reporting the missing input as an advisory, which is why its status
vocabulary had no way to say "full reproduction happened here".

## 2. The three alternatives, evaluated

| # | alternative | what it would take | works on an untrusted PR? | verdict |
| --- | --- | --- | --- | --- |
| A | materialize from trusted storage with a pinned version and SHA-256 | an artifact store (release asset, object store, Actions cache) plus credentials to fetch into the runner | no: needs a secret, and a secret in a PR from a fork is exactly what must not happen | rejected **as storage**, adopted **as the mechanism** (the digest-pinned copy + verify-before-use is exactly the discipline needed) |
| B | a controlled runner with access to the original inputs | a self-hosted runner holding the datasets; infrastructure outside this repository | n/a | rejected: no such infrastructure exists here, and inventing one would put undocumented state behind the gate |
| C | a reproducible evidence bundle, with verifiable provenance and integrity | carry the artifact's input in the repository under a digest, verify it against the digest the **published artefact itself** recorded, and materialize it at its canonical path before the run | yes: the data is public derived aggregates (medians of public klines), no secret, ~3.8 KB | **chosen** |

**Decision:** C, with A's integrity discipline. The evidence copy lives at
`data/recovery/wp7/evidence/COST_BARRIER.json` (3 822 bytes, CRLF, sha256
`2437f446…`), byte-identical to the file the published explorer was built from,
with a sidecar `INPUT_EVIDENCE.json` recording its digests, its capture commit
and the pin it must reproduce.

**The `.gitignore` policy is not changed.** `reports/*` stays ignored; the
exclusion is *justified* rather than removed, because un-ignoring it would apply
to every generated report in the repository, not to this one artifact. The
evidence copy is a new committed **evidence** file in a different tree, not the
un-ignoring of a generated output. `data/recovery/wp7/evidence/**` is marked
`-text` in `.gitattributes`, following the RFC-049 precedent, so a checkout
cannot rewrite the bytes whose digest is pinned.

### What the digest chain actually is

```
published artefact sources[]  ──►  sha256 2437f446…  ==  evidence copy bytes  ──►  materialized input
        (authority)                     (must reproduce)              (byte-identical)
```

The pin authority is the artefact, not the capture machine and not the sidecar;
the sidecar only records what it verified, and is itself checked against the
artefact's live pin. If the artefact is ever regenerated, the check fails and the
evidence must be re-captured — deliberately, in a reviewed commit.

## 3. What CI does now

`.github/workflows/cost-barrier-gate.yml`, in order, with no softened step:

| step | command | what it establishes |
| --- | --- | --- |
| verify + materialize | `python scripts/cost_barrier_evidence.py --materialize --json` | digests verified against the artefact's pin and the producer manifest, **then** the input is placed at its canonical path (refusing to overwrite a differing file) |
| full reproduction | `python scripts/cost_barrier_gate.py --json --report …` | builder and verifier re-run; every published number compared field by field; pins, producer digests, market-horizon re-derivation, activation contract and the six self-controls |
| adversarial suite | `python scripts/cost_barrier_adversarial.py …` | the 17 attacks on isolated copies; any escape fails the job |
| certification | `python scripts/cost_barrier_certify.py --json …` | the record: all seven requirements or a refusal that names the reason |
| keep the evidence | `actions/upload-artifact@v4`, `if: always()` | the reports survive a failure; `if-no-files-found: error` |

The workflow runs on `push`/`pull_request` to `main` filtered by 24 paths, and on
`workflow_dispatch`. It is **not** one of the four required status checks in
`quality/release-gates.md` Bloque 6; it is additive, and says so in the file.

Exit codes are one per state, so a shell cannot confuse them:
`0` full reproduction, `2` partial (check-only), `3` blocked on a missing
required input, `4` the reproduction diverged, `5` integrity failure.

## 4. The state contract (WP-7C)

| state | when | may satisfy full certification |
| --- | --- | --- |
| `FULL_REPRODUCTION_PASS` | full mode; every check passed; nothing blocked | **yes** |
| `FULL_REPRODUCTION_FAIL` | full mode; a check failed (builder, rebuild comparison, verifier, document drift) | no |
| `CHECK_ONLY_PASS` | `--check` with nothing absent | no |
| `CHECK_ONLY_WITH_ADVISORIES` | `--check` with a tolerated absence (the gitignored input not materialized) | no |
| `BLOCKED_MISSING_INPUT` | full mode cannot start because a required input is absent | no |
| `INTEGRITY_FAILURE` | any mode: a published document contradicts itself, its own inputs, the producer manifest, the activation contract or the tampering controls | no |

Precedence is explicit and tested: integrity outranks everything (no re-run
explains a contradiction), then a blocked input (which is not a failed
reproduction), then divergence, then the two check-only states. Checks are
severity-tagged (`integrity` / `reproduction` / `blocked`) rather than classified
by name, so the mapping is visible in the report.

A partial result cannot promote a strategy or certify an economic result: the
report carries a `certification` block whose `satisfies_full_certification` is
true for exactly one state, and the certifier refuses anything else.

## 5. Integrity and provenance (WP-7E)

* **Producer pins.** The four producers that had no pin now carry digests in
  `data/recovery/wp7/evidence/PRODUCER_PINS.json`, verified on every gate run. A
  producer edit is a named failure requiring regeneration, re-verification and an
  explicit re-pin in the same commit (the churn is the point: it is what makes the
  change visible).
* **Pin authority.** For each pin: the artefact's `sources[]` for the five
  inputs, the manifest for the four producers, and behind both the commit that
  carries it. The manifest records that authority, what it deliberately excludes
  and why.
* **The checker is not pinned.** `scripts/cost_barrier_gate.py` is excluded from
  the manifest, and the gate fails if anyone tries to add it: a digest the
  checker verifies against itself is vacuous assurance. This is the honest
  boundary of the scheme, not an oversight.
* **Commit and environment.** Every report carries `head`, `branch`, python
  version/implementation/platform/machine and the digests of what it read; the
  certification record carries the digest of every artefact it rests on plus an
  `evidence_fingerprint` over the set.
* **Failures cannot become PASS.** One decision function maps evidence to the six
  states, it is unit-tested in both directions, and a missing manifest, an
  unreadable workflow or an incomplete bundle all fail closed. An adversarial leg
  sets nine hostile environment variables plus config files that ask the gate to
  stand down, on both a clean and a defective tree, and asserts the verdict is
  unchanged in both directions.

## 6. The certification gate (WP-7F)

`scripts/cost_barrier_certify.py` requires all seven, in order, and writes the
record only after evaluating them:

1. contract and adversarial tests exit 0;
2. the evidence bundle verifies (`VERIFIED`, not `BLOCKED`);
3. the gate reaches `FULL_REPRODUCTION_PASS` **in full mode**;
4. that same run attests the artefact: 0 failed checks, 0 missed mutation
   controls, `false_success` 0;
5. the adversarial suite reports 0 escapes, 0 invalid mutations and 0 failed legs;
6. the record identifies commit, environment and evidence digests;
7. nothing hidden: any non-zero step, any integrity failure, any blocked input is
   named in `decision.reasons`.

Refusals are part of the contract: a `mode: check` report rewritten to claim
`FULL_REPRODUCTION_PASS` is refused (`mode` is cross-checked), a check-only
status yields `PARTIAL`, a missing input yields `BLOCKED_MISSING_INPUT`, an escape
or a failed test yields `FAILED`.

## 7. Independent trust root — evaluated, not available

An independent trust root would be a witness outside the repository: signed
attestations from a second party, a transparency log, or a monotonic external
record. None of that exists here, and inventing an unauthenticated one would be
worse than the gap.

What the design does instead is make the *chain* as narrow and as reviewable as
possible: the inputs' digests, the producers' digests, the artefacts' identity,
the gate's own bytes, the environment and the commit are all recorded in one
place, and the only unwitnessed step is the checker itself. The residual exposure
is stated in the runtime authority and repeated here: **a party who can rewrite
the artefacts, the evidence bundle, the manifest and the checker in one commit
defeats this scheme, and nothing inside the repository can detect that.**

## 7b. Where this decision is recorded, and why not in the ADR log

The architectural decision above (evidence bundle + materialization, producer
pins, the state contract, the certification gate) is recorded here and in
`context/retrieval-log.md`, and deliberately **not** as an entry in
`tasks/decisions.md`.

The reason is measured, not stylistic: `scripts/campaign_state_view.py` parses
`tasks/decisions.md` as one of its own pinned inputs, and its committed payoff
(`data/recovery/CAMPAIGN_STATE_VIEW.json`) is held to a determinism contract by
`tests/unit/research/test_active_recovery_wp.py`. Rebuilding the view with an
extra ADR in the log yields a different payload hash (`f78943f4…` against
`bcc46024…` without it), so an ADR entry here would silently invalidate another
lane's committed artifact - and regenerating it is that lane's work, not this
work package's. The decision is therefore recorded in full in this document, and
the shared ADR log is left byte-identical.

## 8. Declared limitations

* Regenerating `COST_BARRIER.json` itself (from the cached bars) still cannot
  happen in CI: the datasets are not committed and fetching them needs network
  access to venues. The evidence copy is byte-identical input, not a regeneration
  of it, and is labelled as such.
* The four producers' pins create churn by design: editing any of them requires a
  re-pin in the same commit. That is a deliberate cost.
* The GitHub workflow has never executed on GitHub from this lane (no push was
  authorized). What was verified here is the same procedure on a clean `git
  worktree` of the candidate commit — see `RUN_REPORT.md`.
* CI is evidence, not proof against a compromised runner.
