# Methodology — Hybrid SDD / BDD / CDD / TDD

> Documento canónico que define cómo se construye el sistema.
> Aplica a cualquier cambio, desde añadir un indicador hasta activar
> una estrategia en `paper`.
>
> Orquestación práctica de los agentes: `.ai/orchestration.md`.
> Comandos numerados: `.ai/commands/`.

---

## 0. Principios

1. **Antes de tocar código, escribe la intención.** (SDD)
2. **Antes de aceptar el código, define su comportamiento.** (BDD)
3. **Antes de tocar el código, conoce el código y su contexto.** (CDD)
4. **El código crítico se prueba junto a (o antes de) su implementación.** (TDD)
5. **Nada de dinero real sin gates.** (Gating — Fase 9)
6. **Toda decisión es auditable.** (Logs + `context/retrieval-log.md`)
7. **Config gana sobre código.** (El comportamiento cambia por YAML, no por PRs.)

## 1. SDD — Spec Driven Development

Cada cambio relevante genera un artefacto antes de escribir código:

| Artefacto                | Ubicación                                        | Contenido mínimo                                                     |
| ------------------------ | ------------------------------------------------ | -------------------------------------------------------------------- |
| Requisitos               | Comentarios del PR / `context/codebase-map.md`   | Funcionales + no funcionales + criterios de aceptación               |
| Especificación técnica   | `context/impact-analysis.md` o doc dedicado      | Diseño de tipos, contratos, dependencias                             |
| Criterios de aceptación  | Escenarios BDD                                   | Casos felices + casos límite                                        |
| Riesgos                  | `docs/risk-policy.md` + ticket en `tasks/decisions.md` (ADR) | Modo de fallo, mitigación, severidad              |
| Pruebas esperadas        | `tests/` + `bdd/features/`                       | Unit + integration + regresión                                       |

Regla: **No abrir un PR sin tener al menos 3 secciones rellenas** (requisitos, criterios, pruebas esperadas).

## 2. BDD — Behavior Driven Development

Los comportamientos del sistema se escriben en Gherkin en `bdd/features/*.feature`.

Cada feature incluye:

- `Feature:` nombre legible y propósito.
- `Background:` estado común (modo `paper`, capital inicial, pares de prueba, etc.).
- `Scenario:` casos felices y casos límite.

Las features vivas son las del prompt maestro:

- `market_scanner.feature`
- `signal_generation.feature`
- `risk_manager.feature`
- `paper_trading.feature`
- `backtesting.feature`
- `execution_engine.feature`

Reglas:

- Toda regla nueva del bot debe tener al menos un escenario.
- Los escenarios describen **comportamiento externo**, no implementación interna.
- Los escenarios que se rompan significan que la implementación cambió de contrato → actualizar la spec.

## 3. CDD — Context Driven Development / RAG

Antes de tocar código, se refresca el contexto:

- `context/codebase-map.md` — módulos, archivos clave y su rol.
- `context/dependency-map.md` — dependencias internas y externas.
- `context/impact-analysis.md` — qué se rompe si cambio X.
- `context/retrieval-log.md` — log de cada decisión/consulta.
- `context/exchange-api-notes.md` — particularidades del exchange.
- `context/trading-domain-notes.md` — terminología y supuestos del dominio.

Cada agente refresca lo que le toca antes de actuar:

- `context-engineer` mantiene el mapa global.
- `strategy-engineer` actualiza `impact-analysis` si añade una estrategia.
- `execution-engineer` actualiza `exchange-api-notes` si el exchange cambia.
- `security-reviewer` actualiza `impact-analysis` si cambian permisos o secretos.

## 4. TDD — Test Driven Development

Módulos críticos deben tener tests antes o junto a su implementación:

- Risk manager (cálculo de tamaño, drawdown, kill switch).
- Cálculo de indicadores (sobre series sintéticas y series reales).
- Generación de señales (caminos felices + filtros).
- Motor de ejecución (idempotencia, retries).
- Validación de órdenes.

Reglas:

- Cobertura mínima 70% en `src/trading_bot/` (`pyproject.toml → coverage.fail_under`).
- Para módulos de riesgo, cobertura mínima 90% + property tests con `hypothesis`.
- Cada bug encontrado genera un test que reproduce el bug.

## 5. FLUJO INTEGRADO (THE LOOP)

```
┌─────────────────┐
│ 00-context-scan │  ← context-engineer
└────────┬────────┘
         ▼
┌─────────────────┐
│ 01-requirements │  ← quant-researcher (si toca estrategia) + bdd-analyst
└────────┬────────┘
         ▼
┌─────────────────┐
│    02-bdd       │  ← bdd-analyst
└────────┬────────┘
         ▼
┌─────────────────┐
│   03-specify    │  ← strategy-engineer / execution-engineer (según módulo)
└────────┬────────┘
         ▼
┌─────────────────┐
│    04-plan      │  ← strategy/risk/execution engineers
└────────┬────────┘
         ▼
┌─────────────────┐
│   05-tasks      │  ← any agent
└────────┬────────┘
         ▼
┌─────────────────┐
│ 06-implement-   │  ← implementador (puede ser humano o LLM)
│     next        │
└────────┬────────┘
         ▼
┌─────────────────┐
│  07-evaluate    │  ← reviewers + CI
└────────┬────────┘
         ▼
┌─────────────────┐
│  08-backtest    │  ← backtest-engineer + quant-researcher
└────────┬────────┘
         ▼
┌─────────────────┐
│ 09-paper-       │  ← observability-engineer + risk-manager
│    trading      │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 10-risk-review  │  ← risk-manager + security-reviewer
└────────┬────────┘
         ▼
┌─────────────────┐
│ 11-release-live │  ← TODOS — y humanos con confirmación explícita
└─────────────────┘
```

## 6. Línea roja

Activar live trading saltándose uno de los pasos del flujo es un **fallo grave de proceso**. Toda excepción debe quedar registrada en `tasks/decisions.md` con firma explícita.

## 7. Cuándo NO se aplica la metodología

- Cambios puramente cosméticos (typos, comentarios, formato).
- Refactors pequeños documentados en un ADR.
- Cambios en dependencias que se cubren con su propia suite de tests.

En esos casos, basta con un commit descriptivo que **referencie** el artefacto afectado (e.g. "doc: aclarar caso límite en risk-policy.md").
