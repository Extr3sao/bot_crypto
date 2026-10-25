# NEXT_EXPERIMENT — EXP-COST-LINE-001

> Una sola pregunta, un solo experimento, reutilizando lo que ya existe.
> No requiere tocar el runtime, ni el ledger, ni los criterios de admisión.

---

## La pregunta

**¿Cuál es la línea de coste *medida* —no asumida— de una vuelta completa maker/maker en las dos
celdas con mayor gross (`volatility@30m` +8.912 bps, `volatility@1h` +6.276 bps), y sigue siendo
positiva después de ella?**

Es la única incógnita que puede mover el veredicto sin violar el pre-registro:

- el gross ya está medido (8.912 / 6.276 bps, 194 / 96 trades);
- la línea taker ya está modelada (12.177 bps) y **mata** ambas celdas;
- la línea maker de 1.25 bps que las haría viables **está asumida**: `rests_on_assumed_component: true`,
  sin modelo de llenado. Nadie ha medido si esa orden se llena.
- la evidencia existente de fills medidos (EXP-003M) es de **spot** y de otra señal.

Todo lo demás (más indicadores, más timeframes, más familias) cae por debajo de una línea que ya
sabemos que no cruzan.

### Fuente · evidencia · decisión de las tres premisas

| Premisa | Fuente | Evidencia | Decisión |
| --- | --- | --- | --- |
| el gross máximo es 8.912 bps | `data/recovery/COST_BARRIER_EXPLORER.json` → `cells` | 24 celdas, máximo `volatility@30m`, 194 trades | es el techo a batir; ningún otro experimento lo sube |
| la línea taker es 12.177 bps | ídem → `reachability.frontier.cheapest_line_taker` | `BINANCE_USDM_PERP_TAKER`, 200 USD, deep | con taker, las 7 celdas positivas están muertas |
| la línea maker de 1.25 bps no está medida | ídem → `cheapest_line_any` | `rests_on_assumed_component: true`; sin modelo de llenado | **medirla es el único hueco que puede cambiar el veredicto** |

---

## Hipótesis falsable

| | |
| --- | --- |
| H1 | Existe una línea maker medida ≤ 8.9 bps RT con tasa de llenado suficiente para que `volatility@30m` y/o `@1h` tengan **net > 0** con IC95 % inferior > 0. |
| H0 | La línea medida supera 8.9 bps, o la selección adversa del llenado maker se come el gross. |
| Predicción (a priori) | H0. EXP-003M midió +2.057 bps de selección adversa por fill de cinta y un techo de bruto que no cubre el suelo de comisiones. Se declara aquí para que un resultado favorable sea informativo y no una sorpresa narrada después. |

---

## Diseño

**Población:** `volatility@30m` (194 trades), `volatility@1h` (96), con
`mean_reversion@30m` (934) y `trend@30m` (1 562) como controles de mayor muestra.
BTCUSDT, ETHUSDT, SOLUSDT. Periodo W1–W7 (2026-03-01 → 2026-09-24). Holdout 2026-08-06 → 08-20
**cerrado**, igual que en EXP-003M.

**Ejecución:** post-only maker en el mejor bid/ask, entrada y salida; si no llena en N barras, la
señal caduca (se cuenta como no-trade, no como pérdida).

**Motor de fills (reutilizado, no reescrito):** `scripts/exp_003m_fills.py` — el que ya barrió
cola × latencia en 24 puntos y midió selección adversa contra la cinta. Se parametriza el
producto (spot → USDⓈ-M) y el esquema de comisiones.

**Coste (reutilizado):** `COST_MODEL_V3` (`src/trading_bot/research/microstructure/cost_model_v3.py`)
con Binance USDⓈ-M VIP0: **maker 2 bps/lado, taker 5 bps/lado**, funding aplicable solo si el
horizonte cruza un timestamp de funding (se mide, no se estima).

**Datos nuevos (única dependencia externa):** `aggTrades` públicos de USDⓈ-M para los mismos 42
pares `(símbolo, día)` de EXP-003M, vía `GET /fapi/v1/aggTrades` (sin claves). Volumen
comparable al de EXP-003M: 27.9 M trades descargados, 680 484 conservados.

