from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from editor_catalogo.knowledge_catalog import CatalogValidationError  # noqa: E402
from editor_catalogo.knowledge_retriever import (  # noqa: E402
    RetrievalConfig, RetrievalError, retrieve_knowledge,
)

CATALOG_PATH = PROJECT_ROOT / "editor_catalogo" / "catalogo_conocimientos_ficticio.json"


def catalog_fixture():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


class KnowledgeRetrieverTests(unittest.TestCase):
    def retrieve(self, **changes):
        arguments = {
            "catalog_path": CATALOG_PATH,
            "position_id": "PUESTO-FICTICIO-ARCHIVO-02",
            "position_name": "Coordinador de Archivo Meteorológico Ficticio",
            "functions": [
                "Clasificar expedientes de estaciones meteorológicas imaginarias.",
                "Controlar préstamos y devolución de expedientes simulados.",
                "Aplicar criterios de resguardo documental meteorológico ficticio.",
            ],
        }
        arguments.update(changes)
        return retrieve_knowledge(**arguments)

    def test_three_fictitious_positions_and_empty_category(self):
        cases = (
            ("PUESTO-FICTICIO-ARCHIVO-02", "Coordinador de Archivo Meteorológico Ficticio", ["Clasificar y organizar expedientes meteorológicos imaginarios."], "CON-000001"),
            ("PUESTO-FICTICIO-PRESTAMOS-01", "Encargado de Circulación Documental Ficticia", ["Registrar préstamos y devolución de expedientes simulados."], "CON-000002"),
            ("PUESTO-FICTICIO-RESGUARDO-01", "Responsable de Resguardo Meteorológico Ficticio", ["Aplicar criterios de resguardo documental meteorológico imaginario."], "CON-000003"),
        )
        for position_id, name, functions, expected in cases:
            with self.subTest(position_id=position_id):
                result = self.retrieve(position_id=position_id, position_name=name, functions=functions)
                self.assertIn(expected, [item.knowledge_id for item in result.candidates])
        empty = self.retrieve(
            position_name="Auxiliar de Reportes Ficticio",
            categories=["normativos"],
            functions=["Preparar reportes mensuales."],
        )
        self.assertEqual(empty.candidates, ())

    def test_acceptance_cases_remove_generic_document_false_positives(self):
        archive = self.retrieve(
            position_name="Coordinador de Archivo Meteorológico Ficticio",
            functions=[
                "Clasificar y organizar expedientes de estaciones meteorológicas imaginarias.",
                "Preparar reportes mensuales de movimientos documentales simulados.",
                "Controlar préstamos y devolución de expedientes ficticios.",
            ],
        )
        self.assertEqual(
            [item.knowledge_id for item in archive.candidates],
            ["CON-000001", "CON-000002"],
        )

        circulation = self.retrieve(
            position_id="PUESTO-FICTICIO-PRESTAMOS-01",
            position_name="Encargado de Circulación Documental Ficticia",
            functions=[
                "Registrar préstamos de carpetas simuladas.",
                "Dar seguimiento a la devolución de expedientes imaginarios.",
                "Elaborar informes ficticios de documentación en circulación.",
            ],
        )
        self.assertEqual(
            [item.knowledge_id for item in circulation.candidates],
            ["CON-000002"],
        )

        calibration = self.retrieve(
            position_id="PUESTO-FICTICIO-CALIBRACION-01",
            position_name="Técnico de Calibración Acústica Ficticia",
            functions=[
                "Calibrar sensores acústicos imaginarios.",
                "Documentar mediciones de frecuencia simuladas.",
                "Verificar el funcionamiento de equipos ficticios de laboratorio.",
            ],
        )
        self.assertEqual(calibration.candidates, ())

    def test_each_root_scores_once_and_functions_outrank_name_only_evidence(self):
        result = self.retrieve()
        technical = next(item for item in result.candidates if item.knowledge_id == "CON-000001")
        roots = {
            root
            for evidence in technical.evidence
            for root in evidence.matched_roots
        }
        self.assertNotIn("docume", roots)
        self.assertEqual(technical.score, 11)
        self.assertTrue(any(item.matched_in == "functions" for item in technical.evidence))
        self.assertTrue(any(item.matched_in == "position_name" for item in technical.evidence))

    def test_only_globally_human_approved_and_no_duplicates(self):
        result = self.retrieve()
        ids = [candidate.knowledge_id for candidate in result.candidates]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("CON-000004", ids)
        self.assertTrue(ids)
        for candidate in result.candidates:
            self.assertEqual(candidate.result_type, "retrieved_candidate")
            self.assertFalse(candidate.human_selected)

    def test_rejected_and_deprecated_are_excluded(self):
        for status in ("rejected", "deprecated"):
            with self.subTest(status=status):
                catalog = catalog_fixture()
                catalog["knowledge"][0]["status"] = status
                catalog["knowledge"][0]["global_approval"] = None
                catalog["selection_records"][0]["decision"] = "discarded"
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "catalog.json"
                    path.write_text(json.dumps(catalog), encoding="utf-8")
                    result = self.retrieve(catalog_path=path)
                self.assertNotIn("CON-000001", [item.knowledge_id for item in result.candidates])

    def test_evidence_sources_priority_and_deterministic_order(self):
        first = self.retrieve()
        second = self.retrieve()
        self.assertEqual(first, second)
        expected = sorted(first.candidates, key=lambda item: (
            -item.score, {"tecnicos": 0, "administrativos": 1, "normativos": 2}[item.category], item.knowledge_id,
        ))
        self.assertEqual(list(first.candidates), expected)
        normative = next(item for item in first.candidates if item.category == "normativos")
        self.assertEqual(normative.source_ids, ("FUE-FIC-000001",))
        self.assertTrue(normative.evidence)
        self.assertTrue(all(evidence.matched_roots for evidence in normative.evidence))
        self.assertEqual(first.catalog_version, "0.1.0")

    def test_candidate_and_context_limits(self):
        self.assertEqual(len(self.retrieve(max_candidates=1).candidates), 1)
        self.assertEqual(self.retrieve(config=RetrievalConfig(max_context_chars=1)).candidates, ())
        with self.assertRaisesRegex(RetrievalError, "max_candidates"):
            self.retrieve(max_candidates=21)
        with self.assertRaisesRegex(RetrievalError, "entrada excede"):
            self.retrieve(functions=["x" * 20], config=RetrievalConfig(max_input_chars=10))

    def test_fixture_is_rejected_in_production_context(self):
        with self.assertRaisesRegex(CatalogValidationError, "no permitido en contexto production"):
            self.retrieve(context="production")

    def test_categories_and_generic_terms_do_not_create_false_matches(self):
        technical = self.retrieve(categories=["tecnicos"])
        self.assertTrue(technical.candidates)
        self.assertTrue(all(item.category == "tecnicos" for item in technical.candidates))
        generic = self.retrieve(position_name="Puesto Ficticio", functions=["Realizar actividades de control interno."])
        self.assertEqual(generic.candidates, ())

    def test_does_not_mutate_inputs_or_catalog_and_uses_no_external_services(self):
        functions = ["Clasificar expedientes meteorológicos imaginarios."]
        categories = ["tecnicos", "normativos"]
        original_functions = copy.deepcopy(functions)
        original_categories = copy.deepcopy(categories)
        before = CATALOG_PATH.read_bytes()
        with patch("socket.socket", side_effect=AssertionError("red no permitida")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("red no permitida")):
            result = self.retrieve(functions=functions, categories=categories)
        self.assertEqual(functions, original_functions)
        self.assertEqual(categories, original_categories)
        self.assertEqual(CATALOG_PATH.read_bytes(), before)
        self.assertTrue(result.candidates)


if __name__ == "__main__":
    unittest.main()
