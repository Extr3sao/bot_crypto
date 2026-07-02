# Sprint 001

> Sprint de arranque. Foco: cimientos de Fase 1 con configuración
> tipada. **No se hace fetch real todavía** — CCXT queda para
> sprints posteriores, una vez TSK-099 firme.

---

## Duración

- **Inicio**: 2026-07-02.
- **Fin blando** (revisión): 2026-07-09 (límite blando de 1 semana).
- **Fin duro** (cierre): 2026-07-16 (límite duro, con buffer).

## Objetivo del sprint

Poner en pie la **capa de configuración tipada con Pydantic v2**
(TSK-099) y el **baseline de calidad** (lint + tipos + CI + audit
de deps, TSK-008) sobre el que los próximos sprints podrán
construir el conector CCXT y la descarga OHLCV. Si termina antes
del fin blando, **solo entonces** se promueve TSK-101; el resto
queda para sprint-002.

## Tickets en curso

### Foundations (objetivo de este sprint)

| ID      | Descripción                                                                | Est. | Owner     | Depende de | Estado  |
| ------- | -------------------------------------------------------------------------- | ---- | --------- | ---------- | ------- |
| TSK-008 | Baseline de calidad: ruff, mypy, pytest, pip-audit, CI en GitHub Actions   | S    | Mixto     | —          | todo    |
| TSK-099 | Capa de configuración tipada con Pydantic v2 (`src/trading_bot/config/`)   | M    | Mixto     | —          | todo    |

### Bloqueados por TSK-099 (no objetivo de este sprint)

| ID      | Descripción                                                                | Est. | Owner | Depende de | Estado  |
| ------- | -------------------------------------------------------------------------- | ---- | ----- | ---------- | ------- |
| TSK-100 | ADR firmados (gestor deps + licencia) si se decide promover este sprint   | S    | Tú    | —          | blocked |
| TSK-101 | `ExchangeConnector` (interfaz + esqueleto sin fetch real)                  | M    | IA    | TSK-099    | blocked |
| TSK-102 | Descarga OHLCV con validación + normalización                              | L    | Mixto | TSK-099, TSK-101 | blocked |
| TSK-103 | Persistencia local OHLCV en `data/raw/` (formato parquet/CSV + manifest)   | M    | Mixto | TSK-099, TSK-102 | blocked |
| TSK-104 | Scheduler on-demand + caché de velas recientes                             | M    | IA    | TSK-099, TSK-102 | blocked |
| TSK-105 | Tests: unit (CCXT mock) + integration (testnet real si hay credenciales)   | M    | Mixto | TSK-101    | blocked |
| TSK-110 | BDD `market_scanner.feature` ejecutado en `pytest-bdd`                     | S    | Mixto | TSK-102    | blocked |

> Leyenda: **Est.** = T-shirt size (S = ½ día, M = 1 día, L = 2-3 días).
> **Owner**: Tú (acciones manuales/decision), IA (escritura guiada), Mixto.
> **blocked** = no se aborda hasta cerrar dependencias.

## Definition of Done

### TSK-008 — Baseline de calidad

- [ ] `ruff check` y `ruff format` configurados en `pyproject.toml`
      y pasando en limpio en todo el repo.
- [ ] `mypy` configurado en `pyproject.toml` (modo `check-untyped-defs`
      como punto de partida) y pasando en limpio.
- [ ] `pytest` configurado con markers: `unit`, `integration`,
      `regression`, `slow`, `market`.
- [ ] Workflow de GitHub Actions en `.github/workflows/ci.yml`
      ejecutando ruff + mypy + pytest en cada PR y push a `main`.
- [ ] `pip-audit` integrado en CI para detección de CVEs.
- [ ] README breve (o sección en AGENTS.md) sobre cómo correr
      los linters y tests localmente.

### TSK-099 — Configuración tipada con Pydantic v2

- [ ] Modelos Pydantic v2 por YAML: `Assets`, `Exchange`, `Risk`,
      `Strategies`, `Indicators`, `Runtime` en
      `src/trading_bot/config/`.
- [ ] `Settings` raíz que carga `runtime.yaml` y aplica overrides
      desde `.env` con `pydantic-settings`.
