# COST_MODEL_V3 — modelo de coste parametrizable

Fecha: 2026-09-27. Módulo: `src/trading_bot/research/microstructure/cost_model_v3.py`.
Artefacto: `docs/COST_MODEL_V3.json`. Tests: `tests/unit/microstructure/test_cost_model_v3.py` (26 tests).

> RESEARCH_ONLY. No toca `trading_bot.execution.cost_model` ni ningún camino de
> producción (§50).

## 1. Por qué V3 sustituye a V2

`COST_MODEL_V2` era **cuatro escalares fijos**. Un escalar no puede expresar
que "el coste de Binance Spot VIP0 pagando en BNB con orden pasiva y tamaño
grande en un libro fino" es un objeto distinto de "el coste de Binance USD-M
perp taker a tamaño pequeño". V3 convierte el coste en una **función** de las
dimensiones que de verdad lo determinan.

## 2. Dimensiones del modelo

| dimensión | cómo se modela |
| --- | --- |
| venue | registro `VENUE_SPECS` (10 escenarios) |
| product | spot / USD-M perpetual |
| jurisdiction | campo informativo (acceso regulatorio) |
| account / fee tier | `tier` publicado (VIP0, Lv1, standard…) |
| fee-payment mode | `quote_asset`, `bnb`, `exchange_token` |
| maker / taker | fee por lado según el **tipo de orden** de cada pata |
| entry / exit order type | `market`, `limit_post_only`, `limit_ioc`, `limit_gtc` |
| spread | observado si se pasa `spread_bps`; si no, estimado por defecto |
| slippage | `base_slippage_bps × liq × size × vol × nº patas taker` |
| size | `1 + sqrt(size / 10,000 USD)` sobre el slippage base |
| liquidity | `deep 0.5`, `normal 1.0`, `thin 2.5` |
| volatility | `1 + vol_bps / 50` |
| fill probability | `maker_fill_prob` (default 0.5) |
| partial fills | penalización por pata maker no llena |
| adverse selection | `adverse_selection_bps` por pata maker |
| funding / carry | `funding_bps_por_intervalo × intervalos(8h)` |
| holding period | `horizon_minutes` |

## 3. Las cuatro clases de conocimiento (nunca mezcladas)

| clase | significado | ejemplo en V3 |
| --- | --- | --- |
| `KNOWN` | publicado por el exchange, sin ambigüedad | fee 10 bps/lado Spot VIP0 (SRC-01) |
| `OBSERVED` | medido por nosotros contra un endpoint live | spread bookTicker de majors |
| `ESTIMATED` | derivado con método declarado | slippage por tamaño |
| `ASSUMED` | elección de modelado sin evidencia directa | adverse selection 0.5 bps |

Cada `CostComponent` lleva **una sola** clase. El coste agregado expone la
**peor** clase presente: si algo es `ASSUMED`, el total lo dice. Ningún
componente se promociona silenciosamente de `ASSUMED` a `OBSERVED`.

## 4. Escenarios

| scenario_id | venue | product | maker | taker | payment | applicability |
| --- | --- | --- | ---: | ---: | --- | --- |
| `BINANCE_SPOT_STANDARD_TAKER` | Binance | Spot | 10.0 | 10.0 | quote | NOT_APPLICABLE (sin promo) |
| `BINANCE_SPOT_STANDARD_MAKER` | Binance | Spot | 10.0 | 10.0 | quote | NOT_APPLICABLE |
| `BINANCE_SPOT_BNB_TAKER` | Binance | Spot | 7.5 | 7.5 | BNB | **POSSIBLE** |
| `BINANCE_SPOT_BNB_MAKER` | Binance | Spot | 7.5 | 7.5 | BNB | **POSSIBLE** |
| `BINANCE_USDM_PERP_TAKER` | Binance | USD-M perp | 2.0 | 5.0 | quote | POSSIBLE (promo maker 0%) |
| `BINANCE_USDM_PERP_MAKER` | Binance | USD-M perp | 2.0 | 5.0 | quote | POSSIBLE |
| `BYBIT_SPOT_TAKER` | Bybit | Spot | 10.0 | 10.0 | quote | NOT_APPLICABLE |
| `OKX_SPOT_TAKER` | OKX | Spot | 8.0 | 10.0 | quote | POSSIBLE |
| `MEXC_SPOT_TAKER` | MEXC | Spot | 0.0 | 5.0 | quote | POSSIBLE |
| `KRAKENPRO_SPOT_TAKER` | Kraken Pro | Spot | 25.0 | 40.0 | quote | POSSIBLE |

