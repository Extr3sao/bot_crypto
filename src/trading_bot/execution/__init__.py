"""Motor de ejecución: órdenes idempotentes, retries, slippage.

Fase objetivo: implementación cruzada Fase 4-6 según modo.

Responsabilidades:
- ``OrderBuilder``: validación antes del envío.
- ``IdempotencyKey``: garantiza una sola orden por client_order_id.
- ``RetryPolicy``: backoff exponencial para errores transitorios.
- ``SlippageEstimator``: estimación y comparación con el fill real.
"""
