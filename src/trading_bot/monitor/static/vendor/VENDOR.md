# Vendored asset — TradingView Lightweight Charts

| Field | Value |
| --- | --- |
| Package | `lightweight-charts` |
| Version | **5.0.9** |
| File | `lightweight-charts.standalone.production.js` |
| Source | `https://unpkg.com/lightweight-charts@5.0.9/dist/lightweight-charts.standalone.production.js` |
| SHA-256 | `e6bd6516d9ab9cb897c0d6438e3fe1126f2fdce07e68c23836e84d527de81f52` |
| Size | 182 311 bytes |
| License | Apache License 2.0 (see `LICENSE.lightweight-charts.txt`) |
| Attribution | The file keeps TradingView's `/*! @license … */` banner intact; the UI renders the required "TradingView Lightweight Charts™" attribution in the footer. |

## Why vendored instead of a CDN

RFC-TAP-OBS-001 §10 requires a CSP without unauthorised remote scripts. Serving the library from
`'self'` keeps the page offline-capable and makes the delivered artifact hash-verifiable: the monitor
exposes each static asset's SHA-256 at `GET /api/monitor/health`.

## Upgrade procedure

1. Download the new standalone production build.
2. Update `version`, `SHA-256` and `Size` here.
3. Re-run `tests/unit/monitor/test_static_assets.py` (it asserts this file's hash and the banner).
