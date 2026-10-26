# EXECUTION_COST_REALITY_AUDIT — Phase A (§5-13)

> Auditoría del coste REALISTA de ejecución del venue/instrumento que
> utilizaría el runtime. Todo READ-ONLY. No se modifica el core runtime (§50).

Fecha: 2026-09-26. HEAD: `5b4051e`.

## 1. Intended venue / product (descubierto, no asumido)

| campo | valor | fuente |
| --- | --- | --- |
| venue | **Binance** | `config/realdata/exchange.yaml` `exchange.id: binance` |
| market type | **Spot** | `account_type: spot`, `default_type: spot` |
| entorno | testnet (`sandbox: true`), read-only en runtime | `exchange.sandbox` |
| símbolos | BTC/USDT, ETH/USDT, SOL/USDT (enabled) + 22 más en el universo | `config/realdata/assets.yaml` |
| order types | market/limit; `post_only_default: true`; `time_in_force: GTC` | `exchange.yaml` |
| derivados | **excluidos** | `excluded_markets: [Leveraged Tokens, Derivatives, Options]` |
| rate limit | 250 ms/req | `exchange.rate_limit_ms` |

**Conclusión de venue:** el runtime está cableado a **Binance Spot**. No hay
evidencia en configuración/arquitectura de un venue alternativo. Los
derivados *no* son producto objetivo del runtime.

## 2. CURRENT_PROJECT_COST_MODEL (qué usa hoy el proyecto)

Dos implementaciones coherentes entre sí:

| componente | valor | fichero |
| --- | --- | --- |
| comisión | 5 bps/lado | `scripts/*` `FEES = 0.0005`; `ExecutionCostModel(commission_bps=5)` |
| slippage | 1 bp/lado | `SLIP = 0.0001`; `ExecutionCostModel(slippage_bps=1)` |
| spread | **0** (no modelado) | — |
| market impact | **0** (no modelado) | — |
| **round-trip** | **12 bps** | `scripts/cost_barrier.py` |

Variantes pre-registradas existentes: `2X_COST` = 24 bps; `STRESSED_SLIPPAGE`
= 5x slip = 32 bps. `ZERO_COST` es solo diagnóstico.

El `PaperBroker` (`src/trading_bot/paper/broker.py`) usa por defecto
`commission_bps=5.0`, `slippage_bps=1.0` — idéntico. La conversión bps es
correcta (`bps/10000`) y está cubierta por tests (`cost_integrity.py`,
`CostSanityGate`). **El modelo es internamente consistente; el problema es el
nivel de la comisión.**

## 3. Fee model oficial (SRC-01)

Binance Spot, **Regular User / VIP0** (30d volume < 1,000,000 USD):

| tier | maker | taker |
| --- | --- | --- |
| VIP0 (sin BNB) | **0.100% (10 bps)** | **0.100% (10 bps)** |
| VIP0 pagando con BNB (−25%) | 0.075% (7.5 bps) | 0.075% (7.5 bps) |
| VIP1 (≥1M USD / ≥5 BNB) | 0.090% (9 bps) | 0.100% (10 bps) |

Evidencia: snippet oficial de https://www.binance.com/en/fee/trading
(`Regular User · < 1,000,000 USD · ≥ 0 BNB · 0.100% / 0.100% · 0.07500% /
0.07500%`). Ver `docs/source_registry.md` SRC-01.

**El proyecto asume 5 bps/lado. La realidad es 10 bps/lado (el doble).** No se
asume BNB, VIP, ni rebates como baseline (§7).

## 4. Componentes observados/estimados

| componente | observado/estimado | evidencia |
| --- | --- | --- |
| fee taker | 10 bps/lado | SRC-01 |
| spread (full) BTC/USDT | ~0.0012 bps | muestreo live `bookTicker` (5 muestras) |
| spread ETH/USDT | ~0.037 bps | ídem |
| spread SOL/USDT | ~0.83 bps | ídem |
| slippage | ≥1 bp/lado (asumido; no hay libro histórico para estimar) | — |
| market impact | pequeño para notional 20-500 USDT | order size del proyecto |
| funding/carry | 0 (spot) | — |
| adverse selection | solo relevante maker | — |

