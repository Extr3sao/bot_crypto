# COST_BARRIER_RUNTIME_AUTHORITY — WP-7A audit

> Who can change a published cost-barrier number, what would notice, and what
> nothing in this repository can notice. Written from the artefacts and the code
> as they are, not from how they are described. Baseline: `main` at `38b8e18`
> (the WP-6 drift gate). Everything below was measured on that tree; the WP-7
> changes are marked where they close a gap, and the residual gaps are stated
> rather than papered over.

## 1. Method

| step | what was done | result |
| --- | --- | --- |
| identify HEAD and tree | `git log`, `git status --porcelain` | `38b8e18` on `main`; 81 dirty entries, none of them this lane's until WP-7 wrote its own files |
| audit entrypoints | read the four lane scripts and the workflow | WP-6 gate (784 lines), builder (1171), verifier (521), workflow (102) |
| audit inputs | `git ls-files --error-unmatch` per declared input, plus digests | 9 declared inputs: 4 tracked+pinned, 1 gitignored+pinned, 4 tracked+unpinned producers |
| audit authority | compared pins with bytes; re-ran the tools | pins reproduce; verifier 4/4 checks, 13/13 mutation controls |
| attack the wiring | 17 attacks on isolated copies (WP-7D) | **3 escaped the WP-6 gate** (A07, A08, A17); each is addressed below, and the two remaining gaps are declared |

Nothing was redesigned that already worked: the builder, the verifier and the
published artefacts of WP-6 are byte-identical to `38b8e18` in this lane.

## 2. Entrypoints and interfaces (real, as declared by `--help` and by the code)

| entrypoint | role | interface | writes |
| --- | --- | --- | --- |
| `scripts/cost_barrier_explorer.py` | builder of the explorer artefact | `[--out-dir DIR] [--check]` | `COST_BARRIER_EXPLORER.{json,md}` (or `DIR/`) |
| `scripts/cost_barrier_verify.py` | independent verifier (never imports the builder) | `[--explorer PATH] [--out PATH] [--json]` | `COST_BARRIER_VERIFICATION.json` (or `PATH`) |
| `scripts/cost_barrier_gate.py` | drift gate: pins, re-derivation, re-run, contract | `[--check] [--strict] [--json] [--report PATH] [--explorer|--verification PATH]` | nothing but `--report` |
| `scripts/cost_barrier_evidence.py` | **WP-7**: verify/capture/materialize the evidence bundle | `[--capture] [--materialize] [--json] [--report PATH]` | the evidence bundle; the gitignored input under `--materialize` |
| `scripts/cost_barrier_adversarial.py` | **WP-7**: 17 attacks on isolated copies | `[--gate-source PATH] [--label] [--only ID] [--workdir] [--out] [--report] [--json]` | its own reports |
| `scripts/cost_barrier_certify.py` | **WP-7**: certification gate | `[--out PATH] [--json] [--workdir]` | `COST_BARRIER_CERTIFICATION.json` |

Runtime dependencies are stdlib only (`hashlib`, `json`, `subprocess`,
`fnmatch`, `platform`) plus the executable cost model the runtime itself uses,
imported through `src/trading_bot/research/microstructure/cost_model_v3.py`. The
gate reads its own activation contract with a line scanner rather than PyYAML, so
a missing parser cannot silently disable that check.

## 3. The nine declared inputs

| # | path | role | tracked | bytes | pin | authority of the pin |
| --- | --- | --- | --- | ---: | --- | --- |
| 1 | `config/strategy_admission.json` | the only source of "may this run PAPER?" | yes | 28 172 | `6c4dd0be…` | artefact `sources[]`, then the commit that carries it |
| 2 | `src/trading_bot/research/microstructure/cost_model_v3.py` | the executable cost model every line is evaluated with | yes | 32 463 | `bc7e2753…` | idem |
| 3 | `docs/COST_MODEL_V3.json` | venue scenarios and knowledge classes | yes | 28 651 | `2f0e62d2…` | idem |
| 4 | `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` | the 24 cells and their zero-cost gross edge | yes | 200 987 | `31fc6d4f…` | idem |
| 5 | `reports/strategy-baseline/COST_BARRIER.json` | market-horizon medians | **no (gitignored)** | 3 822 | `2437f446…` | idem, plus the WP-7 evidence copy |
| 6 | `scripts/active_economic_audit.py` | producer of input 4 | yes | 62 292 | WP-7 manifest | `data/recovery/wp7/evidence/PRODUCER_PINS.json` |
| 7 | `scripts/cost_barrier.py` | producer of input 5 | yes | 4 233 | WP-7 manifest | idem |
| 8 | `scripts/cost_barrier_explorer.py` | builder of the artefact | yes | 55 446 | WP-7 manifest | idem |
| 9 | `scripts/cost_barrier_verify.py` | independent verifier | yes | 23 599 | WP-7 manifest | idem |

Input 5 is the whole problem of this work package: it is the **only** declared
input that is neither committed nor recoverable in a clean checkout, because its
own inputs (`reports/strategy-baseline/data/*.json`, the cached bar datasets) are
gitignored too. Everything else travels with the commit.

## 4. The provenance chain, and where each link is recorded

```
        inputs 1-4 (tracked)          input 5 (generated, gitignored)
                │                              │
                │                              └── producer 7 ──► cached bars (not in git)
                ▼
   producer 6 ──► input 4 ──┐
                            ├──► BUILDER (8) ──► COST_BARRIER_EXPLORER.json ──► payload_sha256
   inputs 1,2,3,5 ──────────┘                          │                │
                                                       │                └──► pins of inputs 1-5 in sources[]
                                                       ▼
                                   VERIFIER (9) ──► COST_BARRIER_VERIFICATION.json
                                                       │   (recomputes from inputs 1-4 and the model;
                                                       │    13 mutation controls, cross-pinned to payload_sha256)
                                                       ▼
                                     GATE ──► re-runs 8 and 9, compares field by field
                                          ──► checks pins, producer digests, market-horizon re-derivation,
                                              the activation contract and its own six controls
```

