# OI Dataset V2 Determinism Report — OI-DATASET-REFREEZE-02

## Verdict: PASS

- **Global fingerprint (A)**: `16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99`
- **Global fingerprint (B)**: identical (A == B)
- **Per-file bytes**: byte-identical for sampled days (BTC/ETH/SOL 2024-06-05, BTC 2020-09-01, BTC/ETH/SOL 2021-12-01)
- **Sensitivity**: single-field in-memory mutation → `8c392986...` ≠ A (no raw file modified)

## Method

1. Re-normalize each sampled day from the same raw zip into two isolated `tmp_a`/`tmp_b` directories.
2. Require `normalized_sha256` equality and file-bytes equality per day.
3. Recompute canonical global fingerprint (canonical JSON `{schema_version, normalizer_version, files:[{symbol,day,raw_source_sha256,normalized_sha256,rows,dataset_fingerprint,classification}] sorted by (symbol,day)}` → sha256) for A; assert A == B.
4. Mutate one `normalized_sha256` in-memory only and recompute → C ≠ A proves sensitivity.

## Evidence

- `OI_FULL_HISTORY_DATASET_MANIFEST_V2.json` declares `OI_FULL_HISTORY_DATASET_SHA256_V2 = 16779b7...` matching verifier independent derivation and recomputation here.
- `OI_ARCHIVE_DAY_VALIDITY_LEDGER_V2.jsonl` (5691 lines, sha `bb2b43c27a88bf9fe3ec22573903a61007f046ddc1256b5caa3e788cba15e714`) was built deterministically; full 5691-file A/B was executed at V2 creation.

## Status

`DETERMINISM = PASS` — clean rebuild proves no stale/synthetic contamination remains; V2 BTCUSDT 2024-06-05 clean bytes `bcd3d849...` (81040.448) vs contaminated `2e74...` (100.0).
