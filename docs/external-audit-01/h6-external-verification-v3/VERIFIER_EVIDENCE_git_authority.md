# VERIFIER_EVIDENCE_git_authority.md — H6 V3 Git Authority Gate

**Gate:** `GIT_AUTHORITY` (includes `PREREG_FREEZE`, `FROZEN_ARTIFACT_HASH_RECOMPUTATION`, `POST_PREREG_IMMUTABILITY`)
**Verdict:** `GIT_AUTHORITY_STATUS = PASS`
**Machine-readable evidence:** `VERIFIER_EVIDENCE_git_authority.json`
**Independent script:** `verifier_git_authority.py` (verifier-owned, uses only `git cat-file` blob bytes + stdlib `hashlib` + an independent pure-Python SHA256)

Everything below was produced by reading **Git object-database blobs**, never working-tree copies,
and never the builder's hash helper.

---

## 1. Resolved commit identities

| abbrev | full SHA | parent(s) | tree SHA | merge? | subject |
|---|---|---|---|---|---|
| `0941082` | `0941082fc875a66287d2b09159112963141bcf27` | `ee58c7a…` (1) | `f69e880c8f18a61994f272a9e5af09fcc01fc330` | no | H6-REPAIR-CLOSE-01: verifier package V2 + final evidence (NOT_EXECUTED) |
| `f048520` | `f048520b1828d5035da7eb6859b854c6b1670e97` | `0941082` (1) | `19580846f22e77e884314be06cee9931d8abc421` | no | [H6-V3-01] repair whitelist/hash/data/PIT portability |
| `2cd8f85` | `2cd8f850633cd2f04c22f00ffed8d9b0ab636d09` | `f048520` (1) | `0f144769da69039bfd3416585d274485a5398860` | no | [H6-V3-02] repair confirmation/Shadow governance |
| `9f1d844` | `9f1d844312419575d6b635a7356111050fd9b93a` | `2cd8f85` (1) | `8279000b6eaf6b37a32ed2d30b16c10e9e3ec071` | no | H6-PREREG-V3: frozen preregistration (PENDING_EXTERNAL_VERIFICATION_V3) |
| `b2c6b2b` | `b2c6b2b15274688b3feb117b1f5a78c3db44ee5a` | `9f1d844` (1) | `0ccd6cac873c8abdf23372500ac63c550221f470` | no | [H6-V3-04a] Shadow/price governance evidence + durable test records |
| `a548716` | `a5487164803fb601f87f2cd4c865929c30da274e` | `b2c6b2b` (1) | `c52321dee44c97a34a6aab28963076fd88d913b0` | no | [H6-V3-04] add V3 external verifier package and final evidence |

Auxiliary commits not in the requested set: `ee58c7a5a0a46cf6af17dc9606118ef0f1fcd335` (parent of `0941082`).

## 2. Ancestry — tested, not assumed

Direct-parent relationships were **explicitly distinguished** from mere ancestry. Each row below was
computed with `git merge-base --is-ancestor` and `git rev-list --parents -n 1`.

| claimed relation | observed | is_ancestor | is_direct_parent | pass |
|---|---|---|---|---|
| `0941082` is **ancestor** of `f048520` | `DIRECT_PARENT` | true | true | ✅ |
| `f048520` is **direct parent** of `2cd8f85` | `DIRECT_PARENT` | true | true | ✅ |
| `2cd8f85` is **direct parent** of `9f1d844` | `DIRECT_PARENT` | true | true | ✅ |
| `9f1d844` is **ancestor** of `b2c6b2b` | `DIRECT_PARENT` | true | true | ✅ |
| `b2c6b2b` is **direct parent** of `a548716` | `DIRECT_PARENT` | true | true | ✅ |

Walk of first-parents from `a548716`:

```
a548716 -> b2c6b2b -> 9f1d844 -> 2cd8f85 -> f048520 -> 0941082
```

- `commit_count(0941082..a548716)` = **5**
- merge commits in slice = **none**
- verdict: the builder-described chain resolves to a **linear, non-rewritten** history.
  No `UNRELATED` pairs were found; every claim resolved at least as strongly as claimed.

## 3. `9f1d844` is genuinely the frozen preregistration commit

Commit message (verbatim subject + body) confirms intent, and the tree confirms content:

