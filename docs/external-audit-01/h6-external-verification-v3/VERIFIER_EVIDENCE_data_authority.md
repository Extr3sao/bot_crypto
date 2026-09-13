# VERIFIER_EVIDENCE_data_authority.md — H6 V3 Data Authority Gate

**Gate:** `DATA_AUTHORITY`
**Verdict:** `DATA_AUTHORITY = PASS` (10/10 checks)
**Machine-readable:** `VERIFIER_EVIDENCE_data_authority.json`
**Script:** `verifier_data_authority.py` (run with `PYTHONPATH=<verifier>/src`, per `PYTHON_IMPORT_AUTHORITY`)
**Audited target:** `a5487164803fb601f87f2cd4c865929c30da274e`
**Read-only:** the raw authority was never written to.

---

## 1. Data-root resolution (autonomous, frozen discovery order)

| order | mechanism | value | result |
|---|---|---|---|
| 1 | `--data-root` CLI | not supplied | – |
| 2 | `TRADING_AGENTIC_DATA_ROOT` | **unset** | – |
| 3 | repo-relative cache | `C:\Users\GVLLFR0035\Downloads\bot freebuff\data` | **RESOLVED** |
| 4 | public reconstruction | not needed | – |

- `resolution_mechanism = repo_relative_shared_cache`
- The verifier worktree's own `data/` tree contains only empty versioned directories
  (`raw/`, `processed/`, `backtests/`, `storage/`) — **no dataset lives there**.
- The authoritative root is the **shared main-checkout cache**, consumed **read-only**.
  This matches the frozen `verifier_read_only_mapping` and
  `portability_constraint` ("no machine-specific absolute Windows path is the only authority").

Stray artifact noted: the verifier worktree contains a directory literally named `--data-root/`
(created by an earlier session passing a flag where a path was expected). It is empty and unused;
recorded for hygiene only.

## 2. Raw inventory — reconciling 11,383 vs 5,691

| symbol | `.zip` | `.CHECKSUM` | other | frozen expected | match |
|---|---|---|---|---|---|
| BTCUSDT | 2201 | 2201 | 1 | 2201 | ✅ |
| ETHUSDT | 1745 | 1745 | 0 | 1745 | ✅ |
| SOLUSDT | 1745 | 1745 | 0 | 1745 | ✅ |
| **TOTAL** | **5691** | **5691** | **1** | **5691** | ✅ |

```
AGGREGATE_FILES_IN_RAW_DIR = 11383   (builder-reported value — reconciles exactly)
RAW_UNIQUE_PROVIDER_FILES  = 5691    (unique provider-day authority)
CHECKSUM_SIDECAR_FILES     = 5691
OTHER_FILES                = 1
```

**The builder's 11,383 is an aggregate directory file count, not a unique source count.**
It decomposes exactly as `5,691 zips + 5,691 CHECKSUM sidecars + 1 stray file`. The unique
provider-day authority is **5,691**, which matches the frozen
`expected_file_counts.TOTAL` and the frozen `ledger_line_count_expected`. The two numbers are
therefore fully reconciled, and an aggregate operation/file count is **not** being passed off as a
unique source-file count.

### The 1 other file

`data/raw/binance_um/metrics/BTCUSDT/BTCUSDT-metrics-2026-09-10.csv` (35,891 bytes) — an
uncompressed provider CSV sitting inside the raw authority directory. It is **not** covered by the
frozen `raw_source_locator_pattern` (`…-metrics-{day}.zip`) and **no ledger entry references it**
(the ledger references the `.zip` for that day, which also exists).

- Impact: **none on the frozen authority** — the ledger, manifest and fingerprint derive only from
  `.zip` inputs.
- Classification: hygiene observation, **non-blocking**.

### A/B input file accounting

| counter | value |
|---|---|
| `A_INPUT_FILES` | 5691 (raw `.zip` inputs consumed per normalisation run) |
| `B_INPUT_FILES` | 5691 |
| `A_OUTPUT_FILES` | 5596 (normalised `.jsonl` emitted for `VALID` days) |
| `B_OUTPUT_FILES` | 5596 |

## 3. Ledger — bytes, length, composition

```
path                                   data/processed/oi_full_history_v2/OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl
sha256 (verifier)                      bb2b43c27a88bf9fe3ec22573903a61007f046ddc1256b5caa3e788cba15e714
sha256 (frozen H6_DATA_AUTHORITY_V3)   bb2b43c27a88bf9fe3ec22573903a61007f046ddc1256b5caa3e788cba15e714   ✅ MATCH
line count (verifier)                  5691
line count (frozen)                    5691                                                         ✅ MATCH
malformed lines                        0
```

Classification composition: `VALID = 5596`, `INVALID_GAP = 94`, `INVALID_VALUE = 1`
(total 5691). Per symbol: `BTCUSDT 2201`, `ETHUSDT 1745`, `SOLUSDT 1745`.

## 4. Manifest — bytes and internal consistency

```
path                                   data/processed/oi_full_history_v2/OI_FULL_HISTORY_DATASET_MANIFEST_V2.json
sha256 (verifier, file bytes)          24160d1c8eb42dc6feaaddabed469916898f27814c34d567b5533e54f15532ac
sha256 (frozen)                        24160d1c8eb42dc6feaaddabed469916898f27814c34d567b5533e54f15532ac   ✅ MATCH
declared dataset sha256                == frozen 16779b7d…                                              ✅
declared ledger sha256                 == recomputed ledger sha256                                      ✅
quality_status                         PASS_WITH_EXPLICIT_GAPS
```

