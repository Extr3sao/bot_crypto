Feature: Multi-exchange adapter
  El sistema debe enrutar solicitudes de market data y ejecución de
  órdenes a través de un único punto de conexión que abstrae los
  distintos exchanges habilitados en la sesión. Esto permite operar
  Binance y Bitunix en paralelo (spot + futures) sin código que ramifique
  por exchange en el scanner o las estrategias.

  Background:
    Given el modo TRADING_MODE es "paper"
    And RUNTIME_EXCHANGE_ID está configurado con un id válido
    And SUPPORTED_EXCHANGES contiene al menos ["binance", "bitunix_spot", "bitunix_futures"]

  Scenario: Resolver un id de exchange válido devuelve su adaptador
    Given el id "binance" está habilitado
    When solicito el adaptador para "binance" durante la sesión paper
    Then debe devolver una instancia concreta sin exception
    And la instancia debe responder a la consulta de OHLCV reciente

  Scenario: Solicitar un id no registrado falla con un mensaje útil
    Given el id "fanta-exchange" no está en SUPPORTED_EXCHANGES
    When solicito el adaptador para "fanta-exchange"
    Then debe lanzar un error mencionando el id no soportado
    And el mensaje debe listar los ids válidos disponibles

  Scenario: Selección por session-id sin fallback silencioso a default
    Given RUNTIME_EXCHANGE_ID = "bitunix_spot"
    When el bot arranca en modo paper sin credenciales Bitunix cargadas
    Then debe rechazar el arranque con un error claro
    And no debe caer silenciosamente en Binance como sustituto

  Scenario: Tres exchanges habilitados conviven bajo el mismo hub
    Given SUPPORTED_EXCHANGES contiene "binance", "bitunix_spot" y "bitunix_futures"
    When solicito cada uno por turno durante la misma sesión
    Then las tres instancias deben responder de forma independiente
    And un fallo en uno no afecta a los otros dos

  Scenario: OHLCV del exchange devuelve filas con ts entero y precios float
    Given una respuesta válida de Binance con la última vela OHLCV
    When el hub entrega la vela al consumidor downstream
    Then la fila expuesta debe contener ts_millis como entero
    And los cinco valores siguientes como float
    And no debe aplicar ninguna conversión previa al consumidor

  Scenario: Subclases concretas sólo se invocan desde market_data
    Given una solicitud de OHLCV desde el scanner
    When el hub enruta la solicitud al exchange habilitado
    Then el scanner sólo debe ver el contrato abstracto
    And nunca debe poder importar directamente Binance o Bitunix

  Scenario: Rate-limit independiente por exchange
    Given Binance y Bitunix operan con rate-limits divergentes por diseño
    When lanzo 100 llamadas simultáneas entre los dos
    Then cada exchange debe aplicar su propio throttling
    And ninguna llamada debe colisionar con el throttling del otro

  Scenario: Cada exchange emite logs estructurados con su id reconocido
    Given una iteración sobre tres exchanges habilitados
    When el hub despacha cada solicitud
    Then cada evento de log debe llevar el campo exchange_id presente
    And los eventos deben ser filtrables por exchange_id sin ambigüedad

  Scenario: Reuso de guardas de tipo en runtime
    Given una respuesta malformada de un exchange (clave no str en payload)
    When el hub la procesa en la frontera del exchange
    Then debe lanzar un error mencionando "protocol violation"
    And el consumidor downstream no debe recibir los datos crudos

  Scenario: Resolución no eagerly-construye adapters no consultados
    Given SUPPORTED_EXCHANGES = ["binance", "bitunix_spot", "bitunix_futures"]
    When solicito sólo el adaptador "binance"
    Then las conexiones a "bitunix_spot" y a "bitunix_futures" no deben existir
    And la memoria ocupada por conexiones no consultadas debe ser cero

  Scenario: Lista vacía cuando SUPPORTED_EXCHANGES está vacío por configuración
    Given SUPPORTED_EXCHANGES = [] por configuración explícita
    When el bot arranca en modo paper sin exchanges habilitados
    Then debe registrar un warning de configuración ausente
    And no debe emitir ninguna llamada externa

  Scenario: Lista vacía cuando un id mal escrito está habilitado
    Given el id "bitunix-spot" no existe como adaptador soportado
    When el bot intenta resolver "bitunix-spot"
    Then debe emitir error claro al boot
    And los ids válidos deben estar listados en el mensaje

  Scenario: Arranque sin id seleccionado en runtime falla loud
    Given RUNTIME_EXCHANGE_ID está vacío o ausente en runtime
    When el bot arranca con esta configuración
    Then debe rechazar el arranque con validation error
    And la guía de fix debe apuntar a RUNTIME_EXCHANGE_ID o default

  Scenario: Un id en config que ccxt no soporta se rechaza al construir el hub
    Given el id "no-such-ccxt-id" está habilitado por configuración
    When el hub intenta construir el adaptador
    Then debe emitir ConfigurationError al boot
    And la lista de supported ids del hub no debe incluirlo

  Scenario: Dos exchanges con la misma versión de ccxt no entran en conflicto
    Given Binance y Bitunix retornan listas de OHLCV distintas en cada llamada
    When el hub normaliza ambas respuestas vía guardas de tipo
    Then cada consumidor recibe su payload en el formato unificado
    And no debe asumir consistencia entre exchanges en cada timestamp

  Scenario: Modo paper y modo live respetan sandbox por exchange
    Given el id "binance" tiene sandbox=true y "bitunix_spot" tiene sandbox=false
    When el bot arranca primero en modo paper y luego en modo live
    Then en paper el adaptador de Binance debe usar sandbox url
    And en live el adaptador de Bitunix no debe usar sandbox url
    And el modo nunca debe invertir esos flags por intercambio accidental
