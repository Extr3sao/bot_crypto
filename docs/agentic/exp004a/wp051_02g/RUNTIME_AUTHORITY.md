# WP-051-02G — who is authorised to do what

> Written by the package, read by a reviewer. It answers one question for every artifact: *which
> program may produce it, and which program may only read it?* A package whose builder can also
> certify has no independent verification, whatever its file names say.

## The programs

| Program | Authorised to | Forbidden to |
|---|---|---|
| `scripts/exp004a_wp051_02g_capture.py` (`capture/EXP-004A/WP-051-02G`) | read the declaration and the forward store; plan a shard; write a shard once; write the scheduler watermark; write the consolidated dataset; write its own run report | write beside a shard that already exists; delete a shard; rewrite a manifest; claim `CAPTURED_VERIFIED`; place an order; touch `wp051_02b`..`wp051_02f` |
| `scripts/exp004a_wp051_02g_verify.py` (`verifier-g/EXP-004A/WP-051-02G`) | read everything; recompute every digest, lag and denominator; write one verdict file and nothing else | import the builder, the engine or `trading_bot`; repair a defect; promote a claim; overwrite a claim |
| `src/trading_bot/research/prospective/incremental.py` | pure functions over paths and bytes injected by the caller | hold state, read the clock on its own, touch the network |
| `scripts/exp004a_capture.py`, `scripts/exp004a_wp051_02e_*`, `scripts/exp004a_wp051_02f_*` | nothing in this phase | being modified: their bytes are compared with `HEAD` by the verifier on every run |

## What each artifact is, and who owns it

| Artifact | Produced by | Read by | May be rewritten? |
|---|---|---|---|
| `config/preregistrations/EXP-004A.datasets.phase3.json` | a human, once, before the window opened | both programs | no |
| `data/exp004a/phase3/<interval>_<asset>/<YYYY-MM-DD>.jsonl` | the builder | the verifier, byte for byte | never |
| `…/<YYYY-MM-DD>.MANIFEST.json` | the builder | the verifier | never |
| `data/exp004a/phase3/**/consolidated/<run_id>.jsonl` | the builder, from the shards | the verifier | no; a new run writes a new file |
| `data/exp004a/phase3/**/state/scheduler.json` | the builder | the builder | yes — it is a watermark, not evidence, and the verifier never opens it |
| `docs/agentic/exp004a/wp051_02g/evidence/<run_id>/RUN_REPORT.json` | the builder | the verifier | no |
| `docs/agentic/exp004a/wp051_02g/evidence/<run_id>/INDEPENDENT_VERIFICATION.json` | the verifier | a reader, `--seal` | no; re-verification writes its own file |
| `docs/agentic/exp004a/wp051_02g/RUN_REPORT.json` | `--seal`, from one run | a reader | only from the same run id |
| `docs/agentic/exp004a/wp051_02g/EVIDENCE_MANIFEST.json` | `--seal` | a reader | regenerated on re-seal, never merged |
| `docs/agentic/exp004a/wp051_02g/FINAL_REPORT.md` | a human | a reader | no |

## The words that are reserved

* `CAPTURE_COMPLETE_AWAITING_VERIFICATION` — the builder's strongest state. It says bytes were
  written; it says nothing about whether they are right.
* `PASS_COVERAGE_COMPLETE` / `PASS_COVERAGE_INCOMPLETE` / `PASS_PENDING_WINDOW_OPEN` / `FAIL` — the
  verifier's only verdicts, computed from the declaration, the store and the shards.
* `certification_allowed` — true only for a **prospective** run whose every declared bar verified.
  A rehearsal can reach `COVERAGE_COMPLETE` and still carry
  `certification_blocked_by: REHEARSAL_IS_NOT_EVIDENCE`.
* `COVERAGE_COMPLETE` — reachable only when `admissible_rows == declared_rows` exactly. The
  declaration's `coverage_required: 0.9` is a floor for adjudication, not a licence to certify a
  short dataset.

## What this package does not authorise

No live trading, no paper orders, no order entry point, no credential, no risk limit, no promotion,
no certification of EXP-004A. `economic_executions` and `orders_placed` are `0` in every report and
`live_trading` is `DISABLED`; the verifier re-reads those fields and refuses a report that moves
them.
