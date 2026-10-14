from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from editor_catalogo.knowledge_generator import (  # noqa: E402
    InvalidFunctionsError,
    InvalidProviderResponseError,
    KnowledgeGenerator,
    WordLimitExceededError,
    normalize_functions,
)
from editor_catalogo.providers.base import ProviderResult  # noqa: E402
from editor_catalogo.providers.simulated import SimulatedProvider  # noqa: E402


FIXTURE = Path(__file__).with_name("fixtures") / "puestos_ficticios.json"


def response_with_word_count(count: int) -> ProviderResult:
    words = tuple(f"palabra{i}" for i in range(count))
    return ProviderResult(tecnicos=words, administrativos=(), normativos=())


class NormalizeFunctionsTests(unittest.TestCase):
    def test_deduplicates_copy_preserving_order_and_first_wording(self):
        original = [
            "I. Primera función institucional.",
            "  primera   función institucional. ",
            "Segunda función.",
        ]
        snapshot = copy.deepcopy(original)

        result = normalize_functions(original)

        self.assertEqual(
            result,
            ("I. Primera función institucional.", "Segunda función."),
        )
        self.assertEqual(original, snapshot)

    def test_rejects_empty_collection_and_empty_item(self):
        with self.assertRaises(InvalidFunctionsError):
            normalize_functions([])
        with self.assertRaises(InvalidFunctionsError):
            normalize_functions(["   "])

    def test_rejects_malformed_collection_and_item(self):
        with self.assertRaises(InvalidFunctionsError):
            normalize_functions("No es una lista")
        with self.assertRaises(InvalidFunctionsError):
            normalize_functions(["Válida", 7])


class GenerationTests(unittest.TestCase):
    def test_calls_provider_once_and_sends_only_deduplicated_copy(self):
        source = ["Función A", " función   a ", "Función B"]
        snapshot = list(source)
        provider = SimulatedProvider()

        proposal = KnowledgeGenerator(provider).generate("1", "Puesto", source)

        self.assertEqual(provider.call_count, 1)
        self.assertEqual(
            provider.received_requests[0]["functions"],
            ("Función A", "Función B"),
        )
        self.assertEqual(source, snapshot)
        self.assertLessEqual(proposal.word_count, 80)
        self.assertEqual(len(proposal.source_digest), 64)

    def test_accepts_exactly_80_words(self):
        provider = SimulatedProvider(response_with_word_count(80))
        proposal = KnowledgeGenerator(provider).generate("1", "Puesto", ["Función"])
        self.assertEqual(proposal.word_count, 80)
        self.assertEqual(provider.call_count, 1)

    def test_rejects_81_words_without_truncating_or_retrying(self):
        response = response_with_word_count(81)
        provider = SimulatedProvider(response)
        with self.assertRaises(WordLimitExceededError):
            KnowledgeGenerator(provider).generate("1", "Puesto", ["Función"])
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(len(response.tecnicos), 81)

    def test_rejects_incorrect_categories(self):
        provider = SimulatedProvider(
            {
                "tecnicos": ["Técnico"],
                "administrativos": ["Administrativo"],
                "otra": ["No permitida"],
            }
        )
        with self.assertRaises(InvalidProviderResponseError):
            KnowledgeGenerator(provider).generate("1", "Puesto", ["Función"])
        self.assertEqual(provider.call_count, 1)

    def test_rejects_non_list_category_and_markup(self):
        invalid_shape = SimulatedProvider(
            {"tecnicos": "texto", "administrativos": [], "normativos": []}
        )
        with self.assertRaises(InvalidProviderResponseError):
            KnowledgeGenerator(invalid_shape).generate("1", "Puesto", ["Función"])

        markup = SimulatedProvider(
            {"tecnicos": ["<script>alert(1)</script>"], "administrativos": [], "normativos": []}
        )
        with self.assertRaises(InvalidProviderResponseError):
            KnowledgeGenerator(markup).generate("1", "Puesto", ["Función"])

    def test_fixture_and_temporary_copy_remain_unchanged(self):
        fixture_bytes = FIXTURE.read_bytes()
        fixture_hash = hashlib.sha256(fixture_bytes).hexdigest()
        data = json.loads(fixture_bytes)
        record = data["registros"][0]

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            temporary = Path(directory) / "puestos_ficticios.json"
            temporary.write_bytes(fixture_bytes)
            before = hashlib.sha256(temporary.read_bytes()).hexdigest()

            KnowledgeGenerator(SimulatedProvider()).generate(
                str(record["fila_excel"]),
                record["puesto"],
                record["funciones_genericas"],
            )

            after = hashlib.sha256(temporary.read_bytes()).hexdigest()
            self.assertEqual(before, after)

        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), fixture_hash)


if __name__ == "__main__":
    unittest.main()
