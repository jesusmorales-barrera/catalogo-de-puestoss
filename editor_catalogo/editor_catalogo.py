#!/usr/bin/env python3
"""Visor/editor local para puestos_unificados.json, sin dependencias externas."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from pypdf import PdfReader, PdfWriter

from editor_catalogo.knowledge_generator import (
    InvalidFunctionsError,
    InvalidProviderResponseError,
    KnowledgeGenerator,
    count_words,
)
from editor_catalogo.providers.simulated import SimulatedProvider
from editor_catalogo.fixture_reference_api import query_fixture_references


DEFAULT_JSON = Path(r"D:\DOCUMENTOS\Codex\Catalogo de puestos\entrada\puestos_unificados.json")
DEFAULT_OUTPUT = Path(r"D:\DOCUMENTOS\Codex\Catalogo de puestos\salida")
HTML_PATH = Path(__file__).with_name("editor.html")
GENERATOR_PATH = Path(os.environ.get("CATALOGO_GENERADOR", Path(__file__).resolve().parents[1] / "generar_catalogo.py"))
LOGO_PATH = Path(os.environ.get("CATALOGO_LOGO", Path(__file__).resolve().parents[1] / "ssh_logo_recortado.png"))
GENERATION_LOCK = threading.Lock()
PROPOSAL_TTL_SECONDS = 15 * 60
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
        # Exclusión solo entre hilos de esta instancia. No protege frente a
        # otros procesos que abran el mismo JSON simultáneamente.
        self.write_lock = threading.Lock()

    def load(self):
        if not self.path.is_file():
            raise FileNotFoundError(f"No existe el catálogo: {self.path}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("registros"), list):
            raise ValueError("El JSON debe contener una lista en el campo 'registros'.")
        return data

    def revision(self):
        # Revision basada en contenido para detectar cambios con igual mtime.
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

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


class ProposalError(Exception):
    status = HTTPStatus.BAD_REQUEST


class DuplicateProposalRequest(ProposalError):
    status = HTTPStatus.CONFLICT


class ProposalNotFound(ProposalError):
    status = HTTPStatus.NOT_FOUND


class ProposalExpired(ProposalError):
    status = HTTPStatus.GONE


class ProposalUsed(ProposalError):
    status = HTTPStatus.CONFLICT


class ProposalStale(ProposalError):
    status = HTTPStatus.CONFLICT


@dataclass
class PendingProposal:
    proposal_id: str
    position_id: str
    revision: str
    source_digest: str
    rendered_text: str
    word_count: int
    categories: dict[str, list[str]]
    idempotency_key: str
    expires_at: float
    used: bool = False


class PendingProposalStore:
    """Almacén efímero e intra-proceso para propuestas no aprobadas."""

    def __init__(self, ttl_seconds=PROPOSAL_TTL_SECONDS, clock=time.monotonic):
        if ttl_seconds <= 0:
            raise ValueError("La caducidad debe ser positiva.")
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._proposals: dict[str, PendingProposal] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._in_flight: set[str] = set()

    def generate(
        self,
        *,
        position_id,
        revision,
        idempotency_key,
        position_name,
        functions,
        generator,
    ):
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ProposalError("Se requiere el encabezado Idempotency-Key.")
        idempotency_key = idempotency_key.strip()
        if len(idempotency_key) > 200:
            raise ProposalError("Idempotency-Key es demasiado largo.")
        lookup = (position_id, idempotency_key)
        now = self.clock()
        with self._lock:
            existing_id = self._idempotency.get(lookup)
            if existing_id is not None:
                proposal = self._proposals[existing_id]
                self._validate_available(proposal, now)
                return proposal, True
            if position_id in self._in_flight:
                raise DuplicateProposalRequest(
                    "Ya existe una generación en curso para este puesto."
                )
            self._in_flight.add(position_id)

        try:
            result = generator.generate(position_id, position_name, functions)
            proposal = PendingProposal(
                proposal_id=str(uuid.uuid4()),
                position_id=position_id,
                revision=revision,
                source_digest=result.source_digest,
                rendered_text=result.rendered_text,
                word_count=result.word_count,
                categories={
                    "tecnicos": list(result.tecnicos),
                    "administrativos": list(result.administrativos),
                    "normativos": list(result.normativos),
                },
                idempotency_key=idempotency_key,
                expires_at=self.clock() + self.ttl_seconds,
            )
            with self._lock:
                self._proposals[proposal.proposal_id] = proposal
                self._idempotency[lookup] = proposal.proposal_id
            return proposal, False
        finally:
            with self._lock:
                self._in_flight.discard(position_id)

    def get_for_acceptance(self, proposal_id, position_id, revision, source_digest):
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise ProposalNotFound("No se encontró la propuesta.")
            self._validate_available(proposal, self.clock())
            if proposal.position_id != position_id:
                raise ProposalError("La propuesta no corresponde al puesto seleccionado.")
            if proposal.revision != revision:
                raise ProposalStale("La propuesta corresponde a otra revisión del catálogo.")
            if proposal.source_digest != source_digest:
                raise ProposalError("El resumen de origen de la propuesta no coincide.")
            return proposal

    def mark_used(self, proposal_id):
        with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise ProposalNotFound("No se encontró la propuesta.")
            if proposal.used:
                raise ProposalUsed("La propuesta ya fue utilizada.")
            proposal.used = True

    def _validate_available(self, proposal, now):
        if proposal.used:
            raise ProposalUsed("La propuesta ya fue utilizada.")
        if now >= proposal.expires_at:
            raise ProposalExpired("La propuesta expiró; genera una nueva.")


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
    knowledge_generator: KnowledgeGenerator
    proposals: PendingProposalStore
    fixture_reference_catalog: Path | None = None

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

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("El cuerpo JSON está vacío o excede el límite permitido.")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("El cuerpo JSON debe ser un objeto.")
        return payload

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
            acceptance = re.fullmatch(r"/api/puestos/([^/]+)/conocimientos", path)
            payload = self.read_json()
            if acceptance:
                return self.accept_knowledge(unquote(acceptance.group(1)), payload)

            expected = payload.pop("revision", None)
            if not str(payload.get("puesto") or "").strip():
                return self.send_json({"error": "El campo Puesto es obligatorio."}, HTTPStatus.BAD_REQUEST)
            key = unquote(path.removeprefix("/api/puestos/"))
            with self.store.write_lock:
                if expected is not None and str(expected) != self.store.revision():
                    return self.send_json(
                        {"error": "El archivo cambió. Recarga la cédula antes de guardar."},
                        HTTPStatus.CONFLICT,
                    )
                data = self.store.load()
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
                response = {
                    "guardado": True,
                    "campos_modificados": changed,
                    "revision": self.store.revision(),
                }
            self.send_json(response)
        except ProposalError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def accept_knowledge(self, key, payload):
        allowed = {"revision", "proposal_id", "source_digest", "conocimientos"}
        if set(payload) != allowed:
            return self.send_json(
                {"error": "La aceptación contiene campos faltantes o no autorizados."},
                HTTPStatus.BAD_REQUEST,
            )
        expected = str(payload["revision"])
        proposal_id = payload["proposal_id"]
        source_digest = payload["source_digest"]
        knowledge = payload["conocimientos"]
        if not isinstance(proposal_id, str) or not isinstance(source_digest, str):
            raise ValueError("proposal_id y source_digest deben ser textos.")
        if not isinstance(knowledge, str):
            raise ValueError("conocimientos debe ser texto.")
        knowledge = knowledge.strip()
        countable_knowledge = re.sub(
            r"(?im)^\s*(?:Técnicos|Administrativos|Normativos)\s*:\s*",
            "",
            knowledge,
        )
        words = count_words(countable_knowledge)
        if not knowledge or words == 0:
            raise ValueError("conocimientos no puede estar vacío.")
        if words > self.knowledge_generator.max_words:
            raise ValueError(
                f"conocimientos contiene {words} palabras; el máximo es "
                f"{self.knowledge_generator.max_words}."
            )
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", knowledge):
            raise ValueError("conocimientos contiene caracteres de control.")
        if re.search(r"<\s*/?\s*[A-Za-z][^>]*>", knowledge):
            raise ValueError("conocimientos contiene marcado no permitido.")

        with self.store.write_lock:
            current_revision = self.store.revision()
            if expected != current_revision:
                raise ProposalStale(
                    "El archivo cambió. Recarga la cédula antes de aceptar."
                )
            proposal = self.proposals.get_for_acceptance(
                proposal_id, key, current_revision, source_digest
            )
            data = self.store.load()
            record = self.store.find(data, key)
            if record is None:
                return self.send_json(
                    {"error": "No se encontró la cédula."}, HTTPStatus.NOT_FOUND
                )
            changed = []
            if str(record.get("conocimientos") or "").strip() != knowledge:
                record["conocimientos"] = knowledge
                changed.append("conocimientos")
                data.setdefault("historial_cambios", []).append({
                    "fecha": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "fila_excel": record.get("fila_excel"),
                    "puesto": record.get("puesto"),
                    "campos": ["conocimientos"],
                })
                self.store.save(data)
            self.proposals.mark_used(proposal.proposal_id)
            response = {
                "guardado": True,
                "campos_modificados": changed,
                "revision": self.store.revision(),
            }
        self.send_json(response)

    def do_POST(self):
        path = urlparse(self.path).path
        reference_route = re.fullmatch(
            r"/api/puestos-ficticios/([^/]+)/referencias-conocimientos", path
        )
        if reference_route:
            return self.query_knowledge_references(unquote(reference_route.group(1)))
        proposal_route = re.fullmatch(
            r"/api/puestos/([^/]+)/propuestas-conocimientos", path
        )
        if proposal_route:
            return self.generate_knowledge_proposal(unquote(proposal_route.group(1)))
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

    def query_knowledge_references(self, key):
        """Consulta aislada de referencias ficticias; nunca utiliza self.store."""
        if self.fixture_reference_catalog is None:
            return self.send_json(
                {"error": "La consulta ficticia no está habilitada."},
                HTTPStatus.NOT_FOUND,
            )
        try:
            payload = self.read_json()
            result = query_fixture_references(
                catalog_path=self.fixture_reference_catalog,
                position_id=key,
                payload=payload,
            )
            return self.send_json(result)
        except (ValueError, TypeError) as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            # No devolver rutas del servidor ni datos potencialmente sensibles.
            return self.send_json(
                {"error": "No fue posible consultar el catálogo ficticio."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def generate_knowledge_proposal(self, key):
        try:
            payload = self.read_json()
            if set(payload) != {"revision", "funciones"}:
                return self.send_json(
                    {"error": "La generación contiene campos faltantes o no autorizados."},
                    HTTPStatus.BAD_REQUEST,
                )
            expected = str(payload["revision"])
            functions = payload["funciones"]
            with self.store.write_lock:
                current_revision = self.store.revision()
                if expected != current_revision:
                    raise ProposalStale(
                        "El archivo cambió. Recarga la cédula antes de generar."
                    )
                data = self.store.load()
                record = self.store.find(data, key)
                if record is None:
                    return self.send_json(
                        {"error": "No se encontró la cédula."}, HTTPStatus.NOT_FOUND
                    )
                position_name = str(record.get("puesto") or "").strip()

            proposal, reused = self.proposals.generate(
                position_id=key,
                revision=current_revision,
                idempotency_key=self.headers.get("Idempotency-Key", ""),
                position_name=position_name,
                functions=functions,
                generator=self.knowledge_generator,
            )
            self.send_json({
                "proposal_id": proposal.proposal_id,
                "position_id": proposal.position_id,
                "source_digest": proposal.source_digest,
                "revision": proposal.revision,
                "conocimientos": proposal.categories,
                "texto": proposal.rendered_text,
                "palabras": proposal.word_count,
                "maximo_palabras": self.knowledge_generator.max_words,
                "reutilizada": reused,
                "caducidad_segundos": self.proposals.ttl_seconds,
            })
        except ProposalError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except (json.JSONDecodeError, InvalidFunctionsError, InvalidProviderResponseError, ValueError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main():
    parser = argparse.ArgumentParser(description="Editor local del catálogo de puestos")
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--fixture-reference-catalog", type=Path, default=None,
                        help="Habilita consultas solo contra un catálogo de conocimientos ficticio")
    args = parser.parse_args()
    Handler.store = CatalogStore(args.json, args.output_dir)
    # Etapa 1B-1: la única implementación habilitada es la simulada.
    Handler.knowledge_generator = KnowledgeGenerator(SimulatedProvider())
    Handler.proposals = PendingProposalStore()
    Handler.fixture_reference_catalog = args.fixture_reference_catalog
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
