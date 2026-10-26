# DATASET_RESTORE — RFC-TDM-013

El paquete TDM-12 dejó sus entradas fuera de Git. Este documento restaura, byte a byte,
los datasets sellados en un clon limpio y comprueba cada SHA-256 antes de ejecutar nada.

- `schema_version`: `tdm13-dataset-manifest-v1`
- `source_commit`: `a96e9c80c608ed91943d1fab35db6fa1704111bb`
- `storage_mode`: `BUNDLE_IN_GIT`
- `dataset_count`: **26** archivos (10310475 bytes)
- `input_state`: **AVAILABLE**
- `license_status`: `UNKNOWN_NOT_VERIFIED`

## Procedimiento desde cero

```bash
# 1. clon limpio fijado al commit de evidencias de TDM-12
git clone <repo> tdm13-clean
cd tdm13-clean
git checkout --detach a96e9c80c608ed91943d1fab35db6fa1704111bb

# 2. restaurar los inputs sellados (copia byte a byte + verificación de hashes)
python scripts/tdm13_inputs.py restore --target .

# 3. comprobar que los bytes son los del manifiesto
python scripts/tdm13_inputs.py verify
```

`restore` escribe en `data/tdm08/` y `data/tdm10/`, las rutas que el pipeline de TDM-12
lee. Los archivos quedan *untracked* en el clon: no se modifica ningún archivo versionado.

## Inventario

| dataset_id | ruta original | bytes | sha256 | estado |
| --- | --- | --- | --- | --- |
| `HOLD:BTC:15m` | `data/tdm08/BTC_15m.json` | 189574 | `b95cf9b70c09b3e2…` | `SEALED_IN_BUNDLE` |
| `HOLD:BTC:1h` | `data/tdm08/BTC_1h.json` | 47853 | `29adf88af85d9c70…` | `SEALED_IN_BUNDLE` |
| `HOLD:BTC:30m` | `data/tdm08/BTC_30m.json` | 95347 | `38c1e47387454572…` | `SEALED_IN_BUNDLE` |
| `HOLD:BTC:5m` | `data/tdm08/BTC_5m.json` | 563493 | `3a70c00da7404a23…` | `SEALED_IN_BUNDLE` |
| `HOLD:ETH:15m` | `data/tdm08/ETH_15m.json` | 179824 | `2e5ab01fad4d9ad2…` | `SEALED_IN_BUNDLE` |
| `HOLD:ETH:1h` | `data/tdm08/ETH_1h.json` | 45423 | `618a7af43c79e41a…` | `SEALED_IN_BUNDLE` |
| `HOLD:ETH:30m` | `data/tdm08/ETH_30m.json` | 90406 | `b381aa516055a0ab…` | `SEALED_IN_BUNDLE` |
| `HOLD:ETH:5m` | `data/tdm08/ETH_5m.json` | 534696 | `95808c1dfba8e581…` | `SEALED_IN_BUNDLE` |
| `HOLD:SOL:15m` | `data/tdm08/SOL_15m.json` | 168750 | `f1e6de05aa4472c7…` | `SEALED_IN_BUNDLE` |
| `HOLD:SOL:1h` | `data/tdm08/SOL_1h.json` | 42601 | `697d334065ab7bbb…` | `SEALED_IN_BUNDLE` |
| `HOLD:SOL:30m` | `data/tdm08/SOL_30m.json` | 84851 | `d1df8c63248ea802…` | `SEALED_IN_BUNDLE` |
| `HOLD:SOL:5m` | `data/tdm08/SOL_5m.json` | 501027 | `cec3085e2d06b6df…` | `SEALED_IN_BUNDLE` |
| `HOLD:manifest` | `data/tdm08/DATASET.json` | 3932 | `af7fa95ced41f363…` | `SEALED_IN_BUNDLE` |
| `DEV:BTC:15m` | `data/tdm10/BTC_15m.json` | 585337 | `aa38cfd3678dbe0c…` | `SEALED_IN_BUNDLE` |
| `DEV:BTC:1h` | `data/tdm10/BTC_1h.json` | 147782 | `95b3d29655ef9722…` | `SEALED_IN_BUNDLE` |
| `DEV:BTC:30m` | `data/tdm10/BTC_30m.json` | 294398 | `7eed75ae36c74b35…` | `SEALED_IN_BUNDLE` |
| `DEV:BTC:5m` | `data/tdm10/BTC_5m.json` | 1742651 | `7185907c6c847214…` | `SEALED_IN_BUNDLE` |
| `DEV:ETH:15m` | `data/tdm10/ETH_15m.json` | 557957 | `d3dc523bff863efb…` | `SEALED_IN_BUNDLE` |
| `DEV:ETH:1h` | `data/tdm10/ETH_1h.json` | 140803 | `e32c3ed8302c4d68…` | `SEALED_IN_BUNDLE` |
| `DEV:ETH:30m` | `data/tdm10/ETH_30m.json` | 280146 | `957e5b90abf38fdb…` | `SEALED_IN_BUNDLE` |
| `DEV:ETH:5m` | `data/tdm10/ETH_5m.json` | 1659013 | `078a70969decbee2…` | `SEALED_IN_BUNDLE` |
| `DEV:SOL:15m` | `data/tdm10/SOL_15m.json` | 497419 | `b74e8e92a1efb208…` | `SEALED_IN_BUNDLE` |
| `DEV:SOL:1h` | `data/tdm10/SOL_1h.json` | 125667 | `96776edbca673e99…` | `SEALED_IN_BUNDLE` |
| `DEV:SOL:30m` | `data/tdm10/SOL_30m.json` | 250153 | `43a004b6b2c423fc…` | `SEALED_IN_BUNDLE` |
| `DEV:SOL:5m` | `data/tdm10/SOL_5m.json` | 1477421 | `3bfdaf60fcc60511…` | `SEALED_IN_BUNDLE` |
| `DEV:manifest` | `data/tdm10/DATASET_DEV.json` | 3951 | `4a9e30c47b54144c…` | `SEALED_IN_BUNDLE` |

## Qué no se puede afirmar de estos datos

- **Licencia:** `UNKNOWN_NOT_VERIFIED`. Son klines públicas de exchange sin credenciales y sin datos personales, pero las condiciones de redistribución no se comprobaron.
- **Endpoint de captura:** no consta la URL exacta por archivo; el manifiesto de cada split solo declara `binance spot (public klines, no credentials)`.
- **Versión del transform:** `UNKNOWN`. Se conserva la regla de sellado (`close_time <= fetched_at`), no el código que la aplicó.
- **Reproducibilidad desde el proveedor:** re-descargar hoy no garantiza los mismos bytes; lo que se certifica es la copia sellada, no el origen.
