# FINAL REPORT — RFC-TAP-EXEC-SEC-002

**Verdict:** `P0_ORDER_AUTHORIZATION_VERIFIED_SCOPED`
**Code:** `de72ad2a` · **Verified export:** `09a44c21` · **Before:** `43e1ce2c`
**Trading:** none · **Exchange contact:** none · **Push/deploy:** none
**Status retained:** `LIVE_NO_GO`, `PRODUCTION_READY = false`

## The defect, in one sentence

P0 made the gate run, but it still let the **caller** decide whether an order was
a reduction, so a futures `CLOSE` without `reduceOnly`, a spot `sell`, a
`set-tpsl` and a `close-position` with no observable position all skipped the
ten checks — and `run --auto-trade` could dispatch live with no per-invocation
consent at all.

## What changed

**WP-01 — consent.** `run --auto-trade` in `live` or `shadow_live` now requires
`--confirm-live`. Without it: stderr, `exit 2`, zero scanner builds, zero client
constructions, zero broker calls. The sink re-checks the flag, so a direct call
that skips the CLI check is still denied. Paper/demo are unaffected.

**WP-02 — proof instead of a name.** A new classifier derives one of three
categories at the sink from the order primitive, `tradeSide`, `reduceOnly`, the
position id/side/qty/mode/freshness and the venue's real payload support:

- `PROVEN_REDUCTION` — only (a) futures `reduceOnly` + `tradeSide=CLOSE` against
  a matching, fresh, one-way position on the closing side with
  `0 < qty <= position.qty`, or (b) `flash_close_position` with an observable
  position, whose payload is `{positionId}` only.
- `OPEN_OR_INCREASE` — everything that acquires exposure.
- `UNKNOWN` — spot `sell`, `set-tpsl`, `CLOSE` without `reduceOnly`, no/zero
  position, excess quantity, wrong side, hedge/ambiguous mode, stale snapshot,
  unreadable position. It takes the same confirmation, stop and ten gate checks
  as an entry.

The proof is revalidated on the **wire payload** inside the adapter, immediately
before `_request`. Dropping `reduceOnly`, rewriting `tradeSide` or injecting a
side/size loses the exemption with zero calls. Every decision is written to
`live_order_authorizations.jsonl` with the rule, the gate verdict and a
non-sensitive settings fingerprint.

`hot_stop.py` and the ten gate checks are untouched; `hot_stop.py` is
byte-identical to `76cfca23…`.

## Evidence

| Check | Result |
|---|---|
| Baseline before any edit (`43e1ce2c`) | 113 passed / 108.00 s |
| Worktree affected suites | 190 passed / 148.70 s |
| Export suite (verifier V-20) | 182 passed / 132.86 s |
| Mutation matrix (V-21, `2d512920`) | **14/14 killed** |
| Separate verifier, before (`43e1ce2c`) | **8/21 — `NOT_VERIFIED`** |
| Separate verifier, after (`2d512920`) | **21/21 — verified** |

The before column is measured, not reconstructed. On `43e1ce2c`, a futures
`CLOSE` with no position, excess quantity, hedge mode, wrong side, a spot
`sell`, a `set-tpsl`, a dropped `reduceOnly` and an injected flash-close side
each produced **one broker call**. They produce zero after.

## What the verification proves

- All seven live sinks remain lexically inside `_live_order_boundary`; every
  call site carries `intent`, `settings`, `capabilities` and `confirm_live`; no
  `opens_risk` boolean survives.
- The boundary has no defaults for the security inputs.
- `run` refuses an unconfirmed auto-trade before the scanner, and the parser
  declares the flag.
- All ten gate checks stop the live loop with zero calls; settings errors and a
  crashing gate fail closed.
- Only the two proven shapes skip the gate; six unproven shapes do not.
- A mutated final payload loses the exemption.
- `set-tpsl` takes the gate but still works when every check passes.
- The hot stop keeps G-3's skip/exit-0 for the loop and still permits a proven
  close.
- Paper is not blocked by the live flag.

## What it does not prove

- **No exchange accepted a payload.** Every broker is a recorder. The proof is
  about the bytes the process would send.
- **Same author.** The verifier is a separate artefact with its own scenarios,
  but not a second person. Independence is procedural.
- **Hedge mode is refused, not exercised.** No hedge-mode venue was contacted.
- **G-4 (`run --demo`)** still has its own broker path with neither gate nor
  stop. That remains the largest uncovered route.
- **DEF-P0-03** (`GATE-006` and the cwd) and GATE-009/010 configuration are
  unchanged.

## Defects

Closed: DEF-P0-04, DEF-EXEC-001…006.
Open: DEF-P0-03, G-4, GATE-009/010 configuration, hedge-mode coverage.

## Reading order

1. [`WP00_RUNTIME_MAP.md`](WP00_RUNTIME_MAP.md) — what the runtime actually was.
2. [`BEFORE_AFTER.md`](BEFORE_AFTER.md) — measured behaviour, row by row.
3. [`COVERAGE_MATRIX.md`](COVERAGE_MATRIX.md) — entrypoint → category → gate → broker.
4. [`verification.json`](verification.json) and [`verification-before.json`](verification-before.json).
5. [`RUN_REPORT.md`](RUN_REPORT.md) — failures found, fixes, limitations.
6. [`ARTIFACTS.sha256`](ARTIFACTS.sha256) and [`EVIDENCE.sha256`](EVIDENCE.sha256).

## Bottom line

The live gate is no longer a claim made by a command name. Opening risk requires
consent, the ten checks and a closed stop; skipping them requires a reduction
the venue itself enforces, and that proof is checked again on the payload that
would be sent. Nothing here authorizes live trading: `LIVE_NO_GO` stands, and
G-4 still has to be closed before any global claim about paper or demo.
