# WP-EDGE-05 — Informe ejecutivo (castellano)

**Qué es.** El cierre del paquete de trabajo que la RFC-EDGE-005 pedía: un vigilante independiente de
la lane de observación forward, una reconciliación posterior a una caída, una auditoría real de la
continuidad de Windows, un presupuesto de recursos medido y una verificación independiente con
sabotajes. Nada de esto opera, promociona ni toca límites de riesgo: **observa y comprueba**.

**Qué NO es.** No es un certificado. No autoriza `PAPER` ni `LIVE`. No declara rentabilidad. Sesenta
días forward siguen siendo **0 de 60**, y ninguna afirmación de este informe puede cambiarlo.

---

## 1. Resumen en seis líneas

| | |
| --- | --- |
| Vigilante independiente | 13 comprobaciones, sin lease, sin pipeline, sin peticiones de mercado, con **tarea programada propia** (`TradingAgentic-EDGE05-Watchdog`, cada 15 min) |
| Parada real detectada | **sí**: la lane se deshabilitó a propósito, el vigilante la detectó en **6 segundos** y cerró el episodio cuando la propia lane se recuperó |
| Reconciliación | **42 ticks · 36 consumidores · 35 sellos · 456 filas de ledger · 38 intentos**, cadena intacta en las seis series, **0 defectos abiertos** |
| Las seis barras de la caída anterior | **trazables**: presentes en la tienda, cubiertas exactamente una vez, por el intento que nunca se registró |
| Presupuesto | 1,49 MB/día medidos (umbral aviso 16 MiB/día, parada 64 MiB/día); 5,65 GiB libres, con el suelo de aviso de 5 GiB acercándose por actividad **ajena** a esta lane |
| Verificación independiente | `VERIFY_PASS` **13/13** y `SELF_TEST_PASS` **15/15** sabotajes detectados, código de salida real **0** |

---

## 2. La línea de tiempo que se puede reconstruir

Todo lo que sigue está en artefactos, no en afirmaciones: lecturas del vigilante
(`data/forward/edge05/watchdog.jsonl`), alertas (`watch_alerts.jsonl`), registro de la lane
(`runs.jsonl`), ledger de ingesta y las dos tareas del Programador exportadas tal cual por el sistema.

| instante (UTC) | quién | qué hizo |
| --- | --- | --- |
| `18:40:54Z` | lane | tick `FWD-EDGE04-20261013T183000Z`, 3 barras nuevas |
| `18:47:10Z` | vigilante | primera lectura de este paquete: `WATCH_OK` |
| `18:48:10Z` | operador (autorizado, reversible) | `Disable-ScheduledTask TradingAgentic-EDGE04-Forward` |
| `18:48:16Z` | **vigilante** | `WATCH_ALARM` / `SCHEDULER_FAILURE` — **6 s después**, hallazgo `scheduler_task: the task is disabled` |
| `18:55:53Z` | sistema | el disparo que se perdió (la tarea estaba deshabilitada) |
| `18:55:59Z` | vigilante | `WATCH_ALARM` + `scheduler_cadence: 1 missed run(s)` |
| `19:06:06Z` | operador | tarea de la lane **reactivada** |
| `19:11:27Z` | **lane** | se recupera sola: consume el slot `19:00Z` con **9 barras** |
| `19:12:07Z` | **vigilante** | `WATCH_OK` + alerta `WATCHDOG_RECOVERED` nombrando `FWD-EDGE04-20261013T190000Z` |
| `20:02:31Z` | sistema | **ejecución desatendida del propio vigilante**, resultado `0`, lectura `20:02:39Z` |
| `20:11:33Z` | lane | tick `FWD-EDGE04-20261013T200000Z`: 6 barras nuevas (la lane sigue viva tras el episodio) |
| `20:13:12Z` | reconciliación | 42 ticks · 456 filas de ledger · **0 defectos abiertos** |
| `20:13:18Z` | verificación | `VERIFY_PASS 13/13` y `SELF_TEST_PASS 15/15`, código de salida `0` |

Episodio de problema: `18:48:16Z` → `19:12:07Z`, **1 episodio, 1 recuperación**, cerrado por un tick que
existe en el registro de la lane. Ninguna barra perdida: las nueve son exactamente las que cerraron
mientras el planificador estaba apagado — `(2 de 15m + 1 de 1h) × 3 activos` — y la segunda pasada de
ingesta en el mismo instante añadió **0**.

