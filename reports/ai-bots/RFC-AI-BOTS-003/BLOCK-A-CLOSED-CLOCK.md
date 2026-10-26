# RFC-TAP-AI-BOTS-003 · Bloque A — reloj de cierre de velas y paridad de riesgo neto

**Fecha:** 2026-10-18 · **Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` (desde `b7e100a`) ·
**Issue funcional:** #12 · **Estado:** `PASS` (7 pruebas nuevas, sin degradar 155 existentes).

## El defecto

`Bar.ts_ms` es la **apertura** de la vela. El carril `src/trading_bot/vision/lane.py` construía
la imagen con la vela ya cerrada (`bars[: i + 1]`) y la enviaba al modelo, pero sellaba la
decisión con `decision_ts_ms = bar.ts_ms` — la apertura — y calculaba la llegada de la respuesta
como `bar.ts_ms + latency_ms`. Una decisión que lee el cierre quedaba registrada como si hubiera
existido una hora antes de que ese cierre fuera conocible, y la latencia se medía contra un
reloj que ya iba una vela por detrás.

Además, la curva publicaba `risk_equity` del motor de riesgo mientras `equity` era el
mark-to-market del broker: `RiskManager.mark_equity` **nunca se llamaba** durante la curva, así
que los gates de drawdown y de tamaño veían una equity realizada que ningún informe mostraba.

## Qué cambió

| pieza | archivo | garantía |
| --- | --- | --- |
| Reloj | [clock.py](../../../src/trading_bot/vision/clock.py) | `timeframe_ms` (nunca adivina: `UnknownTimeframe`), `information_ms = open + timeframe + data_delay` |
| Guarda PIT | [guards.py](../../../src/trading_bot/vision/guards.py) | `assert_causal(bars, instant, bar_interval_ms=…)` exige que **cada vela haya cerrado**; el intervalo es obligatorio, porque un llamador que no lo sabe no puede responder |
| Carril | [lane.py](../../../src/trading_bot/vision/lane.py) | decisión sellada en el cierre; `decision_bar_ts_ms` nombra la vela; `received_at_ms = cierre + latencia`; la marca del broker nunca entra en `_marks` antes de que la vela cierre |
| Paridad | `lane.run` | cada vela cierra con `risk.mark_equity(mtm)` y la curva publica el mismo número en `equity` y `risk_equity` |
| Config | [settings.py](../../../src/trading_bot/vision/settings.py) | `lane.data_delay_ms` (+ `VISION_DATA_DELAY_MS`), registrado en el ledger junto al timeframe |

Consecuencia directa y honesta: **cualquier latencia real descarta el fill**. La respuesta llega
después de que la vela de ejecución abriera, así que no se rellena a ese precio; `NO_TRADE` es el
resultado legítimo. Antes se permitían latencias de hasta una hora entera.

## Evidencia RED → GREEN

RED, con el reloj revertido temporalmente a `decision_ts_ms = bar.ts_ms`:

```text
pytest tests/unit/vision/test_causal_clock.py -q
FAILED test_a_decision_is_taken_at_the_bar_close_not_at_its_open
FAILED test_the_information_instant_carries_the_data_delay
FAILED test_a_latency_below_the_timeframe_no_longer_buys_the_next_open
FAILED test_a_zero_latency_answer_still_fills
FAILED test_the_risk_engine_is_marked_with_the_equity_the_curve_publishes
5 failed, 2 passed
```

RED de la paridad, con `risk.mark_equity` retirado:

```text
AssertionError: the risk engine must see the same net mark the curve reports,
not the realised-only equity
({'ts_ms': 1772611200000, 'equity': 10001.37988951, 'risk_equity': 10000.0})
```

GREEN, estado actual:

```text
pytest tests/unit/vision/test_causal_clock.py -q                      exit 0   7 passed
pytest tests/unit/vision tests/unit/intelligence tests/unit/reports -q exit 0  200 passed
ruff check src/trading_bot/vision tests/unit/vision                   exit 0
mypy src/trading_bot/vision/{clock,guards,lane,settings}.py           exit 0
```

Dos pruebas existentes cambian de forma porque afirmaban el reloj defectuoso, y se endurecen en
lugar de relajarse:

- `test_AIV_03_a_bar_that_had_not_closed_is_a_pit_violation` comparaba aperturas; ahora exige que
  la última vela del cuadro haya cerrado en el instante de decisión (antes pasaba siempre).
- `test_a_decision_is_executed_at_the_next_bar_open_never_its_own` afirma que la vela de fill
  **abre** en el instante de la decisión y nombra la vela de decisión (`decision_bar_ts_ms`).

## Lo que este bloque no hace

- No llama a ningún proveedor real: `REAL_MODEL_CALLED = false`, y los runs siguen siendo replay.
- No mide rentabilidad ni certifica patrones externos.
- No mide la latencia de red: `data_delay_ms` es un parámetro declarado, y el ledger dice si valía
  cero (no medido) o algo distinto.
- No toca `config/risk.yaml`, brokers, ni los límites de riesgo.

## Siguiente bloque

Con el reloj arreglado, el objetivo verificable es un run prospectivo: proveedor real o replay
sancionado con latencia declarada, marcado de equity neto por vela, y comparación
VIS/CTX/CURRENT/NO_TRADE con el mismo calendario, capital y fricción.