### Dual-hash nuance (recorded so it is not mistaken for drift)

Two distinct "manifest hashes" exist in this system, and both were verified:

| hash | value | what it covers |
|---|---|---|
| file-bytes sha256 | `24160d1c…` | the manifest **as written to disk**; this is what `H6_DATA_AUTHORITY_V3.json` pins |
| embedded `manifest_sha256` field | `bdf3088c…` | `sha256(compact_json(manifest minus that field))` — excludes itself |

Both recomputed and consistent. A naive consumer hashing the manifest file and comparing to the
**embedded field** will see a mismatch that is **by design, not a defect**.

## 5. Independent dataset fingerprint recomputation

The documented algorithm was re-implemented by the verifier from the frozen authority text and run
against **ledger bytes read by the verifier** (no builder helper involved):

```
sha256(canonical_json({schema_version, normalizer_version,
                       files: sorted by (symbol, day) of
                       [symbol, day, raw_source_sha256, normalized_sha256,
                        rows, dataset_fingerprint, classification]}))
```

| | value |
|---|---|
| verifier fingerprint | `16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99` |
| frozen `dataset_sha256` | `16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99` |
| match | ✅ |

The fingerprint therefore **commits to actual bytes**, not to a declared constant.

### Per-day fingerprint recomputation

For **all 5596 `VALID` days**, the per-day `dataset_fingerprint` was recomputed independently from
that day's `{symbol, day, raw_source_sha256, normalized_sha256, rows, schema_version,
normalizer_version}` — **0 mismatches**.

## 6. Byte-level normalised dataset verification (all days)

Every `VALID` day's normalised `.jsonl` on disk was re-hashed by the verifier and compared to the
sha256 recorded in the frozen ledger:

| metric | value |
|---|---|
| entries checked | 5596 |
| matched | **5596** |
| mismatched | **0** |
| missing | **0** |

This is a byte-level reconstruction check equivalent in strength to an independent re-freeze: it
proves the committed ledger describes the bytes that actually exist.

## 7. Raw provider archive integrity (all files)

Every raw `.zip` was re-hashed and compared against its **official Binance `.CHECKSUM` sidecar**:

| metric | value |
|---|---|
| zips checked | **5691** |
| matched official sidecar | **5691** |
| mismatched | **0** |
| missing sidecar | **0** |

## 8. BTCUSDT 2024-06-05 forensic

| check | value | result |
|---|---|---|
| raw zip sha256 | `0ef289911a8aa9bd0ee68ab04473dca51c815bfca438629d580aa2fcb0e06058` | – |
| official sidecar | `0ef289911a8aa9bd0ee68ab04473dca51c815bfca438629d580aa2fcb0e06058` | ✅ match |
| matches frozen forensic checksum | – | ✅ |
| normalised sha256 | `bcd3d84950632e7cc70434b75b135bf1eaf56c4ebe72fd13fbea2bbb510a1fb7` | – |
| matches frozen forensic normalised hash | – | ✅ |
| ledger `normalized_sha256` == disk | – | ✅ |
| ledger `raw_source_sha256` == disk | – | ✅ |

The V1 contamination mechanism (shared canonical root, per-file provenance absent) is
**not reproducible** against this V2/V3 authority: the day's official raw, its normalised output and
the ledger's provenance all agree byte-for-byte.

## 9. Test isolation

`scripts/normalize_oi_full_history_v2.py` contains a canonical-root guard:

- `_guard_not_canonical_under_pytest(out_dir)` is invoked when `PYTEST_CURRENT_TEST` is present;
- committed evidence copies are written **only** when `out_dir` resolves to the canonical root.

So a test or A/B run into a temp root cannot mutate the canonical dataset or the committed evidence
copies in `docs/external-audit-01/oi-full-history-02/`. Verified the guard symbol is present in the
tracked script at the audited commit.

## 10. Gate results

| check | result |
|---|---|
| raw inventory reconciles with builder's 11,383 | ✅ |
| raw counts match frozen expected counts | ✅ |
| ledger sha256 matches frozen | ✅ |
| ledger line count matches frozen | ✅ |
| manifest sha256 matches frozen | ✅ |
| independent dataset fingerprint matches frozen | ✅ |
| per-day fingerprints recompute (5596 days) | ✅ |
| normalised bytes match ledger (5596 files) | ✅ |
| raw zips match official checksums (5691 files) | ✅ |
| forensic day passes end-to-end | ✅ |
| **`DATA_AUTHORITY`** | **PASS** |

## 11. Deliberately NOT done here

- **No H6 backtest, no H6 execution, no performance observation.** `H6_BACKTESTS=0`,
  `H6_EXECUTIONS=0`, `PERFORMANCE_OBSERVED=false`. This gate is data authority only.
- **Full independent A/B re-normalisation into verifier temp roots was not run in this gate.** It is
  tracked as the next heavy gate. Rationale: the byte-level checks above already re-hash **every**
  normalised file and **every** raw zip, and recompute **every** per-day fingerprint, which is a
  stronger per-file statement than fingerprint equality between two runs. An A/B re-normalisation
  additionally proves *determinism of the normaliser*, which remains open.

## 12. Open items carried forward

| id | item | severity |
|---|---|---|
| `DATA-01` | stray `BTCUSDT-metrics-2026-09-10.csv` in raw authority dir | LOW (hygiene, non-blocking) |
| `DATA-02` | full A/B re-normalisation determinism not independently reproduced yet | MEDIUM (open gate) |
| `DATA-03` | manifest carries two valid but different "manifest hashes" | INFO (documented, not a defect) |
