# MARKET_MICROSTRUCTURE_DATA_AUDIT — Phase B (§14-19, §56)

> Auditoría de qué fuentes públicas/read-only están disponibles y qué
> histórico puede obtenerse de forma **reproducible**. Máquina:
> `docs/MARKET_MICROSTRUCTURE_DATA_AUDIT.json`.

Fecha: 2026-09-26. Todo lo verificado empíricamente (descargas reales), no
solo por documentación.

## 1. Tabla de fuentes (§56)

| Source | Product | History | Resolution | PIT safe | Public | Status |
| --- | --- | --- | --- | --- | --- | --- |
| DS-01 klines+flow | spot | full | 1m..1M | sí | sí | **DATA_SUFFICIENT** |
| DS-02 aggTrades | spot | full (zips) | tick | sí | sí | **DATA_SUFFICIENT** |
| DS-03 bookTicker | spot | none | live | sí | sí | **LIVE_ONLY** |
| DS-04 order book depth | spot | none | live | sí | sí | **LIVE_ONLY** |
| DS-05 funding rate | perp | full | 1h..8h | sí | sí | **DATA_SUFFICIENT** |
| DS-06 premium index | perp | full | 1m..1d | sí | sí | **DATA_SUFFICIENT** |
| DS-07 open interest | perp | latest 30d | 5m..1d | sí | sí | **LIMITED_HISTORY** |
| DS-08 basis / long-short | perp | latest 30d | 5m..1d | sí | sí | **LIMITED_HISTORY** |

## 2. Verificación empírica (lo que realmente descargamos)

`scripts/fetch_microstructure_data.py` (read-only) descargó, para BTC/ETH/SOL:

| dataset | puntos | rango | fuente |
| --- | ---: | --- | --- |
| KLINES_*_5m | 59,905 | 2026-03-01 .. 2026-09-25 | Spot `/api/v3/klines` |
| PREMIUM_*_5m | 59,905 | 2026-03-01 .. 2026-09-25 | USD-M `/fapi/v1/premiumIndexKlines` |
| FUNDING_* | 624 | 2026-03-01 .. 2026-09-24 | USD-M `/fapi/v1/fundingRate` |
| OPENINTEREST_* | 8,928 | 2026-08-26 .. 2026-09-26 (30d) | USD-M `/futures/data/openInterestHist` |
| BASIS_* | ~30d (paginación inestable) | 2026-09-24 .. 2026-09-26 | USD-M `/futures/data/basis` |

Gaps de klines: **0** (BTC/ETH/SOL, 5m, `classify_gaps`). Orden y duplicados:
limpios (`check_ordering_and_duplicates`).

## 3. Order flow — qué es y qué NO es

Las klines se enriquecen con columnas 8-10 de Binance:
`number of trades`, `taker buy base volume`, `taker buy quote volume`. De ahí:

```
flow_imbalance = (taker_buy - taker_sell) / volume,  taker_sell = volume - taker_buy
```

Esto es **agressor flow agregado por barra**, no tick data. Es un proxy legítimo
del desequilibrio de órdenes agresoras (M-01/M-03). Para tick real está
`aggTrades` (DS-02) — disponible en histórico completo por zips, pero no
necesario para M-01.

## 4. Order book — sin histórico (§16)

`bookTicker` (DS-03) y `depth` (DS-04) **solo existen en vivo**. No hay
endpoint REST de histórico de libro. Verificado: respuestas live 200, sin
parámetro temporal.

Por tanto **M-02 (book imbalance) NO es testeable históricamente.** No se
reconstruye un libro ficticio desde OHLCV. Se clasifica `LIVE_ONLY` y se
planifica `MICROSTRUCTURE-FORWARD-DATA-V1` (colector read-only, §17, §62).

## 5. Derivados — funding/premium sí, OI/basis limitado (§15)

- **Funding (DS-05)**: histórico completo. 624 pagos 8h/4h por activo desde
  marzo. ✅
- **Premium index (DS-06)**: histórico completo (59,905 barras 5m). ✅
- **Open interest (DS-07)**: **solo últimos 30 días** (doc oficial: *"Only the
  data of the latest 30 days is available"*; verificado: `endTime=now-30d` →
  200, `endTime=now-60d` → 400). Cae casi todo en la ventana OOS; no cubre
  DEV/VAL. → `LIMITED_HISTORY`.
- **Basis (DS-08)**: también 30d y su paginación por `endTime` devuelve la
  ventana reciente repetida. Redundante con premium index (mark−index).

No se inventa un backtest de 12 meses de OI (§15).

## 6. Integridad temporal (§18, §64-65)

Para todo dato nuevo se distinguen tres relojes:
`event_time` (exchange), `available_at` (cuándo es conocible), `receive_time`
(colector). Regla: `available_at <= decision_time`.

- klines: `available_at = closeTime + 1` ms.
- premium klines: `available_at = closeTime + 1`.
- funding: `available_at = fundingTime`.
- OI/basis: `available_at = timestamp + period`.

La alineación (`asof_align`/`align_series`) usa `bisect_right` sobre
`available_at`, por lo que una feature nunca ve un dato que no existía en el
momento de decidir.

