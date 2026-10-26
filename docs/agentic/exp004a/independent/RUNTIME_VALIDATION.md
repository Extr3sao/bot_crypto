# Runtime validation — what was executed, where, and with which exit status

Every row below was run by `scripts/exp004a_verify.py` in the same process as the report it belongs
to, except the two probes marked *(separate)*, which were run by hand and are recorded as
observations. No command writes outside `docs/agentic/exp004a/independent/`.

**Environment:** win32 · Python 3.11.15 · `C:\...\bot freebuff\.venv\Scripts\python.exe` ·
source and evidence root `C:\...\bot freebuff` · head `881f0610` · 263 dirty entries (none owned by
this mission) · 21 registered worktrees.

## Commands

| # | Command | Exit | Effect / observation |
| --- | --- | --- | --- |
| 1 | `python -m trading_bot.research.prereg_gate --repo . --manifest config/preregistrations/EXP-004A.json --registry config/preregistrations/EXP-004A.datasets.json --experiment-id EXP-004A --mode inspect --json-out <tmp>` | **3** | `INSPECTION_ONLY_NO_RUN`, 0 defects, `economic_executions=0` |
| 2 | same, `--mode authorize` | **2** | `BLOCKED`, exactly `TWO_PHASE_PHASE_1_IS_NOT_AUTHORISABLE` |
| 3 | `python scripts/exp004a_foundation.py --skip-seal --out <tmp>` (twice) | **0**, **0** | 159.0 s and 148.2 s; identical stdout digest; ledgers unchanged |
| 4 | `git worktree add --detach <tmp> 47116b2` then `worktree remove` | **0** | both ledgers reproduce byte for byte; no `data/forward/edge03` in the checkout |
| 5 | `python -m pytest <6 EXP-004A suites> -q` | **0** | **128 passed, 1 skipped** (223.98 s) |
| 6 | `python -m pytest tests/unit/research/test_exp004a_verify_adversarial.py -q` | **0** | **20 passed** (23.53 s) |
| 7 | junction control: `cmd /c mklink /J <root>/config/escape <outside>` | **0** | link reaches the file; containment refuses it; positive control inside passes |
| 8 | `python -m ruff check` / `python -m mypy --strict` on the verifier | **0** / **0** | clean; `mypy` strict is the repository's configured mode |
| 9 *(separate)* | `python scripts/exp004a_foundation.py --skip-seal` under a 180 s external timeout | **124** | first probe, under load: exceeded 180 s. Re-run inside the audit finished in 159 s — recorded as evidence that the replay is load-sensitive, which is why it is budgeted rather than unbounded. |
| 10 *(separate)* | gate probe with the **default** registry path | **2** | three registry errors plus `TWO_PHASE…`: a harness defect, fixed at #1. Kept in the record on purpose. |

## `TEST_TARGET == RUNTIME_TARGET`

The verifier does not re-implement the gate, the foundation measurement or the admission classifier
and then call that a verification. It:

- executes the real gate module as a subprocess, with the manifest and registry the manifest itself
  names, and compares exit codes, error lists and check lists;
- executes the real measurement entrypoint for the idempotency claim and compares what it produced;
- recomputes admission, digests and cost arithmetic **itself**, from bytes, and then states where
  the builder's numbers disagree — it never asks the builder's classifier what a day is.

## Runtime reachability

`prereg_gate` is reachable and returns its documented codes (`3` inspect, `2` authorize).
`scripts/exp004a_foundation.py` is reachable and exits `0` with `--skip-seal`. Both the 1h and
15m bar stores are present and readable; the cost tape is present (`912` rows, `3d5755d7…`).
The gitignored stores are absent from a clean checkout by design, and that is reported as a limit
rather than a failure.

## Budgets and failure behaviour

| Resource | Limit | Behaviour at the limit |
| --- | --- | --- |
| Measurement replay | 300 s per run (`EXP004A_REPLAY_TIMEOUT`) | process tree killed, claim reported `BLOCKED / IDEMPOTENCY_NOT_REPLAYED` |
| Gate / tests / acceptance | 300 s / 1800 s / 900 s | non-zero timeout propagates as `ERROR` (exit 4), never as `PASS` |
| Verifier output | `docs/agentic/exp004a/independent/` only | `OUTPUT_ROOT_FORBIDDEN` if pointed at `data/`, `reports/ai-bots/` or `evidence/` |

A timeout is not evidence of success. `_run_bounded` redirects the child's output to a file because
`subprocess.run(capture_output=True, timeout=…)` can hang forever waiting for a pipe that a
grandchild still holds — that failure mode was observed twice during this audit and is covered by
`test_a_timeout_is_reported_as_a_budget_not_as_idempotence`.

## Isolation

`check_write_isolation` hashes every builder-owned artifact before the audit and again at the end:
the two admission ledgers, the four gate files, the handoff directory, the cost tape, the three
preregistration manifests and RFC-050. Result: **0 files changed**. The bar store is excluded from
the mutation check for a deliberate reason — it is appended by the forward observer, so the correct
assertion is that the sealed prefixes still verify (786/786 do), not that the file stops growing.
