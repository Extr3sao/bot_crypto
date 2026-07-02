# Risk Quality Gates

> Cómo se audita que el código relacionado con riesgo cumple la política.

---

## 1. Cobertura mínima

- `src/trading_bot/risk/` ≥ **90%** líneas y branches.
- `src/trading_bot/execution/` ≥ **85%**.
- `src/trading_bot/strategies/` ≥ **80%**.

## 2. Tests obligatorios para `risk/`

- Pérdida diaria → cooldown.
- Drawdown total → kill switch.
- Racha pérdidas → cooldown.
- Exceso de exposición por activo.
- Exceso de exposición total.
- Bloqueo por spread/volumen/latencia.
- Cálculo de tamaño de posición (varios escenarios).
- Kill switch ON/OFF (test funcional).

## 3. Property tests con `hypothesis`

- Sizing: invariantes (no negative, no zero when valid).
- Drawdown: monotónico.
- Kill switch: ON nunca se desactiva accidentalmente.

## 4. Auditoría de cambios

- Toda PR que toque `risk/` o `config/risk.yaml` requiere:
  - Aprobación explícita de `risk-manager` (humano o agente).
  - ADR firmado.
  - Test específico que cubra el cambio.

## 5. Prohibido

- Constantes mágicas en código (los límites van en YAML).
- Desactivar límites por feature flag sin ADR.
- Re-emisión de señales rechazadas.

## 6. Inspección periódica

- Reporte semanal ejecutado por `risk-manager`:
  - Estado de los límites.
  - Eventos relevantes (kill switch ON/OFF, rechazos).
  - Recomendaciones a humanos.
