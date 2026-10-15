# WP-EDGE-04R — Informe ejecutivo (castellano)

**Instante de lectura:** 2026-10-15T18:31:46Z · **Ventana:** 2026-10-13T11:23:38Z → 2026-10-15T18:31:46Z (55,136 h)
**Veredicto del paquete:** la ingeniería del observador forward resiste; su continuidad está limitada por la sesión, y ese límite queda medido, cuantificado y entregado con los comandos exactos para que lo levante un operador.

## 1. Qué se ha implementado

Tres módulos y dos herramientas, todos nuevos y todos verificables sin este host:

| fichero | qué hace |
| --- | --- |
| `src/trading_bot/research/edge04r/os_evidence.py` | lee lo que el propio host registró: arranques, apagados, inicios y cierres de sesión, transiciones de energía, la tarea registrada y el parque de volúmenes. No lee ninguna credencial (la sonda de autologon lee el interruptor y el nombre de cuenta, nunca una contraseña), no inventa causas y no cambia nada del host |
| `src/trading_bot/research/edge04r/continuity.py` | la auditoría atribuida: fase medida de los lanzamientos reales, emparejamiento uno-a-uno entre instantes y ticks, atribución por instante, reconciliación por día, lectura de almacenamiento e invariantes |
| `src/trading_bot/research/edge04r/session.py` | las sondas de independencia de sesión y la definición de tarea que añade un disparador de inicio de sesión y una acción testigo |
| `scripts/edge04r_continuity.py` | recoge, audita y renderiza; con `--offline --stored-snapshot --until` reproduce la lectura solo desde la evidencia versionada |
| `scripts/edge04r_verify.py` | verificador independiente, sin código compartido con la auditoría, y cada una de sus comprobaciones se paga con un sabotaje |

## 2. Qué se ha ejecutado realmente

* Los **cinco commits locales se publicaron**: fast-forward sobre la propia rama del carril, de `26eeea4` a `5980e37`. Sin `force`, sin tocar ninguna otra rama.
* La auditoría se ejecutó **contra la lane viva** y se reprodujo después **desde la instantánea versionada**, con el mismo resultado.
* Las **sondas de sesión se ejercitaron**: se registró una tarea desechable con ambos disparadores, se leyó de vuelta del Programador de tareas, se ejecutó a demanda y se borró. La tarea viva no se tocó.
* Los **tests** se escribieron y se ejecutaron (26/26 en el módulo nuevo), más la suite amplia y la regresión global.

## 3. Disparadores perdidos, causa por causa

```
221 instantes esperados
 195 los contestó un tick        (152 consumieron su slot; 43 dispararon y fueron rechazados)
  26 no los contestó ningún proceso
      24  NO_SESSION      una sola ventana de 22 876,438 s (6,355 h) con el host encendido y nadie con la sesión iniciada
       1  HOST_DOWN       dos reinicios, 458,525 s
       1  SILENT          host encendido, sesión presente, sin ningún registro
       0  SLEEP           el host no registró ni un solo sueño o suspensión
```

**Dos hipótesis locales quedan refutadas con evidencia, no con razonamiento:**

1. **«La máquina se duerme».** El host no registra sueño ni suspensión en la ventana: 0 pares 42/107 de Kernel-Power y el registro de Power-Troubleshooter vacío. Lo que sí registra es un cierre de sesión, dos reinicios y un inicio de sesión seis horas después. `AutoAdminLogon=0`, así que un reinicio deja la máquina en la pantalla de inicio hasta que alguien entra.
2. **«El tick se alarga y se come el siguiente».** Mediana 34,64 s, máximo 349,035 s y **cero** ticks por encima de los 900 s de intervalo. No es la causa.

**Y una separación que importa:** 43 de las 69 pérdidas **no son de planificación**. El guardián de disco rechazó *antes* de cualquier petición de mercado: costó una llamada y un slot, nunca una observación falsa. El espacio libre bajó hasta **0,8302 GiB**, con **10,764 h** por debajo del suelo crítico de 2 GiB y **6,49 h** por debajo del aviso de 5 GiB.

## 4. Disponibilidad y su techo

| | |
| --- | --- |
| Fracción planificable (host encendido **y** sesión presente) | **0,8824** |
| Host encendido sin sesión | 6,355 h |
| Host apagado | 0,127 h |
| Latencia de recuperación tras el único inicio de sesión | **321,41 s** |
| Silencios por encima del umbral (2× intervalo + 300 s) | 1 (23 418,872 s, 25 disparadores) |

Esa fracción planificable **es el techo de observación de esta lane**, no una molestia: es la parte de la ventana en la que la tarea podía arrancar.

## 5. Almacenamiento: ¿hay algún volumen mejor?

El árbol de la lane ocupa **12 368 125 B de los 268 435 456 B que declara como presupuesto**: no es la lane la que llena el volumen. En este host sólo hay un disco físico (SSD NVMe de 238,47 GiB), una partición de datos al 97 % y un montaje FAT32 de Google Drive cuya capacidad reportada es la del propio host. **Veredicto: `NO_VOLUME_WITH_CAPACITY`.** No se movió nada y no se tocó el dato de ningún otro workstream.

## 6. Independencia de sesión: qué permite este host de verdad

Cada mecanismo se **intentó**; el veredicto es lo que contestó el host, no lo que dice la documentación.

