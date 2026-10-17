# FINAL_REPORT — RFC-TAP-AI-BOTS-002

**Rama:** `agent/ai-vision/RFC-AI-VISION-001` (baseline `b17644a`, HEAD al ejecutar la
verificación: ver `RUN_REPORT.json` y el log de Git).
**Modo:** paper/shadow. Sin trading real, sin cambios de riesgo, sin coste de API.

## 1. Veredicto

| Bot | Estado real | Qué está probado | Qué no |
| --- | --- | --- | --- |
| BOT-VIS-01 | `IMPLEMENTED`, `UNIT_TESTED`, `MOCK_TEST` | PNG causal adjunto, trazas, riesgo y broker canónicos, PnL neto reconciliado | **`REAL_MODEL_CALLED` BLOCKED**: sin `VISION_API_KEY` no hubo ninguna petición multimodal |
| BOT-CTX-01 | `IMPLEMENTED`, `UNIT_TESTED`, `MOCK_TEST` | Mismo libro, cero imágenes, prompt MTF propio | Igual: bloqueado por credencial |

Ningún bot es `PAPER_RUNTIME_EXECUTED` ni `INDEPENDENT_VERIFIED` como estrategia: el
modelo fue un guion determinista y la economía está marcada `NOT_EVIDENCE`.

## 2. Correcciones P0 del análisis visual (RED → GREEN)

Los defectos se fijaron primero como tests que fallaban, y se corrigieron después:

| Defecto | RED observado | Test que lo fija |
| --- | --- | --- |
| Volumen dibujado dos veces | 80 barras de volumen para 40 velas | `test_visual_defects.py::test_volume_is_drawn_once` |
| Etiqueta pegada al borde derecho | 34 px de tinta en el margen | `test_visual_defects.py::test_price_axis_keeps_a_margin` |
| Cuerpos de vela demasiado finos | 5,93 px por vela con ventana fija | `test_visual_defects.py::test_candle_bodies_are_wide_enough` |
| Rejilla/leyenda robando tinta | conteo de píxeles por región | `test_visual_defects.py::test_grid_does_not_hide_price` |

Además, en el lane:

- el guard de *hueco de datos* impide ejecutar una opinión en una barra que no es la
  siguiente en el tiempo (`test_guards_and_controls.py`), que era un fallo real de
  causalidad de ejecución;
- los guards de PIT/esquema (`guards.py`) rechazan imagen stale, activo ajeno, `data_time`
  futuro y niveles fuera del mercado **antes** de pagar la llamada.

## 3. Registro de bots y ejecución

- `BotCapabilityRegistry` cerrado: dos bots, ambos desactivados por defecto, activación
  explícita por `AI_BOTS_ENABLED` **y** `AI_BOTS_ALLOW`, y lista negra de capacidades que
  lanza `RegistryError` si alguien intenta concederlas.
- `AITradeOpinion` prohíbe por nombre `quantity`, `leverage`, `notional_usdt`, `execute`.
- Un solo `RiskManager` y un solo `PaperBroker` por run; el bot no puede importarlos
  (verificado por AST en la verificación independiente).

## 4. Evidencia ejecutada

```text
pytest tests/unit/vision tests/unit/intelligence tests/unit/paper tests/unit/risk
  366 passed
ruff (vision, intelligence, scripts, tests)      All checks passed
mypy (vision, intelligence, scripts)             Success: no issues found in 18 files

python scripts/ai_bots_run.py --mode mock --limit-bars 600     EXIT 0
python scripts/ai_bots_verify.py                               PASS 34 / FAIL 0
python scripts/ai_bots_run.py --mode live                      EXIT 2 BLOCKED
```

| bot | llamadas | fills | cerrados | net USDT | costes USDT | PNG |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BOT-VIS-01 | 40 | 14 | 14 | −34,448805 | 22,393861 | 40 |
| BOT-CTX-01 | 40 | 14 | 14 | −34,448805 | 22,393861 | 0 |

El resultado negativo es **esperado y no es un hallazgo**: el guion alterna
LONG/NO_TRADE/SHORT sin ninguna señal, así que paga costes por construcción. Sirve para
demostrar que las dos rutas usan el mismo libro (idénticos números) y que sólo la visual
adjunta píxeles.

Datos: `data/edge08/universe-1h` (Binance 1h ya versionado), 600 barras, AAVE y UNI,
ventana de 120 barras, decisión cada 24, `cost_for` 1×, capital 10 000 USDT.

## 5. Artefactos

- `BOT_CAPABILITY_REGISTRY.json`, `VISION_SNAPSHOT_MANIFEST.json` (por bot),
  `MODEL_INVOCATIONS.jsonl`, `BOT_DECISION_TRACE.jsonl`, `BOT_BENCHMARK.csv`,
  `RUN_REPORT.json/.md`, `INDEPENDENT_VERIFICATION.json`, `REA_FINDINGS.json`.
- Ledgers encadenados: `runs/bot-*/BOT-*_DECISIONS.jsonl` (cadena verificada, 40
  decisiones por bot, 14 cierres).
- Los 40 PNG enviados están guardados con su SHA-256; el verificador recalcula el hash del
  fichero y lo compara con el manifiesto.

## 6. Bloqueos declarados (no PASS)

1. **`BLOCKED_MODEL_API`** para ambos bots: no hay credencial. Sin petición no hay
   `provider_id`, `model_id`, `request_id` ni prueba de que el proveedor reciba la imagen.
   Cualquier afirmación de visión real sería falsa.
2. **Comparación económica**: `NOT_EVIDENCE`. Un replay histórico no es evidencia
   prospectiva y el modelo no es un modelo.
3. **REA**: CLI ejecutada (`doctor.json`, `help.txt`); análisis estático de terceros
   `NOT_EXECUTED` por falta de clones, motores y licencias. Ver `REA_FINDINGS.json`.

## 7. Limitaciones

- Cadencia de decisión 24 barras frente a cada barra del sistema determinista.
- Coste estimado por tabla de precios, no factura del proveedor.
- Una sola realización no es un test de significancia.
- `matplotlib` es dependencia del proyecto desde AI-VISION-001.
- El `model_status` sólo se eleva a `REAL_MODEL_CALL` con recibo de éxito; hoy no existe.

## 8. Reanudación exacta

```bash
printf 'VISION_API_KEY=sk-...\n' >> .env
./.venv/Scripts/python scripts/ai_vision_smoke.py            # 1 llamada real, recibo
./.venv/Scripts/python scripts/ai_bots_run.py --mode live --limit-bars 600
./.venv/Scripts/python scripts/ai_bots_verify.py
```

Hasta entonces el estado correcto es **BLOCKED**, no PASS.
