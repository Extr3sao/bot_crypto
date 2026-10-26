# RFC-048V — Delivery Commit Verification

- delivery commit: `9898cc476ef289c5c6cd9f056158b6f78b1a2b97`
- subject: Make the RFC-048V certificate verifiable against the commit it describes
- tree: `974ec600481a29a9bc7142b3e90327466820e0a5`
- certificate: `RFC048_OFFLINE_CERTIFIED` generated `2026-10-10T09:40:10Z` at head `081201f1eeaf`
- manifest: 50 files, digest `4ee673cc040a7ded…`

## Blob identity

- manifest files re-hashed: 50
- mismatches: none
- delivered paths with uncommitted change: none
- verdict: PASS

## Files excluded from the manifest (self-referential)

A document cannot contain the hash of its own final bytes, so the certifier's own outputs are excluded from its manifest and hashed here instead.

- `data/rfc048/INDEPENDENT_CERTIFICATION.json` — sha256 `0abeaaf0fc2d5f4f…`, git blob `238b6b1d7027`
- `data/rfc048/INDEPENDENT_CERTIFICATION.md` — sha256 `79f2fefd5daba363…`, git blob `37cec6812510`
- `data/rfc048/FINAL_CERTIFICATION_REPORT.json` — sha256 `de3f56ec67b8b863…`, git blob `f7dea61e7f81`
- `data/rfc048/FINAL_CERTIFICATION_REPORT.md` — sha256 `1b7376eeb370db13…`, git blob `d10811560241`

Every file in the certified manifest hashes to the same git object in the delivered commit, the certificate's own files are hashed here, and the delivered paths carry no uncommitted change: the certificate describes the tree this commit records.
