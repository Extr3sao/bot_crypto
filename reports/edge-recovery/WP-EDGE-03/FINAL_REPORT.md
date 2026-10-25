# WP-EDGE-03 — Cierre: observacion forward, shadow y paridad de riesgo

## 1. Veredicto

| | |
|---|---|
| lane | `WP-EDGE-03` (forward evidence + runtime parity) |
| estado | **OBSERVACION OPERATIVA, sin promocion** |
| veredicto de observacion | `OBSERVATION_AVAILABLE` — 226 dias de observacion independiente (suelo declarado 60) |
| promocion | **`NONE`** (no es parametro: la lane no lee ningun criterio de admision) |
| paridad de riesgo | `PARITY_PASS` — 544 casos clasificados, **0** `PARITY_DEFECT` |
| verificacion independiente | `VERIFY_PASS` **19/19** · `SELF_TEST_PASS` **20/20** sabotajes detectados |
| capital real | **ninguno**; 0 ordenes, 0 credenciales, 0 endpoints privados |
| `RENTABLE` / `CERTIFIED` / `PAPER` / `PRODUCTION_READY` | **false** — no se declara ninguna de las cuatro |
| `FALSE_SUCCESS` | **0** |

## 2. Que funciona realmente (demostrado, no razonado)

1. **Ingesta incremental real.** Cuatro corridas contra el venue publico hoy: `05:00:53Z` anadio 84 barras
   (6×1h + 22×15m por la ventana abierta desde la congelacion), `05:10:43Z` **no** anadio ninguna y lo
   registro como `no_new_data` en las 6 series, `05:16:27Z` anadio 3, `05:30:48Z` anadio 3. El prefijo
   congelado de WP-EDGE-01/02 **no se escribe jamas**, y se re-lee y re-verifica en cada corrida.
2. **Rendicion de cuentas de datos.** Cero gaps, cero duplicados, cero barras fuera de orden, cero barras
   abiertas guardadas, cero barras en o antes de la congelacion (17.940 barras comprobadas una a una por un
   verificador que no importa el paquete). Una barra corrupta se cuenta y **no** se guarda; un gap se cuenta y
   **nunca** se rellena.
3. **Reinicio sin duplicados.** La segunda pasada en el **mismo instante** devolvio `no_new_data`, anadio 0
   barras y dejo los 6 digests identicos. Repetible: se ejecuto en cuatro corridas.
4. **Shadow hipotetico y honesto.** Los rulesets congelados (digest re-derivado y **pinado** contra el
   publicado) imprimen senales sobre las barras nuevas; cada relleno lleva `hypothetical: true` y
   `order_sent: false`. La lectura de la ventana es **negativa** (primario 4h: −44,31 USDT BASE, 31 rellenos,
   DD 2,78 %, exposicion 28,86 %) y se publica como es.
5. **Paridad con el motor autoritativo.** El mismo estado y la misma intencion entran al presupuesto de
   investigacion y al Risk Engine real: 544 casos, 0 defectos, 0 umbrales relajados. Los 72 casos
   `RULE_NOT_MODELLED_BY_RESEARCH` y las 194 diferencias de orden de reglas se publican como tales.
6. **Observabilidad reproducible.** Informe diario + acumulado generados **del artefacto**: `--reports-only`
   los re-renderiza sin red desde un `OBSERVATION.json` guardado, y eso se ejecuto.
7. **Autonomia.** El sistema arranca, ingiere, decide, clasifica y publica sin intervencion humana; "no hay
   datos nuevos" es un resultado registrado, no un fallo (exit 0).

## 3. Que se corrigio en este cierre

| defecto | por que importaba | correccion |
|---|---|---|
| la lane **afirmaba** que el ruleset se re-derivaba y comparaba, y no lo hacia | una edicion posterior de `FROZEN_PARAMS` habria medido un ruleset distinto **sin que nada se quejara** | `assert_frozen_params()`: re-hash desde cero, comparacion con la constante y con `OOS_TREND.json#params_hash`, aborto si no cuadra; publicado en `OBSERVATION.json#frozen_params`; comprobado por el verificador parseando el fuente con `ast`; 4 pruebas + 1 sabotaje |
| la latencia publicada era el **backfill** de marzo, no la de la corrida | el informe diario decia `19.521.591 s` como si fuera el estado de hoy | dos lecturas separadas (ventana / esta corrida: **48,8 s** de mediana hoy), dos tablas, linea diaria propia, verificador que recomputa ambas y exige `null` cuando la corrida no trajo barras; 2 pruebas + 1 sabotaje |
| 23 hallazgos de ruff y 15 errores de mypy en los ficheros de la propia lane | el paquete no podia declarar sus gates | 38 puntos resueltos sin desactivar reglas ni anadir `# type: ignore`; los 9 ficheros quedan limpios |

## 4. Que NO funciona / no se declara

- **Nada se promueve.** La ventana forward es corta (2 dias nuevos desde la congelacion) y las lecturas son
  negativas en los escenarios BASE/2X_FEES/ADVERSE. La lane no evalua criterios de admision, por diseno.
- **`ruff format --check`** no esta verde en los ficheros de la lane (8 de 9 se reformatearian): deuda
  preexistente del repo, no se reformatea para no enterrar el diff semantico.
- **`ruff check .`** da 150 hallazgos con la ruff local (0.15.20, pin `>=0.4.0`), **ninguno** en los ficheros de
  esta lane: deuda de otras lanes con la toolchain local, medida y publicada.
- **La suite completa no esta verde: 15 failed / 3663 passed en 487 s**, y **ninguno** de esos fallos es de esta
  lane (0 en `edge03`). Causas: el preflight de disco de WP-9 rechaza porque el host esta al 97 % (7,4 GB
  libres), vistas de estado de otras lanes desactualizadas por commits ajenos, la reproduccion del cost barrier,
  y 8 tests del scanner. Se publican como ajenos y preexistentes; no se tocan porque pertenecen a otras lanes.
- **Publicacion a GitHub: `BLOCKED_GITHUB_AUTH`.** Sin token, sin credenciales y con helper interactivo; las
  tres sondas de escritura fallan (128/128/124) y la lectura anonima confirma que **no existe** ninguna ref de
  la lane en el remoto. Los commits quedan locales.
- Sin capital real, sin libro de ordenes historico y solo lado largo: nada de este informe toca dinero.

## 5. Siguiente paso hacia un PAPER operativo

El pipeline que un PAPER necesita —ingerir, decidir, clasificar contra el motor de riesgo autoritativo,
publicar y ser verificado— **ya existe y se ejecuta**. Lo que falta para PAPER no es codigo de esta lane:

1. **Un desbloqueo humano de credenciales** para publicar (el bloqueo es de autenticacion, no tecnico).
2. **Mas dias de observacion con el mismo criterio congelado.** La lane ya sabe contar dias independientes
   (226 incluyendo el prefijo congelado; 2 nuevos), asi que basta con dejarla correr en un horario — el
   proximo informe diario acumulara `2026-10-13`, `2026-10-14`, … y la cobertura del dia (90 % de las barras
   del calendario) decidira si el dia cuenta.
3. **Una decision explicita de admision**, que hoy no existe por diseno: la lane puede alimentar los criterios
   vigentes, pero **no** los interpreta ni los relaja.
