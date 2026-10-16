# Catálogo de Conocimientos de Referencia — fase 2D-1B

Esta fase es independiente del Editor de Cédulas. No está conectada al flujo de
generación o aceptación y no lee ni modifica `entrada/puestos_unificados.json`.
El catálogo incluido contiene exclusivamente ejemplos ficticios.

## Cierre técnico de la fase 2D-1B

La fase 2D-1B queda técnicamente implementada y disponible para revisión, sin
constituir un despliegue productivo institucional. Incluye el validador
independiente `knowledge_catalog.py`, la separación explícita entre conjuntos
`fixture` y `production`, controles de integridad referencial, aprobación humana
obligatoria, límites configurables de tamaño y cantidad, y el perfil temporal
RFC3339 restringido descrito más adelante.

La verificación final confirmada ejecutó 62 pruebas dentro de una copia temporal
del proyecto en un contenedor basado en `catalogo-puestos:2.8`: 62 correctas y
0 fallidas. El contenedor se ejecutó sin red y la copia evitó modificar los
archivos originales del proyecto.

El archivo original `entrada/puestos_unificados.json` conservó el SHA-256 de
referencia:

```text
5E32C17A31834EADC7BBD126C1275E513056E3869817ED7548F915C214A8547C
```

Este cierre no incorpora recuperación, ponderación, integración con proveedores
de IA ni conexión del catálogo auxiliar con el Editor de Cédulas. Esas funciones
requieren diseño, autorización y pruebas posteriores antes de cualquier uso
productivo.

## Fixture y producción

`dataset_type` admite `fixture` y `production`. El archivo incluido está marcado
como `fixture`; sus fuentes, conocimientos, aprobaciones y decisiones incluyen
también una marca ficticia explícita. La carga usa contexto `fixture` de forma
predeterminada para conservar compatibilidad. Un fixture siempre se rechaza si se
solicita contexto `production`. Toda integración productiva futura deberá invocar
explícitamente `load_and_validate(..., context="production")`; no deberá depender
del contexto predeterminado. No existe todavía un catálogo productivo.

## Archivos

- `editor_catalogo/catalogo_conocimientos.schema.json`: contrato JSON Schema.
- `editor_catalogo/catalogo_conocimientos_ficticio.json`: catálogo mínimo de prueba.
- `editor_catalogo/knowledge_catalog.py`: validador sin dependencias externas.
- `tests/test_knowledge_catalog.py`: casos válidos e inválidos.

Los pesos para una recuperación futura no forman parte de esta fase ni se
consideran definidos.

## Etapa 2D-2A: recuperación aislada

`editor_catalogo/knowledge_retriever.py` incorpora una recuperación léxica,
determinista y sin servicios externos sobre el fixture validado. Recibe un ID y
nombre de puesto ficticio, funciones ficticias, categorías opcionales y un máximo
de candidatos. Devuelve únicamente candidatos recuperados; `result_type` vale
`retrieved_candidate` y `human_selected` permanece en `false`. No crea
aprobaciones ni registros de selección.

Solo participan conocimientos con estado `approved` y aprobación global humana.
Los normativos requieren todas sus fuentes activas. La coincidencia compara raíces
normalizadas del texto de entrada con etiqueta preferida, alias y dominios. Se
ignoran palabras genéricas y términos menores de cuatro caracteres.

La ponderación inicial configurable es 3 por coincidencia en etiqueta preferida,
2 en alias y 1 en dominio, multiplicada por el número de raíces coincidentes. La
puntuación solo ordena candidatos: no mide certeza ni autoriza su incorporación a
una cédula. Los desempates usan categoría e ID, por lo que el resultado es estable.

Los valores predeterminados limitan la entrada a 10,000 caracteres, la salida a
8,000 caracteres y la solicitud a un máximo de 20 candidatos. El consumidor puede
solicitar menos resultados o límites más estrictos mediante `RetrievalConfig`.
Los pesos y la lista de términos genéricos deberán revisarse en 2D-2B; no se
consideran definitivos ni aptos todavía para datos institucionales.