---

## 3. A. Vigilante independiente

**Qué vigila.** Trece comprobaciones: estado de la tarea programada, cadencia del planificador,
resultado del último disparo, cadencia de la lane, lease, proceso del tick, frescura de la tienda,
expectativa de mercado, integridad de la evidencia, prueba de reinicio (que la segunda pasada no
escriba nada), disco, crecimiento y la propia cadencia del vigilante. El veredicto es **el peor** de
las trece: nunca una media ni una votación.

**Qué lo hace independiente.** No toma lease, no ejecuta el pipeline y **no pide datos de mercado**.
Todo lo que afirma lo deriva de los ficheros de la lane y de lo que dice el propio sistema operativo.
Y vive en su **propia** tarea programada, porque un vigilante que comparte planificador con lo que
vigila no puede informar de la muerte de ese planificador. Los 9 registros de lectura no contienen ni
una petición de mercado ni una escritura en la lane.

**La distinción que sostiene los 60 días.** Un mercado sin barra nueva **no** es un fallo operativo, y
un lazo callado **no** es un mercado muerto. La comprobación `market_expectation` compara las barras
que el calendario dice que han cerrado con la cola de la tienda y lo escribe con palabras: con la lane
deshabilitada decía *«3 bar(s) closed since the last tick and are pending the next trigger: normal
latency inside the declared schedule, not a failure»*. Solo una tarea deshabilitada o fallando, un
lease que sobrevive a su dueño, un tick muerto a mitad de escritura, una tienda estancada, evidencia
ilegible o un disco por debajo del suelo merecen alarma.

**Alertas por transición**, no por lectura: un fallo se anuncia una vez y su recuperación una vez,
nombrando el tick que la produjo. 25 filas, 16 tipos.

**Defecto encontrado y corregido aquí**: el sabotaje de «mercado tranquilo» del auto-test solo
producía contradicción cuando la tienda iba por detrás del calendario, es decir, casi nunca justo
después de un tick. El mismo comando podía informar `15/15` o `14/15` según la hora. Ahora el sabotaje
adelanta tres horas el instante de la lectura **manteniendo su afirmación**, de modo que el calendario
siempre debe barras que la tienda no tiene, y la comprobación se reforzó además para verificar la
aritmética interna de la lectura (un resumen que llama «tranquilo» al mercado mientras sus propias
series dicen que hay barras pendientes). El auto-test es determinista, no afortunado.

---

## 4. B. Reconciliación tras la caída

`scripts/edge05_reconcile.py` recalcula, **desde los ficheros crudos y nada más**, la cadena que va
desde la época de cada serie hasta su última barra: qué intento de ingesta escribió cada barra, qué
tick la reclamó, si un intervalo se escribió una o dos veces y si las decisiones registradas coinciden
con las barras que el tick dice haber leído.

| | |
| --- | --- |
| Estado | `HISTORICAL_ONLY` · veredicto `RECONCILIATION_INCOMPLETE` · `20:13:12Z` |
| Series | seis; cadenas que **se sostienen** en todas |
| Barras contabilizadas | 76 filas de ledger por serie · 609 `15m` y 5 444 `1h` por activo |
| Defectos | `CHAIN_BROKEN`, `CLAIMED_BUT_ABSENT`, `DECISION_DIVERGENCE`, `DOUBLE_CLAIM`, `RESTART_PROOF_BROKEN`, `SEAL_MISSING`, `SEAL_ORPHANED`, `UNATTRIBUTED_BAR` → **0**; **0 abiertos** de cualquier tipo |
| Nombrados, no abiertos | 2 `UNATTRIBUTED_ATTEMPT`, ambos episodios cerrados |
| Idempotencia | 38 instantes con dos pasadas de ingesta; la segunda añadió **0** barras y rompió **0** pruebas de reinicio |
| Decisiones | 3 636 capturas, 35 pares comparables, **1 solo digest**, **0 divergencias** |

