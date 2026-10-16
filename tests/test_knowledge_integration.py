"""Pruebas aisladas de 2D-2C.1 con fixture; ningún servicio externo."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from editor_catalogo.knowledge_catalog import CatalogValidationError
from editor_catalogo.knowledge_generator import KnowledgeGenerator
from editor_catalogo.knowledge_integration import KnowledgeIntegration
from editor_catalogo.providers.base import ProviderResult

CATALOG = ROOT / "editor_catalogo" / "catalogo_conocimientos_ficticio.json"


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.provider = Mock()
        self.provider.generate_knowledge.return_value = ProviderResult(
            tecnicos=("Clasificación documental",),
            administrativos=(),
            normativos=(),
        )
        self.generator = KnowledgeGenerator(self.provider, max_words=80)
        self.integration = KnowledgeIntegration(self.generator, CATALOG)
        self.functions = [
            "Clasificar y organizar expedientes meteorológicos imaginarios.",
            "Controlar préstamos y devolución de expedientes simulados.",
        ]

    def test_combines_without_passing_references_to_provider(self):
        before = list(self.functions)
        result = self.integration.generate_with_references(
            "PUESTO-FICTICIO-ARCHIVO-01",
            "Coordinador de Archivo Meteorológico Ficticio",
            self.functions,
        )
        self.assertEqual(self.functions, before)
        self.assertEqual(self.provider.generate_knowledge.call_count, 1)
        kwargs = self.provider.generate_knowledge.call_args.kwargs
        self.assertEqual(set(kwargs), {"position_name", "functions", "max_words"})
        self.assertEqual(kwargs["functions"], tuple(self.functions))
        self.assertFalse(result.references_used_by_generator)
        self.assertFalse(result.human_selected)
        self.assertEqual(result.references.position_id, "PUESTO-FICTICIO-ARCHIVO-01")
        self.assertTrue(result.references.candidates)
        self.assertTrue(all(not candidate.human_selected for candidate in result.references.candidates))

    def test_invalid_production_context_prevents_provider_call(self):
        integration = KnowledgeIntegration(self.generator, CATALOG, context="production")
        with self.assertRaises(CatalogValidationError):
            integration.generate_with_references(
                "PUESTO-FICTICIO-ARCHIVO-01", "Archivo ficticio", self.functions
            )
        self.provider.generate_knowledge.assert_not_called()

    def test_invalid_functions_do_not_call_provider(self):
        with self.assertRaises((TypeError, ValueError)):
            self.integration.generate_with_references(
                "PUESTO-FICTICIO-ARCHIVO-01", "Archivo ficticio", "texto suelto"
            )
        self.provider.generate_knowledge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
