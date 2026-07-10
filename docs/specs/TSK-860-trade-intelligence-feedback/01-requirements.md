# TSK-860 - Trade Intelligence Feedback Loop: Requirements (Command 01)

> Documento de requisitos para que el bot se retroalimente tras cada
> operacion y conserve evidencia visual, tecnica y estadistica.
> Consumido por `02-bdd.md`, `03-specify.md`, `04-plan.md` y
> `05-tasks.md`.
> Metodologia: `.ai/methodology-hybrid.md`.

---

## 1. Resumen ejecutivo

TSK-860 convierte cada operacion en un caso auditable. Antes de abrir
una posicion, el sistema debe guardar una tesis de entrada con los
criterios tecnicos que se cumplen: estructura de mercado, soportes,
resistencias, zonas de acumulacion/distribucion, order blocks, techos,
suelos, indicadores, entrada, TP y SL. Al cerrar la operacion, el bot
debe comparar la tesis contra el resultado real para aprender por que
acerto o fallo.

El objetivo no es que el bot "adivine" el mercado, sino que acumule
evidencia organizada para mejorar reglas, filtros y gestion de riesgo.

## 2. Alcance

### 2.1 En scope

- Crear un `TradeCase` persistente por cada senal que llegue a riesgo.
- Guardar el motivo exacto de entrada: criterios cumplidos, indicadores,
  niveles y contexto de mercado.
- Detectar y persistir zonas tecnicas:
  - soporte y resistencia,
  - techos y suelos recientes,
  - acumulacion/distribucion,
  - order blocks,
  - rango, ruptura y retesteo,
  - proximidad a niveles clave.
- Capturar una imagen del grafico con overlays:
  - entrada,
  - direccion LONG/SHORT,
  - TP,
  - SL,
  - soportes/resistencias,
  - bloques/zona relevante,
  - timestamp de decision.
- Usar TradingView como proveedor preferido de imagen cuando este
  configurado de forma segura.
- Incluir un fallback local de grafico si TradingView no esta disponible.
- Evaluar cada operacion cerrada con:
  - resultado en R,
  - PnL neto,
  - MFE/MAE,
  - si TP/SL se tocaron,
  - si el precio respeto o invalido la zona,
  - causa probable del acierto/fallo.
- Alimentar un `learning journal` consultable por los agentes.
- Exponer datos al frontend para revisar casos historicos.

### 2.2 Fuera de scope inicial

- Entrenamiento ML automatico con pesos en produccion.
- Scraping agresivo o no autorizado de TradingView.
- Guardar claves o cookies de TradingView en Git.
- Cambiar parametros de riesgo automaticamente sin revision humana.
- Abrir mas ordenes solo porque el feedback historico sea positivo.

## 3. Requisitos funcionales

| ID | Requisito | Criterio de aceptacion |
| --- | --- | --- |
| RF-1 | Cada senal aceptada por riesgo genera un `TradeCase`. | Existe `trade_case_id` antes de enviar la orden. |
| RF-2 | El `TradeCase` guarda tesis de entrada. | Incluye `entry_reason`, `criteria_met`, `criteria_failed`, `direction`, `timeframe` y `confidence_score`. |
| RF-3 | Se calculan zonas tecnicas antes de entrar. | Guarda lista tipada de zonas con `kind`, `low`, `high`, `strength`, `source` y `timeframe`. |
| RF-4 | El sistema evalua proximidad a zonas. | Guarda distancia en bps/precio entre entrada y cada zona relevante. |
| RF-5 | El sistema guarda indicadores usados. | Incluye valores de EMA/RSI/MACD/ATR/VWAP/volumen/spread cuando existan. |
| RF-6 | Se captura imagen de la operacion. | `chart_snapshot_path` existe y contiene entry/TP/SL/niveles. |
| RF-7 | TradingView es proveedor preferido configurable. | `chart_snapshot.provider=tradingview` solo se usa si esta habilitado y autenticado localmente. |
| RF-8 | Existe fallback local. | Si falla TradingView, se guarda snapshot local y se marca `provider=local_renderer`. |
| RF-9 | Al cerrar la posicion se etiqueta el resultado. | `TradeOutcome` contiene `win_loss`, `r_multiple`, `mfe`, `mae`, `exit_reason`. |
| RF-10 | El sistema explica acierto/fallo. | Guarda `post_trade_diagnosis` con tags normalizados. |
| RF-11 | El feedback no cambia live trading por si solo. | Cualquier cambio automatico de reglas queda detras de feature flag y ADR. |
| RF-12 | Los agentes pueden consultar casos. | Existe API/CLI para listar, filtrar y exportar casos por simbolo, estrategia, zona y resultado. |

## 4. Requisitos no funcionales

| ID | Requisito | Criterio |
| --- | --- | --- |
| RNF-1 | No bloquear la ejecucion de ordenes por captura lenta. | La orden no espera mas de `chart_snapshot.max_wait_ms`; si excede, se difiere. |
| RNF-2 | Persistencia local durable. | SQLite con WAL o almacenamiento existente del proyecto. |
| RNF-3 | Trazabilidad completa. | `trade_case_id`, `signal_id`, `order_id`, `position_id` y `snapshot_id` correlacionados. |
| RNF-4 | Seguridad de secretos. | Cookies/API keys de TradingView nunca se imprimen ni se versionan. |
| RNF-5 | Reproducibilidad. | El diagnostico post-trade se puede recalcular desde OHLCV + fills + config. |
| RNF-6 | Coste controlado. | Capturas y datos historicos tienen retencion configurable. |
| RNF-7 | Compatible con paper y live. | Mismo contrato en `paper`, `shadow_live` y `live`, con flags de riesgo. |

## 5. Casos limite

| ID | Caso | Mitigacion |
| --- | --- | --- |
| CL-1 | TradingView no carga o pide login. | Usar fallback local y marcar `snapshot_status=fallback`. |
| CL-2 | La orden falla tras crear el caso. | Marcar `trade_case.status=order_rejected` y guardar error. |
| CL-3 | TP/SL se modifican tras entrar. | Versionar niveles con `level_revision`. |
| CL-4 | La posicion se cierra manualmente en exchange. | Reconciliacion detecta cierre y genera outcome. |
| CL-5 | Faltan velas suficientes para estructuras. | Guardar diagnostico parcial con `insufficient_history`. |
| CL-6 | Zona detectada contradice indicadores. | Guardar conflicto y bajar `confidence_score`. |
| CL-7 | Multiples timeframes dan lecturas opuestas. | Guardar `multi_timeframe_conflict=true` y no ocultarlo. |

## 6. Vocabulario de dominio

- `TradeCase`: expediente completo de una operacion o intento de operacion.
- `EntryThesis`: razon estructurada por la que el bot quiso entrar.
- `TechnicalZone`: zona tecnica detectada, no una linea unica.
- `ChartSnapshot`: imagen con overlays y metadatos.
- `TradeOutcome`: resultado cuantitativo tras cerrar.
- `PostTradeDiagnosis`: explicacion normalizada de por que funciono o fallo.

## 7. Criterios de aceptacion global

1. Ninguna orden real sale sin `trade_case_id`.
2. Cada caso tiene tesis, niveles, indicadores y snapshot o fallback.
3. Cada cierre genera outcome y diagnostico.
4. El feedback es consultable por CLI y exportable a JSON/CSV.
5. BDD cubre caminos feliz, fallback, rechazo, cierre manual y fallo de tesis.
6. Risk-manager y security-reviewer firman antes de activar en live.