**Las seis barras de la caída anterior siguen trazables.** El intento de `15:02:10Z` no tiene fila de
run: escribió **6 barras** (`1h` `14:00Z` ×3, `15m` `14:45Z` ×3) y su proceso murió antes de
registrarse. La reconciliación no las borra ni se las atribuye en silencio: **nombra el intento, cuenta
las barras y demuestra cobertura única** con el high-water mark del tick siguiente, que añadió 0. La
otra entrada sin run (`11:25:20Z`, 0 barras) es una ingesta que no encontró nada nuevo.

**Lección de orden**: la reconciliación es una *lectura de la tienda en un instante* y la tienda viva
se mueve. Tras el tick de recuperación falló por exactamente un tick (`ledger_rows` 68 vs 66), así que
el orden documentado es **reconciliar y verificar seguidos, y después publicar**.

---

## 5. C. Continuidad de Windows

Las dos tareas se leen del **export del propio sistema**, por ruta de elemento y no por búsqueda de
texto (el intervalo de repetición del reintento y el del disparador se llaman igual, y confundirlos
convierte un plan de 15 minutos en uno de 5).

| | | |
| --- | --- | --- |
| `logon_type` | `InteractiveToken` | la lane necesita **sesión de usuario iniciada** |
| `trigger` | `PT15M`, duración `P3650D` | cada 15 minutos |
| `MultipleInstancesPolicy` | `IgnoreNew` | un tick lento nunca se duplica |
| `StartWhenAvailable` | `true` | un disparo perdido por suspensión se lanza al despertar |
| `RestartOnFailure` | `3 × PT5M` | reintento del propio sistema |
| `ExecutionTimeLimit` | `PT1H` | un tick colgado se mata |
| `RunLevel` | `LeastPrivilege` | **sin elevación y sin credenciales guardadas** |

Observado de verdad en este paquete: **con sesión iniciada y sin ningún agente abierto**, la lane y el
vigilante se disparan solos (última ejecución desatendida del vigilante: `20:02:31Z`, resultado `0`).
**Bloqueo de pantalla**: se espera que siga funcionando, **NO EJERCIDO** porque bloquear la pantalla de
esta máquina interrumpiría a quien la está usando. **Cierre de sesión**: la lane **no** se ejecuta —
es la mayor salvedad sobre los 60 días y **requiere decisión del propietario**; eliminarla exige
guardar una contraseña, exactamente lo que las reglas de este proyecto prohíben a un agente
automatizado. **Reinicio y suspensión/reanudación**: declarados por el registro, **no ejercidos**.
Los dos comandos `schtasks /change /ru … /rp …` quedan registrados para que los ejecute una persona.

---

## 6. D. Presupuesto de recursos

| | |
| --- | --- |
| Árbol de la lane / presupuesto declarado | 3 288 974 / 268 435 456 bytes (**1,23 %**) |
| Árbol del vigilante | 193 564 bytes |
| Tienda | 5 621 615 bytes · 18 159 barras |
| Volumen | 5,653 GiB libres de 237,5 GiB (**97,62 % usado**) |
| Crecimiento medido | **1 493 484 bytes/día** en una ventana de 8,0 h — es una **medición**, no una previsión |
| Umbrales declarados | aviso 16 MiB/día, parada 64 MiB/día; el presupuesto de 256 MiB repartido en 60 días es 4,37 MiB/día |
| Suelos de disco | aviso 5 GiB → la lane sigue ingiriendo y la publicación pesada espera; crítico 2 GiB → el tick registra `DISK_BUDGET_EXCEEDED` y **no hace ninguna petición de mercado** |
| Nunca se borra | la tienda, `daily/<fecha>.json`, todo informe publicado, el registro de runs, el ledger de slots y el de ingesta |
| Se poda | los logs operativos acotados, en sus topes declarados, y las lecturas/alertas del propio vigilante |

Instantáneas redundantes: una instantánea idéntica a la anterior **se rechaza y el rechazo queda
registrado**; el vigilante copia sus propias lecturas, nunca la tienda. Los dos suelos se ejercitan en
tests, no en vivo: el volumen está al 97,62 % y eso no es culpa de esta lane, pero sí es su riesgo.

