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

---

## 7. Ejecución autónoma y recuperación entre sesiones

Las sesiones de agente pueden cortarse (límite de contexto, timeout, cierre del cliente). Para que
el trabajo sea reanudable sin perderlo y sin fingir avances, rige esta política:

1. **Checkpoint persistente.** Al abrir sesión se lee `docs/agentic/EXECUTION_CHECKPOINT.md` y se
   contrasta con el estado real de Git (`git log -1`, `git status`). Tras cada hito relevante el
   checkpoint se actualiza con: objetivo, último commit, hecho, pendiente, bloqueos y comandos
   exactos de reanudación.
2. **La autonomía no se interrumpe por volumen.** El número de respuestas, acciones o llamadas a
   herramientas no es motivo para pedir confirmación de trabajo ya autorizado. Solo se pide
   autorización para: trading real, credenciales, privilegios administrativos, costes relevantes o
   acciones irreversibles.
3. **Un checkpoint no declara terminado lo no ejecutado.** Si una prueba o verificación no se
   ejecutó (o falló), se registra como pendiente o bloqueada; nunca como superada
   (`FALSE_SUCCESS=0`).
4. **Manda Git.** Si el checkpoint y el repositorio discrepan, el estado real es el de Git y el
   checkpoint se corrige de inmediato con ese estado.
5. **Un solo escritor por fichero.** No se sobrescriben modificaciones de otros agentes: los
   cambios ajenos se dejan intactos, se identifican y se anotan en el checkpoint.
6. **Reanudación verificable.** Los comandos de reanudación del checkpoint deben poder ejecutarse
   tal cual y producir evidencia (log, artefacto, exit code), no una promesa.
