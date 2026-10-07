# Historial de decisiones

## Encabezado institucional

El diseño inicial mostraba un logotipo demasiado grande y centrado. Después se probó un símbolo pequeño a la izquierda con el nombre institucional a un lado. La versión aprobada usa el logotipo institucional horizontal completo, centrado y sin repetir el nombre como texto adicional.

La franja superior inicialmente combinaba dorado y vino. Se cambió a una sola celda completamente vino con el color `691A32`.

## Descripciones de puestos

El Excel contiene saltos de línea dentro de algunos incisos. Al insertarlos en un único párrafo justificado, Word los interpretaba como saltos manuales y estiraba la última línea, creando espacios excesivos entre palabras.

La solución aprobada es `split_description_paragraphs`:

- detecta viñetas e incisos romanos o numéricos;
- une líneas que continúan el mismo inciso;
- cierra el párrafo cuando encuentra punto, punto y coma, una línea vacía o un inciso nuevo;
- crea párrafos Word independientes;
- aplica 4 puntos de separación entre párrafos.

También separa un inciso romano aunque aparezca dentro de una misma línea del Excel. Por ejemplo, el texto `...Organismo; IX. Promover...` se convierte en dos párrafos reales antes de insertarse en Word.

## Flujo Docker

- Cambios únicamente en Excel: ejecutar el contenedor sin reconstruir.
- Cambios en Python, logo, dependencias o Dockerfile: reconstruir sin caché y ejecutar.
- Mantener Word cerrado durante la generación para evitar que bloquee el archivo de salida.

## Datos del puesto y requisitos

Cada ficha presenta dos bloques independientes debajo del título del catálogo:

- `DATOS DEL PUESTO`: nivel y cargo en estructura;
- `REQUISITOS`: escolaridad requerida y experiencia en años.

Ambos encabezados usan la franja institucional vino `691A32` y los valores se toman del registro correspondiente en el Excel.

## Continuación en páginas adicionales

Cada puesto se genera en una sección independiente de Word. El logotipo, la franja institucional, el título del catálogo y `DATOS DEL PUESTO` forman el encabezado de esa sección. Si conocimientos o descripción continúan en una segunda página, Word repite automáticamente ese encabezado con el nivel y cargo del puesto correspondiente.

El bloque `REQUISITOS` permanece en el cuerpo y se muestra una sola vez al inicio de cada ficha.

## Nombres y orden de campos

`DATOS DEL PUESTO` muestra primero `PUESTO`, después `NIVEL` y, en una segunda fila, `DENOMINACIÓN GENÉRICA DEL PUESTO`. Este último valor proviene de una columna independiente con el mismo nombre en el Excel; no utiliza la columna académica `PERFIL`.

La sección antes llamada `CONOCIMIENTOS` se presenta como `PERFIL DEL PUESTO`. La sección antes llamada `DESCRIPCIÓN DE PUESTOS (GENÉRICA)` se presenta como `FUNCIONES`.

## Archivos de referencia

Las muestras aprobadas se conservan en `muestras/`. El logotipo anterior se conserva en `assets/logo_anterior.png` únicamente como respaldo.
