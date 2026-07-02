"""Risk manager: sizing, drawdown, kill switch, bloqueos.

Fase objetivo: 5.

Reglas duras:
- Ningún sizing se calcula fuera de este módulo.
- ``KillSwitch`` solo se desactiva manualmente.
- Toda decisión se registra en ``logs/risk-decisions.log``.
- Tests con ``hypothesis`` para invariantes.
"""
