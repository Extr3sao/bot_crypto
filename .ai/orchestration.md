# Orquestación de Agentes

> Cómo se combinan los 9 agentes y los 12 comandos en la práctica.
> Para la metodología: `.ai/methodology-hybrid.md`.

---

## 1. Topología

Hay **9 agentes** especializados (ver `AGENTS.md` y `.ai/agents/*.md`) y **12 comandos SDD numerados** (`.ai/commands/00-…-11-…`).

Los agentes son **roles**. Los comandos son **instrucciones**. La realidad es que varios agentes pueden colaborar dentro de un mismo comando. Ningún agente es sustituible por otro salvo emergencia documentada.

```
                         ┌────────────────────────┐
                         │   00 context-engineer   │
                         └────────────┬───────────┘
                                      │  refresca contexto
                                      ▼
   ┌────────────┐   ┌────────────┐   ┌────────────┐    ┌────────────┐
   │  quant-    │   │  bdd-      │   │  security- │    │  risk-     │
   │ researcher │   │  analyst   │   │  reviewer  │    │ manager    │
   └─────┬──────┘   └─────┬──────┘   └─────┬──────┘    └─────┬──────┘
         │                │                │                 │
         ▼                ▼                ▼                 ▼
   ┌────────────┐   ┌──────────────────────────────────────────┐
   │ strategy-  │   │  execution-engineer / backtest-engineer   │
   │ engineer   │   └─────────────────┬────────────────────────┘
   └────────────┘                     │
                                      ▼
                       ┌────────────────────────────┐
                       │   observability-engineer   │
                       └────────────────────────────┘
```

## 2. Responsabilidades transversales

- **context-engineer**: cualquier agente puede pedirle refresco. Nunca decide lo que cambia — solo **describe el estado**.
- **risk-manager**: tiene **veto** sobre cualquier acción de live. Su decisión se registra en `logs/decisions.log`.
- **security-reviewer**: tiene **veto** sobre merges que toquen `.env`, secrets o permisos.
- **observability-engineer**: instrumenta y mide. No modifica lógica de negocio.
- **quant-researcher**: propone hipótesis. Nunca declara una estrategia rentable sin evidencia validada.

## 3. Mapeo comando → agentes

| # | Comando                  | Agente(s) principal(es)                                       | Salida                                                    |
| - | ------------------------ | ------------------------------------------------------------- | --------------------------------------------------------- |
| 00 | `00-context-scan.md`     | context-engineer                                              | `context/*` actualizado                                   |
| 01 | `01-requirements.md`     | quant-researcher (si aplica) + bdd-analyst                    | Requisitos completos                                     |
| 02 | `02-bdd.md`              | bdd-analyst                                                   | Escenarios en `bdd/features/`                             |
| 03 | `03-specify.md`          | strategy-engineer / execution-engineer                        | Spec técnica + contratos                                  |
| 04 | `04-plan.md`             | strategy/risk/execution engineers                            | Plan incremental                                         |
| 05 | `05-tasks.md`            | cualquier agente                                             | Lista de tareas pequeñas y trazables                      |
| 06 | `06-implement-next.md`   | implementador (humano/LLM)                                    | PR pequeño con tests                                      |
| 07 | `07-evaluate.md`         | reviewers + CI                                                | Reporte de evaluación                                     |
| 08 | `08-backtest.md`         | backtest-engineer + quant-researcher + risk-manager          | Informe de backtest                                       |
| 09 | `09-paper-trading.md`    | observability-engineer + risk-manager                        | Informe paper + comparación                               |
| 10 | `10-risk-review.md`      | risk-manager + security-reviewer                              | Revisión de riesgos                                       |
| 11 | `11-release-live.md`     | risk-manager + execution-engineer + backtest-engineer + SEC   | Veredicto + checklist firmado                            |

## 4. Routers prácticos

### 4.1 Quiero añadir una nueva estrategia

`00-context-scan → 01-requirements (quant-researcher) → 02-bdd (bdd-analyst) → 03-specify (strategy-engineer) → 04-plan → 05-tasks → 06-implement-next (con TDD) → 07-evaluate → 08-backtest → 09-paper-trading → 10-risk-review → (decisión)`.

### 4.2 Quiero añadir un nuevo indicador

`00-context-scan → 01-requirements → 03-specify (strategy-engineer o execution-engineer según uso) → 04-plan → 05-tasks → 06-implement-next (TDD sobre series sintéticas) → 07-evaluate → registrado en `config/indicators.yaml``.

### 4.3 Quiero añadir un exchange

`00-context-scan → 03-specify (execution-engineer) → 04-plan → 09-...` La validación de live pasa por security-reviewer.

### 4.4 Quiero habilitar paper trading con una estrategia

`08-backtest` (run) → resultados OK → `09-paper-trading` → métricas mínimas (ver `docs/paper-trading-methodology.md`) → `10-risk-review`.

### 4.5 Quiero habilitar live

`09-paper-trading` (≥ N sesiones) → `10-risk-review` → `11-release-live`.

## 5. Estado de un agente

Cada agente, al inicio de su turno, **lee**:

1. Su ficha en `.ai/agents/<nombre>.md`.
2. La metodología en `.ai/methodology-hybrid.md`.
3. El contexto en `context/*`.
4. El estado del backlog en `tasks/backlog.md`.

Y al final **deja registrado** en `context/retrieval-log.md`:

```
[YYYY-MM-DD HH:MM] agent=<name> action=<action> artifacts=<list>
```

## 6. Inspección humana

Los humanos firman:

- Cualquier ADR en `tasks/decisions.md`.
- Activación de `live` con `LIVE_TRADING_ENABLED=true I_UNDERSTAND_THE_RISKS=true` y asunción consciente.
- Cualquier excepción a la metodología.