Recorded identities in the published artefacts: the explorer carries
`payload_sha256` (`da4ab061…`) plus `head` = `dfeb140f2572` (the commit it was
built on); the verification carries `head` = `c9eeb61d301c` and names its two
subjects. The gate's report carries `head`, `branch`, `environment`
(python, implementation, platform, machine), its own `gate_sha256` and the
digests of everything it read.

## 5. What could change a published result without activating the workflow

Measured by the WP-7D sweep against the gate as committed at `38b8e18`: **14 of
17 attacks detected, 3 escaped** — A07, A08 and A17, all three for the same
structural reason. Each row below is a real run, not a hypothesis.

| vector | concrete attack | on the WP-6 gate | status after WP-7 |
| --- | --- | --- | --- |
| A07 an unpinned producer edited | `scripts/cost_barrier.py`: `BASE 12.0 -> 11.0` | **escaped, both modes** (`status PASS`, exit 0): no digest in the tree changes | detected (producer pins) |
| A08 builder and result modified together | builder edited, then re-run to regenerate artefact *and* attestation | **escaped, both modes**: the tree is self-consistent, every digest matches, the builder reproduces its own lie | detected (producer pins) |
| A17 CI path filters pruned | the cost model removed from both filters | **escaped, both modes**: nothing in the repository reads the workflow | detected (activation contract) |
| A14 dependency path altered | cost model moved, every citation rewired, artefact and manifest re-pinned | detected **incidentally**: the reroute left the tools erroring (builder exit 1, verifier exit 1) rather than any check naming the real problem - adequate detection, wrong witness, and nothing stops a more careful reroute | detected by a *named* check: `ci:activation_contract_covers_every_declared_input` |
| A01/A02 a published number edited, with or without an honest re-hash; A13 the same defect with every off-switch set | `cells[0].zero_cost_gross_bps +5 bps` | detected in both modes (self-hash, and the verifier's own re-derivation) | unchanged; A13 adds a two-sided invariance leg proving the hostile knobs change no verdict in either direction |

Detected by the WP-6 gate already, and still detected: A03 cost model edited,
A04 ledger edited, A05 pin substituted with a valid digest from another file,
A06 input removed (blocked in full mode), A09 published verdict rewritten, A10
negative controls fabricated, A12 content+EOL change, A15 partial dressed as
full.

A16 (a derived market-horizon row edited with an honest re-hash) is the one case
the WP-6 gate would have missed in check mode: the independent verifier never
reads the market-horizon source. It is listed here rather than in the escape
column because the WP-7 sweep is what measures it, and the gate now re-derives
the section itself.

One correction about the harness itself, kept because it is instructive: its
first version "attacked" `cells[0].zero_cost_gross_bps` with a literal that
happened to equal the published value, so nothing changed and the WP-6 gate
"passed". The sweep now fingerprints the sandbox before and after every mutation
and refuses to count an unchanged tree as an attack; the corrected run is the one
reported above.

Two structural facts behind the escapes:

1. **Pins only cover what someone thought to pin.** The four producers had no
   digest anywhere, so editing them left every recorded hash in the tree
   unchanged, and a builder that regenerates its own artefact reaches a state
   where *every* recorded digest is consistent with a lie. That is the single
   largest hole and it is closed by `PRODUCER_PINS.json` (WP-7E).
2. **The independent verifier never reads the market-horizon input.** Its
   subjects are the explorer and the audit (inputs 1-4 + the model). The
   `horizon.market_horizon` section was therefore attested only by full
   reproduction: an honestly re-hashed row passed check mode. The gate now
   re-derives all twelve rows and the published lines from the pinned source
   itself (WP-7D, check `source:market_horizon_rows_match_the_pinned_source`).

## 6. What nothing in this repository can notice

| residual gap | why | how it is surfaced |
| --- | --- | --- |
| a party who can rewrite the artefacts, the evidence bundle, the producer manifest **and** `scripts/cost_barrier_gate.py` in the same commit | the checker verifies the pins; nothing verifies the checker | stated as a limitation in the CI design; the manifest explicitly refuses to pin the gate because a pin the checker checks against itself is vacuous |
| a party who can rewrite the git history or force-push `main` | the trust anchor is the commit | declared: the pin authority is "the commit that carries it", which assumes review and branch protection |
| the WP-3 audit's own economic content (whether 8.912 bps is the right number) | the lane treats the audit as the primary source of the cells | out of scope: WP-3 owns that; the gate only holds the explorer to the audit's published values |
| the cached bar datasets behind input 5 | not committed, not reproducible from the repo (need network) | the evidence copy is byte-identical to what the artefact was built from; regenerating the *input itself* remains outside CI and is declared as such |
| a malicious GitHub Action or a compromised runner | infrastructure, not repository state | declared: CI is evidence, not proof against the runner |

## 7. Authority summary

* **The pin authority** for inputs 1-5 is the published artefact's own
  `sources[]`; for the four producers it is the manifest; for both, the
  *authority behind the pin* is the commit that carries it (reviewed, path
  filtered, re-verified in CI). There is no external authority, no signature and
  no second party.
* **The result authority** is the explorer artefact (`payload_sha256`), attested
  by the independent verifier, reproduced by the gate, and recorded in the
  certification record together with the commit and the environment.
* **No component in this lane authorizes anything.** `claims` is `false` / `0` /
  `NOT_AUTHORIZED` in every document, promotion is never claimed, and the gate
  only checks for the *continued falsehood* of those claims, never for truth.
