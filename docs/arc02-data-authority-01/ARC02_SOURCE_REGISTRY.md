# ARC02_SOURCE_REGISTRY.md

> Every byte ARC-02 depends on, with provenance, binding and verification status.
> ARC-02 DOWNLOADS NOTHING: the certified ARC-03 5m authority is reused by content identity.

## 1. Provider

| Property | Value |
| --- | --- |
| Provider | Binance (official public market-data archive) |
| Host | `data.binance.vision` |
| Family | `futures/um/monthly/klines` (+ `futures/um/daily/klines` supplements, reused) |
| Market | Binance USD-M **perpetual** futures |
| Interval | `5m` |
| Symbols | `BTCUSDT` (leader), `ETHUSDT`, `SOLUSDT` (followers) |
| Credentials | none |
| Cost | none |
| Downloads performed by ARC-02 | **0** |

## 2. Reuse identity (proved, not asserted)

| Symbol | Reused ARC-03 partition SHA256 | Identity |
| --- | --- | --- |
| `BTCUSDT` | `eb75ab97881fd941c05d1b188778f1a832ab404c59f5991eff12ead779e4ab02` | BYTE_IDENTICAL |
| `ETHUSDT` | `24c886902760b2e2c873df7721c12098e65b768762f55e2144d990deac04c211` | BYTE_IDENTICAL |
| `SOLUSDT` | `d872bc7dc8a52eb697962516fbd24a636483acd43e524cdbbf09985d2720f548` | BYTE_IDENTICAL |

Source dataset SHA256 (certified ARC-03): `1a6ad11712ce436ce9d413d6b53162d66996778cd98643ef7c3eb746a54745ef`
Raw archives verified in this checkpoint: **237** (each against its provider `.CHECKSUM` sidecar)

## 3. ARC-02 projection

```
data/processed/arc02_klines_5m/{SYMBOL}.jsonl   records {t, ct, o, c, sym, ms}
```

`h`, `l`, `v`, `qv`, `n`, `tb`, `tq` are DROPPED: volume is the ARC-03 participation field and the
taker-buy fields are H5 order-flow territory. ARC-02 therefore cannot structurally read either family.
Numeric values are preserved as the exact provider strings, so the fingerprint cannot drift through
float re-formatting.

## 4. Funding authority (cashflow only)

| Symbol | Reused partition SHA256 | Identity |
| --- | --- | --- |
| `BTCUSDT` | `700b0c4c7e5ffa9dbe82cd84e98be9f505bce6f1792d33d0eae88d07a7585855` | BYTE_IDENTICAL |
| `ETHUSDT` | `2edf501ea69807bbf67cdd519e53de18c8dea25ea8bdf009beb88ef2e2693943` | BYTE_IDENTICAL |
| `SOLUSDT` | `6b16d13f5115f906f9ceb4f5a418f7a541c37609e780cfbad0d52ed565808f85` | BYTE_IDENTICAL |

Certified ARC-01 funding dataset SHA256: `5f4845f5062e68353ef421b9687bf728a56693951e2f74e17221a8e3373b62ec`

Funding is **never** a signal input for ARC-02. It is read only as a cashflow leg over
`(entry_time_ms, exit_time_ms]`, because a 5-minute hold can straddle a settlement.

## 5. Superseded draft data (NOT part of the authority chain)

`data/raw/binance_usdm/arc02/**` and `data/processed/arc02_ohlcv_5m/**` are the 2024-only draft
inventories of the earlier candidate-design checkpoint. They cover a narrower window than the reused
authority and carry a different schema, so they are retained as provenance only and are explicitly
excluded from the ARC-02 dataset identity.
