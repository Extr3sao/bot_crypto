# Real decision ledger (CAP-003)

Append-only, versioned store of every real decision the campaign has sealed and
of everything that was later measured from it. `reports/` is gitignored scratch
space; this directory is the campaign's scientific record.

```
evidence/real_decisions/
    decisions.jsonl     snapshot_hash -> decision_hash
    outcomes.jsonl      decision_hash -> outcome_hash
    evaluations.jsonl   outcome_hash  -> evaluation_hash
    raw_evidence/       per-cycle OHLCV behind each snapshot (local only, gitignored)
```

Each file is JSON Lines: one self-contained JSON object per line, sorted keys.
Nothing is ever rewritten or deleted.

## The chain

```
MarketSnapshot (real, completed bars only)
        |  snapshot_hash = sha256(canonical_json(snapshot))
        v
DecisionRecord (sealed before the outcome exists)
        |  decision_hash = sha256(canonical_json(timestamp, prompt_version,
        |                  evidence_snapshot_hash, agent_output, critic_output, decision))
        v
DecisionOutcome (deterministic market outcome at decision_time + horizon)
        |  outcome_hash = sha256(canonical_json(outcome payload))
        v
DecisionPerformance (sealed decision + outcome + seal-time comparators)
           evaluation_hash = sha256(canonical_json(performance payload))
```

Every link is re-derivable from the written files alone, and
`scripts/cap003_verify.py` re-derives all of them without importing the modules
that produced them.

## Rules the ledger enforces on append

* a decision is only stored with **complete analyst provenance**
  (`analyst_id`, `prompt_version`, `prompt_digest`, `model`, `provider`,
  `temperature`, `schema_version`, `feature_version`, `dataset`), so an
  unreproducible run can never become a campaign observation;
* the sealed `decision_hash` must still recompute, and the embedded snapshot must
  re-digest to the `snapshot_hash` the decision was sealed against;
* duplicates are refused;
* an outcome must point at a decision already in the ledger, and an evaluation at
  an outcome already in the ledger;
* each decision has at most one outcome and one evaluation **per horizon**.

The two CAP-002 pilot decisions are deliberately **not** here: they were sealed
before the provenance contract existed, so they are not campaign observations.

## Replay

```
ledger.replay(decision_id)
```

returns the exact snapshot the analyst saw, the sealed decision, every outcome
and evaluation attached to it, and a `checks` block (`decision_record_verified`,
`snapshot_digest_matches`, `provenance_complete`, `raw_evidence_present`,
`raw_evidence_hash_matches`).

The snapshot is stored inline and is enough to reconstruct the analyst input.
The raw OHLCV behind it is stored locally under `raw_evidence/` (gitignored for
size) and pinned by `raw_evidence_hash`; if the local copy is gone, replay says
so instead of pretending the evidence is present.

Research only: no orders, no credentials, no capital.