- [ ] **fail-fast**: el bot no arranca con configuración inválida
      (test cubre al menos 3 casos: YAML malformado, `live=true`
      sin `I_UNDERSTAND_THE_RISKS`, riesgo inconsistente).
- [ ] Caso explícito: `live=true` sin `I_UNDERSTAND_THE_RISKS=true`
      → `ValidationError` con mensaje humano legible.
- [ ] Tests unitarios con cobertura ≥ 90% en
      `src/trading_bot/config/`.
- [ ] `ruff` y `mypy` limpios sobre el módulo.
- [ ] README del módulo explica cómo se carga, valida y override.

## Criterio de salida del sprint

- ✅ TSK-008 y TSK-099 cerrados con DoD verde.
- ✅ CI verde en `main` con ruff + mypy + pytest.
- ✅ ADR nuevo (ADR-0008) si surgió alguna decisión durante el sprint.
- ✅ `tasks/backlog.md` actualizado con estimaciones explícitas
  + dependencias para los tickets bloqueados.
- ❌ **No** objetivo: ninguna llamada real a CCXT, ninguna descarga
  de OHLCV, ningún test de integración con testnet.

## Riesgos detectados

- **R1 — Tamaño real de TSK-099.** Pydantic v2 cambia respecto a v1
  (modelos, validators, settings). Mitigación: si no entra en M,
  dividir en **TSK-099a** (schemas puros) y **TSK-099b** (loader
  + override por env).
- **R2 — Ruido de `mypy`.** `mypy --strict` no será realista en el
  scaffolding actual (muchos `__init__.py` vacíos, mocks). Mitigación:
  arrancar en `mypy --check-untyped-defs` y subir gradualmente Sprint
  por Sprint.
- **R3 — CI sin runners en este repo.** Si aún no hay GitHub remoto o
  secrets configurados, el workflow puede fallar al primer push.
  Mitigación: validar localmente con `act` o equivalente antes de
  abrir el PR; documentar cualquier manual step necesario.
- **R4 — Repositorio aún no inicializado.** Si el directorio no es
  aún un repo git, el paso de CI no aplica. Mitigación: si decides
  inicializarlo ahora, abrir un ADR-0008 (o ADR-0009) sobre hosting
  y remotos antes de tocar CI.

## Daily / Ceremony

- Daily async: añadir entrada al final de este archivo cada día con
  `[YYYY-MM-DD] [autor] [notas]`.
- Review al cierre: el propio `sprint-001.md` se reedita con el
  resultado final (qué se hizo, qué se movió, qué se aprendió)
  antes de marcar el sprint como cerrado en el roadmap.

## Log

```
[2026-07-02] [Buffy + usuario] Sprint abierto. Scope reducido a TSK-099 + TSK-008 por recomendación del thinker (config tipada antes de cualquier conector). TSK-10x marcados como bloqueados. Pendiente: si decides hacer git init + remote, abrir ADR sobre hosting; ADR-0001/0002/0003/0004 siguen 'Pendiente' en decisions.md (no bloqueantes para este sprint).

[2026-07-02] [Buffy + usuario] Decisiones firmadas hoy:
  - ADR-0005 limpiado: typos ("sar", "depe\nndencias") y caracteres chinos (过早) reemplazados por texto limpio. Estado: Decidido.
  - ADR-0009 firmado: Hosting = GitHub privado, HTTPS, rama main, URL https://github.com/Extr3sao/bot_crypto.git. ADR-0008 queda reservado como forward-reference de ADR-0006 (sustitucion futura de exchange).
Bootstrap git: el basher del entorno requiere bash y no está disponible en este Windows, así que entrega scripts/git_init_and_push.ps1 como script PowerShell nativo (idempotente, con pre-flight security filter, dos pausas humanas y rebase sobre origin/main si el remoto tiene README previo). El usuario corre el script desde PowerShell/VS Code terminal local y push ocurre desde la suya máquina.
Pendiente:
  - ADR-0010 (politica de proteccion de rama + PR/force-push/tags) tras el push inicial.
  - Instalar Git for Windows o exponer bash.exe via CODEBUFF_GIT_BASH_PATH para poder ejecutar git desde el basher en siguientes turnos.
```
