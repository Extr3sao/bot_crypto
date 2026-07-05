# TSK-103 - Universe Scanner: Architectural Plan (Command 04)

> Plan incremental de implementacion. 5 tickets pequenos, ordenados
> por reversibilidad y verifica-antes-de-avanzar. Metodologia:
> `.ai/commands/04-plan.md`.

---

## Pre-condiciones

1. TSK-099 mergado en `main` (ya verdadero).
2. TSK-101 y TSK-102 al menos a nivel local (hoy `in_progress`,
   pendiente PR). Como el scanner **NO** depende de la API publica
   del connector/store (solo usa el Protocol `MarketDataSourceProtocol`
   y `OHLCV`), estos tickets pueden entrar en paralelo con TSK-103.1.
3. ADR-0013 firmada antes del merge final de TSK-103.5.

## Fases

### F1. TSK-103.1 - Tipos y protocolos

- **Objetivo**: tener el contrato publico cerrado antes de cualquier
  logica. Cero logica de negocio.
- **Archivos nuevos**:
  - `src/trading_bot/scanner/__init__.py` (re-exports).
  - `src/trading_bot/scanner/types.py` (`MarketSnapshot`,
    `FilterOutcome`, `Literal` de motivos).
  - `src/trading_bot/scanner/protocols.py` (`MarketDataSourceProtocol`,
    `Filter`).
  - `src/trading_bot/scanner/exceptions.py`.
- **Tests**:
  - `tests/unit/scanner/test_types.py`: dataclass frozen, slots,
    campos obligatorios, isinstance OHLCV.
  - `tests/unit/scanner/test_protocols.py`: runtime_checkable OK,
    atributos de protocolo detectados por mypy.
- **Gate**: `pytest tests/unit/scanner/test_types.py
  tests/unit/scanner/test_protocols.py` >= 8 verde; mypy verde.
- **Reversibilidad**: borrar 4 archivos, cero side-effects.

### F2. TSK-103.2 - Filtros y registry

- **Objetivo**: encapsular cada filtro aisladamente y permitir
  composicion extensible sin tocar el orquestador.
- **Archivos nuevos**:
  - `src/trading_bot/scanner/registry.py`.
  - `src/trading_bot/scanner/filters.py` (`VolumeFilter`,
    `SpreadFilter`, `AtrFilter`).

> **TODO(R5-LATENT) — `_compute_atr_pct` = media(TR) sobre todas las velas**
> El helper privado ``_compute_atr_pct`` en `filters.py` calcula ATR
> como media aritmetica de True Ranges sobre TODAS las velas que
> recibe (``mean(TR_1..TR_N)``), no como ATR-Wilder de ventana fija
> (e.g. ATR-14). Si se quiere ATR-14 estricto: aceptar
> ``window: int`` opcional, decidir si el recorte viene de la fuente
> o se hace in-place, y emitir ADR para cambiar la firma publica.
> Cualquier inversion del contrato requiere ADR firmada en
> `tasks/decisions.md` antes de modificar los tests existentes
> (`tests/unit/scanner/test_filters.py::test_compute_atr_pct_*`).
> Releease este riesgo antes de promover a Fase 7/8.
- **Tests**:
  - `tests/unit/scanner/test_registry.py`: register/unregister,
    duplicados levantan ValueError, orden preservado.
  - `tests/unit/scanner/test_filters.py`: parametrizado por filtro y
    por umbral, mock OHLCV sintetico.
- **Gate**: `pytest tests/unit/scanner/test_registry.py
  tests/unit/scanner/test_filters.py` >= 14 verde.
- **Reversibilidad**: borrar 2 archivos, no afecta F1.

### F3. TSK-103.3 - Scoring y normalizacion

- **Objetivo**: determinismo y formula cerrada (RF-10). Cualquier
  cambio requiere ADR.
- **Archivos nuevos**:
  - `src/trading_bot/scanner/scoring.py` (`compute_rank_score`).
- **Tests**:
  - `tests/unit/scanner/test_scoring.py`: parametrizado con 8
    casos (extremos, valores optimos, atr None).
  - property test con `hypothesis` para formula invariante:
    `0 <= rank_score <= 1`.
- **Gate**: 4 + property verde.
- **Reversibilidad**: borrar 1 archivo, F1/F2 intactas.

### F4. TSK-103.4 - Orquestador `UniverseScanner`

- **Objetivo**: pegar todos los modulos. AQUI vive el asyncio loop
  principal y el manejo de errores transitorios.

