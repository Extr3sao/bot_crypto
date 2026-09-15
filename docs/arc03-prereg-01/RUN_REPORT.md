# ARC03 RUN REPORT — `ARC03-PREREG-001`

> **FINAL_STATUS = `PENDING_INDEPENDENT_PREREG_VERIFICATION`**
> Builder: DeepSeek (`deepseek-v4-flash`). DeepSeek performed a **BUILDER_CROSSCHECK** only and
> **does not claim independent verification**.
>
> `ARC03_BACKTESTS = 0` · `ARC03_EXECUTIONS = 0` · `ARC03_PERFORMANCE_OBSERVED = false` ·
> `FALSE_SUCCESS = 0`

---

## 1. Location and authority

| | |
| --- | --- |
| worktree | `.research/arc03-participation-reversal-01` |
| branch | `research/arc03-participation-reversal-01` |
| data-authority commit | `8668a3174234255b1b1f27a7bf04b8f022af68bb` |
| base selection | `docs/arc03-data-authority-01/ARC03_BASE_SELECTION.json` |
| spec | `ARC03_SPEC_V1.json` — SHA256 `a69edabb2931b3897cc0bcabdb7c203009ace742af1a729e47f7cb058a407a2d` |
| manifest | `ARC03_MANIFEST_V1.json` — SHA256 `3b022693fde0a4e362329a009125292410bb1ba3d0e2b3f8571b795a15b1d1a3` |
| prereg commit | `8ebf8a181a3cfaf03737ef585f8906d28f8d419f` (`[ARC03-PREREG-001] freeze participation-shock reversal discovery`) |
| self-reference | the prereg commit carries `prereg_commit = null` and `report_commit = null` (a commit cannot embed its own SHA); the resolved SHA is recorded by the pointer commit `[ARC03-PREREG-002]` in `ARC03_PREREG_COMMIT_POINTER.json` |

Base selection required the frozen Alpha Research Universe, the current research/data
utilities, and *not* the ARC-01 execution branch, the ARC-02 worktree, the verifier-only
branches or any H6 branch. The chosen base (`367f58f`, the ARC-01 data-authority HEAD) has all
of those properties and no uncommitted cross-worktree dependency.

## 2. Data authority (four checkpoints, all PASS)

* **`ARC03-DATA-001`** — established the authority from **official** `data.binance.vision`
  USD-M 5m archives (CHECKSUM-verified). `dataset_sha256 = 1a6ad117…4745ef`, partitions
  `eb75ab97…ab02` (BTC) / `24c88690…c211` (ETH) / `d872bc7d…f548` (SOL).
* **`ARC03-DATA-002`** — resolved raw bytes against a **portable** data root and bound the
  authority commit; the verifier fails closed on a wrong root.
* **`ARC03-DATA-003`** — recorded portable verification evidence.
* **`ARC03-DATA-004`** — re-proved the authority from a **clean throwaway worktree**:
  no data root ⇒ `FAIL_CLOSED` (exit 2); certified root ⇒ `PASS` (exit 0); unit tests executed
  from that worktree so `TEST_TARGET == AUDITED_TARGET`.

Data quality findings, all disclosed in `ARC03_DATA_QUALITY_LEDGER.jsonl`: a **provider schema
change** (a header row appears from `2022-01` onward, `SOLUSDT 2022-03` excepted) detected by
exact match, and real `SOLUSDT 2022-02` / `2022-04` archive gaps filled from **official daily**
archives (no reconstruction, no third-party data).

**Reuse before download** was audited by inspecting the actual frozen bytes of every existing
candidate authority. Verdict: **nothing reusable** — every committed kline authority is 1h or
coarser, so a 5m study cannot be spliced from them.

**Funding** is reused, not re-downloaded: the ARC-03 funding partitions are **byte-identical**
(SHA256 equality) to the certified ARC-01 funding authority, and that identity is recomputed by
the reader (`matches_arc01_authority`) and by the prereg unit tests. Funding is a **cashflow
leg only** and is never an ARC-03 signal input.

## 3. Frozen economics

