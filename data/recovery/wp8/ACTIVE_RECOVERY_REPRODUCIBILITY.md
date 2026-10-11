# ACTIVE_RECOVERY_REPRODUCIBILITY — WP-8D

> What the ACTIVE economic audit was reconstructing itself from, what was repaired, and the
> proof that no economic finding moved while the provenance did.

---

## 1. The defect

`data/recovery/ACTIVE_ECONOMIC_AUDIT.json` reported 24 registered strategies, 7 zero-cost
gross-positive cells, a best gross edge of 8.912 bps, a sample of 23 cells with ≥100 trades,
and a paper lane that failed with 0 trades. On a clean checkout the same program, from the
same commit, reported **1** gross-positive cell, a best edge of **1.4854 bps**, a sample of
**6**, and `paper_lane.present = False`.

Nothing had been edited. The difference was that four of the audit's declared inputs sit in
gitignored `reports/` and one (`PAPER_DATA_24H_REPORT.json`) was untracked:

| input | class | present in a clean checkout |
| --- | --- | --- |
| `reports/strategy-baseline/TIMEFRAME_AUDIT.json` | gitignored local output | no |
| `reports/strategy-baseline/REGIME_ANALYSIS.json` | gitignored local output | no |
| `reports/strategy-baseline/COST_BARRIER.json` | gitignored local output | no |
| `reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md` | gitignored local output | no |
| `PAPER_DATA_24H_REPORT.json` | untracked by the paper lane | no |

An audit that quietly degrades when its evidence is missing is worse than one that fails: the
degraded numbers look like findings.

## 2. The repair

The audit now reads **committed, digest-pinned inputs** (`scripts/recovery_input_evidence.py`):

1. `PAPER_DATA_24H_REPORT.json` and its narrative are committed at their own paths — the paper
   lane's closed 24h report is governance evidence and belonged in the repository;
2. the four `reports/` inputs are carried as byte-identical evidence copies under
   `data/recovery/wp8/evidence/inputs/`, `-text` in `.gitattributes` so a checkout cannot
   rewrite their bytes, and admissible **only while they reproduce the digest the published
   audit itself recorded** for that input (`sources[].sha256`, now also recorded in content form);
3. the two frozen price series stay gitignored (repository policy, `data/raw/*`): they are
   declared, graded against the RFC-049 manifest digest when present, and their absence is a
   materialization note instead of a contradiction;
4. every digest is now a content digest: `sha256_lf`/`sha256_crlf` are the authorities, a
   line-ending-only difference is an advisory;
5. the audit publishes its input declarations inside its identity (`input_authority.declared_inputs`)
   and per-machine materialization facts outside it (`local_observations`), and adds the check
   `inputs:every_external_input_resolves_from_the_commit`.

## 3. The proof that no economic finding moved

`data/recovery/wp8/evidence/ECONOMIC_INVARIANCE.json` compares the artefact published before
the repair (at `3f8d646^`) with the one published after it, field by field, from the committed
blobs:

```
verdict: IDENTICAL
per_strategy_records_identical: true        (all 24 strategy records, byte for byte)
aggregates_identical:           true        (7 gross-positive cells, best 8.912 bps, sample 23)
admitted_for_paper:             0 → 0
net_positive_count:             0 → 0
answers (Q1..Q6):               identical
paper_lane block:               identical   (337 cycles, 0 trades, PAPER_24H_DATA_FAILED)
declared_source_discrepancies:  identical   (DEF-ACT-03, breakout@5m)
cost_plane:                     identical   (23.353553391 bps at 200 USDT)
changed findings:               none
```

What did change is the artefact's *identity* (`355d018b…` → `023b66ff…`) and its `sources[]`
shape: the sources now record where each byte came from (`HEAD`, `EVIDENCE_COPY`),
their content digests, and whether the file is in the commit. One check was added
(`inputs:every_external_input_resolves_from_the_commit`); 19 checks pass, 0 fail.

Nothing about the strategy admission criteria, the research cost model, the materiality
bounds or the declared discrepancies was touched. No strategy is declared profitable, no
strategy is admitted to paper, and no authorization is created: the audit's own answer
`Q6_next_rfc.authorization_state` still reads `NOT_AUTHORIZED`, and `admitted_for_paper`
is still `0`.

## 4. Dependencies and provenance after the repair

| artefact | identity | inputs resolved from | checks |
| --- | --- | --- | --- |
| `ACTIVE_ECONOMIC_AUDIT.json` | `023b66ffd1213b06…` | HEAD (strategy evidence, closure, registry, cost model) + 4 committed evidence copies + 1 committed paper report | 19 passed / 0 failed |
| `CAMPAIGN_STATE_VIEW.json` | `e7bee5d8b710640c…` | HEAD + 1 committed snapshot (the live lane) | 7 invariants PASS, 0 contradictions |

Both artefacts are reproduced byte for byte in a clean checkout of this commit
(`data/recovery/wp8/CLEAN_CHECKOUT_REHEARSAL_REPORT.json`), and the audit's `sources[]`
records `resolved_from` for every row, so a fallback read is visible rather than silent.

## 5. Effect on the cost-barrier (WP-7) certification

The WP-7 certification record lists `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` among the
paths it fingerprints, and this work package regenerates that artefact. The record's
fingerprint is therefore re-issued in this branch, with the previous fingerprint preserved in
the record's own `supersession` block: a record that silently stopped matching its evidence
would be the same class of defect this work package exists to close. The cost-barrier
*lane's* conclusions (the explorer, the verification, the 17/17 adversarial sweep) are
unchanged, and its evidence set is verified again by the rehearsal.

## 6. Limitations

- The four evidence copies are copies of local research outputs. They are admissible only
  while they reproduce the digest the audit published for them, and the chain is anchored in
  the commit — not a signature.
- The audit cannot be regenerated without the committed evidence bundle. That is deliberate:
  the alternative is what this document describes.
- The two frozen price series remain outside the repository by policy. Nothing published is
  derived from them; they are integrity evidence for the RFC-049 preregistration and are
  graded only when a machine holds them.
