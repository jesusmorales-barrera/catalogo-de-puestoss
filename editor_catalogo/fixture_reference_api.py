"""Consulta 2D-2C.2A, solo lectura y exclusivamente con catálogo ficticio.

No importa CatalogStore, no usa puestos institucionales, ni llama al generador.
"""
from __future__ import annotations

import re
from pathlib import Path

from .knowledge_retriever import retrieve_knowledge

_FICTITIOUS_ID = re.compile(r"PUESTO-FICTICIO-[A-Za-z0-9_-]{1,64}\Z")


def query_fixture_references(*, catalog_path: str | Path, position_id: str, payload: dict) -> dict:
    """Valida estrictamente y entrega referencias; no ejecuta escrituras."""
    if not isinstance(position_id, str) or not _FICTITIOUS_ID.fullmatch(position_id):
        raise ValueError("Solo se permiten identificadores de puestos ficticios.")
    if not isinstance(payload, dict) or set(payload) != {"puesto", "funciones"}:
        raise ValueError("La solicitud debe contener solo puesto y funciones ficticias.")
    name, functions = payload["puesto"], payload["funciones"]
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValueError("puesto ficticio inválido.")
    if not isinstance(functions, list) or not 1 <= len(functions) <= 50:
        raise ValueError("funciones debe contener entre 1 y 50 textos.")
    if any(not isinstance(value, str) or not value.strip() or len(value) > 2_000 for value in functions):
        raise ValueError("Cada función debe ser un texto no vacío de hasta 2000 caracteres.")
    result = retrieve_knowledge(
        catalog_path=catalog_path,
        position_id=position_id,
        position_name=name,
        functions=tuple(functions),
        context="fixture",
    )
    return {
        "position_id": result.position_id,
        "catalog_version": result.catalog_version,
        "references": [candidate.as_dict() for candidate in result.candidates],
        "references_used_by_generator": False,
        "human_selected": False,
    }