- 4 `H6_*_V3.json` artifacts are present in the `9f1d844` tree:
  - `docs/external-audit-01/oi-full-history-03/H6_SPEC_V3.json`
  - `docs/external-audit-01/oi-full-history-03/H6_MANIFEST_V3.json`
  - `docs/external-audit-01/oi-full-history-03/H6_FEATURE_AUTHORITY_WHITELIST_V3.json`
  - `docs/external-audit-01/oi-full-history-03/H6_DATA_AUTHORITY_V3.json`
- `git diff-tree` shows `9f1d844` touched **9** paths, of which **3** are frozen artifacts it authored:
  `H6_SPEC_V3.json`, `H6_MANIFEST_V3.json`, `H6_FEATURE_AUTHORITY_WHITELIST_V3.json`.
- `H6_DATA_AUTHORITY_V3.json` was **not** authored by `9f1d844`; it was introduced by the immediately
  preceding repair commit `f048520` and **carried unchanged** into the prereg tree. Both were absent at
  base `0941082`. Interpretation: the prereg commit *froze* the data-authority artifact rather than
  regenerating it. This is recorded because it means the data-authority artifact's authorship predates
  the freeze by one commit — relevant to any claim that the freeze regenerated all four artifacts.
- After `9f1d844` no commit in `b2c6b2b` or `a548716` touches any of the four paths.

## 4. Independent SHA256 of frozen blob bytes

Bytes read via `git cat-file blob <commit>:<path>`; hashed with stdlib `hashlib` and cross-checked with
a **from-scratch pure-Python SHA256** in the verifier script (selftest: `sha256_pure(b"abc")` matches
`hashlib`). No line-ending normalization was applied.

| artifact | path | declared SHA256 | verifier SHA256 | match |
|---|---|---|---|---|
| `H6_SPEC_V3` | `…/oi-full-history-03/H6_SPEC_V3.json` | `cd354e06…50eeea` | `cd354e0603a4b8ee754d38a2a6e3a2689c06e683b732ab34bec03e631c50eeea` | ✅ |
| `H6_MANIFEST_V3` | `…/oi-full-history-03/H6_MANIFEST_V3.json` | `de42e4a1…95ecb3` | `de42e4a1581855243969820ba4658582f398735586764ca0a8684920db95ecb3` | ✅ |
| `H6_FEATURE_AUTHORITY_WHITELIST_V3` | `…/oi-full-history-03/H6_FEATURE_AUTHORITY_WHITELIST_V3.json` | `c59718ca…0a1b31` | `c59718cafcd8c0a23ea6cbf7244e328f668c95bf40744e3520752c52fa0a1b31` | ✅ |
| `H6_DATA_AUTHORITY_V3` | `…/oi-full-history-03/H6_DATA_AUTHORITY_V3.json` | `4e2bada4…28466b` | `4e2bada45fa06fb10ed89815759f2bc258d093afab70b93c6a983763e528466b` | ✅ |

`hashlib` and the independent pure-Python implementation agreed bit-for-bit on every artifact.

## 5. Post-prereg immutability (blob-ID level)

| artifact | prereg blob `9f1d844` | `b2c6b2b` blob | final blob `a548716` | DRIFT |
|---|---|---|---|---|
| `H6_SPEC_V3` | `fb9f5457948edcb7ac8956ad7d4cd24d1d6010c3` | `fb9f5457948edcb7ac8956ad7d4cd24d1d6010c3` | `fb9f5457948edcb7ac8956ad7d4cd24d1d6010c3` | **false** |
| `H6_MANIFEST_V3` | `73a66e1436b2379e9a0b81edbe68a4f2d42fbcf3` | `73a66e1436b2379e9a0b81edbe68a4f2d42fbcf3` | `73a66e1436b2379e9a0b81edbe68a4f2d42fbcf3` | **false** |
| `H6_FEATURE_AUTHORITY_WHITELIST_V3` | `eaeb60715b2f789b01c04ba17b340a245d917eea` | `eaeb60715b2f789b01c04ba17b340a245d917eea` | `eaeb60715b2f789b01c04ba17b340a245d917eea` | **false** |
| `H6_DATA_AUTHORITY_V3` | `66c27831d339c7c3fc25a0c6f75c0592259bb192` | `66c27831d339c7c3fc25a0c6f75c0592259bb192` | `66c27831d339c7c3fc25a0c6f75c0592259bb192` | **false** |

