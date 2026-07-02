Feature: Signal generation
  Las estrategias únicamente emiten señales. Las señales deben ser
  trazables, explicables y compatibles con el risk-manager.

  Background:
    Given una estrategia con estado "paper"
    And un snapshot de mercado válido
    And todos los indicadores necesarios disponibles

  Scenario: Generar señal candidata
    When la estrategia evalúa el snapshot
    Then debe producir una señal con campos: symbol, side, entry_type, reason, indicators
    And debe registrar la señal con un signal_id único

  Scenario: Rechazar señal por falta de confirmación
    Given la estrategia requiere "volumen relativo > 1.5"
    And el valor observado es 0.9
    When la estrategia evalúa el snapshot
    Then NO debe emitir señal
    And debe registrar el motivo "confirmation_failed"

  Scenario: Rechazar señal por baja liquidez
    Given el volumen 24h del par < min_volume_24h_usdt
    When la estrategia evalúa el snapshot
    Then NO debe emitir señal
    And debe registrar el motivo "low_liquidity"

  Scenario: Rechazar señal por volatilidad extrema
    Given ATR% > extreme_atr_pct
    When la estrategia evalúa el snapshot
    Then NO debe emitir señal
    And debe registrar el motivo "extreme_volatility"

  Scenario: Registrar explicación de la señal
    Given una señal emitida por la estrategia "trend_pullback_scalping"
    When la señal llega al risk-manager
    Then debe incluir los valores de los indicadores en el momento de la decisión
    And debe incluir el motivo humano legible

  Scenario: Cambiar de estrategia sin reiniciar el motor
    Given la estrategia activa es "trend_pullback_scalping"
    When se desactiva y se activa "range_reversion_scalping"
    Then el motor no debe reiniciar el scheduler
    And la siguiente evaluación usa la nueva estrategia
