# Catálogo de puestos

Proyecto para generar en Word y PDF el Catálogo Sectorial de Puestos de Servicios de Salud de Hidalgo a partir de `entrada/puestos_unificados.json`.

## Estado actual

- Genera un archivo DOCX con una ficha por puesto.
- Usa el logotipo institucional horizontal de Servicios de Salud de Hidalgo y Secretaría de Salud.
- Mantiene una franja institucional completamente color vino.
- Convierte los incisos de la descripción en párrafos Word reales.
- Une correctamente las líneas que pertenecen al mismo inciso.
- Evita los espacios excesivos causados por saltos manuales dentro de texto justificado.
- Conserva un pequeño espacio entre párrafos.

## Estructura

```text
Catalogo de puestos/
  generar_catalogo.py
  editor_catalogo/
  Dockerfile
  docker-compose.yml
  requirements.txt
  ssh_logo_recortado.png
  salida/
  entrada/
    puestos_unificados.json
  assets/
    logo_salud_hidalgo.png
    logo_anterior.png
  muestras/
  docs/
```

## Generar el catálogo

Abre PowerShell en esta carpeta y ejecuta:

```powershell
docker compose build --no-cache
docker compose run --rm catalogo-puestos
```

El resultado queda en:

```text
salida/catalogo_puestos.docx
```

## Actualizaciones normales

Si solo cambia `entrada/puestos_unificados.json`, no reconstruyas la imagen:

```powershell
docker compose run --rm catalogo-puestos
```

Si cambia el código, el logotipo, las dependencias o el Dockerfile:

```powershell
docker compose build --no-cache
docker compose run --rm catalogo-puestos
```

Antes de regenerar, cierra en Word el archivo de salida para evitar bloqueos de escritura.

## Prueba con tres registros

```powershell
docker compose run --rm catalogo-puestos /datos/puestos_unificados.json --logo /app/ssh_logo_recortado.png --salida /salida/prueba_3.docx --limite 3
```

Revisa primero la prueba cuando se modifique el diseño o la lógica de párrafos.

## Editor web de cédulas

El editor trabaja directamente con `entrada/puestos_unificados.json`, crea los
respaldos en `entrada/respaldos` y guarda los PDF en `salida`.

Los botones `PDF actual` y `PDF completo` guardan primero los cambios y generan
el PDF desde el mismo editor. La cédula individual conserva la numeración que le
corresponde dentro del catálogo.

```powershell
docker compose build --no-cache
docker compose up -d editor-catalogo
```

En la computadora que ejecuta Docker abre `http://localhost:8765`. Desde otro
equipo de la red abre `http://IP-DE-LA-COMPUTADORA:8765`.

Para detenerlo:

```powershell
docker compose down
```
