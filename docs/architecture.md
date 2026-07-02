# Architecture

> Decisiones técnicas del proyecto. Se actualiza con cada ADR en
> `tasks/decisions.md`. La pregunta no es "¿qué es lo más moderno?",
> sino "¿qué mantiene el sistema auditable, testeable y seguro?".

---

## 1. Lenguaje: Python 3.11+

Justificación:
- Ecosistema maduro para data (pandas/numpy) y trading algorítmico.
- Tipado gradual ayuda a evitar bugs sin sacrificar velocidad de iteración.
- Multiplataforma y fácil de testear con `pytest`.

Trade-offs:
- Más lento que C++/Rust para hot paths. Aceptable: el bot opera
  en timeframes 1m–15m, no HFT.
- Concurrencia limitada a `asyncio` y `APScheduler`. Suficiente para
  nuestras cadencias.

## 2. Conector: CCXT

Justificación:
- Capa de abstracción multi-exchange.
- Reduce acoplamiento del dominio al exchange concreto.
- Soporta sandbox en la mayoría de exchanges populares.

Trade-offs:
- Si una feature específica del exchange no está en CCXT, requiere
  adaptador. Se aísla en `market_data/`.

## 3. Datos: pandas + NumPy

Justificación:
- Maduros; conocidos por el equipo; suficientes para los volúmenes actuales.
- Fáciles de testear con `hypothesis`.

Pendiente:
- Considerar `polars` si el volumen/performance lo justifica (ADR pendiente).

## 4. Configuración: Pydantic v2

Justificación:
- Validación tipada de YAML y `.env` al cargar.
- Errores claros al arranque: imposible arrancar con config inválida.
- Compatible con `pydantic-settings`.

## 5. Persistencia: SQLite → PostgreSQL (futuro)

Justificación:
- Empezar simple (sin servidor) reduce fricción local.
- Migración a Postgres sin cambios mayores en código: usar `SQLAlchemy`
  o `sqlite3` con un DAL.

## 6. CLI: Rich

Justificación:
- Mejor DX en consola.
- Tablas y trazas legibles para humanos y CSVs/Jsons para máquinas.

## 7. Scheduler: APScheduler

Justificación:
- Fácil de testear.
- Suficiente para cadencia de minutos (no microsegundos).
- Mercado-aware vía reglas de horario.

## 8. Observabilidad: structlog (+ opcional `loguru`)

Justificación:
- Logs estructurados JSON ingestables por cualquier agregador.
- `structlog` permite chaining y binding (`request_id`, `signal_id`).

## 9. Testing: pytest + hypothesis

Justificación:
- Estándar de facto.
- `hypothesis` para property tests, especialmente en `risk` y `indicators`.

## 10. Calidad: Ruff + Mypy

Justificación:
- Ruff reemplaza black+isort+flake8 en una sola herramienta rápida.
- Mypy strict + plugin de pydantic → errores en compile-time.

## 11. Capas y dependencias

```
indicators ────────────────┐
                           ▼
strategies ─────> signals ──> risk (sizing, veto) ──> execution
                                                  │
                                                  ▼
                                           portfolio / paper / live
                                                  │
                                                  ▼
                                            observability
```

Reglas:
- `strategies` no importa `execution`.
- `risk` no envía órdenes — solo veredictos.
- `execution` no conoce sizing — solo orden + idempotencia.
- `indicators` no conoce el par ni el exchange.

## 12. Modos y gating

Los modos (`research | backtest | paper | shadow-live | live`) y el bloqueo
de live se controlan en `config/runtime.yaml` + `.env`. El código debe
fallear rápido si está en `live` sin todas las variables requeridas.

## 13. Decisiones pendientes (ADR)

| ID     | Tema                                            | Estado |
| ------ | ----------------------------------------------- | ------ |
| ADR-0001 | Licencia del proyecto                          | Pendiente |
| ADR-0002 | Gestor de deps (uv vs poetry vs pip)            | Pendiente |
| ADR-0003 | Dashboard (web vs CLI)                          | Pendiente |
| ADR-0004 | Telemetría (Prometheus vs OpenTelemetry)        | Pendiente |
| ADR-0005 | Persistencia de órdenes y fills                  | Pendiente |

## 14. Anti-patrones arquitectónicos prohibidos

1. **Lógica en `__init__.py`** que importe side-effects.
2. **Cross-imports entre submódulos no relacionados** (`strategies` → `execution`).
3. **Send-and-forget en threads sin traceback handling**.
4. **Estado mutable global** no encapsulado.
5. **Mezclar I/O y cálculo** en una misma función.
