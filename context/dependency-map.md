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

`python-dotenv` llegó como dep transitiva vía `pydantic-settings` pero
se importa directamente en
`src/trading_bot/config/settings.py::FlatEnvAliasSource`. Mantener.

## Dependencias externas (dev)

| Paquete     | Versión mín. | Uso                                       | Notas                                    |
| ----------- | ------------ | ----------------------------------------- | ---------------------------------------- |
| `pytest`    | ≥ 8.0        | Tests unitarios, integración, regresión.  | markers ya definidos en `pyproject.toml`.|
| `pytest-bdd`| ≥ 7.0        | BDD scenarios (`bdd/features/*.feature`). | Usado por TSK-110 sprint-002.            |
| `pytest-cov`| ≥ 4.1        | Cobertura.                                | `fail_under` promovido de 70 a 90 en TSK-008. |
| `hypothesis`| ≥ 6.98       | Property tests (especialmente risk).      | Uso futuro (TSK Fase 5/6).                |
| `ruff`      | ≥ 0.4        | Lint + format.                            | `target-version = "py311"`.               |
| `mypy`      | ≥ 1.9        | Tipado estático.                          | `python_version = "3.11"` (TSK-008 fix). |
| `safety`    | ≥ 3.0        | Auditoría de CVEs.                        | Complementa a pip-audit.                  |
| `pip-audit` | ≥ 2.7        | Auditoría adicional.                      | Será integrado en GHA por TSK-008.       |
| `types-PyYAML` | ≥ 6.0     | Stub types para Pydantic/MyPy strict.    | Útil para type-check estricto.           |
| `types-requests` | ≥ 2.31  | Stub types para `requests`.               | Sólo si `httpx`/`requests` entran.        |
| `anyio`     | ≥ 4.3        | Async helpers para tests async.           | Uso futuro.                              |

## Gestor de dependencias: `uv`

`uv` según ADR-0002. PEP 735 `[dependency-groups]` añadido en TSK-099
para que `uv sync` instale ruff/mypy/pytest/pip-audit en `.venv/Scripts/`.

`uv.lock` está pin-eado. Para CI: `astral-sh/setup-uv@v3` con cache
nativo sobre `uv.lock`.

## Pin de Python

- `pyproject.toml::requires-python = ">=3.11"` (target).
- `pyproject.toml::[tool.ruff].target-version = "py311"`.
- `pyproject.toml::[tool.mypy].python_version` debería ser `"3.11"`
  para alinear con los dos anteriores. Pendiente del TSK-008.
- `.python-version` (a introducir con TSK-008): single line `3.11`
  para anclar GitHub Actions y reproducir exactamente el ambiente
  local.

## Reglas

1. Toda dependencia nueva requiere:
   - Justificación en `docs/architecture.md` o ADR firmada.
   - `pip-audit` verde.
2. No se añaden dependencias transitivas innecesarias.
3. Las dependencias que tocan red/secretos pasan por `security-reviewer`.

## Pendientes (a evaluar)

- `httpx` para mejorar resiliencia de llamadas HTTP.
- `loguru` (opcional) si se prefiere UX de logs más simple.
- `polars` (opcional) si se decide migrar de `pandas` por rendimiento.
- `prometheus-client` cuando se active la fase 8 (observabilidad).

## Última actualización

2026-07-03 — context-engineer tras cierre de sprint-001 (TSK-099 +
ADR-0010/0011). Próximo refresh post-TSK-008 (cuando se anclen Python
3.11 + coverage 90%).
