# Command 10 — Risk Review

## Objetivo
Revisar **riesgos de trading, software, seguridad y configuración** antes
de cualquier promoción o release.

## Agente(s) responsable(s)
- `risk-manager` + `security-reviewer`.

## Entradas
- Cambios recientes (`context/impact-analysis.md`).
- Resultados de `08-backtest.md` y `09-paper-trading.md` (cuando aplique).
- `config/risk.yaml`, `config/strategies.yaml`, `config/indicators.yaml`.

## Salidas
- `reports/risk-review-<fecha>.md` con:
  - Cambios evaluados, severidad, mitigación.
  - Estado del kill switch.
  - Estado del live trading bloqueado.
  - Recomendaciones firmadas.

## Pasos
1. Listar cambios desde la última revisión.
2. Evaluar con matriz probabilidad × impacto.
3. Identificar nuevos riesgos y mitigaciones.
4. Comprobar que el kill switch está activo.
5. Comprobar que `LIVE_TRADING_ENABLED=false`.
6. Validar `.env.example`, secretos, dependencias (`safety`, `pip-audit`).
7. Firmar la revisión.

## Criterio de finalización
- Revisión firmada.
- Cualquier riesgo abierto requiere ADR al lado.

## NO
- No firmar la revisión con riesgos críticos abiertos.
- No aprobar cambios que debiliten el kill switch.
