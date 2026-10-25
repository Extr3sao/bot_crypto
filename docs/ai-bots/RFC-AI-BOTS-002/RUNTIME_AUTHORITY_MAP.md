# RUNTIME_AUTHORITY_MAP — quién puede hacer qué en un bot AI

**Base:** rama `agent/ai-vision/RFC-AI-VISION-001`, baseline `b17644a`.
**Regla dura:** un bot puede *opinar*; el libro, el riesgo y los costes siguen siendo del runtime.

## Mapa de autoridad

| Decisión | Quién la toma | Quién no puede tomarla | Evidencia |
| --- | --- | --- | --- |
| Dirección y oportunidad (LONG/SHORT/CLOSE/NO_TRADE) | bot (LLM) | — | `vision/contract.py`, `ai_bots/contracts.py` |
| Tamaño de la posición | `RiskManager.check_signal` | bot, prompt, ledger | `ai_bots/runner.py` construye `VisionLane`; el bote sale de `PositionSize` |
| Stop / take profit efectivos | política de riesgo canónica | bot (su `stop_loss_pct` se registra como consejo, nunca sustituye el stop) | `vision/lane.py` |
| Comisiones, spread, slippage | `cost_for` + `BrokerCost` del `PaperBroker` | bot | `vision/lane.py` (`cost_schedule`) |
| Libro, posiciones, equity | `PaperBroker` único por run | bot | `book_id = paper-<bot>` |
| Matar el sistema | `RiskManager` (kill switch, semana, cooldown) | bot | `risk/manager.py` |
| Aprobar una estrategia | `strategy_admission` (no tocado) | bot | sin cambios en este paquete |

## Comprobaciones medidas

```text
# Ningún módulo de bots importa un exchange ni el libro
$ python -m ruff ...   # sin hallazgos
$ scripts/ai_bots_verify.py
  bots_cannot_import_an_exchange .................... PASS (0 offenders)
  bot_module_does_not_own_the_book[runner.py] ....... PASS
  bot_module_does_not_own_the_book[contracts.py] .... PASS
  bot_module_does_not_own_the_book[bots.py] ......... PASS

# La política de riesgo no se ha tocado
$ git diff b17644a..HEAD -- config/risk.yaml   -> 0 bytes
  risk_policy_unchanged_vs_baseline ................. PASS
```

## Superficie que un bot *sí* puede leer

- OHLCV causal (`read_ohlcv`), la imagen renderizada (`render_chart`), sus propias
  posiciones (`read_positions`) y el contexto numérico de `VisionLane._context`.
- Nada más. `ALLOWED_CAPABILITIES` en `ai_bots/registry.py` es una lista cerrada:
  `place_order`, `modify_risk`, `call_exchange`, `withdraw` provocan `RegistryError`
  en el registro, no un permiso concedido en silencio.

## Presupuesto y trazas

- `TracedProvider` cuenta llamadas y **se niega** por encima de `max_calls`; escribe un
  recibo `CALL_BUDGET_EXCEEDED` una sola vez.
- El lane se detiene en el mismo número, de modo que un run termina limpio en vez de
  pagar un intento que la traza tendría que rechazar.
- `MODEL_INVOCATIONS.jsonl` se escribe **antes** de usar la respuesta: si el proceso
  muere, queda el recibo de lo pagado.
- `model_status` sólo dice `REAL_MODEL_CALL` cuando existe un recibo de éxito; un
  proveedor real que falla se reporta como `REAL_MODEL_ATTEMPTED_FAILED`.

## Estados de los bots (vocabulario del roadmap)

| Bot | Estado | Qué falta para subir |
| --- | --- | --- |
| BOT-VIS-01 | `IMPLEMENTED`, `UNIT_TESTED`, `MOCK_TEST` ejecutado en paper | `REAL_MODEL_CALLED`: falta `VISION_API_KEY` → **BLOCKED** |
| BOT-CTX-01 | `IMPLEMENTED`, `UNIT_TESTED`, `MOCK_TEST` ejecutado en paper | idem; es el control, no un candidato a promoción por sí solo |

`PAPER_RUNTIME_EXECUTED` no se declara: el broker y el riesgo son reales, pero el modelo
fue un guion. `INDEPENDENT_VERIFIED` sólo cubre los artefactos de plumbing, no la calidad
de decisión de un modelo.
