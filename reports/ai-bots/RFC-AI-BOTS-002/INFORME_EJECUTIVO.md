# Informe ejecutivo — RFC-TAP-AI-BOTS-002 v3.1

## En una frase

Teníamos un error de atribución en el centro del informe anterior: el bundle público de
`www.nof1.ai` no sale del repositorio `195440/nof1.ai`. Lo hemos demostrado, hemos conservado
toda la evidencia y hemos ido al repositorio exacto a hacer el trabajo de verdad.

## Qué estaba mal

El informe v3 decía "analizamos nof1.ai con REA". En realidad analizamos **un sitio web** y le
pusimos la etiqueta de un repositorio. No es lo mismo, y la diferencia importa: cualquier
conclusión sobre el proyecto era una suposición.

## Qué hemos hecho

1. **Medido el commit** `5d27641dfa47…` en un sandbox aislado (108 ficheros, 2.3 MB).
2. **Refutado la asociación con datos, no con opiniones**: el bundle público es Next.js con
   Turbopack; el repositorio no tiene Next.js en ningún fichero y su dashboard son dos scripts
   estáticos publicados en otro dominio.
3. **Preservado la evidencia antigua** con sus hashes y `evidence_id` intactos, en un dossier
   que ahora se llama por lo que es: un deployment sin origen demostrado.
4. **Ejecutado REA sobre el repositorio exacto**: 3 ficheros, 4.812 nodos AST, exit 0.
5. **Ejecutado REA sobre Semantic Signal y FenixAI** construyendo sus artefactos desde el
   commit exacto: 14 módulos JS en uno, bundle de 868 kB en el otro, más dos capturas de
   pantalla verificables por hash.
6. **Auditado por fuente** lo que REA no puede ejecutar: los backends Python/TypeScript.
7. **Ejecutado el render de FenixAI** con velas sintéticas y sin claves: produjo un PNG real
   y reveló dos fallos medidos — relleno silencioso con `ok=True` y `max_age=0` que aplica el
   TTL por defecto. Etiquetado `INSTRUMENTED_EXECUTION_NOT_REA`, no como evidencia REA.

## Los tres hallazgos que cambian decisiones

1. **nof1 no es visual.** No hay gráfico en su código. El RFC lo tenía clasificado en la
   categoría equivocada.
2. **nof1 deja que el modelo decida el apalancamiento** (hasta 15×) y su protección de
   drawdown está comentada. Dos anti-patrones que no se copian.
3. **FenixAI manda la imagen al modelo sin hash, sin símbolo y sin reloj.** Es el mismo fallo
   que acabamos de cerrar en nuestro runtime; su código sirve como caso de estudio de por qué
   el `INTEGRITY_FAILURE` que añadimos es necesario.

## Lo que no se ha hecho, y no se va a maquillar

- **Cero llamadas reales a un modelo.** Sin clave y sin autorización de gasto.
- **Cero dinero, cero órdenes, cero límites de riesgo tocados.**
- **Cero patrones externos certificados.** Ningún `ADOPT_VERIFIED` de terceros.
- El backend de ninguno de los tres proyectos se ejecutó: REA no ejecuta Python ni servicios,
  y arrancarlos exige claves que no tenemos.

## Coste

Tres checkouts y un `node_modules` de 205 MB en un sandbox temporal, con 2.3 GB libres de
disco al empezar. Nada dentro del repositorio salvo informes, dossiers y dos PNG de evidencia.