Pruebas de esta etapa:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m unittest -v tests.test_knowledge_retriever
```

## Reglas

- Un conocimiento normativo aprobado requiere una fuente existente y activa.
- Una propuesta originada por IA queda pendiente; una IA no puede aprobarla.
- Una selección o descarte tiene alcance para un puesto y no concede aprobación global.
- Cada decisión registra puesto ficticio, hashes de funciones, versión, revisor y motivo.
- La ausencia de selecciones en una o más categorías es válida.
- Solo una persona puede aprobar globalmente un conocimiento o decidir su uso en
  un puesto. La aprobación para un puesto no concede aprobación global.
- La validación Python es obligatoria. Validar únicamente con JSON Schema no es
  suficiente para autorizar el uso del catálogo.

## Límites predeterminados

- Archivo JSON: 1 MiB.
- Conocimientos: 5,000.
- Fuentes: 1,000.
- Decisiones: 20,000.
- Alias por conocimiento: 50.
- Referencias o hashes por elemento: 50.
- Etiquetas e identificadores descriptivos: 200 caracteres.
- Definiciones y justificaciones: 2,000 caracteres.

Los límites se configuran mediante `CatalogLimits`. Se comprueba el tamaño del
archivo y se leen como máximo `max_json_bytes + 1` bytes antes de decodificarlo.

## Perfil temporal

Las fechas deben usar el perfil RFC3339 `AAAA-MM-DDTHH:MM:SS[.fracción]zona`.
Se admiten `Z` y desplazamientos desde `-14:00` hasta `+14:00`. Se rechazan:

- fechas inexistentes;
- valores sin hora o sin zona;
- desplazamientos superiores a 14 horas;
- `-00:00`, porque representa un desplazamiento local desconocido;
- segundos intercalares `:60`.

## JSON Schema y validación Python

El JSON Schema Draft 2020-12 comprueba forma, campos obligatorios, propiedades
adicionales, tipos, patrones, límites estructurales, marcas ficticias y el perfil
textual de las fechas. La palabra clave `format` requiere que la herramienta de
JSON Schema tenga habilitada la comprobación de formatos.

Las siguientes reglas dependen exclusivamente del validador Python:

- coincidencia entre `dataset_type` y el contexto de ejecución;
- tamaño máximo del archivo antes de decodificar;
- unicidad de IDs entre objetos;
- equivalencia normalizada de etiquetas y alias;
- existencia de fuentes y conocimientos referenciados;
- estado activo de fuentes normativas;
- selección exclusiva de conocimientos globalmente aprobados;
- coincidencia de la versión registrada en cada decisión;
- validación calendario real de las fechas;
- ausencia de mutaciones del catálogo recibido.

## Límites del prototipo

Los hashes del fixture son marcadores con formato SHA-256, no hashes de funciones institucionales.

El prototipo incorpora recuperación y ponderación de conocimientos mediante `knowledge_retriever.py`, así como integración aislada con el generador mediante `knowledge_integration.py`.

Las referencias recuperadas no se envían al proveedor de inteligencia artificial y no fundamentan automáticamente sus propuestas. La integración utiliza datos ficticios y todavía no está conectada al flujo productivo.

Los prefijos `FUE-FIC` y `SEL-FIC` siguen siendo exclusivos del conjunto ficticio.

## Validación

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m editor_catalogo.knowledge_catalog `
  editor_catalogo/catalogo_conocimientos_ficticio.json
```

## Pruebas

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m unittest -v tests.test_knowledge_catalog
```

Las pruebas utilizan datos ficticios, no abren conexiones y no requieren Docker
ni paquetes adicionales.

## Etapa 2D-2C.1 — Integración aislada del recuperador y generador

**Estado:** implementación validada con datos ficticios. Pendiente de cierre documental.

### Objetivo

Integrar el recuperador de conocimientos aprobados con el generador existente mediante un adaptador independiente, sin modificar los contratos del generador ni de los proveedores de inteligencia artificial.

### Componentes

- `knowledge_retriever.py`: identifica candidatos del catálogo ficticio y conserva sus evidencias.
- `knowledge_generator.py`: produce una propuesta mediante el proveedor configurado.
- `knowledge_integration.py`: coordina ambos componentes y mantiene separadas las referencias recuperadas de la propuesta generada.

Las referencias recuperadas no se transmiten al proveedor de IA. Por tanto, no debe afirmarse que la propuesta generada está fundamentada en dichas referencias.

### Resultados de validación

- Etapa 2D-2B: seis puestos ficticios evaluados con resultados esperados.
- Etapa 2D-2C.1: tres pruebas específicas aprobadas.
- Regresión general del proyecto: 75 pruebas aprobadas, sin errores reportados.

La validación se realizó con Docker en un contenedor temporal, sin conexión de red, utilizando copias de los archivos de desarrollo.

### Garantías y restricciones

- No se modifican las funciones originales.
- No se modifican los 213 puestos institucionales.
- Las propuestas de IA no reciben aprobación automática.
- Los conocimientos recuperados no se seleccionan automáticamente para un puesto.
- Se preservan los contratos existentes de `KnowledgeGenerator` y `AIProvider`.
- No se realizan cambios en la API, el frontend ni los proveedores.
- No existe conexión de esta integración con el flujo productivo.
- La evaluación no demuestra precisión general con catálogos institucionales.

### Siguiente etapa

**2D-2C.2 — Presentación para revisión humana.**

Diseñar la presentación diferenciada de los conocimientos generados y las referencias recuperadas, incluyendo evidencias y trazabilidad, sin conceder permisos de aprobación automática.

## Etapa 2D-2C.2A — API de referencias ficticias

**Estado:** validada técnicamente. Cierre documental registrado.

### Implementación

Se incorporó una API independiente para consultar referencias del catálogo ficticio, sin modificar las operaciones existentes de generación y aceptación de propuestas.

Componentes:

- `fixture_reference_api.py`: validación y consulta de referencias ficticias.
- `editor_catalogo.py`: incorporación de la ruta de consulta.
- `test_fixture_reference_api.py`: pruebas de funcionamiento y restricciones.
- `test_catalog_revision.py`: pruebas del mecanismo de revisión de archivos.

### Corrección del control de revisiones

Se sustituyó el mecanismo basado únicamente en la fecha de modificación del archivo por una huella SHA-256 de su contenido.

La prueba que verificaba el rechazo de una propuesta desactualizada dejó de fallar después de la corrección.

### Resultados

- 8 pruebas específicas de la API aprobadas.
- Prueba de rechazo de propuestas desactualizadas aprobada.
- 85 pruebas de regresión general aprobadas.
- Ejecución con contenedor Docker temporal y datos ficticios.

### Restricciones vigentes

La nueva consulta permanece deshabilitada por defecto y requiere configuración explícita del catálogo ficticio.

No se autoriza utilizarla con datos institucionales ni integrarla al flujo productivo.

No se modificaron intencionalmente el Editor 2.8, los 213 puestos institucionales, los proveedores de IA ni el frontend.

### Siguiente etapa

**2D-2C.2B — Presentación visual de referencias.**

Diseñar una sección independiente que muestre referencias recuperadas, fuentes y evidencias, manteniendo la revisión humana y sin incorporar automáticamente los conocimientos a las cédulas.
