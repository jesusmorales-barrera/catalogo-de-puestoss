"""Recuperación léxica aislada y explicable sobre el catálogo ficticio validado."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .knowledge_catalog import CATEGORIES, load_and_validate


class RetrievalError(ValueError):
    """La solicitud de recuperación es inválida o excede sus límites."""


GENERIC_TERMS = frozenset({
    "actividad", "actividades", "area", "areas", "control", "datos",
    "ficticia", "ficticias", "ficticio", "ficticios", "funcion", "funciones",
    "gestion", "imaginaria", "imaginarias", "imaginario", "imaginarios",
    "interna", "internas", "interno", "internos", "puesto", "puestos",
    "realizar", "sistema", "sistemas", "trabajo",
})
GENERIC_PREFIXES = ("docum",)

CATEGORY_ORDER = {"tecnicos": 0, "administrativos": 1, "normativos": 2}


@dataclass(frozen=True)
class RetrievalConfig:
    """Parámetros revisables; las puntuaciones solo ordenan candidatos."""

    preferred_label_weight: int = 3
    alias_weight: int = 2
    domain_weight: int = 1
    function_evidence_multiplier: int = 2
    min_function_roots: int = 2
    min_token_length: int = 4
    root_length: int = 6
    max_candidates: int = 20
    max_input_chars: int = 10_000
    max_context_chars: int = 8_000

    def __post_init__(self):
        for name, value in vars(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} debe ser un entero positivo")
        if self.root_length < self.min_token_length:
            raise ValueError("root_length no puede ser menor que min_token_length")


DEFAULT_CONFIG = RetrievalConfig()


@dataclass(frozen=True)
class MatchEvidence:
    field: str
    catalog_term: str
    matched_roots: tuple[str, ...]
    matched_in: str

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "catalog_term": self.catalog_term,
            "matched_roots": list(self.matched_roots),
            "matched_in": self.matched_in,
        }


@dataclass(frozen=True)
class RetrievedCandidate:
    knowledge_id: str
    category: str
    preferred_label: str
    evidence: tuple[MatchEvidence, ...]
    source_ids: tuple[str, ...]
    catalog_version: str
    score: int
    result_type: str = "retrieved_candidate"
    human_selected: bool = False

    def as_dict(self) -> dict:
        return {
            "result_type": self.result_type,
            "human_selected": self.human_selected,
            "knowledge_id": self.knowledge_id,
            "category": self.category,
            "preferred_label": self.preferred_label,
            "evidence": [item.as_dict() for item in self.evidence],
            "source_ids": list(self.source_ids),
            "catalog_version": self.catalog_version,
            "score": self.score,
        }


@dataclass(frozen=True)
class RetrievalResult:
    position_id: str
    catalog_version: str
    candidates: tuple[RetrievedCandidate, ...]
    context_chars: int

    def as_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "catalog_version": self.catalog_version,
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "context_chars": self.context_chars,
        }


def _plain(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _roots(value: str, config: RetrievalConfig) -> frozenset[str]:
    roots = set()
    for token in re.findall(r"[a-z0-9]+", _plain(value)):
        if (
            len(token) < config.min_token_length
            or token in GENERIC_TERMS
            or token.startswith(GENERIC_PREFIXES)
        ):
            continue
        root = token[:config.root_length]
        roots.add(root)
    return frozenset(roots)


def _validated_text(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RetrievalError(f"{name} debe ser texto no vacío")
    return value


def _requested_categories(categories: Iterable[str] | None) -> tuple[str, ...]:
    if categories is None:
        return tuple(sorted(CATEGORIES, key=CATEGORY_ORDER.__getitem__))
    if isinstance(categories, (str, bytes)):
        raise RetrievalError("categories debe ser una colección")
    values = tuple(categories)
    if len(values) != len(set(values)) or any(value not in CATEGORIES for value in values):
        raise RetrievalError("categories contiene valores inválidos o duplicados")
    return values


def _match(
    item: dict,
    function_roots: frozenset[str],
    name_roots: frozenset[str],
    config: RetrievalConfig,
):
    evidence = []
    best_score_by_root = {}
    matched_function_roots = set()
    fields = (
        ("preferred_label", (item["preferred_label"],), config.preferred_label_weight),
        ("alias", item["aliases"], config.alias_weight),
        ("domain", item["domains"], config.domain_weight),
    )
    for field, terms, weight in fields:
        for term in terms:
            term_roots = _roots(term, config)
            for matched_in, input_roots, multiplier in (
                ("functions", function_roots, config.function_evidence_multiplier),
                ("position_name", name_roots, 1),
            ):
                matched = tuple(sorted(input_roots & term_roots))
                if not matched:
                    continue
                evidence.append(MatchEvidence(field, term, matched, matched_in))
                if matched_in == "functions":
                    matched_function_roots.update(matched)
                weighted = weight * multiplier
                for root in matched:
                    best_score_by_root[root] = max(
                        best_score_by_root.get(root, 0), weighted
                    )
    return sum(best_score_by_root.values()), tuple(evidence), matched_function_roots


def retrieve_knowledge(
    catalog_path: str | Path,
    position_id: str,
    position_name: str,
    functions: Iterable[str],
    *,
    categories: Iterable[str] | None = None,
    max_candidates: int = 10,
    context: str = "fixture",
    config: RetrievalConfig = DEFAULT_CONFIG,
) -> RetrievalResult:
    """Recupera candidatos aprobados; no selecciona ni modifica ningún dato."""
    if not isinstance(config, RetrievalConfig):
        raise RetrievalError("config debe ser RetrievalConfig")
    _validated_text(position_id, "position_id")
    _validated_text(position_name, "position_name")
    if isinstance(functions, (str, bytes)):
        raise RetrievalError("functions debe ser una colección")
    function_values = tuple(functions)
    if not function_values:
        raise RetrievalError("functions no puede estar vacío")
    for function in function_values:
        _validated_text(function, "función")
    requested = _requested_categories(categories)
    if type(max_candidates) is not int or not 1 <= max_candidates <= config.max_candidates:
        raise RetrievalError(f"max_candidates debe estar entre 1 y {config.max_candidates}")

    function_text = "\n".join(function_values)
    if len(position_id) + len(position_name) + len(function_text) > config.max_input_chars:
        raise RetrievalError("entrada excede el límite de contexto")
    function_roots = _roots(function_text, config)
    name_roots = _roots(position_name, config)
    catalog = load_and_validate(catalog_path, context=context)
    active_sources = {
        source["id"] for source in catalog["sources"] if source["status"] == "active"
    }

    ranked = []
    seen = set()
    for item in catalog["knowledge"]:
        approval = item["global_approval"]
        if item["status"] != "approved" or not approval:
            continue
        if approval["scope"] != "global" or approval["reviewer_type"] != "human":
            continue
        if item["category"] not in requested or item["id"] in seen:
            continue
        if item["category"] == "normativos" and (
            not item["source_ids"] or any(
                source_id not in active_sources for source_id in item["source_ids"]
            )
        ):
            continue
        score, evidence, matched_function_roots = _match(
            item, function_roots, name_roots, config
        )
        if len(matched_function_roots) < config.min_function_roots:
            continue
        seen.add(item["id"])
        ranked.append(RetrievedCandidate(
            knowledge_id=item["id"],
            category=item["category"],
            preferred_label=item["preferred_label"],
            evidence=evidence,
            source_ids=tuple(item["source_ids"]),
            catalog_version=catalog["catalog_version"],
            score=score,
        ))

    ranked.sort(key=lambda candidate: (
        -candidate.score,
        CATEGORY_ORDER[candidate.category],
        candidate.knowledge_id,
    ))
    selected = []
    context_chars = 0
    for candidate in ranked[:max_candidates]:
        encoded = json.dumps(
            candidate.as_dict(), ensure_ascii=False, separators=(",", ":")
        )
        if context_chars + len(encoded) > config.max_context_chars:
            break
        selected.append(candidate)
        context_chars += len(encoded)
    return RetrievalResult(
        position_id=position_id,
        catalog_version=catalog["catalog_version"],
        candidates=tuple(selected),
        context_chars=context_chars,
    )
