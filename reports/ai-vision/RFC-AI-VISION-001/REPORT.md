# AI Visual Discretionary Trading Agent — estado real

> Rama aislada `agent/ai-vision/RFC-AI-VISION-001`, creada desde `b17644a` (HEAD publicado de
> EDGE-017). No se modificó ningún fichero de otros agentes: todo lo nuevo vive en
> `src/trading_bot/vision/`, `tests/unit/vision/`, `scripts/ai_vision_*.py`, `config/vision.yaml`,
> más dos adiciones mínimas (`matplotlib` en `pyproject.toml` y `VISION_API_KEY` documentada en
> `.env.example`).

`FALSE_SUCCESS=0` · `BUILDER != VERIFIER` · `TEST_TARGET == RUNTIME_TARGET`

## 1. Qué está hecho y probado

| pieza | estado | evidencia |
| --- | --- | --- |
| Render PNG determinista (velas, volumen, EMA20/50) | **PASS** | `test_chart_determinism.py` (12): mismo input → mismos bytes; ventana fija; sin fuga de futuro; rechaza NaN/OHLC imposible |
| Contrato `VisionDecision` + parser estricto | **PASS** | `test_contract.py` (25): `extra="forbid"`, NaN/∞ fuera, stop obligatorio en direccional, símbolo ajeno = rechazo, matriz de coherencia |
| Proveedor multimodal agnóstico (OpenAI-compatible) | **PASS (con mock HTTP)** | `test_provider.py` (16): la imagen del payload re-hasheada coincide con el gráfico, 401 no se reintenta y no filtra la clave, 503 sí se reintenta, envelope roto ≠ decisión |
| Ledger append-only encadenado (single-writer) | **PASS** | `test_ledger.py` (8): manipular una línea rompe la cadena, borrar una línea la rompe, segundo escritor rechazado |
| Lane vertical gráfico → LLM → `Signal` → `RiskManager` → `PaperBroker` → PnL neto | **PASS** | `test_lane_vertical.py` (13): fills reales, identidad contable al céntimo, imagen reproducible desde las barras, ejecución en la apertura siguiente, CLOSE del modelo, bloqueo por slot, presupuesto |
| Comparador económico vs determinista | **PASS (lógica)** | `test_compare.py` (9): veredictos, `UNKNOWN` en vez de 0, `NOT_A_COMPARISON` si los inputs difieren |

**86 tests, 86 passed** (`pytest tests/unit/vision`), `ruff` limpio, `mypy` limpio en el paquete.

```
gráfico PNG (hash)  →  prompt versionado (hash)  →  proveedor multimodal
        ↓                                                    ↓
   ledger encadenado  ←  VisionDecision validada  ←  respuesta cruda + id de petición
        ↓
   Signal(side, confidence)  →  RiskManager.check_signal  →  PaperBroker.execute_signal
        ↓                                                        ↓
   política intacta (sizing/stops de config/risk.yaml)     ClosedTrade.pnl NETO
        ↓
   record_trade_result  →  equity curada  →  drawdown pico-valle
```

## 2. Qué está BLOQUEADO (y por qué no se disfraza)

| pieza | estado | causa exacta |
| --- | --- | --- |
| Llamada multimodal real (smoke) | **BLOCKED** | no existe `.env` ni `VISION_API_KEY` en el entorno; el script sale con **exit 2** y escribe `SMOKE_RESULT.json` con `status: BLOCKED`, sin inventar decisión |
| Comparación económica del modelo | **BLOCKED** | depende de decisiones reales. El modo `replay` marca el veredicto `NOT_EVIDENCE` porque unas respuestas grabadas prueban la tubería, no el modelo |
| Valor económico de la IA | **NO AFIRMADO** | sin llamadas reales no hay resultado que afirmar. Cualquier cifra ahora sería ficción |

Evidencia del bloqueo, ejecutada:

```
$ ./.venv/Scripts/python scripts/ai_vision_smoke.py
[smoke] BLOCKED — no credential: set VISION_API_KEY in .env and re-run. No decision was invented.
EXIT=2

$ ./.venv/Scripts/python scripts/ai_vision_lane.py --mode live
[vision-lane] BLOCKED — MISSING_CREDENTIAL: set VISION_API_KEY in the repository .env; no decision is invented in its absence
EXIT=2

$ ./.venv/Scripts/python scripts/ai_vision_lane.py --mode replay
[vision-lane] BLOCKED — REPLAY_REQUIRES_FIXTURES: replay mode needs a fixtures file of answers recorded from a real run
EXIT=2
```

