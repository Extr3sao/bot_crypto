# Afirmaciones publicadas

Generado por `scripts/evidence004_generate.py`.

- **C-01** — 9 REA work operations were registered; 7 executed and returned an evidence_id; 2 did not execute: `import-reference-source` (unsupported_host) and `compare-source-to-bundle` (NOT_EXECUTED_INVALID_INPUT with exit code zero).
- **C-02** — 7 of those returned an evidence_id from REA.
- **C-03** — `counts.phase_v31.work.not_executed` = 2 (Operations that did not execute are listed with their execution class in RUN_REPORT.md.)
- **C-04** — Only 2 of the 7 have evidence bytes on disk whose sha256 matches the declared digest.
- **C-05** — The four dossiers together hold 12 distinct evidence_ids; this is a different denominator and is never added to the phase counter.
- **C-06** — `ev_4b2bf9c5c3135…` (REA analysed the pinned nof1 public/ tree and emitted this id.)
- **C-07** — `ev_be8c7d74bb6ed…` (REA analysed the FenixAI dist/ build produced from the pinned commit and emitted this id.)
- **C-08** — `ev_9b45318c072de…` (REA analysed Semantic Signal's static dashboard and emitted this id.)