| Element | Frozen value |
| --- | --- |
| participation field | `volume` (base units) |
| participation shock | `v(t) > max{ v(t − 86400000·j) : j = 1..30 }`, all 30 same-5m-slot references required |
| excursion record | `high − low > max{ range(same 30 references) }` (strict) |
| exhaustion | `body > 0 ∧ (high − close) > range/2` → **SHORT**; `body < 0 ∧ (close − low) > range/2` → **LONG** (strict) |
| price context | `NONE` (OHLC is the definition, not an added filter) |
| cadence | one decision per **completed 5m bar**, at its `close_time_ms` |
| entry | OPEN of the first 5m bar with `open_time_ms > decision_time_ms` |
| exit | OPEN of the bar at `entry_open_time_ms + 3600000` |
| holding | exactly **12 bars = 60 minutes** (single primary horizon) |
| stop / cooldown | `NONE` / `NONE` |
| overlap | `SKIP` while open; no queue, no pyramiding; assets independent, max one position per asset |
| costs | primary **10 bps** round trip; frozen scenarios `0/10/20/40` on an **identical** trade set |
| funding cashflow | `sum(−direction_sign · funding_rate)` over certified settlements in `(entry, exit]`; **settlement count never assumed** |
| accounting | `NET = GROSS + FUNDING − COST` |

`NO_SIGNAL` is first-class with a frozen seven-reason precedence, and the funnel accounts for
every evaluated decision.

## 4. Critical gates and controls

`G1` sample · `G2` net expectancy · `G3` ex-funding expectancy · `G4` profit factor ·
`G5` Sharpe · `G6` bootstrap · `G7` permutation · `G8` temporal stability · `G9` asset
stability · `G10` concentration · `G11` cost sensitivity — **all required**.

Controls: `DIRECTION_CONTROL`, `TIMING_CONTROL`, `PARTICIPATION_CONTROL`, `NULL_CONTROL`.
If **any** required control satisfies **all** critical gates ⇒ `DISCOVERY_FAIL` (mechanism not
identified). Controls cannot change the primary trade set, thresholds or direction, and are never
promotable.

Unlike ARC-01, **every estimator convention is written out in full** in
`ARC03_STATISTICAL_GATES.json` (ddof, the annualization factor and its fixed window span, the
bootstrap statistic / resampling unit / index formula / draws / seed, the permutation statistic /
sidedness / p-value formula / draws / seed, split boundaries, and concentration attribution
including its zero-denominator behaviour and UTC entry-month convention). The prereg is
reproducible from the frozen spec alone; the pre-existing project statistical module is cited
as corroboration only.

## 5. Verification evidence

| Check | Result |
| --- | --- |
| `A_B_DETERMINISM` | PASS |
| `MUTATION_SENSITIVITY` | PASS |
| `PIT` (independent adversarial battery) | PASS |
| portable data verifier (wrong root) | `FAIL_CLOSED` exit 2 |
| clean-worktree data verification | PASS |
| `scripts/validate_arc03_spec.py` | `ARC03_SPEC_COMPLETE = PASS` (11 checks, 0 failures) |
| `scripts/verify_arc03_prereg.py` | PASS (certified root) / `FAIL_CLOSED` (wrong root) |
| `tests/unit/research/test_arc03_prereg.py` | 28 passed |
| `POST_FREEZE_ARTIFACT_DRIFT` | 0 |

## 6. Kill rule

```
ONE PREREGISTRATION  →  ONE PRIMARY DISCOVERY
```

Any critical gate failure, an insufficient sample, or a control satisfying all gates ⇒
`ARC03 = DISCOVERY_FAIL` (terminal). No threshold, lookback, holding-period or asset retuning,
and no rerun under this `hypothesis_id`. Any variant requires a `NEW_HYPOTHESIS_ID` and a
`NEW_PREREGISTRATION`.

## 7. Disclosed defects and limitations

* `DEF-ARC03-PREREG-001` (NON_BLOCKING, DOCUMENTATION): the spec names the participation field
  `v` (partition key) where the provider field is index 5; the mapping is stated in the data
  authority and the reader, with no economic ambiguity.
* No critical gate covers **drawdown**; it is a diagnostic only, disclosed so no threshold is
  invented after seeing a result.
* The H5 collision check (ARU kill rule) is **staged immediately after** discovery, because
  measuring it requires economic observation.
* Two **HIGH** residual risks are disclosed in `ARC03_FAILED_MEMORY_COLLISION_REVIEW.md`: the
  5m per-trade cost hurdle (failed-memory #1) and the secular-uptrend short-fade (failed-memory
  #10). They are not argued away.

## 8. Next

```
NEXT = ARC03_INDEPENDENT_PREREG_VERIFICATION
```
