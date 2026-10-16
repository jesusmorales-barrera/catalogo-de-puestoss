"""Integración 2D-2C.1: propuesta y referencias independientes.

Las referencias no se entregan al proveedor de IA ni constituyen aprobación.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .knowledge_generator import KnowledgeGenerator, KnowledgeProposal
from .knowledge_retriever import (
    DEFAULT_CONFIG,
    RetrievalConfig,
    RetrievalResult,
    retrieve_knowledge,
)


@dataclass(frozen=True)
class IntegratedKnowledgeResult:
    """Une los resultados sin atribuir las referencias a la generación."""

    proposal: KnowledgeProposal
    references: RetrievalResult
    references_used_by_generator: bool = False
    human_selected: bool = False

    def __post_init__(self) -> None:
        if self.references_used_by_generator or self.human_selected:
            raise ValueError("2D-2C.1 no permite uso de referencias ni selección automática")


class KnowledgeIntegration:
    """Orquesta recuperación y generación preservando los contratos originales."""

    def __init__(
        self,
        generator: KnowledgeGenerator,
        catalog_path: str | Path,
        *,
        context: str = "fixture",
        retrieval_config: RetrievalConfig = DEFAULT_CONFIG,
        max_candidates: int = 10,
    ) -> None:
        if not isinstance(generator, KnowledgeGenerator):
            raise TypeError("generator debe ser KnowledgeGenerator")
        if not isinstance(retrieval_config, RetrievalConfig):
            raise TypeError("retrieval_config debe ser RetrievalConfig")
        if type(max_candidates) is not int or not 1 <= max_candidates <= retrieval_config.max_candidates:
            raise ValueError("max_candidates fuera de rango")
        if context not in ("fixture", "production"):
            raise ValueError("context debe ser fixture o production")
        self._generator = generator
        self._catalog_path = Path(catalog_path)
        self._context = context
        self._retrieval_config = retrieval_config
        self._max_candidates = max_candidates

    def generate_with_references(
        self,
        position_id: str,
        position_name: str,
        functions: Sequence[str],
    ) -> IntegratedKnowledgeResult:
        # Una copia inmutable para ambos componentes; nunca se alteran las funciones originales.
        if isinstance(functions, (str, bytes)):
            raise TypeError("functions debe ser una secuencia de textos")
        original_functions = tuple(functions)

        # Validar y recuperar antes de consultar al proveedor: si falla, no hay generación.
        references = retrieve_knowledge(
            catalog_path=self._catalog_path,
            position_id=position_id,
            position_name=position_name,
            functions=original_functions,
            max_candidates=self._max_candidates,
            context=self._context,
            config=self._retrieval_config,
        )
        proposal = self._generator.generate(
            position_id=position_id,
            position_name=position_name,
            functions=original_functions,
        )
        return IntegratedKnowledgeResult(proposal=proposal, references=references)
