# WP-TDM-12 — COST AND BIAS AUDIT

**Alcance:** costes aplicados a las 24 celdas y sesgo de selección acumulado por el programa TDM.
**Fuentes:** `COST_MODEL_V3` ejecutado, `evidence/tdm/wp-tdm-11/COST_MODEL_AUDIT.md`,
`config/strategy_admission.json`, `.tdm12/triage.json`.

---

## 1. Costes disponibles (ejecutados, no citados)

| Escenario | Producto | bps | Clase |
| --- | --- | --- | --- |
| `BINANCE_USDM_PERP_MAKER` (p=0,5) | Perp | **9,25** | ASSUMED |
| `BINANCE_USDM_PERP_TAKER` | Perp | 13,79 | ESTIMATED |
| `MEXC_SPOT_TAKER` | Spot | 17,79 | ESTIMATED |
| `BINANCE_SPOT_BNB_TAKER` | Spot | 18,79 | ESTIMATED |
| **`BINANCE_SPOT_STANDARD_TAKER`** (primario TDM-11) | Spot | **23,79** | ESTIMATED |
| `BYBIT_SPOT_TAKER`, `OKX_SPOT_TAKER` | Spot | 23,79 | ESTIMATED |
| `BINANCE_SPOT_BNB_MAKER` (p=0,5) | Spot | 31,25 | ASSUMED |
| `BINANCE_SPOT_STANDARD_MAKER` (p=0,5) | Spot | 41,25 | ASSUMED |
| `KRAKENPRO_SPOT_TAKER` | Spot | 83,79 | ESTIMATED |

Desglose del primario (1 000 USD, 30 min): 10 + 10 fee · 1,00 spread · 2,63 slippage · 0,16 impacto =
**23,7906**. Maker spot 41,25 y maker perp 9,25 salen exactamente del modelo.

## 2. Qué NO está verificado

| Componente | Estado | Consecuencia |
| --- | --- | --- |
| Spread | **ESTIMATED** 1 bp constante para BTC/ETH/SOL | el componente más volátil es una constante; no hay libro en los datasets |
| Slippage | ESTIMATED (1 bp × tamaño × volatilidad) | no modela impacto temporal ni colas |
| Funding perp | **no se cobra** por defecto (`funding_rate = 0` aunque `SRC-05` exista) | holds que cruzan los 8 h no lo pagan |
| Fill maker | **p = 0,5 asumido** | 9,25 y 41,25 son escenarios, no mediciones |
| Borrow spot | ausente | un corto en spot no es ejecutable en el modelo |
| Coste de oportunidad del capital | ausente | no afecta al signo |

**Estado agregado:** `UNVERIFIED_COST` para las 24 celdas — **0 de 24** tiene coste verificado. Y aun así
ninguna celda necesita el coste para ser rechazada (§3).

## 3. El coste no es la causa del rechazo

| Comprobación | Valor |
| --- | --- |
| Mejor edge bruto en HOLD | **+7,05 bps** (`volatility@5m`, 58 trades) |
| Mejor edge bruto en DEV | **+11,30 bps** (`breakout@1h`, 290 trades) |
| Coste más barato del modelo | **9,25 bps** |
| Celdas con neto positivo en HOLD | **0 / 24** |
| Celdas con neto positivo en DEV | **0 / 24** |
| Celdas netas positivas incluso a coste **cero** | **0 / 24** (ninguna con bruto > 0 en ambos windows) |

La mejor celda gana +7,05 bps brutos y pierde −2,20 bps incluso con el coste más barato del modelo. No hay
escenario de coste que la rescate.

## 4. Sesgo de selección acumulado (T-10)

| Fuente | Comparaciones | Estado |
| --- | --- | --- |
| TDM-10: 24 celdas × 4 horizontes | **96** | selección sobre HOLD |
| TDM-10: cubetas de régimen (~144) | **144** | exploratorio, sin corrección |
| TDM-11: hipótesis única | **1** | preregistrada antes de la ventana confirmatoria |
| TDM-11: comparadores descriptivos | 2 | **no** testeados inferencialmente |
| TDM-12: celdas reevaluadas | **24** | **reutilización**, no tests nuevos |
| **Total acumulado** | **≈ 265** | ningún resultado con corrección Holm sobrevive |

TDM-10 aplicó Holm a sus 24 celdas: **p ajustada = 1,000 en las 24**; el mejor p bruto (0,043) no
sobrevivió a un test de permutación (0,0737). La celda `volatility@5m` que TDM-12 vuelve a encontrar como
"mejor bruta" es el **máximo de 24**, de modo que su +7,05 está sesgado hacia arriba por construcción.

## 5. Reutilización de ventanas (B3)

| Ventana | Uso | Etiqueta |
| --- | --- | --- |
| W1–W7 2026-03-01→09-24 | descubrimiento original y ledger de admisión | `SELECTION_EXPOSED` |
| DEV 2026-06-25→09-25 | TDM-10 desarrollo, TDM-11 potencia y retrospectiva, TDM-12 triaje | `DEVELOPMENT` |
| HOLD 2026-09-25→10-24 | veredicto TDM-08/10, selección TDM-11, triaje TDM-12 | `SELECTION_EXPOSED` |
| Confirmatoria 2026-10-24T16:00→ | sellada, nunca leída | `FUTURE_CONFIRMATORY_SEALED` |

Ninguna ventana se reetiqueta. **No existe hoy ninguna ventana limpia** donde probar estas 24 celdas: la
única admisible empieza el 2026-10-24T16:00Z y su rendimiento esperado es de ~1 operación/día.

## 6. Asimetrías de comparación (B5)

- Las 24 celdas se comparan con **idénticos** datos, costes, ventanas y restricciones (una posición a la
  vez, hold 30 min, entrada en open siguiente). No hay asimetría de ejecución entre ellas.
- Asimetría con TDM-10: TDM-10 entraba al cierre de la barra de señal; TDM-12 usa open siguiente
  (0,60 bps más conservador en la regla de TDM-11). Se declara; no se mezclan las cifras.
- La pista ACTIVE exige ≥3 operaciones/día de **portfolio**, y el triaje solo mide celdas individuales:
  no se afirma que el portfolio las alcance, solo que 20 de 24 celdas ya superan ese ritmo por sí solas.

## 7. Conclusión

`UNVERIFIED_COST` en todas las celdas, `SELECTION_EXPOSED` en todas las ventanas, `≈265` comparaciones sin
corrección superviviente, y **0 celdas con edge bruto positivo en las dos ventanas a la vez**. El sesgo de
selección y el coste empujan en la misma dirección: no hay candidato.
