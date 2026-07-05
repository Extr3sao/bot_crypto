# Impact Analysis

> Plantilla viva. Se actualiza con cada cambio (PR o tarea grande). El
> agente responsable la rellena antes de implementar.

---

## Cómo usar este documento

Por cada cambio:

1. Identifica el archivo/módulo tocado.
2. Marca los efectos colaterales previsibles.
3. Marca los efectos colaterales desconocidos (Riesgo === Desconocido).
4. Define mitigaciones y verificaciones.

## Tabla de impacto por tipo de cambio

### Cambiar `config/assets.yaml`
- `market_data` puede fallar al cargar.
- `strategies` puede operar sobre pares nuevos (verificación: lista de pares en `codebase-map.md`).
- **Riesgos desconocidos**: pares sin volumen o con volatilidad extrema.
- **Mitigación**: validar con `runtime.yaml.filters`.

### Cambiar `config/risk.yaml`
- TODO cambio pasa por `risk-manager` + revisión humana.
- Riesgo crítico: relajar límites.
- **Mitigación**: tests + ADR obligatorio.

### Cambiar `config/strategies.yaml`
- Cambiar estado (`research → paper → live_candidate`) sin pasar por gates.
- **Mitigación**: `risk-manager` y `release-live` lo bloquean.

### Cambiar `config/indicators.yaml`
- Indicadores nuevos pueden depender de datos no disponibles.
- **Mitigación**: smoke-tests con data sintética + paper.

### Cambiar `config/exchange.yaml`
- Riesgo crítico: usar exchange no soportado por CCXT o sin sandbox.
- **Mitigación**: `security-reviewer` + ADR + release gate.

### Cambiar `config/runtime.yaml`
- Riesgo: habilitar live accidentalmente.
- **Mitigación**: `LIVE_TRADING_ENABLED` siempre `false` por defecto; variable de entorno requerida.

## Cambios recientes

| Fecha       | Cambio                                                                  | Módulos afectados | Riesgos                                       | Mitigación                                                                          |
| ----------- | ----------------------------------------------------------------------- | ----------------- | --------------------------------------------- | ----------------------------------------------------------------------------------- |
| 2026-07-03  | TSK-099 cerrado: Pydantic v2 typed config + `FlatEnvAliasSource`         | `config/`         | Drift de contrato flat-env vs nested-path     | ADR-0010 firmada; 10 nuevos regression tests pinean el contract.                    |
| 2026-07-03  | ADR-0011 firmada: cierre sprint-001 con excepción (TSK-008 a sprint-002) | docs (no código)   | Trazabilidad de la excepción                   | Excepciones firmadas registradas en `tasks/decisions.md`.                          |
| 2026-07-03  | TSK-008 arranque de spec: `docs/ci.md` redactado                        | docs (no código)   | Bajo (sólo spec, sin implementación aún)      | spec anclado en Python 3.11 + coverage 90% + uv como gestor (ADR-0002).            |

## Pendientes por clarificar

- Convención de IDs (`request_id`, `signal_id`, `order_id`).
- Política de retención de logs (días) en runtime.
- IPC entre módulos (funciones vs eventos vs msgpack).