**Nada de esto se hace:** re-tuning de parámetros, búsqueda de umbrales, nuevo indicador,
apertura del holdout, órdenes live, cambio de criterios de admisión.

---

## Gates (pre-registrados aquí, antes de ver un solo fill)

| ID | Gate | Umbral |
| --- | --- | --- |
| G1 | Reproduce el gross de la celda con el motor de fills de toque | ±0.5 bps del publicado |
| G2 | Muestra cerrada | ≥ 100 trades por celda |
| G3 | Muestra OOS | ≥ 30 trades en la última ventana |
| G4 | **Neto medido** | net bps/trade > 0 **y** IC95 % bootstrap (bloques móviles) inferior > 0 |
| G5 | Estrés de coste | con **2×** el coste medido, PF > 0.9 (criterio c7 ya vigente) |
| G6 | Tasa de llenado declarada | se publica; no es gate, es contexto (un net positivo que solo mejora por llenar menos se marca `FILL_SELECTED` y **no** se promociona) |
| G7 | Clase de evidencia | `MEASURED_FROM_OBSERVED_TAPE`; sin libro L2 la cola es barrida, no medida → el veredicto máximo es `CANDIDATE_FOR_PREREGISTRATION`, nunca `PAPER_CANDIDATE` |

**Criterio de muerte (kill switch), decidido ahora:**
si la línea medida supera **8.912 bps RT**, se cierra la lane OHLCV intradía completa: no se
vuelve a financiar otra campaña de indicadores sobre 5m/15m/30m/1h. El siguiente trabajo sería
mecanismo distinto (funding/basis/order flow) o horizonte multi-día, y eso es otra directiva.

---

## Entregables

```
reports/ai-bots/EXP-COST-LINE-001/
  PREREGISTRATION.md          # este diseño, congelado antes de descargar la cinta
  RUN_REPORT.json|md          # comandos, exit codes, salidas
  FILL_MODEL.json             # barrido cola × latencia, tasa de llenado, selección adversa
  ECONOMICS.json              # gross/net/expectancy/DD por celda y por escenario de coste
  INDEPENDENT_VERIFICATION.json  # verificador que NO importa el builder (BUILDER != VERIFIER)
  FINAL_REPORT.md             # GO/NO_GO con la tabla de gates
```

`INDEPENDENT_VERIFICATION.json` debe: recalcular cada número desde la cinta cruda, ejecutar ≥ 8
mutaciones (gross inflado, comisión bajada, trades eliminados, fill rate movido, veredicto
invertido) y publicar `false_success`. **Un `false_success > 0` retira el veredicto.**

---

## Por qué este y no otro

| Alternativa | Por qué no |
| --- | --- |
| Otra búsqueda de indicadores | 24 experimentos ya registrados, 0 candidatos; el techo de gross no se mueve con más búsqueda |
| Subir a horizontes de días | requiere dataset nuevo y multi-día; más caro y no ataca la línea de coste |
| Bajar el umbral de admisión | prohibido por la directiva y por el pre-registro |
| Arreglar el supervisor / locks / procedencia | no mueve ni un bps la admisión (`PAPER_ADMISSION_REASON` ya lo dice) |
| Comprar un feed L2 | resolvería la cola, pero es un coste y un contrato nuevo; este experimento dice primero si merece la pena |

---

## Coste y duración

- Offline, 0 claves, 0 órdenes. Una descarga pública (~GB) + ~1 h de CPU para el barrido.
- Reutiliza: motor de fills (EXP-003M), modelo de coste (COST_MODEL_V3), señales (D-01), y el
  patrón de verificador independiente que ya usan los paquetes EXP-003M/EXP-003P.
- Lo único genuinamente nuevo es **una cinta de futuros** y **una tabla de comisiones ya
  publicada**.

## Qué decisión habilita

- **Net > 0 con IC > 0** en `volatility@30m` y `@1h` ⇒ existe una hipótesis con evidencia
  económica medida; se abre una fase nueva de pre-registro (no automática) con esas dos celdas.
- **Net ≤ 0** ⇒ `NO_GO` definitivo para la lane OHLCV intradía con costes minoristas, con una
  medición en la mano en lugar de una estimación.