**Observación que conviene leer despacio:** entre las dos pasadas de cierre de este paquete el espacio
libre bajó de 6,012 GiB a 5,653 GiB —0,36 GiB en ocho minutos— mientras la lane escribía 16 KiB. Si ese
ritmo se mantiene una hora, se cruza el suelo de aviso de 5 GiB: la lane **seguiría ingiriendo**, la
publicación pesada esperaría y se emitiría `DISK_WARNING`. No se borra nada para hacer sitio, y ese es
exactamente el motivo de declarar los dos suelos antes de necesitarlos.

---

## 7. E. Observación económica: cohortes separadas y ninguna promoción

Las estrategias están congeladas (`params_hash d073a2d6…`) y **no se han tocado**. Los resultados se
publican por cohorte, sin agregarlas nunca como si fueran una sola muestra:

| cohorte | días | qué significa |
| --- | --- | --- |
| **HISTÓRICO / BACKFILLED** | 226 | barras almacenadas después del congelado pero **no** observadas al cerrarse: es historia, no observación |
| **FORWARD PROSPECTIVO** | **0** | días cuyas barras se guardaron al cerrarse, dentro del límite de latencia de su marco |
| Días con algún dato | 227 | incluye el 2026-10-13, clasificado `INCOMPLETE` (cobertura 0,5) y que **no cuenta** |

Criterios fijados **antes** de acumular: cobertura mínima 90 % de las 24 barras horarias por activo
principal, latencia máxima de 1 h y 15 min, y exclusión explícita del backfill. La cohorte prospectiva
está **vacía** y se declara vacía: no se rellena con datos backfilled.

Economía **hipotética** de la ventana histórica (brazo primario `edge_trend_01_4h:BASE`): neto
**−44,31 USDT**, bruto −9,09 USDT, comisiones 29,61 USDT, costes de precio 5,61 USDT, 31 operaciones,
drawdown máximo 2,78 %, 3 977 barras sin operar. Señales en la ventana 324, rechazos 951; **0 señales y
0 operaciones hoy**. Todo ello es `hypothetical: true`, `order_sent: false`, `promotion: NONE`, y no se
promociona nada: el resultado neto es negativo y así se publica.

---

## 8. F. Verificación independiente

* **Constructor ≠ verificador.** `scripts/edge05_verify.py` no importa ninguna parte de lo que verifica:
  relee los ficheros crudos y vuelve a derivar cada afirmación por su cuenta.
* **En vivo**: `VERIFY_PASS 13/13`, código de salida **0**. Las trece comprobaciones incluyen que el
  veredicto de cada lectura sea el peor de sus estados, que las alertas sean por transición, que el
  resultado del planificador se traduzca con el vocabulario de la propia lane, que la cadena
  ledger↔barras se recalcule desde los ficheros, que ningún artefacto promocione ni envíe órdenes
  (29 artefactos analizados) y que **el vigilante haya detectado de verdad una interrupción**.
* **Con sabotajes**: `SELF_TEST_PASS 15/15`, 0 omitidos. Cada sabotaje muta una **copia** de la
  evidencia y exige que la comprobación correspondiente falle. La comprobación «¿detectó de verdad una
  interrupción?» **falló antes** de que existiera la recuperación: es honesta y no se satisface con un
  historial vacío.
* **Tests**: 46 superados (`test_edge05_watchdog.py` + `test_edge05_reconcile.py`), 0 fallos.
* **Instantánea**: `evidence/SNAPSHOT.json` con tamaño y `sha256` de cada artefacto escrito, para que
  el conjunto se pueda comprobar en lugar de creerse. La verificación puede apuntarse a ese directorio
  con el mismo comando que usa contra el árbol vivo.

---

## 9. Matriz de aceptación (ejecución real, no afirmaciones)

