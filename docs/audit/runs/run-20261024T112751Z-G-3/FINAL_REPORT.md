# G-3 — FINAL REPORT

**Verdict: `G3_VERIFIED_SCOPED`.** The live execution paths that exist today are
enumerated, gated, and demonstrated blocked while a stop is in force — with the
reduction paths deliberately left open so the stop cannot trap the book.

## What is now true

1. **The stop reaches the live program.** `trading-bot run --mode live
   --auto-trade`, `place-order`, `close-position` and `set-tpsl` construct
   `HotStopGate` and consult it at dispatch. A `KILL_SWITCH` written by
   `trading-bot kill-switch --engage` now stops them, not just the autonomous
   paper runtime.
2. **Restart inherits it.** The gate is built from a stable run directory
   (`data/live` by default) before the first iteration; a second process over the
   same directory boots engaged and logs `restored`.
3. **Fail-closed.** An unreadable marker, an authority that raises, a lock
   timeout, and `KILL_SWITCH_ENV` all refuse. Refusal never writes an enabling
   state.
4. **The structure is enforced.** Seven sink call sites, seven
   `_live_order_boundary` calls; a test scans the AST and fails if a sink escapes
   or if the `opens_risk` classification is omitted. A new order path cannot be
   added quietly.
5. **It is falsifiable.** Six mutants remove one property each; all six are
   killed by the suite. A verifier re-derives the properties from an exported
   commit and passes 15/15.

Numbers: **21** focal tests, **426** tests in the verifier export, **6/6**
mutants, **15/15** checks, **0** broker calls under a stop, **1** in the control.

## What is not true

- **Not account-wide.** The stop is scoped to a run directory. `--run-dir`
  elsewhere, or a fresh checkout, boots operational. G-1's limit is now shared by
  three gaps and closed by none.
- **Not preemptive.** A marker written by another process is honoured by the next
  dispatch; a call already on the wire completes. Same guarantee as G-2, no
  stronger.
- **Not G-4.** `run --demo` still reaches `PaperBroker` through `paper_cycle.py`
  without `DecisionEngine`. G-3 did not touch it and does not estimate its risk.
- **Not live-tested.** No exchange was contacted; every sink is a recorder.
- **Not `PRODUCTION_READY`.** No such claim is made or implied.

## Defects this run surfaced

- **DEF-G3-01:** G-2 left `test_app_demo.py` asserting that `kill-switch` does not
  exist, so the suite has been red since G-2 — outside every evidence set G-2
  ran. Fixed here.
- **DEF-G3-02:** the first verifier run failed V-10 on a byte-identical file
  because `git show` was decoded through the Windows code page. Fixed by
  comparing bytes; the failure is in TIMELINE.md.
- **DEF-G3-03 (open):** `LiveTradingGate` is dead code; `run --auto-trade`
  performs none of its ten checks. Admission policy, not stop coverage — out of
  scope by design.

## Recommendation for G-4

G-4 is now the only open gap, and it is the bigger one. Concretely:

1. **Measure first, with the same instrument.** Add a `paper_cycle` entrypoint to
   `scripts/audit/g3_live_probe.py` (the probe already patches at the module
   level) and produce the same
   `ENTRYPOINT → PATH → BOUNDARY → STOP → SINK` matrix for the paper program
   before changing anything. Expect one sink (`paper_cycle.py:510`) and one
   ungated decision path.
2. **Decide the shape, not just the gate.** There are two defensible fixes:
   (a) put `HotStopGate` at `paper_cycle`'s broker call, which is cheap and
   leaves two decision paths in place; or (b) route demo trading through
   `DecisionEngine`, which removes the duplicate path but rewrites the demo flow.
   (b) is the better end state; (a) is the smaller change and should not be
   mistaken for (b).
3. **Reuse the triad.** `g3_live_probe.py` + `g3_mutants.py` + `verify_g3.py`
   generalise: one new entrypoint, four mutants (gate removed, entry/reduction
   inverted, run-dir randomised, lock dropped), and a verifier that re-derives
   from the export.
4. **Do not extend G-3's claim.** G-3 verified the live entrypoints that exist at
   `9eeb8e87`. A paper gate installed later needs its own contract and its own
   verdict.

## Evidence

- [G-3.md](../../G-3.md) — contract and coverage matrix.
- [RUN_REPORT.md](RUN_REPORT.md) — measurements, tests, mutants, verifier, limits.
- [RUN_REPORT.json](RUN_REPORT.json) — machine-readable result and hashes.
- [verification.json](verification.json) — 15/15, `G3_VERIFIED_SCOPED`.
- [COMMANDS.md](COMMANDS.md) — every command with its real output.
- [COMMITS.md](COMMITS.md) — the commit chain and why in that order.
- [TIMELINE.md](TIMELINE.md) — chronology, including the runs that failed.
- `evidence/` — before/after probe matrices and the red test outputs.
