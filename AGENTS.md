# AGENTS.md

> Documento vivo que define **qué agentes existen**, **qué responsabilidades tiene cada uno** y **cómo se invocan dentro de la metodología híbrida SDD/BDD/CDD/TDD**.
>
> Para el flujo completo y orden de invocación, consulta `.ai/orchestration.md`. Para la metodología general, `.ai/methodology-hybrid.md`.

---

## 1. Filosofía

El proyecto se construye como un **sistema multi-agente especializado**. Cada agente es una *función pura de un rol humano*, no un script único que intenta cubrir todo. Antes de modificar código, el agente responsable **lee el contexto**.

Reglas transversales:

- Ningún agente toma decisiones de dinero sin pasar por el **risk-manager** y el **backtest-engineer**.
- Ningún agente introduce credenciales en código (lo valida **security-reviewer**).
- Toda hipótesis de estrategia es **separada de los resultados validados** (`docs/strategy-design.md`).
- Toda acción de un agente queda **registrada** (`context/retrieval-log.md`).

## 2. Los 9 agentes

Cada agente tiene una ficha individual en `.ai/agents/<nombre>.md` con:

- Misión.
- Entradas esperadas.
- Salidas esperadas.
- Artefactos que produce/actualiza.
- Comandos SDD que dispara.
- Restricciones y *do-not-do*.

| # | Agente              | Fichero                              | Foco principal                                          |
| - | ------------------- | ------------------------------------ | ------------------------------------------------------- |
| 1 | **context-engineer**   | `.ai/agents/context-engineer.md`     | Mapear el repo, refrescar contexto, detectar regresiones de dependencias. |
| 2 | **quant-researcher**  | `.ai/agents/quant-researcher.md`    | Formular hipótesis de estrategias; exigir métricas y validación.         |
| 3 | **bdd-analyst**       | `.ai/agents/bdd-analyst.md`         | Convertir requisitos a Gherkin; definir casos límite.                    |
| 4 | **risk-manager**      | `.ai/agents/risk-manager.md`        | Limitar tamaño, drawdown, exposición, kill switch.                       |
| 5 | **strategy-engineer** | `.ai/agents/strategy-engineer.md`   | Implementar estrategias desacopladas de indicadores y del exchange.       |
| 6 | **execution-engineer**| `.ai/agents/execution-engineer.md`  | Órdenes idempotentes, retries, slippage, comisiones.                      |
| 7 | **backtest-engineer** | `.ai/agents/backtest-engineer.md`   | Backtests reproducibles; comisiones, slippage, walk-forward.              |
| 8 | **observability-engineer** | `.ai/agents/observability-engineer.md` | Logs estructurados, métricas, alertas, dashboards.                |
| 9 | **security-reviewer** | `.ai/agents/security-reviewer.md`   | Secretos, permisos del exchange, dependencias, hardening.                  |

## 3. Cuándo invocar cada agente (resumen)

| Necesidad                                                | Agente(s)                                                      |
| -------------------------------------------------------- | -------------------------------------------------------------- |
| Empezar tarea nueva o cambio grande                     | context-engineer → quant-researcher (si toca estrategia) → bdd-analyst |
| Definir módulo nuevo                                    | bdd-analyst + strategy-engineer/risk-manager (según módulo)    |
| Tocar órdenes, retries o slippage                       | execution-engineer + risk-manager + security-reviewer          |
| Ejecutar / ampliar backtests                             | backtest-engineer + quant-researcher + risk-manager            |
| Cambiar configuración, claves, `.env`, permisos         | security-reviewer                                              |
| Revisar logs, métricas o alertas                         | observability-engineer                                          |
| Antes de habilitar live trading                          | risk-manager + backtest-engineer + execution-engineer + security-reviewer |

## 4. Comandos SDD disponibles

Los 12 comandos viven en `.ai/commands/` y numerados `00-…-11-…`:

- `00-context-scan.md`
- `01-requirements.md`
- `02-bdd.md`
- `03-specify.md`
- `04-plan.md`
- `05-tasks.md`
- `06-implement-next.md`
- `07-evaluate.md`
- `08-backtest.md`
- `09-paper-trading.md`
- `10-risk-review.md`
- `11-release-live.md`

Cada uno describe objetivo, entradas, salidas, agente(s) responsables y criterios de finalización.

## 5. Reglas duras

1. No se introduce código sin un **comando SDD aprobado** (`06-implement-next.md`).
2. No se habilita live trading sin pasar el **release gate** (`11-release-live.md`).
3. Ninguna estrategia opera con dinero real sin haber superado **paper trading** con métricas mínimas (ver `docs/paper-trading-methodology.md`).
4. El **contexto** se actualiza tras cada cambio relevante (`context-engineer`).
5. Las **decisiones arquitectónicas** se registran en `tasks/decisions.md` (ADR).

## 6. Diagrama lógico

```
                ┌───────────────┐
                │  context-     │
                │  engineer     │◀─────────┐
                └───────┬───────┘          │
                        │                  │
                        ▼                  │
        ┌────────────────────────────┐     │
        │  quant-researcher (si       │     │
        │  toca estrategia)           │     │
        └─────────────┬──────────────┘     │
                      │                    │
                      ▼                    │
        ┌────────────────────────────┐     │
        │  bdd-analyst               │     │
        └─────────────┬──────────────┘     │
                      │                    │
                      ▼                    │
        ┌────────────────────────────┐     │
        │  strategy-engineer         │─────┤
        └─────────────┬──────────────┘     │
                      │                    │
                      ▼                    │
        ┌────────────────────────────┐     │
        │  risk-manager              │─────┤
        └─────────────┬──────────────┘     │
                      │                    │
                      ▼                    │
        ┌────────────────────────────┐     │
        │  execution-engineer        │─────┤
        └─────────────┬──────────────┘     │
                      │                    │
                      ▼                    │
        ┌────────────────────────────┐     │
        │  backtest-engineer         │─────┤
        └─────────────┬──────────────┘     │
                      │                    │
                      ▼                    │
        ┌────────────────────────────┐     │
        │  observability-engineer    │─────┤
        └─────────────┬──────────────┘     │
                      │                    │
                      ▼                    │
        ┌────────────────────────────┐     │
        │  security-reviewer         │─────┘
        └────────────────────────────┘
```

> En todo loop, **context-engineer** refresca el mapa antes de volver a iterar.
