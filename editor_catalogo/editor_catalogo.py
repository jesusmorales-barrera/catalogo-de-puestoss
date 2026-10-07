#!/usr/bin/env python3
"""Visor/editor local para puestos_unificados.json, sin dependencias externas."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from pypdf import PdfReader, PdfWriter


DEFAULT_JSON = Path(r"D:\DOCUMENTOS\Codex\Catalogo de puestos\entrada\puestos_unificados.json")
DEFAULT_OUTPUT = Path(r"D:\DOCUMENTOS\Codex\Catalogo de puestos\salida")
HTML_PATH = Path(__file__).with_name("editor.html")
GENERATOR_PATH = Path(os.environ.get("CATALOGO_GENERADOR", Path(__file__).resolve().parents[1] / "generar_catalogo.py"))
LOGO_PATH = Path(os.environ.get("CATALOGO_LOGO", Path(__file__).resolve().parents[1] / "ssh_logo_recortado.png"))
GENERATION_LOCK = threading.Lock()
EDITABLE_FIELDS = (
    "perfil", "nivel", "puesto", "categoria", "escolaridad_requerida", "experiencia_anios",
    "conocimientos", "denominacion_generica_puesto", "funciones_genericas",
)
REQUIRED_FIELDS = ("puesto", "nivel", "escolaridad_requerida", "experiencia_anios", "funciones_genericas")


def split_functions(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    text = re.sub(r"(?<=\S)\s+(?=[IVXLCDM]+\.\s*)", "\n", text)
    return [
        re.sub(r"^\s*[IVXLCDM]+\.\s*", "", part).strip()
        for part in text.split("\n")
        if re.sub(r"^\s*[IVXLCDM]+\.\s*", "", part).strip()
    ]


class CatalogStore:
    def __init__(self, path: Path, output_dir: Path):
        self.path = path.resolve()
        self.output_dir = output_dir.resolve()
        self.backup_dir = self.path.parent / "respaldos"

    def load(self):
        if not self.path.is_file():
            raise FileNotFoundError(f"No existe el catálogo: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("registros"), list):
            raise ValueError("El JSON debe contener una lista en el campo 'registros'.")
        return data

    def revision(self):
        # JavaScript cannot represent nanosecond timestamps precisely as numbers.
        return str(self.path.stat().st_mtime_ns)

    @staticmethod
    def key(record, index):
        return str(record.get("fila_excel") or f"indice-{index}")

    def find(self, data, key):
        for index, record in enumerate(data["registros"]):
            if self.key(record, index) == key:
                return record
        return None

    def save(self, data):
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        shutil.copy2(self.path, self.backup_dir / f"puestos_unificados_{stamp}.json")
        descriptor, temp_name = tempfile.mkstemp(
            prefix="catalogo_", suffix=".json", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


def load_generator():
    spec = importlib.util.spec_from_file_location("catalogo_generator", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar el generador: {GENERATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def convert_to_pdf(docx_path: Path, output_dir: Path) -> Path:
    soffice = shutil.which("soffice")
    if not soffice:
        raise RuntimeError("LibreOffice no está disponible. Reconstruye la imagen Docker.")
    profile = output_dir / "libreoffice-profile"
    command = [
        soffice,
        "--headless",
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--convert-to", "pdf",
        "--outdir", str(output_dir),
        str(docx_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    pdf_path = output_dir / f"{docx_path.stem}.pdf"
    if result.returncode != 0 or not pdf_path.is_file():
        detail = (result.stderr or result.stdout or "Error desconocido").strip()
        raise RuntimeError(f"No se pudo convertir el documento a PDF: {detail}")
    return pdf_path


def safe_filename(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-záéíóúüñÁÉÍÓÚÜÑ]+", "_", value).strip("_")
    return value[:70] or "puesto"


def generate_full_pdf(store: CatalogStore) -> Path:
    generator = load_generator()
    records = generator.load_records_json(store.path)
    store.output_dir.mkdir(parents=True, exist_ok=True)
    output = store.output_dir / "catalogo_puestos.pdf"
    with tempfile.TemporaryDirectory(prefix="catalogo_pdf_") as temp_name:
        temp = Path(temp_name)
        docx = temp / "catalogo_puestos.docx"
        generator.build_catalog(records, docx, LOGO_PATH)
        pdf = convert_to_pdf(docx, temp)
        shutil.copy2(pdf, output)
    return output


def generate_record_pdf(store: CatalogStore, key: str) -> Path:
    data = store.load()
    source_record = store.find(data, key)
    if source_record is None:
        raise ValueError("No se encontró la cédula seleccionada.")
    eligible_sources = [
        record for record in data["registros"] if record.get("nivel") or record.get("puesto")
    ]
    source_index = eligible_sources.index(source_record)
    generator = load_generator()
    records = generator.load_records_json(store.path)
    if source_index >= len(records):
        raise ValueError("La cédula no tiene una posición válida en el catálogo.")

    with tempfile.TemporaryDirectory(prefix="cedula_pdf_") as temp_name:
        temp = Path(temp_name)
        previous_pages = 0
        if source_index:
            previous_docx = temp / "anteriores.docx"
            generator.build_catalog(records[:source_index], previous_docx, LOGO_PATH)
            previous_pdf = convert_to_pdf(previous_docx, temp)
            previous_pages = len(PdfReader(previous_pdf).pages)

        prefix_docx = temp / "hasta_cedula.docx"
        generator.build_catalog(records[: source_index + 1], prefix_docx, LOGO_PATH)
        prefix_pdf = convert_to_pdf(prefix_docx, temp)
        reader = PdfReader(prefix_pdf)
        if previous_pages >= len(reader.pages):
            raise RuntimeError("No se pudieron identificar las páginas de la cédula.")
        writer = PdfWriter()
        for page in reader.pages[previous_pages:]:
            writer.add_page(page)
        name = f"cedula_{key}_{safe_filename(str(source_record.get('puesto') or 'puesto'))}.pdf"
        store.output_dir.mkdir(parents=True, exist_ok=True)
        output = store.output_dir / name
        with output.open("wb") as stream:
            writer.write(stream)
    return output


class Handler(BaseHTTPRequestHandler):
    store: CatalogStore

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self):
        body = HTML_PATH.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_pdf(self, path: Path):
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path == "/":
                return self.send_html()
            if path == "/api/puestos":
                data = self.store.load()
                records = []
                for index, record in enumerate(data["registros"]):
                    records.append({
                        "id": self.store.key(record, index),
                        "puesto": record.get("puesto") or "Sin puesto",
                        "nivel": record.get("nivel") or "",
                        "incompleto": any(not record.get(field) for field in REQUIRED_FIELDS),
                    })
                return self.send_json({"registros": records, "revision": self.store.revision()})
            if path.startswith("/api/puestos/"):
                key = unquote(path.removeprefix("/api/puestos/"))
                data = self.store.load()
                record = self.store.find(data, key)
                if record is None:
                    return self.send_json({"error": "No se encontró la cédula."}, HTTPStatus.NOT_FOUND)
                result = {
                    field: record.get(field, [] if field == "funciones_genericas" else "")
                    for field in EDITABLE_FIELDS
                }
                result["funciones_genericas"] = split_functions(
                    result["funciones_genericas"]
                )
                result["fila_excel"] = record.get("fila_excel")
                return self.send_json({"registro": result, "revision": self.store.revision()})
            if path.startswith("/archivos/"):
                name = Path(unquote(path.removeprefix("/archivos/"))).name
                file_path = self.store.output_dir / name
                if file_path.suffix.lower() != ".pdf" or not file_path.is_file():
                    return self.send_json({"error": "No se encontró el PDF."}, HTTPStatus.NOT_FOUND)
                return self.send_pdf(file_path)
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_PUT(self):
        try:
            path = urlparse(self.path).path
            if not path.startswith("/api/puestos/"):
                return self.send_error(HTTPStatus.NOT_FOUND)
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            expected = payload.pop("revision", None)
            if expected is not None and str(expected) != self.store.revision():
                return self.send_json(
                    {"error": "El archivo cambió. Recarga la cédula antes de guardar."},
                    HTTPStatus.CONFLICT,
                )
            if not str(payload.get("puesto") or "").strip():
                return self.send_json({"error": "El campo Puesto es obligatorio."}, HTTPStatus.BAD_REQUEST)
            data = self.store.load()
            key = unquote(path.removeprefix("/api/puestos/"))
            record = self.store.find(data, key)
            if record is None:
                return self.send_json({"error": "No se encontró la cédula."}, HTTPStatus.NOT_FOUND)
            changed = []
            for field in EDITABLE_FIELDS:
                if field not in payload:
                    continue
                value = payload.get(field, [] if field == "funciones_genericas" else "")
                if field == "funciones_genericas":
                    if not isinstance(value, list):
                        return self.send_json({"error": "Las funciones deben ser una lista."}, HTTPStatus.BAD_REQUEST)
                    value = [str(item).strip() for item in value if str(item).strip()]
                else:
                    value = "" if value is None else str(value).strip()
                current = record.get(field)
                same_value = (
                    current == value
                    if field == "funciones_genericas"
                    else str(current or "").strip() == value
                )
                if not same_value:
                    record[field] = value
                    changed.append(field)
            if changed:
                data.setdefault("historial_cambios", []).append({
                    "fecha": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "fila_excel": record.get("fila_excel"),
                    "puesto": record.get("puesto"),
                    "campos": changed,
                })
                self.store.save(data)
            self.send_json({"guardado": True, "campos_modificados": changed, "revision": self.store.revision()})
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/generar/"):
            return self.send_error(HTTPStatus.NOT_FOUND)
        if not GENERATION_LOCK.acquire(blocking=False):
            return self.send_json(
                {"error": "Ya existe una generación de PDF en proceso."},
                HTTPStatus.CONFLICT,
            )
        try:
            if path == "/api/generar/completo":
                output = generate_full_pdf(self.store)
            elif path.startswith("/api/generar/puesto/"):
                key = unquote(path.removeprefix("/api/generar/puesto/"))
                output = generate_record_pdf(self.store, key)
            else:
                return self.send_error(HTTPStatus.NOT_FOUND)
            self.send_json({"generado": True, "archivo": output.name, "url": f"/archivos/{output.name}"})
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            GENERATION_LOCK.release()


def main():
    parser = argparse.ArgumentParser(description="Editor local del catálogo de puestos")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    Handler.store = CatalogStore(args.json, args.output_dir)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Editor disponible en http://{args.host}:{args.port}")
    print(f"Catálogo: {Handler.store.path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