El dry-run sí se ejecutó y demuestra que el payload está bien formado y que la imagen que se
enviaría hashea igual que el PNG en disco: `evidence/smoke/request_shape.json`,
`chart.png` (41 856 bytes, sha256 `f8f707c0…`).

## 3. Cómo se cierra el bloqueo (2 comandos)

```bash
# 1) dejar la credencial FUERA de git (el valor no se pega en el chat)
printf 'VISION_API_KEY=sk-...\n' >> .env      # .env está ignorado por git

# 2) una llamada real, con recibos
./.venv/Scripts/python scripts/ai_vision_smoke.py            # exit 0 solo si el proveedor recibió la imagen
./.venv/Scripts/python scripts/ai_vision_lane.py --mode live  # 3 símbolos, 2 000 barras, coste acotado
```

El segundo comando escribe `VISION_DECISIONS.jsonl` (cadena verificable), `EQUITY_CURVE.json` y
`VISION_LANE_RESULT.json` con la comparación contra el carril determinista (mismos datos, mismo
`cost_for` 1×, mismo capital y misma política). Presupuesto duro: `max_calls_per_run: 300` y
`max_estimated_spend_usd: 2.00` en `config/vision.yaml`; con `gpt-4o-mini` la corrida completa son
~250 llamadas y ~0,5 USD.

## 4. Lo que aportan las cuatro referencias (y lo que ninguna resuelve)

| referencia | imagen | contrato de respuesta | riesgo | hueco que cubre este paquete |
| --- | --- | --- | --- | --- |
| `qrak/LLM_trader` | sí, Plotly→PNG (125 velas) | JSON + Pydantic, checks de claims | sí, cap 10 % | identidad de imagen y replay determinista |
| `Ganador1/FenixAI_tradingBot` | sí, Plotly/mplfinance, 100 velas | JSON de una línea | sí, agente de riesgo | el enlace modelo→ejecución no es verificable; aquí sí |
| `FortuneMal/AI-trading` | sí, mplfinance 60 días | **texto libre** + frase "TECHNICAL VERDICT" | no (1 000 USD fijos) | parser estricto + riesgo real |
| `195440/nof1.ai` | **no** (datos numéricos) | tool-calls con Zod | sí, por herramienta | el caso que el RFC pide: la imagen *es* el input |

Conclusión de la investigación: ninguna de las cuatro guarda el hash de la imagen junto a la
decisión ni permite re-ejecutar la misma decisión sobre el mismo píxel. Eso es exactamente lo que
hace `ledger.py`, y es la diferencia entre un bot que "usa IA" y un experimento que se puede
auditar.

## 5. Riesgos y límites declarados

1. **Cadencia**: el determinista propone en cada barra; el modelo cada 24. Un conteo de operaciones
   distinto no es comparable y el comparador lo marca como `decision_cadence: false`.
2. **Un solo camino**: una realización sobre un dataset no es un test de significancia; el propio
   veredicto lo dice en la misma frase que el número.
3. **Stops**: el modelo propone un stop; la política manda. Se registra si el stop del modelo cae
   dentro o fuera del de la política (`model_stop_inside_policy`).
4. **Coste**: `cost_usd` es una estimación de tabla de precios, no una factura; el ledger guarda
   tokens reales para poder reconciliar después.
5. **Sin órdenes reales**: el paquete no importa ningún cliente de exchange; sólo `PaperBroker`.

## 6. Ficheros

- `src/trading_bot/vision/{chart,contract,prompt,provider,ledger,lane,compare,settings}.py`
- `tests/unit/vision/{test_chart_determinism,test_contract,test_provider,test_ledger,test_lane_vertical,test_compare}.py`
- `scripts/ai_vision_smoke.py`, `scripts/ai_vision_lane.py`
- `config/vision.yaml`, `docs` → ADR-AIV-01 en `tasks/decisions.md`
- Evidencia: `reports/ai-vision/RFC-AI-VISION-001/evidence/`
