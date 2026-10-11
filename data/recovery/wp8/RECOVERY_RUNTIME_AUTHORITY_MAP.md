# RECOVERY_RUNTIME_AUTHORITY_MAP — WP-8B

> What every input of the ACTIVE recovery lane is, **what authority its bytes answer to**,
> and which of the lane's published artefacts change when it moves. Built by reading the
> three programs (`campaign_state_view.py`, `active_economic_audit.py`, `recovery_verify.py`)
> and tracing every read, then checking each one against `git`: tracked at HEAD, ignored by
> design, or owned by another lane.

The one sentence version: before WP-8 this lane's published numbers were a function of
*which files happened to be on the machine*, and after it they are a function of *the commit*.

---

## 1. Why a map was needed

Three programs read inputs and publish derived artefacts that a governance decision rests
on:

| program | publishes | reads (before WP-8) |
| --- | --- | --- |
| `scripts/campaign_state_view.py` | `data/recovery/CAMPAIGN_STATE_VIEW.json` | 11 declared sources + `data/st6/ST6_HEALTH_STATUS.json` + `PAPER_DATA_24H_REPORT.json` + `data/raw/alpha001/*` (pins) |
| `scripts/active_economic_audit.py` | `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` | 17 declared sources, 4 of them under gitignored `reports/` |
| `scripts/recovery_verify.py` | `data/recovery/INDEPENDENT_VERIFICATION.json` | the same 17 sources plus the published artefacts |

"Reads X" was not a declared property: it was `ROOT / path` and `if path.exists()`. Four of
those reads landed on untracked files and four on gitignored ones, and every digest was taken
over raw bytes.

## 2. The authority classes

Declared once, in `scripts/recovery_input_evidence.py`, and used by all three programs.

| class | meaning | how it is resolved | why |
| --- | --- | --- | --- |
| `COMMITTED` | tracked at HEAD | `git show HEAD:<path>` | an uncommitted edit must not enter a certified state, and a clean checkout must see the same bytes |
| `EXTERNAL_GENERATED` | gitignored local research output | the byte-identical evidence copy the repository carries, admissible only while it reproduces the digest the published artefact recorded | the findings must reconstruct where the original does not exist |
| `EXTERNAL_LIVE` | another lane's live state file | the dated snapshot the repository carries; the live file is an **observation** | a file rewritten on another lane's schedule cannot be part of a certified state |
| `EXTERNAL_DATASET` | gitignored raw input pinned by a frozen manifest | graded when present, `LOCAL_MATERIALIZATION`; absent is a materialization note | not needed to reproduce any finding, so its absence is not a contradiction |

Digest convention: `sha256_lf` and `sha256_crlf` are the authorities and the raw-bytes
`sha256` is informational. `core.autocrlf=true` in this repository rewrites line endings on
checkout, so a raw-bytes pin cannot be satisfied in two checkouts of one commit.

## 3. The map

Eight inputs are declared, with the role, the required-ness, the authority and the evidence:

| input | class | required to reproduce a finding | authority | evidence copy |
| --- | --- | --- | --- | --- |
| `PAPER_DATA_24H_REPORT.json` | `COMMITTED` | yes | HEAD (committed by WP-8, where it belonged) | — |
| `data/st6/ST6_HEALTH_STATUS.json` | `EXTERNAL_LIVE` | yes | the dated snapshot's own capture record | `data/recovery/wp8/evidence/inputs/ST6_HEALTH_STATUS.json` |
| `reports/strategy-baseline/TIMEFRAME_AUDIT.json` | `EXTERNAL_GENERATED` | yes | the audit's published `sources[]` digest | `…/inputs/TIMEFRAME_AUDIT.json` |
| `reports/strategy-baseline/REGIME_ANALYSIS.json` | `EXTERNAL_GENERATED` | yes | the audit's published `sources[]` digest | `…/inputs/REGIME_ANALYSIS.json` |
| `reports/strategy-baseline/COST_BARRIER.json` | `EXTERNAL_GENERATED` | yes | the audit's published `sources[]` digest | `…/inputs/COST_BARRIER.json` |
| `reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md` | `EXTERNAL_GENERATED` | yes | the audit's published `sources[]` digest | `…/inputs/STRATEGY_FAILURE_MATRIX.md` |
| `data/raw/alpha001/BTC-USDT_1d.json` | `EXTERNAL_DATASET` | no | the RFC-049 preregistration manifest | — |
| `data/raw/alpha001/ETH-USDT_1d.json` | `EXTERNAL_DATASET` | no | the RFC-049 preregistration manifest | — |

