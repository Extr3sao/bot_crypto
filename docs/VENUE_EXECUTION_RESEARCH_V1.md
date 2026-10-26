# VENUE_EXECUTION_RESEARCH_V1 — economía real de venue/producto

Fecha: 2026-09-27. Artefacto: `docs/VENUE_EXECUTION_MATRIX_V1.json`.
Fuentes: `docs/source_registry.md` (SRC-01..SRC-12).

> Investigación **factual**. No se integra ni se adopta ningún venue nuevo. El
> runtime sigue siendo Binance Spot read-only (§50). Ningún venue se declara
> "mejor": se muestran sus propiedades económicas y sus trade-offs.

## 1. Pregunta

> ¿En qué condiciones reales puede sobrevivir económicamente el tipo de edge
> que buscamos?

La fase anterior dejó el bloqueo dominante identificado como **económico**, no
informativo: el mejor edge bruto OHLCV observado fue **+8.91 bps/trade** contra
un coste realista de **23.5 bps**. Antes de cazar más señales hay que saber si
existe alguna configuración de venue/producto donde el umbral sea alcanzable.

## 2. Registry de venue/producto

| venue | product | jurisdiction | tier | maker | taker | discount | req. requirements | status |
| --- | --- | --- | --- | ---: | ---: | --- | --- | --- |
| Binance | Spot | global (testnet runtime) | VIP0 | 10.0 | 10.0 | BNB −25% (POSSIBLE) | ≥ 5 BNB en cuenta | BASELINE |
| Binance | USDⓈ-M perp | global (excluido del runtime) | VIP0 | 2.0 | 5.0 | promo maker 0% (POSSIBLE) | margen + apalancamiento | NEEDS_GOVERNANCE_DECISION |
| Bybit | Spot | global (no US) | VIP0 | 10.0 | 10.0 | — | — | RESEARCH_CANDIDATE |
| OKX | Spot | global (no US) | Lv1 | 8.0 | 10.0 | OKB/volumen (POSSIBLE) | — | RESEARCH_CANDIDATE |
| MEXC | Spot | global (no US) | standard | 0.0 | 5.0 | 0% maker permanente | — | RESEARCH_CANDIDATE |
| Kraken Pro | Spot | global (incl. US/EU) | tier inicial | 25.0 | 40.0 | volumen/AoP | — | RESEARCH_CANDIDATE |

Cada fila lleva además en el JSON: `min_notional_usd`, disponibilidad de datos
históricos, calidad de API, rate limits, entorno de test/paper, funding y
`source`. No se usan blogs como autoridad de fee: todos los fees vienen de
páginas oficiales del exchange (ver `source_registry.md`).

## 3. Frontera económica (ordenada por coste taker, intención de referencia)

`size = 1,000 USD`, liquidez `normal`, 25 min, patas taker:

| # | escenario | RT cost bps | required ×1.5 | 1.25x | 1.5x | 2.0x |
| --: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | BINANCE_USDM_PERP | 13.79 | 20.69 | 17.24 | 20.69 | 27.58 |
| 2 | **MEXC_SPOT** | **17.79** | 26.69 | 22.24 | 26.69 | 35.58 |
| 3 | BINANCE_SPOT_BNB | 18.79 | 28.19 | 23.49 | 28.19 | 37.58 |
| 4 | BINANCE_SPOT_STANDARD | 23.79 | 35.69 | 29.74 | 35.69 | 47.58 |
| 5 | BYBIT_SPOT | 23.79 | 35.69 | 29.74 | 35.69 | 47.58 |
| 6 | OKX_SPOT | 23.79 | 35.69 | 29.74 | 35.69 | 47.58 |
| 7 | KRAKENPRO_SPOT | 83.79 | 125.69 | 104.74 | 125.69 | 167.58 |

### Por qué MEXC es el único spot con un umbral cualitativamente distinto

MEXC publica **0% maker / 0.05% taker** en spot. Eso baja el término de fee de
20 bps a 10 bps round-trip, es decir **la mitad del coste dominante**. El umbral
pasa de 23.79 a 17.79 bps.

Ese escenario es el único spot donde el techo OHLCV observado (+8.91 bps) se
acerca, pero **sigue sin alcanzarlo**: 8.91 < 17.79. MEXC además tiene un
trade-off que el modelo declara pero no mide: liquidez y profundidad inferiores
a Binance (spread asumido 5 bps frente a 1 bps de majors), menor calidad de API,
y riesgo operacional/regulatorio distinto.

### Por qué el perp no es una respuesta

`BINANCE_USDM_PERP` sale a **13.79 bps** (el más bajo de la tabla), pero:

* añade **funding** (8h) que el modelo incluye vía `funding_carry`;
* exige **margen y apalancamiento**, que cambian el modelo de riesgo por
  completo y están **excluidos del runtime** (`excluded_markets`);
* los datos de funding/OI históricos son parciales (OI solo 30 días).

Por eso su `integration_status` es `NEEDS_GOVERNANCE_DECISION`, **no** una
recomendación.

## 4. Trade-offs explícitos (no hay ganador gratis)

| eje | favorece | coste oculto |
| --- | --- | --- |
| fee bajo (MEXC) | taker fee 5 bps | liquidez/depth peor; spread asumido 5 bps; riesgo operacional |
| venue grande (Binance) | mejor libro, API, datos | fee 10 bps/lado a VIP0 — determinante |
| descuento BNB | −25% → 7.5 bps/lado | no confirmado para nuestra cuenta; hay que mantener BNB |
| maker | evita pagar spread | a VIP0 en Binance el fee maker es **igual** al taker: no ahorra fee, solo añade riesgo de no-fill |
| perp | fee más bajo y funding | margen, apalancamiento, funding, fuera del runtime |
| acceso regulatorio (Kraken) | US/EU | fee de entrada prohibitivo para intradía |

## 5. Uso en admission

`COST_MODEL_V3` se evalúa en **`BINANCE_SPOT_STANDARD_TAKER`** para admission
(comportamiento conservador, sin asumir descuentos). El escenario MEXC se
reporta **solo como contexto** para separar "falta de señal" de "fee del venue",
y **no** puede promocionar una candidata: no está integrado y no tiene
`FillEvidence`.

## 6. Decisión (§58-59)

```text
SPOT_INTRADAY_COST_BLOCKED   (taker intradía, VIP0, majors)
DERIVATIVES_RESEARCH_JUSTIFIED  -> solo como línea de investigación, sin ejecución
```

Matiz verificado: el spot **no** está bloqueado por una propiedad universal del
spot, sino por **el nivel de fee de nuestro venue actual**. MEXC demuestra que
existe configuración spot con la mitad de coste; por eso la siguiente fase
recomendada es de venue/ejecución, no de más señales.
