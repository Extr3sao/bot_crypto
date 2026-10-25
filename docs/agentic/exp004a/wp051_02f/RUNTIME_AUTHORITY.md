# WP-051-02F — runtime authority map

> What this package is allowed to run, what those programs write, and which document makes each
> of them the authority. Written from the repository, not from a report: every hash below was
> recomputed in this checkout at `2026-10-22T14:17:39Z`.

## 1. The checkout this map describes

| Field | Value |
|---|---|
| `pwd` | `/c/Users/GVLLFR0035/Downloads/bot freebuff` |
| branch | `agent/ai-bots/RFC-TAP-AI-BOTS-003` |
| HEAD when the attempt ran | `f20dff9b71fd10a5f110ab6cae88e817c6f5d428` |
| worktree | dirty, 274 tracked-or-new entries, most of them other work packages |
| test target | this checkout (`TEST_TARGET == RUNTIME_TARGET`) |
| python | the repository's `.venv` |

The dirty tree is reported, never cleaned: this package shares the checkout with other work
packages and reverting their files is not its business.

## 2. The three declared commands, located

The declaration is the only source of the commands; none is retyped by hand.

| Dataset | Declared command (verbatim from the declaration) |
|---|---|
| `EXP-004A-1H-BTC` | `python scripts/exp004a_capture.py --slice 1h:BTC` |
| `EXP-004A-1H-ETH` | `python scripts/exp004a_capture.py --slice 1h:ETH` |
| `EXP-004A-1H-SOL` | `python scripts/exp004a_capture.py --slice 1h:SOL` |
| `EXP-004A-ST6-TAPE` | `python scripts/exp004a_capture.py --slice st6:tape` — **deferred**, not a bar series |

`EXP-004A-ST6-TAPE` declares `timeframe: "4h slot, 3 rounds of 15s"`, which is not a bar
interval and for which the freeze defines no round-to-window rule. The extractor refuses it with
exit 2 and this package records the refusal instead of inventing a slice.

**Exit vocabulary of `scripts/exp004a_capture.py`** (`EXIT_*` in that file):

| Code | Meaning |
|---|---|
| 0 | `OK` — a dataset was written |
| 2 | `CONTRACT_REFUSED` — the declaration or the slice contract refuses |
| 3 | `NO_ELIGIBLE_BARS` — an empty selection is not a dataset |
| 4 | `SOURCE_UNREADABLE` — the store could not be read |
| 5 | `NOT_ELIGIBLE` — every candidate failed eligibility |

Only `4` is worth a retry; `2`, `3` and `5` are decisions. Exit `0` without a file on disk is the
false success the failure matrix names, and the runner records it as `EXIT_WITHOUT_OUTPUT`.

## 3. The authorised observation, located

The declaration names its provider as *"Binance public REST /api/v3/klines via the WP-EDGE-03
forward observer"*. That observer is reachable through exactly one documented entry point,
`scripts/edge04_observer.py`, whose docstring states that the tick itself lives in
`trading_bot.research.edge03.autonomous` and that the file only parses arguments, builds the
observer and returns the outcome's exit code. It writes the series this package reads:

```
data/forward/edge03/1h/{BTC,ETH,SOL}.jsonl
```

Its exit vocabulary is not the extractor's (0 observed/no-new-data, 1 runtime exception,
2 already running, 4 missing bars, 5 disk budget, 6 verification failed, 7 provider
unavailable). The runner reports the observer's exit and then reads the store regardless, because
the freshness check — not the observer's self-report — decides whether a bar is present.

No second market-data source is introduced. `--skip-observation` exists only for rehearsals and
fixtures; it never fetches a bar.

## 4. The declared freeze, anchored

| Item | Value | Where the value comes from |
|---|---|---|
| `config/preregistrations/EXP-004A.datasets.phase2.json` sha256 | `eb27cedc2626844daba9c82915c9258687e20072b774ca564142993ed6e7c01e` | recomputed here |
| the same file's Git blob | `a179ed0d74bfc5fd00383b2d575c9949ca6e1f95` touch; blob read from `HEAD:` | `git log`/`git rev-parse` |
| phase-1 declaration sha256 / blob | `8946f871…` / `43c9deea…` | named by the successor declaration, re-hashed |
| `generator.blob_sha256` | `af1ab7cc23980dadac83ba53d2a5f8c1c5f33f6b5dd4841dd58620b9bb421cb8` | the declaration |
| `generator.commit` | `fc036d967923f09a6092cb0e5de7409afd07ebd7` | the declaration |
| window | `[2026-10-22T00:00:00Z, 2027-01-20T00:00:00Z)` | the declaration, read at runtime |
| `effective_from` | `2026-10-21T16:00:00Z` | the declaration, read at runtime |

The runner carries no copy of any of these numbers. RFC §5.5 asks for a check of Git objects
against the working tree; the difference between a SHA-256 of the checkout and a Git blob id is
reported as two fields with a written note, never presented as one value.

## 5. Side effects of the delegated programs

A program presumed read-only is not read-only until its writes are located. Each program is
invoked with an output directory under this package, so the sealed `02D` and `02E` directories
are read and never written.

| Program | Writes | Where this package points it |
|---|---|---|
| `scripts/edge04_observer.py` | `data/forward/edge03/…`, its own state root, its ledger | its own documented state root (unchanged) |
| `scripts/exp004a_wp051_02e_preflight.py` | `WP_051_02E_PREFLIGHT.json`, `WP_051_02E_BASELINE.json`, `EVIDENCE_MANIFEST.json`, `WP_051_02E_CAPTURE_REPORT.json`, `EVIDENCE/` | `--out-dir <package>/evidence/<run_id>/reused_preflight` |
| `scripts/exp004a_capture.py` | `data/exp004a/<id>.jsonl` and `data/exp004a/<id>.MANIFEST.json` | the paths the declaration names |
| `scripts/exp004a_wp051_02e_verify.py` | its JSON verdict and probes, under a temporary directory | `--out <package>/evidence/<run_id>/reused_preflight/02E_REVERIFIED.json` |
| `scripts/exp004a_wp051_02f_verify.py` | `INDEPENDENT_VERIFICATION.json` inside the run directory | `<package>/evidence/<run_id>/` |

The extractor writes a dataset once and refuses to regenerate it (exit 2). The runner therefore
treats an existing dataset as `ALREADY_PUBLISHED` and does not invoke the extractor over it.

## 6. What this package is not allowed to run

No orders, no broker, no paper session, no risk change, no promotion, no credentials, no second
provider. `economic_executions` is `0` in every artefact this package writes, and the verifier
checks that both the runner and itself import neither `trading_bot.paper` nor
`trading_bot.execution` and mention no order-placing call.
