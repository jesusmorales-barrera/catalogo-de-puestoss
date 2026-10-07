# Editor de cédulas

Ejecuta `iniciar_editor.ps1` en PowerShell y abre:

```text
http://127.0.0.1:8765
```

El editor trabaja directamente con:

```text
D:\DOCUMENTOS\Codex\Catalogo de puestos\entrada\puestos_unificados.json
```

Antes de cada guardado crea una copia en `entrada\respaldos`. Los PDF se guardan
en `salida`.

## Acceso desde la red local

Ejecuta una vez `habilitar_red.ps1` como administrador para permitir el puerto
8765 únicamente en redes clasificadas como privadas. Después inicia el editor y
abre desde otro equipo `http://IP-DE-ESTA-COMPUTADORA:8765`.