The declaration of each one is published inside both artefacts (`input_authority.declared_inputs`)
and is part of their identity; the materialization state of each one is published beside it
(`local_observations`) and is explicitly **not**.

### Dependency map: what moves what

| input moves | `CAMPAIGN_STATE_VIEW` identity | `ACTIVE_ECONOMIC_AUDIT` identity | verifier conclusions |
| --- | --- | --- | --- |
| `tasks/decisions.md` (a later ADR) | yes — the governing decision changes | no | C10 (governing ADR re-derived) |
| `PAPER_DATA_24H_REPORT.json` | yes (paper run state) | yes (paper lane block) | C5, C11 |
| `data/st6/ST6_HEALTH_STATUS.json` snapshot | yes (governance mirror) | no | C7 |
| `reports/strategy-baseline/*.json` | no | yes (gross edges, sample counts, cost barrier) | C2, C4 |
| `reports/alpha-recovery-v1/STRATEGY_FAILURE_MATRIX.md` | no | yes (defects, taxonomy evidence) | C2 |
| `data/raw/alpha001/*.json` | no (graded as an observation) | no | — (manifest pins, C6) |

## 4. Contamination vectors, checked one by one

| vector | before WP-8 | after WP-8 |
| --- | --- | --- |
| `tasks/decisions.md` and later ADRs | read from the working tree, so an uncommitted ADR could move the certified state | read from HEAD; a new ADR is a governed change that moves the state deliberately and visibly |
| untracked files | `PAPER_DATA_24H_REPORT.json`, `data/st6/ST6_HEALTH_STATUS.json` were read as if authoritative | committed, or resolved to a dated snapshot, and reported as observations |
| uncommitted modifications | a dirty copy of any source changed the published state and its identity | impossible for `COMMITTED` (HEAD bytes); a working-tree fallback is a **failure**, not a silent read |
| generation order and timestamps | already excluded from the identity (`head`, `branch`, `generated_at_utc` are volatile) | unchanged, and extended to the new observations block |
| line endings | raw-byte digests: the same commit graded differently per checkout | content digests; an EOL-only difference is an advisory, never a finding |
| absolute paths | none in the identity | none; the artefacts record repository-relative paths only |
| residual state of previous runs | `data/recovery/*` was both input and output; a stale artefact fed the next run | the same, but the identity is now recomputed from committed inputs, so a stale artefact is detectable (C13/the contract tests) |
| hashes over variable bytes | every digest | content digests, from HEAD or from a committed evidence copy |
| working-tree directory listing | RFC occupancy came from `data/*` on disk, so any untracked `data/rfcNNN/` moved it | derived from the committed tree (control N12) |

## 5. What this map does not establish

- The evidence copies are **not a signature**. The chain is anchored in the commit that
  carries it: a party able to rewrite an artefact, its evidence copy and the checker together
  defeats it. Stated in the bundle sidecar, not hidden.
- The four `reports/` inputs are copies of locally generated research outputs, captured
  byte-identically and admissible only while they reproduce the digest the published artefact
  recorded. They are as trustworthy as the commit that carries them.
- The two frozen price series are *not* committed, by the repository's own policy
  (`data/raw/*` is gitignored and pinned by digest in the RFC-049 manifest). Their absence on
  a machine is now a materialization note; their content, if present, is graded against the
  frozen digest. Nothing in the lane is reproduced from them.