| ACC | Qué se exigía | Resultado | Base |
| --- | --- | --- | --- |
| ACC-01 | Auditoría del runtime y baseline reproducible | **PASS** | `reports/edge-recovery/runtime_authority_map.md`; commit base `e07785b`, tareas exportadas, espacio libre y snapshot |
| ACC-02 | El planificador dispara de verdad, ≥2 slots sin intervención | **PASS** | ejecución desatendida de lane y vigilante; 41 ticks, 9 lecturas, resultado `0` |
| ACC-03 | El vigilante detecta una parada inducida, con latencia medida y sin falso PASS | **PASS** | 6 s (`18:48:10Z`→`18:48:16Z`), `WATCH_ALARM`/`SCHEDULER_FAILURE`, alerta `SCHEDULER_DISABLED`, episodio cerrado |
| ACC-04 | Caída tras persistencia parcial | **PASS** | 6 barras de `15:02:10Z` presentes, cobertura única, **0 duplicaciones** |
| ACC-05 | Caída durante decisión/sello | **PASS** | 34 sellos, 0 `SEAL_MISSING`, 0 `SEAL_ORPHANED`, 0 `DECISION_DIVERGENCE` |
| ACC-06 | Reintento del mismo slot | **PASS** | 4 `ALREADY_OBSERVED` y 2 `ALREADY_RUNNING`; 37 segundas pasadas que añaden 0 |
| ACC-07 | Reinicio y lease huérfano | **PASS** | sin lease huérfano en ninguna lectura; recuperación del lease en el ensayo de interrupción de WP-EDGE-04 y en tests |
| ACC-08 | Proveedor caído y datos stale | **NOT_TESTED** | clasificación implementada (`STORE_STALE`, `PROVIDER_UNAVAILABLE`) y ejercitada en tests, **no en vivo**: no hubo caída real de proveedor |
| ACC-09 | Presión de disco | **PASS (test)** | dos suelos y dos acciones ejercitados en tests; en vivo 6,01 GiB libres, por encima del aviso |
| ACC-10 | Elegibilidad forward | **PASS** | 226 días backfilled excluidos, 0 prospectivos, día `INCOMPLETE` no contado, criterios congelados con `params_hash` |
| ACC-11 | Comparación de riesgo | **PASS** | sin cambios en el Risk Engine ni en `config/risk.yaml`; 1 digest de decisiones, 0 divergencias |
| ACC-12 | Verificación independiente | **PASS** | 13/13 y 15/15 con código de salida real 0; constructor distinto del verificador |
| ACC-13 | Operación sin órdenes | **PASS** | `order_sent: false`, `hypothetical: true`, `promotion: NONE` en todos los artefactos |
| ACC-14 | Observación prolongada | **NOT_TESTED** | 24 minutos de parada real, no 60 días; el gate de 60 días sigue abierto |
| ACC-15 | Git y trazabilidad | **PASS / BLOCKED** | commits aislados; publicación `BLOCKED_GITHUB_AUTH` documentada |

---

## 10. Limitaciones que se declaran (no se esconden)

1. **El cierre de sesión del usuario detiene la lane.** `InteractiveToken` es la mayor salvedad sobre
   los 60 días; quitarla exige credenciales y **no se ha hecho**.
2. **Nada de fuera del host.** Si la máquina está apagada, nada dentro de ella informa de ello. El
   dominio de fallo está documentado y un observador externo sería otra tarea.
3. **Bloqueo de pantalla, reinicio y suspensión no ejercidos** (interrumpirían a la persona usuaria).
4. **Ningún umbral de disco se ha cruzado en vivo**; se han ejercitado en tests.
5. **Ventana desatendida de 24 minutos**, no de 60 días.
6. **Cohorte prospectiva vacía**: 0 de 60 días forward válidos.
7. **Publicación en GitHub bloqueada** por autenticación; los commits quedan locales.

Nada de esto se declara `PASS`, `CERTIFIED`, `READY_FOR_PAPER` ni `PRODUCTION_READY`.

---

## 11. Reproducción

```bash
python scripts/edge05_watchdog.py --status          # última lectura, sin cambiar nada
python scripts/edge05_watchdog.py --json            # lectura nueva; 0/10/11/12 = OK/DEGRADED/ALARM/BLOCKED
python scripts/edge05_watchdog.py --silence         # cuánto lleva callada cada parte, y por qué
python scripts/edge05_reconcile.py                  # reconciliación contra los ficheros crudos
python scripts/edge05_verify.py --self-test         # verificador independiente + 15 sabotajes
python scripts/edge05_closure.py                    # regenera todos los artefactos desde el estado vivo
```

Informe técnico completo en inglés: [`RUN_REPORT.md`](reports/edge-recovery/WP-EDGE-05/RUN_REPORT.md) y
su gemelo máquina [`RUN_REPORT.json`](reports/edge-recovery/WP-EDGE-05/RUN_REPORT.json).
