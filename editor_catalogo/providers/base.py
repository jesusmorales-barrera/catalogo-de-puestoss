"""Contratos neutrales para proveedores del generador de conocimientos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderResult:
    """Respuesta estructurada devuelta por cualquier proveedor de IA."""

    tecnicos: tuple[str, ...]
    administrativos: tuple[str, ...]
    normativos: tuple[str, ...]


@runtime_checkable
class AIProvider(Protocol):
    """Interfaz mínima e intercambiable para generar conocimientos."""

    def generate_knowledge(
        self,
        *,
        position_name: str,
        functions: tuple[str, ...],
        max_words: int,
    ) -> ProviderResult:
        """Genera una propuesta sin escribir en el catálogo."""
