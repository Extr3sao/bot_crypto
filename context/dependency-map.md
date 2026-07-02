# Dependency Map

> Dependencias externas declaradas en `pyproject.toml` y su rol. Las
> dependencias internas aparecen en `codebase-map.md`.

---

## Dependencias externas (runtime)

| Paquete              | Versión mín. | Uso                                                            | Riesgo |
| -------------------- | ------------ | -------------------------------------------------------------- | ------ |
| `ccxt`               | ≥ 4.0        | Conector multi-exchange.                                       | Cambios de API en upgrades mayores. |
| `pandas`             | ≥ 2.1        | Series temporales OHLCV.                                       | Memoria en datasets grandes. |
| `numpy`              | ≥ 1.26       | Cálculo numérico (indicadores, vec).                           | Estable. |
| `pydantic`           | ≥ 2.6        | Modelos de configuración y validación tipada.                 | v2 vs v1 incompatibles. |
| `pydantic-settings`  | ≥ 2.2        | Carga de settings desde YAML + .env.                          | Acoplado a Pydantic v2. |
| `PyYAML`             | ≥ 6.0        | Lectura de YAML.                                              | — |
| `rich`               | ≥ 13.7       | CLI; tablas; trazas.                                          | — |
| `APScheduler`        | ≥ 3.10       | Scheduler de jobs (scanner, health).                          | — |
| `tenacity`           | ≥ 8.2        | Retries con backoff exponencial.                              | — |
| `structlog`          | ≥ 24.1       | Logs estructurados JSON.                                      | — |
| `python-dotenv`      | ≥ 1.0        | Cargar `.env`.                                                | — |

## Dependencias externas (dev)

| Paquete     | Versión mín. | Uso                                       |
| ----------- | ------------ | ----------------------------------------- |
| `pytest`    | ≥ 8.0        | Tests unitarios, integración, regresión.  |
| `pytest-cov`| ≥ 4.1        | Cobertura.                                |
| `hypothesis`| ≥ 6.98       | Property tests (especialmente risk).      |
| `ruff`      | ≥ 0.4        | Lint + format.                            |
| `mypy`      | ≥ 1.9        | Tipado estático.                          |
| `safety`    | ≥ 3.0        | Auditoría de CVEs.                        |
| `pip-audit` | (recomendado) | Auditoría adicional.                      |

## Pendientes (a evaluar)

- `loguru` (opcional) si se prefiere UX de logs más simple.
- `polars` (opcional) si se decide migrar de `pandas` por rendimiento.
- `prometheus-client` cuando se active la fase 8 (observabilidad).
- `httpx` para mejorar resiliencia de llamadas HTTP.

## Reglas

1. Toda dependencia nueva requiere:
   - Justificación en `docs/architecture.md` o ADR.
   - `safety check` verde.
2. No se añaden dependencias transitivas innecesarias.
3. Las dependencias que tocan red/secretos pasan por `security-reviewer`.

## Versión objetivo

- Python 3.11+.
- Pip / uv / poetry. Pendiente ADR-0002 en `tasks/decisions.md`.

## Última actualización

Pendiente tras la primera revisión de `security-reviewer`.
