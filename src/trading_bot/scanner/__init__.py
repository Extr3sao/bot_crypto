"""Escáner multi-activo.

Fase objetivo: 3.

Responsabilidades:
- Iterar los pares configurados.
- Aplicar filtros (volumen, spread, volatilidad).
- Producir ``MarketSnapshot`` para el motor de estrategias.
- Manejar errores transitorios sin abortar el loop.

Reglas:
- Espera a que ``kill_switch`` esté desactivado.
- Reporta contadores de éxito/error/par inactivo.
"""
