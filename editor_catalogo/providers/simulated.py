"""Proveedor determinista para pruebas sin red, claves ni consumo de tokens."""

from __future__ import annotations

from threading import Lock

from .base import ProviderResult


DEFAULT_RESPONSE = ProviderResult(
    tecnicos=(
        "Manejo de sistemas de registro y control documental",
        "Análisis básico de información operativa",
    ),
    administrativos=(
        "Planeación, seguimiento y elaboración de informes",
        "Organización de expedientes y coordinación de actividades",
    ),
    normativos=(
        "Normativa institucional aplicable",
        "Protección de datos y transparencia",
    ),
)


class SimulatedProvider:
    """Devuelve una respuesta configurada y registra cada invocación."""

    def __init__(self, response: object = DEFAULT_RESPONSE, error: Exception | None = None):
        self.response = response
        self.error = error
        self.call_count = 0
        self.received_requests: list[dict[str, object]] = []
        self._lock = Lock()

    def generate_knowledge(
        self,
        *,
        position_name: str,
        functions: tuple[str, ...],
        max_words: int,
    ) -> object:
        with self._lock:
            self.call_count += 1
            self.received_requests.append(
                {
                    "position_name": position_name,
                    "functions": tuple(functions),
                    "max_words": max_words,
                }
            )
        if self.error is not None:
            raise self.error
        return self.response