## 7. Feature provenance (§19)

| feature | source | raw fields | aggregation | window |
| --- | --- | --- | --- | ---: |
| flow_imbalance | klines | volume, taker_buy_base | (buy−sell)/vol | 1 |
| flow_imbalance_z | klines | ídem | z-score | 20 |
| avg_trade_size | klines | volume, trades | volume/trades | 1 |
| ret_mom_bps | klines | close | close/close[−12]−1 | 12 |
| realized_vol_bps | klines | close | std(ret) | 20 |
| range_bps | klines | high, low, close | (H−L)/C | 1 |
| funding_rate | fundingRate | fundingRate | as-of | 1 |
| funding_z | fundingRate | fundingRate | z-score | 21 |
| premium / premium_z | premiumKlines | mark,index (close) | as-of / z-score | 1/21 |
| oi_change_z | openInterestHist | sumOpenInterest | z-score(pctΔ) | 21 |
| basis_bps | basis | futures,index | (F−I)/I | 1 |

Total: **11 features** (< presupuesto 10-20, §20).

## 8. Conclusión Phase B

- Street: **spot order flow (agregado) y derivados funding/premium son
  históricamente testeables**.
- **Order book: no histórico → forward collection requerido.**
- **OI/basis: 30d → limitado**, no permite DEV/VAL/OOS.
- No se fabricó ninguna microstructure series (§16).

---

## 9. ACTUALIZACIÓN V2 — MICROSTRUCTURE-EDGE & FORWARD-DATA V1 (2026-09-28)

> Máquina: `docs/MICROSTRUCTURE_DATA_AUDIT_V2.json` (registro de fuentes,
> evidencia de captura forward y calidad del panel, todo medido).

### 9.1 Fuentes sondeadas de nuevo (hechos, no supuestos)

| source_id | fuente | profundidad real | clasificación |
| --- | --- | --- | --- |
| SRC-04 | aggTrades bulk spot | histórico completo (muestra 14d) | `HISTORICAL_USABLE` |
| SRC-01 | klines 5m | 59,905 barras | `HISTORICAL_USABLE` |
| SRC-02 | fundingRate | 624 puntos | `HISTORICAL_USABLE` |
| SRC-03 | premiumIndexKlines | 59,905 puntos | `HISTORICAL_USABLE` |
| SRC-05 | basis | ~30 días | `LIMITED_HISTORY` |
| SRC-06 | openInterestHist 5m | 8,928 puntos (~31 días) | `LIMITED_HISTORY` |
| SRC-07 | bookTicker / depth | **sin histórico** | `FORWARD_ONLY` |
| SRC-13 | liquidaciones (`allForceOrders`) | **HTTP 404** en sondeo real | `UNUSABLE_VIA_THIS_ENDPOINT` |

La liquidación **no** se da por disponible: se sondeó el endpoint público el
2026-09-28 (con y sin ventana de 7 días) y devolvió 404. Queda registrado como
hueco de datos, no como resultado.

### 9.2 Captura forward ejecutada en esta fase

`FORWARD-COLLECTOR-V1`, modo continuo, 102.4 s, read-only, sin credenciales:

| métrica | valor |
| --- | --- |
| registros | 11,346 |
| `bookTicker` / `depth` / `aggTrade` / `premiumIndex` | 111 / 111 / 11,100 / 24 |
| por símbolo | 3,782 BTC / 3,782 ETH / 3,782 SOL |
| duplicados / desorden | 0 / 0 |
| SHA-256 | `010475859288580555e96bf63a58ede3723a7a9193581da780314b5a21a95498` |

Sirve para **medir spread por activo** (OBSERVED, 37 observaciones por símbolo)
y para validar la estructura forward. **No** sirve como modelo de fill ni como
sustituto de histórico. Limitaciones medidas y declaradas: 1 hueco de
`aggTrade` en BTCUSDT (REST polling se salta prints en ráfaga,
`worst_step = 25`), 1 periodo stale por símbolo en `premiumIndex` (15.2-15.3 s
> umbral de 15 s), 0 regresiones de secuencia en `depth`.

### 9.3 Calidad del panel histórico usado en V2

4,032 slices de reloj común (288/día × 14 días), **0 huecos**, 0 duplicados, 0
desorden. Verificación externa de la agregación minuto→5m: el volumen agregado
coincide **exactamente** con el volumen de klines reales (ratio 1.0 en 288
barras por activo).

### 9.4 Huecos de datos que limitan la fase

1. **Order book histórico** inexistente ⇒ M-03 sigue `FORWARD_COLLECTION_REQUIRED`.
2. **OI ~31 días** ⇒ M-07 sin DEV/VAL; medido y clasificado `LIMITED_HISTORY`.
3. **Liquidaciones** sin endpoint accesible ⇒ `UNUSABLE_VIA_THIS_ENDPOINT`.
4. **Muestra aggTrades de 14 días discontinuos** ⇒ conclusiones sobre esta
   muestra, no sobre 7 meses.

Gates fail-closed añadidos en esta fase: campo ausente, minuto duplicado,
barra fuera de la rejilla UTC y spread sin observaciones ⇒ excepción, nunca
valor por defecto.
