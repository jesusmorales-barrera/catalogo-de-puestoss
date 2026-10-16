"""Validación independiente del catálogo auxiliar ficticio de conocimientos.

Etapa 2D-1B. No modifica los datos proporcionados ni los puestos originales.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class CatalogValidationError(ValueError):
    """El catálogo incumple su esquema o sus reglas de negocio."""


CATEGORIES = {"tecnicos", "administrativos", "normativos"}
STATUSES = {"pending_review", "approved", "rejected", "deprecated"}
SOURCE_STATUSES = {"active", "inactive", "superseded"}
KNOWLEDGE_ID = re.compile(r"CON-[0-9]{6}\Z")
SOURCE_ID = re.compile(r"FUE-FIC-[0-9]{6}\Z")
SELECTION_ID = re.compile(r"SEL-FIC-[0-9]{6}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
DATE = re.compile(
    r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?"
    r"(?:Z|[+-](?:(?:0\d|1[0-3]):[0-5]\d|14:00))\Z"
)
DATASET_TYPES = {"fixture", "production"}


@dataclass(frozen=True)
class CatalogLimits:
    """Límites conservadores para un catálogo auxiliar local.

    Un MiB evita cargar archivos inesperadamente grandes; las cantidades admiten
    crecimiento muy superior al fixture sin convertir este prototipo en un almacén
    ilimitado. Los límites de texto preservan etiquetas breves y explicaciones
    revisables. Pueden reducirse por llamada, sin desactivar la validación.
    """

    max_json_bytes: int = 1_048_576
    max_knowledge: int = 5_000
    max_sources: int = 1_000
    max_selection_records: int = 20_000
    max_aliases: int = 50
    max_references: int = 50
    max_label_length: int = 200
    max_definition_length: int = 2_000
    max_reason_length: int = 2_000

    def __post_init__(self):
        for name, value in vars(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} debe ser un entero positivo")


DEFAULT_LIMITS = CatalogLimits()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise CatalogValidationError(message)


def keys(value, required, optional=(), context="objeto"):
    require(isinstance(value, dict), f"{context}: debe ser objeto")
    actual = set(value)
    required = set(required)
    require(required <= actual, f"{context}: faltan campos {sorted(required - actual)}")
    require(actual <= required | set(optional), f"{context}: campos adicionales")


def text(value, context, maximum=None):
    require(isinstance(value, str) and bool(value.strip()), f"{context}: texto inválido")
    if maximum is not None:
        require(len(value) <= maximum, f"{context}: excede {maximum} caracteres")


def identifier(value, pattern, context):
    require(isinstance(value, str) and pattern.fullmatch(value) is not None,
            f"{context}: identificador inválido")


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def text_list(value, context, minimum=0, maximum=None, text_maximum=None):
    require(isinstance(value, list) and len(value) >= minimum, f"{context}: lista inválida")
    if maximum is not None:
        require(len(value) <= maximum, f"{context}: excede {maximum} elementos")
    seen = set()
    for term in value:
        text(term, context, text_maximum)
        token = normalized(term)
        require(token not in seen, f"{context}: término duplicado")
        seen.add(token)


def timestamp(value, context):
    require(isinstance(value, str) and DATE.fullmatch(value) is not None,
            f"{context}: fecha RFC3339 inválida")
    require(not value.endswith("-00:00"),
            f"{context}: -00:00 no identifica una zona horaria conocida")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.utcoffset() is not None, f"{context}: fecha sin zona horaria")
        require(abs(parsed.utcoffset().total_seconds()) <= 14 * 3600,
                f"{context}: zona horaria inválida")
    except ValueError as exc:
        raise CatalogValidationError(f"{context}: fecha RFC3339 inválida") from exc


def approval(value, status, dataset_type, limits):
    if status != "approved":
        require(value is None, "estado no aprobado requiere aprobación global nula")
        return
    keys(value, {"scope", "reviewer_type", "reviewer_id", "approved_at", "fictitious"}, context="aprobación global")
    require(value["fictitious"] is (dataset_type == "fixture"),
            "marca ficticia de aprobación global inválida")
    require(value["scope"] == "global", "alcance global inválido")
    require(value["reviewer_type"] == "human", "una IA no puede aprobar globalmente")
    text(value["reviewer_id"], "revisor global", limits.max_label_length)
    timestamp(value["approved_at"], "approved_at")


def validate_catalog(catalog, context="fixture", limits=DEFAULT_LIMITS):
    """Verifica estructura, referencias y reglas sin mutar *catalog*."""
    require(context in DATASET_TYPES, "contexto de ejecución inválido")
    require(isinstance(limits, CatalogLimits), "limits debe ser CatalogLimits")
    keys(catalog, {"dataset_type", "schema_version", "catalog_version", "generated_at", "categories",
                   "sources", "knowledge", "selection_records"}, context="catálogo")
    require(catalog["dataset_type"] in DATASET_TYPES, "dataset_type inválido")
    require(catalog["dataset_type"] == context,
            f"catálogo {catalog['dataset_type']} no permitido en contexto {context}")
    dataset_type = catalog["dataset_type"]
    require(catalog["schema_version"] == "1.0", "schema_version inválida")
    require(isinstance(catalog["catalog_version"], str) and VERSION.fullmatch(catalog["catalog_version"]) is not None,
            "catalog_version inválida")
    timestamp(catalog["generated_at"], "generated_at")

    categories = catalog["categories"]
    require(isinstance(categories, list) and len(categories) == 3, "categorías inválidas")
    seen_categories = set()
    for category in categories:
        keys(category, {"id", "definition"}, context="categoría")
        require(category["id"] in CATEGORIES, "categoría inválida")
        require(category["id"] not in seen_categories, "categoría duplicada")
        text(category["definition"], "definición de categoría", limits.max_definition_length)
        seen_categories.add(category["id"])
    require(seen_categories == CATEGORIES, "faltan categorías")

    sources = catalog["sources"]
    require(isinstance(sources, list), "sources debe ser lista")
    require(len(sources) <= limits.max_sources, "sources excede el límite")
    by_source = {}
    for source in sources:
        keys(source, {"id", "title", "document_type", "version", "status", "fictitious"}, context="fuente")
        identifier(source["id"], SOURCE_ID, "fuente")
        require(source["id"] not in by_source, "identificador duplicado de fuente")
        for field in ("title", "document_type", "version"):
            text(source[field], field, limits.max_label_length)
        require(source["status"] in SOURCE_STATUSES, "estado de fuente inválido")
        require(source["fictitious"] is (dataset_type == "fixture"),
                "marca ficticia de fuente inválida")
        by_source[source["id"]] = source

    knowledge = catalog["knowledge"]
    require(isinstance(knowledge, list), "knowledge debe ser lista")
    require(len(knowledge) <= limits.max_knowledge, "knowledge excede el límite")
    by_knowledge = {}
    seen_terms = set()
    for item in knowledge:
        keys(item, {"id", "category", "preferred_label", "definition", "domains", "aliases",
                    "excluded_meanings", "source_ids", "status", "origin", "global_approval", "revision",
                    "fictitious"},
             context="conocimiento")
        require(item["fictitious"] is (dataset_type == "fixture"),
                "marca ficticia de conocimiento inválida")
        identifier(item["id"], KNOWLEDGE_ID, "conocimiento")
        require(item["id"] not in by_knowledge, "identificador duplicado de conocimiento")
        require(item["category"] in CATEGORIES, "categoría inválida")
        require(item["status"] in STATUSES, "estado inválido")
        text(item["preferred_label"], "etiqueta preferida", limits.max_label_length)
        text(item["definition"], "definición", limits.max_definition_length)
        text_list(item["domains"], "domains", 1, limits.max_references,
                  limits.max_label_length)
        text_list(item["aliases"], "aliases", maximum=limits.max_aliases,
                  text_maximum=limits.max_label_length)
        text_list(item["excluded_meanings"], "excluded_meanings",
                  maximum=limits.max_references,
                  text_maximum=limits.max_definition_length)
        for term in [item["preferred_label"], *item["aliases"]]:
            key = normalized(term)
            require(key not in seen_terms, "término equivalente duplica otro")
            seen_terms.add(key)
        source_ids = item["source_ids"]
        require(isinstance(source_ids, list), "source_ids debe ser lista")
        require(len(source_ids) <= limits.max_references, "source_ids excede el límite")
        seen_ids = set()
        for source_id in source_ids:
            identifier(source_id, SOURCE_ID, "source_id")
            require(source_id not in seen_ids, "source_ids duplicados")
            seen_ids.add(source_id)
            require(source_id in by_source, "referencia inexistente de fuente")
        if item["category"] == "normativos" and item["status"] == "approved":
            require(bool(source_ids), "normativo aprobado requiere fuente")
            for source_id in source_ids:
                require(by_source[source_id]["status"] == "active", "fuente normativa no está activa")
        origin = item["origin"]
        keys(origin, {"type"}, {"model"}, "origen")
        require(origin["type"] in ("human", "ai"), "origen inválido")
        if origin["type"] == "ai":
            require("model" in origin, "origen de IA requiere modelo")
        if "model" in origin:
            text(origin["model"], "modelo", limits.max_label_length)
        approval(item["global_approval"], item["status"], dataset_type, limits)
        require(type(item["revision"]) is int and item["revision"] >= 1, "revisión inválida")
        by_knowledge[item["id"]] = item

    records = catalog["selection_records"]
    require(isinstance(records, list), "selection_records debe ser lista")
    require(len(records) <= limits.max_selection_records,
            "selection_records excede el límite")
    record_ids = set()
    for record in records:
        keys(record, {"id", "position_ref", "function_digests", "knowledge_id", "decision",
                      "approval_scope", "reviewer_type", "reviewer_id", "reason", "decided_at", "catalog_version",
                      "fictitious"},
             context="selección")
        require(record["fictitious"] is (dataset_type == "fixture"),
                "marca ficticia de selección inválida")
        identifier(record["id"], SELECTION_ID, "selección")
        require(record["id"] not in record_ids, "identificador duplicado de selección")
        record_ids.add(record["id"])
        for field in ("position_ref", "reviewer_id"):
            text(record[field], field, limits.max_label_length)
        text(record["reason"], "reason", limits.max_reason_length)
        digests = record["function_digests"]
        require(isinstance(digests, list) and bool(digests), "function_digests inválido")
        require(len(digests) <= limits.max_references,
                "function_digests excede el límite")
        seen_digests = set()
        for digest in digests:
            require(isinstance(digest, str) and SHA256.fullmatch(digest) is not None, "SHA-256 inválido")
            require(digest not in seen_digests, "SHA-256 duplicado")
            seen_digests.add(digest)
        identifier(record["knowledge_id"], KNOWLEDGE_ID, "knowledge_id")
        require(record["knowledge_id"] in by_knowledge, "referencia inexistente de conocimiento")
        require(record["decision"] in ("selected", "discarded"), "decisión inválida")
        require(record["approval_scope"] == "position", "alcance de aprobación inválido")
        require(record["reviewer_type"] == "human", "una IA no puede decidir por puesto")
        if record["decision"] == "selected":
            require(by_knowledge[record["knowledge_id"]]["status"] == "approved",
                    "no se puede seleccionar conocimiento no aprobado")
        require(record["catalog_version"] == catalog["catalog_version"],
                "versión del catálogo no coincide")
        timestamp(record["decided_at"], "decided_at")
    return catalog


def load_and_validate(path, context="fixture", limits=DEFAULT_LIMITS):
    """Carga un JSON acotado y valida; retorna el diccionario sin modificarlo."""
    require(isinstance(limits, CatalogLimits), "limits debe ser CatalogLimits")
    catalog_path = Path(path)
    require(catalog_path.stat().st_size <= limits.max_json_bytes,
            "archivo JSON excede el límite")
    with catalog_path.open("rb") as stream:
        raw = stream.read(limits.max_json_bytes + 1)
    require(len(raw) <= limits.max_json_bytes, "archivo JSON excede el límite")
    catalog = json.loads(raw.decode("utf-8-sig"))
    return validate_catalog(catalog, context=context, limits=limits)
