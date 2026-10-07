# Instrucciones del proyecto

## Objetivo

Mantener el editor web y el generador reproducible del Catálogo Sectorial de
Puestos. La fuente definitiva es `entrada/puestos_unificados.json`. Los DOCX y
PDF generados se guardan en `salida/`.

## Ejecución principal

Abrir PowerShell en la raíz del proyecto:

```powershell
cd "D:\DOCUMENTOS\Codex\Catalogo de puestos"
```

Después de cambiar código, dependencias, Dockerfile, logotipo o configuración:

```powershell
docker compose down
docker compose build --no-cache
docker compose up -d editor-catalogo
```

Comprobar el estado:

```powershell
docker compose ps
docker compose logs --tail 100 editor-catalogo
```

Abrir el editor en la computadora anfitriona:

```text
http://localhost:8765
```

Desde otra computadora de la misma red:

```text
http://IP-DE-LA-COMPUTADORA:8765
```

## Generación de documentos

El editor tiene dos comandos:

- `PDF actual`: guarda los cambios y genera únicamente la cédula seleccionada,
  conservando su numeración dentro del catálogo.
- `PDF completo`: guarda los cambios y genera todo el catálogo.

Los PDF se guardan en `salida/`. El catálogo completo se llama
`salida/catalogo_puestos.pdf`; las cédulas individuales usan el prefijo
`salida/cedula_`.

Para generar el DOCX completo desde PowerShell:

```powershell
docker compose run --rm catalogo-puestos
```

Para generar una prueba DOCX con tres registros:

```powershell
docker compose run --rm catalogo-puestos /datos/puestos_unificados.json --logo /app/ssh_logo_recortado.png --salida /salida/prueba_3.docx --limite 3
```

Si únicamente cambia `entrada/puestos_unificados.json`, no es necesario
reconstruir la imagen. Reiniciar el editor solo cuando sea necesario:

```powershell
docker compose restart editor-catalogo
```

## Datos y respaldos

- `entrada/puestos_unificados.json` es la única fuente de datos vigente.
- El editor modifica directamente ese JSON.
- Antes de guardar, el editor crea una copia en `entrada/respaldos/`.
- `entrada/` y `salida/` están excluidos de Git y deben transferirse por separado.
- No volver a introducir Excel, extractores o unificadores en el flujo normal.

## Archivos importantes

- `generar_catalogo.py`: generador canónico de DOCX.
- `editor_catalogo/editor_catalogo.py`: servidor y API del editor.
- `editor_catalogo/editor.html`: interfaz del editor.
- `entrada/puestos_unificados.json`: datos definitivos.
- `ssh_logo_recortado.png`: logotipo institucional.
- `Dockerfile`: imagen con Python, LibreOffice y las dependencias PDF.
- `docker-compose.yml`: servicios `catalogo-puestos` y `editor-catalogo`.

## Reglas de trabajo

- Usar Docker como método principal de ejecución y distribución.
- No cambiar el contenido sustantivo de los puestos sin petición explícita.
- Mantener una ficha por puesto y conservar todos los registros válidos.
- No borrar ni sustituir funciones existentes de manera automática.
- Mantener los campos ocultos del editor dentro del JSON.
- Usar el color vino `691A32` para las barras institucionales.
- Usar `ssh_logo_recortado.png` sin deformarlo ni duplicar texto institucional.
- Conservar `split_description_paragraphs` y los párrafos reales entre funciones.
- Mantener 4 puntos de espacio posterior entre párrafos de descripción.
- Bloquear generaciones PDF simultáneas para evitar archivos cruzados.

## Validaciones mínimas

1. Confirmar que el JSON es válido y contiene los 213 registros esperados.
2. Confirmar que el editor puede leer, modificar, respaldar y volver a abrir un puesto.
3. Confirmar que los PDF se escriben en `salida/`, nunca en `entrada/`.
4. Confirmar que la cédula individual conserva la numeración del catálogo.
5. Confirmar que no se duplica el nombre institucional en el encabezado.
6. Confirmar que no hay texto recortado, espacios excesivos ni tablas rotas.
7. Después de cambios visuales, generar tres registros y revisar el documento renderizado.