Blob-ID equality is a Git-content guarantee; the recomputed SHA256 of the `a548716` bytes matched the
prereg SHA256 in every case, so this is not merely a `git diff` non-result.

## 6. Post-prereg change classification (actual diffs inspected)

### `9f1d844..b2c6b2b` — 23 files, all additions
- `EVIDENCE_ONLY` × 21 (`docs/external-audit-01/oi-full-history-03/{DASHBOARD_REPEAT_20_RESULT, DATASET_DETERMINISM_V3_RESULT, DATA_AUTHORITY_RESULT, FULL_HERMETIC_RESULT_1/2, H6_SHADOW_ISOLATION_REPORT.(json|md), H6_V2_EXTERNAL_FAILURE_RECORD.(json|md), H6_V3_REPAIR_DEFECT_REGISTER.(json|md), H6_V3_VERIFIER_ENVIRONMENT_CHECK, PIT_DYNAMIC_RESULT, PIT_STATIC_AND_ISOLATION_RESULT, PRICE_OVERLAP_V3_RESULT, SHADOW_MATURITY_AUTHORITY_V2.(json|md), SHADOW_RESOLUTION_REPORT_V2.(json|md), SHADOW_V2_INVALIDATION_RECORD.(json|md)}.json`)
- `DATA_AUTHORITY` × 1 — `H6_DATA_AUTHORITY_CHECK.json` (a *check/report* artifact; the frozen `H6_DATA_AUTHORITY_V3.json` itself was **not** touched)
- `CODE` × 1 — `scripts/verify_price_overlap_v3.py` (**new** verification script, not `src/`)

### `b2c6b2b..a548716` — 5 files, all additions
- `EVIDENCE_ONLY` × 4 (`H6_EXTERNAL_VERIFIER_PACKAGE_V3.json`, `H6_EXTERNAL_VERIFIER_PROMPT_V3.md`, `H6_V3_DEFECT_REGRESSION_MATRIX.json`, `H6_V3_POST_COMMIT_RECORD.json`)
- `CODE` × 1 — `scripts/make_v3_post_commit_record.py` (**new** record-generator script, not `src/`)

**No file under `src/` or `tests/` was modified by either range.**

### Critical question — did post-prereg commits change governed semantics?

| governed area | verdict |
|---|---|
| H6 economic semantics | `UNCHANGED_AFTER_PREREG` |
| Feature authority | `UNCHANGED_AFTER_PREREG` |
| Dataset authority | `UNCHANGED_AFTER_PREREG` |
| PIT implementation | `UNCHANGED_AFTER_PREREG` |
| Confirmation authority | `UNCHANGED_AFTER_PREREG` |
| Shadow behavior | `UNCHANGED_AFTER_PREREG` |

`CRITICAL_QUESTION_VERDICT = NO_GOVERNED_SEMANTIC_MUTATION_AFTER_PREREG`
`POST_PREREG_CHANGES_ARE_EVIDENCE_ONLY = true` (no `src/` path in either range)

---

## 7. Gate results

| gate | result |
|---|---|
| `GIT_AUTHORITY` | **PASS** |
| `PREREG_FREEZE` | **PASS** |
| `FROZEN_ARTIFACT_HASH_RECOMPUTATION` | **PASS** (4/4 declared == verifier) |
| `POST_PREREG_IMMUTABILITY` | **PASS** (0 drift, blob-ID + byte level) |
| `ANCESTRY_INTEGRITY` | **PASS** (linear, no merges, no rewrites) |
| post-prereg governed-semantic mutation | **NONE FOUND** |

## 8. Residual notes / limitations

- Only the six requested commits were resolved by abbreviation. `0941082`'s own parent `ee58c7a…` was
  read but not audited; nothing in the requested gate depends on it.
- The prereg commit froze `H6_DATA_AUTHORITY_V3.json` by carry-forward rather than regeneration.
  This is **not** classified as a defect (the artifact is present in the prereg tree and immutable
  thereafter), but it is recorded so that no downstream claim asserts all four artifacts were
  regenerated at `9f1d844`.
- `SHA256` agreement between `hashlib` and an independent pure-Python implementation is a
  self-consistency check of the verifier toolchain, not a third-party cryptographic attestation.