> **TODO(R1-HIGH) — `VolumeFilter.mode` baked at construction requiere registries per-mode**
> `VolumeFilter` (F2) fija ``mode`` en el constructor (Decision D1-A del
> thinker, ADR-lock). Para alternar el endurcimiento del threshold
> entre `paper` y `live` sin re-construir filtros en runtime, F4
> evaluara entre (a) `self._registries: dict[mode, FilterRegistry]`
> (registries paralelos, uno por modo) o (b) re-builda `VolumeFilter`
> al cambiar `runtime.mode` y los re-registra en un unico registry.
> **Constraint obligatorio**: cualquiera de las dos opciones debe
> preservar la ADR-lock de inmutabilidad del registry post-`freeze()`
> (un registry `freeze()`-ado no acepta mas `register()`); esto veta
> re-registros en runtime si se opta por (b). Cerrar la eleccion
> final con ADR firmada en `tasks/decisions.md` antes de promover
> F4 a `in_progress`. Releer `specs/03-specify.md §5` antes de
> implementar este ticket.
- **Archivos nuevos**:
  - `src/trading_bot/scanner/scanner.py` (`UniverseScanner`,
    `_Counters`, `run()`).
- **Tests**:
  - `tests/unit/scanner/test_universe_scanner.py`: 12+ tests cubriendo
    cada RF (con `FakeMarketDataSource`).
  - cross-layer test: `tests/unit/scanner/test_cross_layer.py`
    parsea AST del modulo y falla si importa `execution`,
    `strategies`, `risk`, `portfolio`.
- **Gate**: `pytest tests/unit/scanner/` >= 30 verde total; mypy
  strict verde en todo el paquete.
- **Reversibilidad**: borrar 1 archivo, F1-F3 siguen testeando.

### F5. TSK-103.5 - Wiring con Settings + BDD + gates

- **Objetivo**: cerrar el ciclo con `trading_bot.config.Settings`,
  anadir los 17 escenarios BDD nuevos y validar los 6 quality gates.
- **Cambios**:
  - En `tests/unit/scanner/test_universe_scanner.py` anadir fixtures
    que cargan `Settings` real desde `assets.yaml`/`risk.yaml`.
  - Anadir los 17 escenarios a `bdd/features/market_scanner.feature`.
  - Registrar decision D1 (scope reconciliation) en
    `tasks/decisions.md` como **ADR-0013** (forward-reference o nuevo).
  - Actualizar `tasks/backlog.md` y `tasks/sprint-002.md`.
- **Gate**: full pre-flight local (`ruff format`, `ruff check`,
  `mypy`, `pytest --cov`, cobertura >= 90); BDD `pytest-bdd` 23/23.
- **Reversibilidad**: borrar scenarios y ADR; F1-F4 intactas.

## Ticket breakdown (resumen)

| ID        | Tam | FASE | Riesgo | DoD resumida                                        |
| --------- | --- | ---- | ------ | --------------------------------------------------- |
| TSK-103.1 | S   | 1    | L      | Tipos frozen + protocolos + 8 tests verdes          |
| TSK-103.2 | M   | 1    | M      | 3 filtros default + registry + 14 tests verdes      |
| TSK-103.3 | S   | 1    | L      | `compute_rank_score` + property test                |
| TSK-103.4 | M   | 1    | H      | `UniverseScanner` + cross-layer enforcement         |
| TSK-103.5 | S   | 1    | M      | BDD + Settings wiring + ADR-0013 + 6 gates verdes   |

## Orden de ejecucion

```
F1 (TSK-103.1) ─> F2 (TSK-103.2) ─> F3 (TSK-103.3) ─> F4 (TSK-103.4) ─> F5 (TSK-103.5)
```

F1-F3 son trivialmente paralelizables entre si (zeros imports
cruzados). F4 depende de F1-F3. F5 depende de F4 + cierre de TSK-101
(PR mergeado) + TSK-102 (PR mergeado) para correr el gate de
integracion contra el connector real.

## Riesgos del plan

- **R1**: mypy strict y `Protocol` con `runtime_checkable` requiere
  cuidado para no introducir Any accidental. Mitigacion: mypy en
  cada fase.
- **R2**: asyncio + tests sync. Si el runner no soporta asyncio, los
  tests del orquestador fallan. Mitigacion: `pytest-asyncio` ya
  presente en `[dependency-groups].dev` (TSK-008).
- **R3**: cross-layer enforcement via AST parsing puede ser fragil.
  Mitigacion: usar `astroid` solo si `ast` directo falla; fallback
  documentado.
- **R4**: cobertura >= 90% en scanner puede quedar justa si los
  modulos crecen. Mitigacion: omit defensivo solo para ramas `pragma:
  no cover` marcadas explicitamente.

## Criterio de salida del plan

- Los 5 tickets pueden entrar en marcha independientemente.
- Cada ticket tiene DoD medible (test count + gate list).
- El plan no asume capacidad adicional de reviewer: el flujo
  `06-implement-next.md` + `code-reviewer-minimax-m3` cubre cada
  PR pequeno.

## Siguiente fase (handoff a `05-tasks.md`)

`05-tasks.md` expande cada ticket del plan en 1..N tareas pequenas
con archivos exactos, tests esperados y dependencias entre tareas.
