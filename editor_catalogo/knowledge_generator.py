"""Núcleo independiente para generar propuestas de conocimientos.

Este módulo no conoce rutas HTTP ni archivos del catálogo y no realiza escrituras.
Las funciones del puesto se consideran datos no confiables y solo se entregan al
proveedor después de validarlas, normalizarlas y deduplicarlas en una copia.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Sequence

from .providers.base import AIProvider, ProviderResult


EXPECTED_CATEGORIES = ("tecnicos", "administrativos", "normativos")
_LEADING_NUMBERING = re.compile(
    r"^\s*(?:(?:\d+|[ivxlcdm]+)[.)]\s+)", re.IGNORECASE
)
_WHITESPACE = re.compile(r"\s+")
_WORD = re.compile(r"[^\W_]+(?:[-'’][^\W_]+)*", re.UNICODE)
_HTML_TAG = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class KnowledgeGenerationError(Exception):
    """Error base del núcleo de generación."""


class InvalidFunctionsError(KnowledgeGenerationError, ValueError):
    """Las funciones recibidas están vacías o no tienen la forma esperada."""


class InvalidProviderResponseError(KnowledgeGenerationError, ValueError):
    """El proveedor devolvió una estructura o contenido no permitido."""


class WordLimitExceededError(InvalidProviderResponseError):
    """La propuesta supera el máximo de palabras, sin truncamiento automático."""


@dataclass(frozen=True)
class KnowledgeRequest:
    position_id: str
    position_name: str
    functions: tuple[str, ...]


@dataclass(frozen=True)
class KnowledgeProposal:
    tecnicos: tuple[str, ...]
    administrativos: tuple[str, ...]
    normativos: tuple[str, ...]
    rendered_text: str
    word_count: int
    source_digest: str


def _clean_text(value: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip()


def _comparison_key(value: str) -> str:
    without_numbering = _LEADING_NUMBERING.sub("", value)
    return _clean_text(without_numbering).casefold()


def normalize_functions(
    functions: Sequence[str],
    *,
    max_functions: int = 50,
    max_characters: int = 12_000,
) -> tuple[str, ...]:
    """Valida y deduplica una copia, conservando orden y primera redacción."""

    if isinstance(functions, (str, bytes)) or not isinstance(functions, Sequence):
        raise InvalidFunctionsError("Las funciones deben ser una secuencia de textos.")
    if not functions:
        raise InvalidFunctionsError("Se requiere al menos una función.")
    if len(functions) > max_functions:
        raise InvalidFunctionsError(
            f"No se permiten más de {max_functions} funciones por solicitud."
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for item in functions:
        if not isinstance(item, str):
            raise InvalidFunctionsError("Cada función debe ser texto.")
        clean = _clean_text(item)
        if not clean:
            raise InvalidFunctionsError("Las funciones no pueden estar vacías.")
        if _CONTROL_CHARACTER.search(clean):
            raise InvalidFunctionsError("Las funciones contienen caracteres de control.")
        key = _comparison_key(clean)
        if not key:
            raise InvalidFunctionsError("Una función no contiene texto útil.")
        if key not in seen:
            seen.add(key)
            normalized.append(clean)

    if sum(len(item) for item in normalized) > max_characters:
        raise InvalidFunctionsError(
            f"Las funciones superan el máximo de {max_characters} caracteres."
        )
    return tuple(normalized)


def count_words(text: str) -> int:
    """Cuenta palabras Unicode; los encabezados se excluyen por separado."""

    return len(_WORD.findall(text))


def _validate_items(category: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise InvalidProviderResponseError(
            f"La categoría '{category}' debe ser una lista de textos."
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise InvalidProviderResponseError(
                f"La categoría '{category}' contiene un elemento no textual."
            )
        clean = _clean_text(item)
        if not clean:
            raise InvalidProviderResponseError(
                f"La categoría '{category}' contiene un elemento vacío."
            )
        if _HTML_TAG.search(clean) or _CONTROL_CHARACTER.search(clean):
            raise InvalidProviderResponseError(
                f"La categoría '{category}' contiene contenido no permitido."
            )
        items.append(clean)
    return tuple(items)


def validate_provider_response(response: object, *, max_words: int) -> ProviderResult:
    """Valida forma, contenido y límite sin recortar la respuesta."""

    if isinstance(response, ProviderResult):
        raw = {
            "tecnicos": response.tecnicos,
            "administrativos": response.administrativos,
            "normativos": response.normativos,
        }
    elif isinstance(response, dict):
        raw = response
    else:
        raise InvalidProviderResponseError("La respuesta debe ser un objeto estructurado.")

    if set(raw) != set(EXPECTED_CATEGORIES):
        raise InvalidProviderResponseError(
            "La respuesta debe contener exactamente las categorías: "
            + ", ".join(EXPECTED_CATEGORIES)
            + "."
        )

    validated = ProviderResult(
        tecnicos=_validate_items("tecnicos", raw["tecnicos"]),
        administrativos=_validate_items("administrativos", raw["administrativos"]),
        normativos=_validate_items("normativos", raw["normativos"]),
    )
    content = " ".join(
        (*validated.tecnicos, *validated.administrativos, *validated.normativos)
    )
    words = count_words(content)
    if words == 0:
        raise InvalidProviderResponseError("La propuesta no contiene palabras.")
    if words > max_words:
        raise WordLimitExceededError(
            f"La propuesta contiene {words} palabras; el máximo es {max_words}."
        )
    return validated


def _render(result: ProviderResult) -> str:
    sections = (
        ("Técnicos", result.tecnicos),
        ("Administrativos", result.administrativos),
        ("Normativos", result.normativos),
    )
    return "\n".join(
        f"{heading}: {'; '.join(items)}" for heading, items in sections if items
    )


def _digest(request: KnowledgeRequest) -> str:
    canonical = json.dumps(
        {
            "position_id": request.position_id,
            "position_name": request.position_name,
            "functions": request.functions,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class KnowledgeGenerator:
    """Orquesta exactamente una consulta por llamada a ``generate``."""

    def __init__(
        self,
        provider: AIProvider,
        *,
        max_words: int = 200,
        max_functions: int = 50,
        max_characters: int = 12_000,
    ):
        if max_words < 1:
            raise ValueError("max_words debe ser positivo.")
        self.provider = provider
        self.max_words = max_words
        self.max_functions = max_functions
        self.max_characters = max_characters

    def generate(
        self,
        position_id: str,
        position_name: str,
        functions: Sequence[str],
    ) -> KnowledgeProposal:
        clean_id = _clean_text(position_id) if isinstance(position_id, str) else ""
        clean_name = _clean_text(position_name) if isinstance(position_name, str) else ""
        if not clean_id:
            raise ValueError("position_id es obligatorio.")
        if not clean_name:
            raise ValueError("position_name es obligatorio.")

        normalized = normalize_functions(
            functions,
            max_functions=self.max_functions,
            max_characters=self.max_characters,
        )
        request = KnowledgeRequest(clean_id, clean_name, normalized)

        # Deliberadamente no hay reintentos: una generación equivale a una llamada.
        response = self.provider.generate_knowledge(
            position_name=request.position_name,
            functions=request.functions,
            max_words=self.max_words,
        )
        result = validate_provider_response(response, max_words=self.max_words)
        content = " ".join(
            (*result.tecnicos, *result.administrativos, *result.normativos)
        )
        return KnowledgeProposal(
            tecnicos=result.tecnicos,
            administrativos=result.administrativos,
            normativos=result.normativos,
            rendered_text=_render(result),
            word_count=count_words(content),
            source_digest=_digest(request),
        )
