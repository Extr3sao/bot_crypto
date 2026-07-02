# Command 11 — Release Live

## Objetivo
**Bloquear o desbloquear live trading** aplicando el checklist obligatorio.
Por defecto **siempre bloquea**.

## Agente(s) responsable(s)
- `risk-manager` + `execution-engineer` + `backtest-engineer` + `security-reviewer` + **un humano**.

## Entradas
- `tasks/decisions.md` con la promoción a `live_candidate`.
- Informes de `08-backtest.md` y `09-paper-trading.md`.
- `docs/live-trading-checklist.md`.

## Salidas
- Veredicto final: `BLOCKED | APPROVED_WITH_CONDITIONS | APPROVED`.
- Si `APPROVED`, se documenta:
  - Estrategias aprobadas.
  - Límites aprobados (pueden ser más estrictos que `config/risk.yaml`).
  - Fecha y firma humana.

## Pasos
1. Re-validar `LIVE_TRADING_ENABLED` y `I_UNDERSTAND_THE_RISKS`.
2. Comprobar que TODOS los gates pasan:
   - Tests unitarios + integración + regresión.
   - `safety` + `pip-audit`.
   - Backtests firmados y dentro de métricas.
   - Paper trading con métricas mínimas.
   - Validación humana en `docs/live-trading-checklist.md`.
3. Confirmar claves API sin permisos de retirada.
4. Confirmar `EXCHANGE_SANDBOX=false` (volver a usar producción solo aquí).
5. Confirmar IP whitelist, monitor y kill switch.

## Criterio de finalización
- Todos los gates verdes y firma humana explícita en el release.
- Entrada en `tasks/decisions.md`.

## NO
- No aprobar live sin paper trading con métricas mínimas.
- No aprobar live sin firma humana.
- No saltarse ni un gate.

## Línea roja
Operar live saltándose este comando = **fallo grave de proceso**. Ningún
agente puede hacerlo por "emergencia". Cualquier excepción se documenta
en `tasks/decisions.md` con la firma correspondiente.
