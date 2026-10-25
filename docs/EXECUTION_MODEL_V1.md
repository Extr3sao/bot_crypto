# EXECUTION_MODEL_V1 — taker determinista vs maker distribucional

Fecha: 2026-09-27. Módulo: `src/trading_bot/research/microstructure/execution_model_v1.py`.
Artefacto: `docs/EXECUTION_MODEL_V1.json`. Tests: `tests/unit/microstructure/test_execution_model_v1.py` (15 tests).

> RESEARCH_ONLY. **No** se promociona a runtime (§44). El `PaperBroker` actual
> no modela fills parciales ni cola, y no se ha tocado.

## 1. El error que este módulo existe para impedir

```text
market order == limit order == free fill
```

es falso, y es la forma más común en que un backtest se miente a sí mismo. Por
eso taker y maker viven en **clases distintas** y el lado maker **se niega a
emitir un escalar** sin evidencia de fill.

## 2. Taker — determinista

```text
coste RT = 2 × (fee + half_spread + slippage_base + book_walk)
```

`book_walk` modela el recorrido del libro cuando el tamaño pedido excede la
capacidad que una sola orden puede tomar:

```text
capacity  = visible_notional × participation_rate      (default 10%)
levels    = ceil(size / capacity) − 1
book_walk = levels × books_per_level_bps               (default 0.5 bps)
```

Estado: `EVIDENCE_BACKED` (el fee y el half-spread son observables/publicados).
El `book_walk` es una **estimación**, no una medida de libro.

## 3. Maker — distribucional

```text
efectivo = maker_fee
         + adverse_selection_after_fill × (p_full + ⅓·p_partial)
         + missed_opportunity          × p_missed
         + requote_penalty
```

Propiedades exigidas:

* **nunca** se acredita la captura del spread a la orden pasiva. Una orden
  pasiva que se llena es, por construcción, una que fue golpeada: el
  contrapeso empírico es el movimiento adverso posterior. Acreditar spread sin
  modelar adverse selection es cómo un backtest maker **fabrica** edge de la
  nada;
* `p_missed` **no es gratis**: una orden que no se llena deja la posición sin
  cubrir respecto a la intención;
* con `maker_fee_bps = 0.0` el coste efectivo sigue siendo **> 0**.

## 4. Evidencia requerida

| campo | de dónde sale |
| --- | --- |
| `fill_rate` | colección forward (n > 0) |
| `partial_fill_rate` | colección forward |
| `median_time_to_fill_ms` | colección forward |
| `adverse_move_after_fill_bps` | colección forward |

Sin esos cuatro, `FillEvidence()` no es utilizable y el modelo devuelve:

```text
status = EXECUTION_MODEL_REQUIRED
expected_effective_cost_bps = null
prob_missed = 1.0
```

Es decir: **no hay número**, no un número optimista.

## 5. Escenarios sintéticos

Permitidos, pero **etiquetados**:

```text
SYNTHETIC_STRESS_TEST — no admissible evidence; bounds a cost envelope only
```

`SyntheticMakerScenario` **rechaza** construir cualquier etiqueta distinta de
`SYNTHETIC_STRESS_TEST`. Un escenario sintético nunca puede ser base de
admission.

## 6. Resultado actual

| camino | estado |
| --- | --- |
| taker | `EVIDENCE_BACKED` |
| maker | **`EXECUTION_MODEL_REQUIRED`** (sin `FillEvidence`) |

Consecuencia directa (§13, §37): **la puerta de maker está cerrada**. Ninguna
estrategia rechazada por coste puede reabrirse por "ser maker", porque no existe
evidencia alcanzable de fill que demuestre

```text
effective maker RT cost < gross edge
```

Esto es coherente con `COST_MODEL_V3`: a VIP0 en Binance Spot el fee maker es
**igual** al taker (10 bps), así que ni siquiera teóricamente hay ahorro de fee.
