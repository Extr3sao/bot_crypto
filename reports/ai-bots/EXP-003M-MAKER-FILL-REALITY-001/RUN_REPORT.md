# RUN REPORT — EXP-003M

## Procedencia

- Commit: `b0e15497d967ff1c1d3015203ffb7cbfcf0a70a0` (2026-10-20T14:04:09+02:00).
- Rama: `agent/ai-bots/RFC-TAP-AI-BOTS-003`.
- Árbol sucio: **sí**, 547 rutas, digest `d040a2a18501302c` (lista completa en `analysis/PROVENANCE.json`).
- `LIVE_ENABLED`: `no`. Credenciales usadas: `no`.
- Entorno: Python 3.11.15, numpy 2.0.2, pytest 9.1.1, ruff 0.15.20, mypy 2.1.0.
- Plataforma: `Windows-10-10.0.26200-SP0`.
- Configuración congelada: `risk.yaml` `3c27c866d5f1`, `runtime.yaml` `ac3cf4fce9ff`, `vision.yaml` `ba817ef6f2c8`.

## Datos

- barras 1 m congeladas de EXP-003K: BTCUSDT `7fbdfefa1278`, ETHUSDT `cf04dc37617a`, SOLUSDT `33342aacc2ac`.
- cinta observada: 42 pares, 680.484 operaciones, 405.6 MiB, manifiesto `2d5154449fe17aba`.
- selección: every (symbol, UTC day) that contains at least one pre-registered signal, and inside it every trade in [decision-60 s, decision+16 min] for those signals. No filter on price, side or outcome; missed signals are impossible to hide.

## Comandos de reproducción

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py generate   # abajo = descarga + todo
./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py verify
./.venv/Scripts/python.exe scripts/exp_003m_pipeline.py seal
(cd reports/ai-bots/EXP-003M-MAKER-FILL-REALITY-001 && sha256sum -c SHA256SUMS.txt)
```

## Pruebas ejecutadas

| comando | código de salida | resumen |
| --- | ---: | --- |
| `python -m pytest tests/unit/reports/test_exp_003m_*.py -q` | 0 | 25 passed, 0 failed, 0 skipped |
| `python -m ruff check scripts/exp_003m_*.py tests/unit/reports/test_exp_003m_*.py` | 0 | clean |
| `python -m mypy --strict scripts/exp_003m_*.py` | 0 | Success: no issues found in 7 source files |

Total: 25 pasadas, 0 falladas, 0 saltadas. ¿Todo verde? **sí**.

## Verificación independiente

- 13/14 PASS, 0 FAIL, 1 `NOT_EXECUTED`.
- Controles negativos detectados: 8/8.
- `false_success=0`.

## Defectos

### `D1_TOQUE_NO_ES_FILL`

EXP-003L supone que cualquier toque del rango de un minuto nos llena enteros al precio mejorado. La cinta confirma que el supuesto no cambia el número de señales llenadas (44 de 47 con cola cero), pero sí el resultado por operación: el neto por cierre pasa de -0.4831 a -0.4709 con la misma tasa, y a -0.5347 cuando se exige una orden de cola. El daño no está en cuántas señales se llenan, sino en *cuándo*.

Medido: `{"f0_fill_rate": 0.93617, "f0_net_per_fill_usdt": -0.48309107, "f1_fill_rate": 0.893617, "f1_net_per_fill_usdt": -0.53469052, "f3_fill_rate": 0.93617, "f3_net_per_fill_usdt": -0.47093984}`.

### `D2_BASE_FEE_WAS_THE_BNB_DISCOUNT`

El escenario maker base de EXP-003L valoraba spot VIP0 con el descuento del 25 % por pagar comisiones en BNB. Sin ese descuento cada operación cerrada cuesta más, y EXP-003L no separaba el descuento del mecanismo: el resultado base dependía de una condición de la cuenta que no se declaró como supuesto.

Medido: `{"bnb_fee_per_trade_usdt": 0.75, "extra_cost_per_trade_usdt": 0.25, "plain_fee_per_trade_usdt": 1.0}`.

### `D3_LAS_UNIDADES_DE_TIEMPO_DISCREPAN`

El archivo diario de klines publica microsegundos mientras el dataset congelado (REST /api/v3/klines) está en milisegundos. Una comprobación de procedencia que asumiera una sola unidad habría comparado cero barras y habría pasado en vacío. Ahora se normaliza y falla ante cualquier diferencia: la comprobación compara barras de verdad, no la nada.

Medido: `{"bars_compared": 60480, "bars_exact": 60480}`.

### `D4_LA_COLA_NO_ES_OBSERVABLE`

No existe libro L2 spot histórico publicado, así que la cola por delante de una orden en reposo no se puede medir. Se declara y se barre. Con una orden de 500 USDT la cola apenas muerde: solo 3 de 47 señales cambian de fracción entre cola 0 y cola 1. Lo que sí mueve el resultado es la selección adversa del momento del llenado, no el tamaño de la cola.

Medido: `{"evidence_class": "ESTIMATED_FROM_OBSERVED_TRADE_TAPE", "queue_points_swept": 24, "signals": 47, "signals_where_queue_binds": 3}`.

### `D5_EL_INDICE_DEL_FILL_ERA_EPOCA`

El primer motor de fills convertía el instante del llenado en un índice de barra dividiendo la época por 60 s, sin restarle el origen de la serie. Resultado: todas las posiciones de cinta salían `OPEN_AT_END`, y el informe habría dicho que ninguna llegó a su stop ni a su objetivo. Se detectó por la distribución de estados, no por un test, y ahora el índice se busca en el diccionario de barras con error explícito si el minuto no existe.

Medido: `{"closed_after_fix": 42, "open_at_end_after_fix": 0, "symptom_before_fix": "100 % de los fills de cinta en OPEN_AT_END"}`.

## Limitaciones

- no order was sent to an exchange: every fill here is inferred from published trades.
- the queue position at the limit is unobservable without a spot L2 feed; it is declared and swept, not measured.
- a trade at our price is not proof that our order was the one matched.
- cancel/replace traffic and hidden liquidity are not modelled.
- the holdout 2026-08-06 → 2026-08-20 stays closed; nothing here is out-of-sample in the forward sense.
- a moving-block bootstrap on 47 signals is a wide interval, not a proof of anything.

## Sello

`SHA256SUMS.txt` se emite **después** de este informe y de la verificación, y cubre todos los ficheros del directorio salvo él mismo y `SEAL.json`. El informe no incluye el digest del sello: incluirlo sería un hash circular.