Los spreads spot de majors son **minúsculos** (< 1 bp). Por tanto el coste
dominante es la **comisión de exchange**, no el spread. Esto agrava el
hallazgo de la fee: duplicar la fee duplica casi todo el coste.

## 5. COST_MODEL_STATUS (§9)

```text
COST_MODEL_STATUS: OPTIMISTIC
```

Razón: el modelo previo usa 5 bps/lado cuando el fee real de Binance Spot
VIP0 es 10 bps/lado. Subestima el término dominante por 2x. **No es INVALID**
(conversión y tests correctos) ni CONSERVATIVE (no sobreestima). Es OPTIMISTIC.

Consecuencia: el coste round-trip realista no es 12 bps sino **~23.5 bps**
(taker VIP0 + spread + slippage + impacto pequeño). Ver `COST_MODEL_V2.md`.

**No se reescriben resultados históricos** (§9): los baselines de
STRATEGY-DISCOVERY-V3 se reinterpretan, no se recalculan.

## 6. Break-even edge y margen (§10)

| escenario | RT cost | min gross edge | required edge (×1.5) |
| --- | ---: | ---: | ---: |
| CURRENT_PROJECT_COST_MODEL | 12.0 bps | 12.0 | 18.0 |
| REALISTIC_RETAIL_COST_MODEL | 23.5 bps | 23.5 | **35.25** |
| REALISTIC_RETAIL_BNB | 18.5 bps | 18.5 | 27.75 |
| REALISTIC_MAKER (theoretical) | 21.0 bps | 21.0 | 31.5 |
| STRESS_COST_MODEL | 30.0 bps | 30.0 | 45.0 |

`edge = cost` **no** es suficiente (§42): se exige **materialmente mayor**. El
criterio de admission usa `required = 23.5 × 1.5 = 35.25 bps` de edge bruto por
trade.

## 7. Re-evaluación de V3 bajo COST_MODEL_V2 (§11)

Techo de edge bruto OHLCV observado en V3: **+8.91 bps/trade** (`volatility@30m`).
Otros candidatos: `mean_rev@5m` +1.49 bps, `mean_rev@30m` +5.47 bps,
`trend@15m` +1.28 bps, `volatility@1h` +6.28 bps.

```text
max OHLCV gross edge (8.91 bps)  <  12 bps (modelo viejo)  <<  23.5 bps (real)
```

Ninguna familia OHLCV de V3 sobrevive ni siquiera el modelo VIEJO; bajo el
modelo realista quedan aún más lejos. Clasificación formal:

```text
OHLCV_CURRENT_FAMILIES_NOT_EXECUTION_VIABLE
```

## 8. Maker feasibility (§12-13)

| item | hallazgo |
| --- | --- |
| maker fee VIP0 Spot | **10 bps también** (idéntico a taker) |
| maker más barato que taker | solo desde VIP1 (maker 9 bps), requiere ≥1M USD/30d |
| post-only supported | sí (`post_only_default: true`) |
| fill probability / queue / adverse selection | **no medibles sin libro** (LIVE_ONLY) |

**THEORETICAL vs ACHIEVABLE:** a nivel VIP0 maker NO es más barato que taker.
No existe un modelo de fill. Por tanto:

```text
maker execution does NOT reduce cost for a retail VIP0 account on Binance Spot.
OHLCV rejected candidates are NOT reopened on cost grounds (MAKER EDGE GATE: FAIL).
```

El maker solo podría justificarse si (a) el proyecto alcanza VIP tiers con
volumen real — no demostrable hoy — o (b) un fill model forward demuestra fill
prob y adverse selection favorables. Ninguna de las dos existe: se mantiene
`REJECT` para las candidatas OHLCV.

## 9. Veredicto Phase A

- Venue: Binance Spot, retail VIP0, taker.
- Coste realista round-trip: **~23.5 bps** (BASE taker), no 12 bps.
- `COST_MODEL_STATUS = OPTIMISTIC`.
- La barrera de coste es ~2x más dura de lo asumido.
- Maker no rescata a una cuenta retail VIP0.
- Los resultados V3 no se reescriben: se reinterpretan como
  `OHLCV_CURRENT_FAMILIES_NOT_EXECUTION_VIABLE`.