| mecanismo | veredicto | qué necesita |
| --- | --- | --- |
| Disparador de inicio de sesión | **VIABLE (ejercitado)** | nada nuevo |
| Acción testigo | **VIABLE (ejercitada)** | nada nuevo |
| Tarea S4U (elimina la dependencia) | `NEEDS_ELEVATION` | el derecho de inicio de sesión por lotes |
| Servicio de Windows | `NEEDS_ELEVATION` | permisos de administrador |
| Inicio de sesión automático | `NEEDS_CREDENTIALS` | guardar la contraseña de la cuenta en la máquina |
| Registro operativo del Programador | `NEEDS_ELEVATION` | permisos de administrador (la activación respondió *Acceso denegado*) |
| `WakeToRun` | `NOT_APPLICABLE` | no hubo sueño que despertar |

**No se aplicó nada a la tarea viva.** Re-registrar la tarea de una lane en marcha cambia la fase que mide esta auditoría y es una decisión de despliegue de un operador, no un efecto colateral de una auditoría: las sondas usaron un nombre desechable y se borraron, dejando exactamente una tarea programada en la máquina.

Lo que compraría cada mecanismo, con precio tomado de la auditoría: el **disparador de inicio de sesión** acota la recuperación a un minuto en lugar de hasta un cuarto de hora (la recuperación medida fue de 321,41 s, así que recupera minutos); la **acción testigo** convierte el único disparador inatribuible en atribuible, sin administrador; y **S4U** es el único que haría planificables los 24 disparadores perdidos por ausencia de sesión, justo el que este paquete no puede registrar.

## 7. El certificado económico obsoleto

`data/recovery/wp7/COST_BARRIER_CERTIFICATION.json` fija `data/recovery/ACTIVE_ECONOMIC_AUDIT.json` en `8a101e88…`; el contenido de HEAD da `d1d49f09…`, y por eso falla el test adversarial.

| | |
| --- | --- |
| Commit del certificado | `57772ef` (2026-10-11) |
| Digest del artefacto **en ese commit** | `8a101e88…` — coincide con el registro |
| Commit que lo volvió a renderizar | `7522255` (2026-10-12, `[WP-EDGE-01]`) |
| Valores hoja que cambiaron, de 2 985 | **6** |
| De ellos, económicos | **0** |

El re-render cambió la rama, el commit al que se refiere y **una observación viva** (`data/st6/ST6_HEALTH_STATUS.json`, 6 143 → 6 290 bytes, con los mismos campos atestiguados). Los agregados económicos no se movieron.

**Veredicto: `STALE_BY_PROVENANCE`, declarado y no silenciado.** El registro era correcto cuando se escribió y su entrada fue re-renderizada un día después por el carril que la posee. Editar el digest registrado para que el test pase sería sustituir evidencia por una afirmación que ya no se puede trazar a un commit: exactamente lo que se pidió no hacer.

## 8. Commits y ficheros

* **Publicados:** `351ecba`, `046c7df`, `f1a6b31`, `570ccd6`, `5980e37` en `refs/heads/agent/edge-recovery/WP-EDGE-00-baseline`.
* **De este paquete:** los commits aislados de WP-EDGE-04R (código, tests, evidencia e informes), listados en `GIT_STATE.json` con el árbol limpio de la lane y sin ficheros de otros carriles.
* Ningún artefacto de este paquete adelanta una admisión: `hypothetical: true`, `order_sent: false` y promoción `NONE` en todos.

## 9. Defectos y bloqueos

| | |
| --- | --- |
| Defecto encontrado y corregido en esta auditoría | el emparejamiento de arranques y apagados informaba como caída un arranque anterior a su apagado; hay regresión en los tests |
| Defecto de WP-EDGE-04 corregido aquí | la atribución del silencio a un sueño de la máquina que el host no registra |
| Bloqueo | S4U, servicio de Windows y registro operativo del Programador: requieren permisos que este paquete no puede obtener legítimamente |
| Bloqueo | inicio de sesión automático: requeriría guardar una credencial |
| No ejercitado | un ciclo real de cierre e inicio de sesión bajo el disparador propuesto (provocarlo terminaría la sesión en la que corre este trabajo), una tarea S4U real sin sesión y una caída real del proveedor |
| Heredado y con dueño | el fallo del certificado económico de §7 |

## 10. Siguiente paso hacia PAPER

1. **Levantar el bloqueo de sesión**, que es el único que cambia la aritmética: un administrador registra la tarea con `LogonType=S4U` (o se habilita el inicio de sesión automático, que exige guardar la contraseña y por eso queda fuera de este paquete). Sin eso, cualquier cuenta de días forward seguirá siendo cero por construcción.
2. **Habilitar el registro operativo del Programador de tareas** (`wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true`), para que el próximo disparador sin proceso sea atribuible en lugar de convertirse en `SILENT_UNATTRIBUTABLE`.
3. **Decidir sobre el volumen**: 10,764 h de la ventana por debajo del suelo crítico no se arreglan moviendo esta lane (12,4 MiB), sino liberando espacio donde vive.
4. **Adoptar el disparador de inicio de sesión y la acción testigo** si se acepta el despliegue: acotan la recuperación y hacen atribuible lo que hoy no lo es.

**Ninguna de estas cuatro cosas es una estrategia**, y ninguna autoriza operar: este paquete no habilita PAPER ni LIVE bajo ninguna circunstancia.