Los descuentos **nunca** se asumen como baseline. El modelo además **falla al
construirse** si alguien marca un escenario BNB como `CONFIRMED`:

```python
VenueSpec(..., fee_payment_mode="bnb", discount_applicability="CONFIRMED")
# ValueError: a BNB-discounted rate cannot be CONFIRMED for our account
```

## 5. Coste round-trip — referencia pre-registrada

Intención de referencia: `size = 1,000 USD`, `liquidity_regime = normal`,
`horizon = 25 min`, patas taker (market/market).

| escenario | fee 2x | spread | slippage 2x | impacto 2x | **RT bps** | required ×1.5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BINANCE_USDM_PERP | 10.00 | 1.00 | 2.63 | 0.16 | **13.79** | 20.69 |
| MEXC_SPOT | 10.00 | 5.00 | 2.63 | 0.16 | **17.79** | 26.69 |
| BINANCE_SPOT_BNB | 15.00 | 1.00 | 2.63 | 0.16 | **18.79** | 28.19 |
| **BINANCE_SPOT_STANDARD** | 20.00 | 1.00 | 2.63 | 0.16 | **23.79** | **35.69** |
| BYBIT_SPOT | 20.00 | 1.00 | 2.63 | 0.16 | **23.79** | 35.69 |
| OKX_SPOT | 20.00 | 1.00 | 2.63 | 0.16 | **23.79** | 35.69 |
| KRAKENPRO_SPOT | 80.00 | 1.00 | 2.63 | 0.16 | **83.79** | 125.69 |

> El escenario de admission es `BINANCE_SPOT_STANDARD_TAKER` = **23.79 bps**
> (V2 decía 23.5; la diferencia de 0.29 bps es el término de tamaño de V3, y
> queda documentada, no ocultada).

## 6. Estrés de coste

`BASE 1.0x / 1.25x / 1.5x / 2.0x`. Para el escenario de admission:

| múltiplo | RT cost bps | edge bruto mínimo |
| --- | ---: | ---: |
| 1.0x | 23.79 | 23.79 |
| 1.25x | 29.74 | 29.74 |
| 1.5x | 35.69 | 35.69 |
| 2.0x | 47.58 | 47.58 |

## 7. Invariantes que los tests fijan

* fee round-trip de 10 bps/lado × 2 presente en el escenario standard;
* **a VIP0 el maker de Binance Spot NO es más barato que el taker** — al añadir
  adverse selection y penalización por no-fill, el escenario maker sale
  **estrictamente más caro**;
* fee maker 0% **no** produce coste 0 (MEXC: 0% fee sigue pagando adverse
  selection);
* una pata maker no paga spread; una pata taker sí (media por pata);
* slippage y market impact **crecen** con tamaño, liquidez fina y volatilidad;
* el descuento BNB es `POSSIBLE` y **no puede** ser `CONFIRMED`;
* `stress(0.5)` y componentes negativos se **rechazan**;
* funding negativo se rechaza; el carry crece con el holding;
* la evaluación es determinista (`as_dict()` idéntico en dos llamadas).

## 8. Qué NO modela V3 (declarado)

* No modela rebates (`maker_rebate_bps > 0` se rechaza).
* No modela la captura del spread por el maker: un fill pasivo es, por
  construcción, uno que fue golpeado; la adverse selection es el contrapeso real.
* No tiene `FillEvidence` medido → el camino maker permanece
  `EXECUTION_MODEL_REQUIRED` (ver `EXECUTION_MODEL_V1.md`).
* El slippage por tamaño es un modelo, no una medida de libro: falta el libro
  histórico (§16) y por eso existe la campaña forward.
