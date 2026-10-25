# T-QR-SIGNAL · correlación fuente ↔ REA ↔ runtime

`REA_EVIDENCE_ID` de superficie: `ev_9b45318c072de54798bb93a37354c38ec82b2bccf31d3cd1fbf9be0898a16b99`, `ev_b954b8b016f1736a766bc45627a3d21f600503c1d4294e7147133a7ce461c46c`, `ev_ee6845ff71d389439559036e9c661edbaee90a518ac18bd29639ef72995417a3`.
La cadena de análisis es Python y se audita por fuente: REA no la ejecuta.

## La cadena, leída en el commit `65e67dc2a8b6493adb74ab24b8e484530b667d27`

| paso | fichero | hecho medido |
| --- | --- | --- |
| datos | `src/analyzer/data_fetcher.py`, `market_data_collector.py` | OHLCV + ticker por exchange público |
| render | `src/analyzer/pattern_engine/chart_generator.py` | figura → PNG en `BytesIO` (`create_chart_image`) |
| contexto | `src/analyzer/analysis_engine.py:578` | `_generate_chart_image()` usa **el mismo `context`** (símbolo, timeframe, velas) |
| payload | `src/platforms/ai_providers/base.py:153` | `{{"type": "image_url", "image_url": {{"url": "data:image/png;base64,…"}}}}` |
| gate de capacidad | `analysis_engine.py:186` | si el modelo no soporta imagen, **no se genera gráfico** y se analiza texto |
| decisión | `src/parsing/unified_parser.py` | `position_size` se valida contra un contrato 0.0–1.0 |
| riesgo | `src/managers/risk_manager.py` | `_resolve_position_size_pct` **recorta** al cap y registra `position_size_clamp` |
| guards | `src/trading/guards/max_position_size.py` | veto de tamaño |
| ejecución | `src/trading/executor_handler.py` | lee `leverage`/`quantity` del análisis; `risk_manager` decide antes |
| UI | `src/dashboard/static/*` | **REA**: 14 módulos, 0 bundler |

## Divergencias con nuestro runtime

1. **Coherencia imagen↔contexto por construcción, no por comprobación.** Genera el PNG
   dentro del mismo objeto de contexto; no hay hash ni símbolo ligado a la imagen enviada.
   Lo nuestro (`vision/lane.py`) liga `sha256` y aborta con `INTEGRITY_FAILURE`. Es más
   estricto: adoptar su enfoque sería un retroceso.
2. **Recorte de tamaño por riesgo.** Coincide con nuestro contrato: el modelo propone, el
   risk manager manda. No hay nada que adoptar; hay confirmación de diseño.
3. **Sin `NOT_COMPARABLE`.** Su dashboard no compara corridas; no aplica.
4. **Modelo puede proponer `position_size`.** En el nuestro el modelo no fija tamaño: sólo
   dirección/tesis. Divergencia deliberada, no un defecto suyo.

## Lo que este target sí aporta

Una implementación **MIT** de referencia para "el gráfico se genera desde el mismo contexto
que se analiza", que es exactamente el invariante que acabamos de blindar con un test. Sirve
como contraste externo del invariante, no como código a importar.
