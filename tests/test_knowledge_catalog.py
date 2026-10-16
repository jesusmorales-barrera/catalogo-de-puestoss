from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from editor_catalogo.knowledge_catalog import (  # noqa: E402
    CatalogLimits, CatalogValidationError, load_and_validate, validate_catalog,
)

CATALOG_PATH = PROJECT_ROOT / "editor_catalogo" / "catalogo_conocimientos_ficticio.json"
SCHEMA_PATH = PROJECT_ROOT / "editor_catalogo" / "catalogo_conocimientos.schema.json"


def fixture() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


class KnowledgeCatalogTests(unittest.TestCase):
    def assert_invalid(self, catalog, expected):
        with self.assertRaises(CatalogValidationError) as caught:
            validate_catalog(catalog)
        self.assertIn(expected, str(caught.exception))

    def test_fictitious_catalog_is_valid(self):
        catalog = load_and_validate(CATALOG_PATH)
        self.assertEqual(catalog["catalog_version"], "0.1.0")
        self.assertEqual(len(catalog["knowledge"]), 4)

    def test_rejects_duplicate_knowledge_id(self):
        catalog = fixture()
        catalog["knowledge"][1]["id"] = catalog["knowledge"][0]["id"]
        self.assert_invalid(catalog, "identificador duplicado")

    def test_rejects_invalid_category_and_status(self):
        invalid_category = fixture()
        invalid_category["knowledge"][0]["category"] = "habilidades"
        self.assert_invalid(invalid_category, "categoría inválida")

        invalid_status = fixture()
        invalid_status["knowledge"][0]["status"] = "automaticamente_aprobado"
        self.assert_invalid(invalid_status, "estado inválido")

    def test_rejects_duplicate_equivalent_terms(self):
        catalog = fixture()
        catalog["knowledge"][1]["aliases"].append(" CLASIFICACIÓN Y ORGANIZACIÓN DOCUMENTAL ")
        self.assert_invalid(catalog, "duplica")

        same_item = fixture()
        same_item["knowledge"][0]["aliases"].append(
            " CLASIFICACIÓN Y ORGANIZACIÓN DOCUMENTAL "
        )
        self.assert_invalid(same_item, "duplica")

    def test_normative_approval_requires_existing_active_source(self):
        no_source = fixture()
        no_source["knowledge"][2]["source_ids"] = []
        self.assert_invalid(no_source, "normativo aprobado requiere fuente")
        missing = fixture()
        missing["knowledge"][2]["source_ids"] = ["FUE-FIC-999999"]
        self.assert_invalid(missing, "referencia inexistente")
        inactive = fixture()
        inactive["sources"][0]["status"] = "inactive"
        self.assert_invalid(inactive, "no está activa")

    def test_ai_cannot_grant_global_approval(self):
        catalog = fixture()
        item = catalog["knowledge"][3]
        item["status"] = "approved"
        item["global_approval"] = {"scope": "global", "reviewer_type": "ai",
            "reviewer_id": "MODELO-FICTICIO", "approved_at": "2026-10-14T13:00:00-06:00",
            "fictitious": True}
        self.assert_invalid(catalog, "una IA no puede aprobar")

    def test_fixture_is_rejected_in_production_context(self):
        catalog = fixture()
        with self.assertRaisesRegex(CatalogValidationError, "no permitido en contexto production"):
            validate_catalog(catalog, context="production")

    def test_requires_dataset_type(self):
        catalog = fixture()
        del catalog["dataset_type"]
        self.assert_invalid(catalog, "faltan campos")

    def test_requires_fixture_markers(self):
        source = fixture()
        source["sources"][0]["fictitious"] = False
        self.assert_invalid(source, "marca ficticia de fuente")

        knowledge = fixture()
        knowledge["knowledge"][0]["fictitious"] = False
        self.assert_invalid(knowledge, "marca ficticia de conocimiento")

        approval = fixture()
        approval["knowledge"][0]["global_approval"]["fictitious"] = False
        self.assert_invalid(approval, "marca ficticia de aprobación")

        decision = fixture()
        decision["selection_records"][0]["fictitious"] = False
        self.assert_invalid(decision, "marca ficticia de selección")

    def test_rejects_collection_limits(self):
        sources = fixture()
        extra_source = copy.deepcopy(sources["sources"][0])
        extra_source["id"] = "FUE-FIC-000002"
        sources["sources"].append(extra_source)
        with self.assertRaisesRegex(CatalogValidationError, "sources excede"):
            validate_catalog(sources, limits=CatalogLimits(max_sources=1))

        knowledge = fixture()
        with self.assertRaisesRegex(CatalogValidationError, "knowledge excede"):
            validate_catalog(knowledge, limits=CatalogLimits(max_knowledge=3))

        decisions = fixture()
        with self.assertRaisesRegex(CatalogValidationError, "selection_records excede"):
            validate_catalog(decisions, limits=CatalogLimits(max_selection_records=1))

    def test_rejects_alias_reference_and_text_limits(self):
        aliases = fixture()
        aliases["knowledge"][0]["aliases"].append("Alias ficticio adicional")
        with self.assertRaisesRegex(CatalogValidationError, "aliases: excede"):
            validate_catalog(aliases, limits=CatalogLimits(max_aliases=1))

        references = fixture()
        with self.assertRaisesRegex(CatalogValidationError, "domains: excede"):
            validate_catalog(references, limits=CatalogLimits(max_references=1))

        label = fixture()
        label["knowledge"][0]["preferred_label"] = "x" * 201
        with self.assertRaisesRegex(CatalogValidationError, "etiqueta preferida: excede"):
            validate_catalog(label)

        definition = fixture()
        definition["knowledge"][0]["definition"] = "x" * 2001
        with self.assertRaisesRegex(CatalogValidationError, "definición: excede"):
            validate_catalog(definition)

        reason = fixture()
        reason["selection_records"][0]["reason"] = "x" * 2001
        with self.assertRaisesRegex(CatalogValidationError, "reason: excede"):
            validate_catalog(reason)

    def test_rejects_oversized_file_before_decoding(self):
        with self.assertRaisesRegex(CatalogValidationError, "archivo JSON excede"):
            load_and_validate(CATALOG_PATH, limits=CatalogLimits(max_json_bytes=1))

    def test_rfc3339_accepts_z_and_valid_offsets(self):
        for value in (
            "2026-10-15T12:30:00Z",
            "2026-10-15T12:30:00-06:00",
            "2026-10-15T12:30:00+14:00",
        ):
            with self.subTest(value=value):
                catalog = fixture()
                catalog["generated_at"] = value
                validate_catalog(catalog)

    def test_rfc3339_rejects_invalid_temporal_values(self):
        cases = (
            ("2026-02-30T12:30:00Z", "fecha RFC3339 inválida"),
            ("2026-10-15", "fecha RFC3339 inválida"),
            ("2026-10-15T12:30:00", "fecha RFC3339 inválida"),
            ("2026-10-15T12:30:00+14:01", "fecha RFC3339 inválida"),
            ("2026-10-15T12:30:00-00:00", "-00:00"),
            ("2026-12-31T23:59:60Z", "fecha RFC3339 inválida"),
        )
        for value, message in cases:
            with self.subTest(value=value):
                catalog = fixture()
                catalog["generated_at"] = value
                self.assert_invalid(catalog, message)

    def test_rejects_duplicate_source_and_selection_ids(self):
        duplicate_source = fixture()
        duplicate_source["sources"].append(copy.deepcopy(duplicate_source["sources"][0]))
        self.assert_invalid(duplicate_source, "identificador duplicado de fuente")

        duplicate_selection = fixture()
        duplicate_selection["selection_records"].append(
            copy.deepcopy(duplicate_selection["selection_records"][0])
        )
        self.assert_invalid(duplicate_selection, "identificador duplicado de selección")

    def test_rejects_malformed_identifiers(self):
        malformed_source = fixture()
        malformed_source["sources"][0]["id"] = "FUENTE-1"
        self.assert_invalid(malformed_source, "fuente: identificador inválido")

        malformed_knowledge = fixture()
        malformed_knowledge["knowledge"][0]["id"] = "CON-X"
        self.assert_invalid(malformed_knowledge, "conocimiento: identificador inválido")

        malformed_selection = fixture()
        malformed_selection["selection_records"][0]["id"] = "SEL-X"
        self.assert_invalid(malformed_selection, "selección: identificador inválido")

    def test_rejects_missing_and_additional_fields(self):
        missing = fixture()
        del missing["knowledge"][0]["definition"]
        self.assert_invalid(missing, "faltan campos")

        additional = fixture()
        additional["selection_records"][0]["campo_inesperado"] = True
        self.assert_invalid(additional, "campos adicionales")

    def test_rejects_invalid_global_approvals(self):
        missing_field = fixture()
        del missing_field["knowledge"][0]["global_approval"]["approved_at"]
        self.assert_invalid(missing_field, "faltan campos")

        wrong_scope = fixture()
        wrong_scope["knowledge"][0]["global_approval"]["scope"] = "position"
        self.assert_invalid(wrong_scope, "alcance global inválido")

        invalid_date = fixture()
        invalid_date["knowledge"][0]["global_approval"]["approved_at"] = "2026-02-30T00:00:00Z"
        self.assert_invalid(invalid_date, "fecha RFC3339 inválida")

        pending_with_approval = fixture()
        pending_with_approval["knowledge"][3]["global_approval"] = copy.deepcopy(
            pending_with_approval["knowledge"][0]["global_approval"]
        )
        self.assert_invalid(pending_with_approval, "aprobación global nula")

    def test_rejects_invalid_decisions_and_catalog_versions(self):
        invalid_decision = fixture()
        invalid_decision["selection_records"][0]["decision"] = "automatic"
        self.assert_invalid(invalid_decision, "decisión inválida")

        invalid_scope = fixture()
        invalid_scope["selection_records"][0]["approval_scope"] = "global"
        self.assert_invalid(invalid_scope, "alcance de aprobación inválido")

        invalid_reviewer = fixture()
        invalid_reviewer["selection_records"][0]["reviewer_type"] = "ai"
        self.assert_invalid(invalid_reviewer, "una IA no puede decidir")

        wrong_version = fixture()
        wrong_version["selection_records"][0]["catalog_version"] = "9.9.9"
        self.assert_invalid(wrong_version, "versión del catálogo no coincide")

    def test_schema_declares_lot_one_and_temporal_guards(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertIn("dataset_type", schema["required"])
        self.assertEqual(
            schema["properties"]["dataset_type"]["enum"],
            ["fixture", "production"],
        )
        timestamp_schema = schema["$defs"]["rfc3339Timestamp"]
        self.assertEqual(timestamp_schema["format"], "date-time")
        self.assertIn("-00:00", timestamp_schema["pattern"])
        self.assertEqual(schema["properties"]["knowledge"]["maxItems"], 5000)
        self.assertEqual(schema["$defs"]["knowledge"]["properties"]["aliases"]["maxItems"], 50)

    def test_position_decision_is_separate_from_global_approval(self):
        catalog = fixture()
        self.assertEqual(catalog["knowledge"][3]["status"], "pending_review")
        self.assertIsNone(catalog["knowledge"][3]["global_approval"])
        self.assertEqual(catalog["selection_records"][1]["decision"], "discarded")
        validate_catalog(catalog)

    def test_rejects_selection_of_non_approved_knowledge(self):
        catalog = fixture()
        catalog["selection_records"][1]["decision"] = "selected"
        self.assert_invalid(catalog, "no se puede seleccionar")

    def test_rejects_broken_reference_and_digest(self):
        broken_reference = fixture()
        broken_reference["selection_records"][0]["knowledge_id"] = "CON-999999"
        self.assert_invalid(broken_reference, "referencia inexistente")

        invalid_digest = fixture()
        invalid_digest["selection_records"][0]["function_digests"] = ["no-es-sha256"]
        self.assert_invalid(invalid_digest, "SHA-256 inválido")

    def test_allows_empty_categories_in_a_position_selection(self):
        catalog = fixture()
        catalog["selection_records"] = [catalog["selection_records"][0]]
        validate_catalog(catalog)
        self.assertFalse(any(item["category"] == "normativos" and any(
            record["decision"] == "selected" and record["knowledge_id"] == item["id"]
            for record in catalog["selection_records"]) for item in catalog["knowledge"]))

    def test_validation_does_not_mutate_catalog(self):
        catalog = fixture()
        original = copy.deepcopy(catalog)
        validate_catalog(catalog)
        self.assertEqual(catalog, original)


if __name__ == "__main__":
    unittest.main()
