Feature: Execution engine
  Toda orden debe ser idempotente, validada antes del envío, y
  reintentada solo ante errores transitorios.

  Background:
    Given un exchange configurado en modo sandbox
    And una señal aprobada por el risk-manager

  Scenario: Validar orden antes de enviarla
    Given el tamaño de la orden no supera min_order_notional_usdt
    When el execution-engineer intenta enviarla
    Then debe rechazarla
    And debe registrar "below_min_notional"

  Scenario: No duplicar orden
    Given una orden con client_order_id = "X-001" ya enviada
    When se intenta enviar otra con el mismo client_order_id
    Then el sistema debe tratarla como no-op
    And debe registrar "duplicate_order_ignored"

  Scenario: Reintentar ante error transitorio
    Given el exchange devuelve error "rate limit"
    When el execution-engineer maneja el error
    Then debe reintentar con backoff exponencial hasta max_attempts

  Scenario: Cancelar orden insegura
    Given la orden sale fuera de los límites de precio definidos
    When se detecta antes del envío
    Then debe cancelarse automáticamente
    Y debe registrarse "order_canceled_unsafe_price"

  Scenario: Registrar error de API definitivo
    Given el exchange devuelve error "insufficient balance"
    When el execution-engineer procesa el error
    Then NO reintenta
    Y emite alerta al observability-engineer
    Y registra evento "execution_error_definitive"

  Scenario: Slippage estimado vs real fuera de banda
    Given el slippage estimado es 5 bps
    When el fill real muestra slippage = 20 bps
    Then debe marcarse "slippage_out_of_band"
    Y debe alertar al observability-engineer
