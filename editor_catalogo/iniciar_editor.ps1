$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "editor_catalogo.py"
$catalogo = "D:\DOCUMENTOS\Codex\Catalogo de puestos\entrada\puestos_unificados.json"
$salida = "D:\DOCUMENTOS\Codex\Catalogo de puestos\salida"

if (-not (Test-Path -LiteralPath $catalogo)) {
    throw "No se encontró el catálogo: $catalogo"
}

$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) {
    & py -3 $script --json $catalogo --output-dir $salida --host 0.0.0.0 --port 8765
} else {
    & python $script --json $catalogo --output-dir $salida --host 0.0.0.0 --port 8765
}
