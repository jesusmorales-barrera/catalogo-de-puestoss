# Editor de Cédulas del Catálogo de Puestos 3.0

## Guía de instalación con Docker

### Requisitos

- Windows con Docker Desktop o Ubuntu con Docker Engine.
- Docker Compose v2.
- Acceso a Docker Hub para descargar la imagen.
- Archivo JSON de puestos autorizado.

### Estructura de carpetas

```text
editor-cedulas-3/
├── compose.yaml
├── entrada/
│   └── puestos_unificados.json
└── salida/
```

Las carpetas `entrada` y `salida` se encuentran fuera del contenedor Docker. Los archivos operativos no se incluyen en GitHub ni en la imagen.

### Instalación

1. Crear una carpeta para la aplicación.
2. Copiar el archivo `compose.yaml`.
3. Crear las carpetas `entrada` y `salida`.
4. Colocar `puestos_unificados.json` en `entrada`.
5. Abrir una terminal en la carpeta de instalación.

La imagen `jmoralesbarrrera/catalogo-puestos:3.0.0` todavía está pendiente de publicación.

### Iniciar el Editor

```bash
docker compose pull editor-catalogo
docker compose up -d editor-catalogo
```

Abrir en el navegador:

`http://localhost:8765`

### Generar catálogo Word

```bash
docker compose --profile generador run --rm --no-deps catalogo-puestos
```

El documento se guardará en `salida/catalogo_puestos.docx`.

### Detener el Editor

```bash
docker compose down
```

Este comando no elimina las carpetas externas de datos.

### Respaldos y actualizaciones

Realizar copias periódicas de `entrada` y `salida`. Antes de actualizar la imagen, respaldar los datos y comprobar la compatibilidad de la nueva versión.

### Seguridad

- No publicar información institucional.
- No incluir contraseñas, tokens ni claves.
- Restringir el acceso a las carpetas.
- No exponer directamente el Editor a Internet.
- Configurar autenticación y HTTPS antes de habilitar acceso desde redes no confiables.

### Estado de la versión

**Versión objetivo:** 3.0.0

Pruebas locales satisfactorias: 86 pruebas automatizadas, guardado de datos, respaldos, generación PDF y DOCX.

Pendiente: publicación autorizada e instalación en otra computadora.