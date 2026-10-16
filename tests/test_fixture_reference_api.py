"""Pruebas 2D-2C.2A sin red ni cédulas institucionales."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from editor_catalogo.editor_catalogo import Handler
from editor_catalogo.fixture_reference_api import query_fixture_references
from editor_catalogo.knowledge_retriever import RetrievalError
from editor_catalogo.knowledge_catalog import CatalogValidationError

FIXTURE = ROOT / 'editor_catalogo' / 'catalogo_conocimientos_ficticio.json'
VALID = {
    'puesto': 'Coordinador de Archivo Meteorologico',
    'funciones': [
        'Clasificar y organizar expedientes meteorologicos.',
        'Controlar prestamos y devoluciones de expedientes.',
    ],
}
ID = 'PUESTO-FICTICIO-ARCHIVO'


class FakeHandler(Handler):
    fixture_reference_catalog = FIXTURE

    def read_json(self):
        return copy.deepcopy(self.payload)

    def send_json(self, data, status=200):
        self.response = (int(status), copy.deepcopy(data))


class ReferenceApiTests(unittest.TestCase):
    def call(self, path, payload=VALID, enabled=True):
        handler = object.__new__(FakeHandler)
        handler.path = path
        handler.payload = payload
        handler.headers = {}
        handler.fixture_reference_catalog = FIXTURE if enabled else None
        handler.response = None
        handler.do_POST()
        return handler.response

    def test_returns_approved_references_with_evidence(self):
        status, data = self.call('/api/puestos-ficticios/' + ID + '/referencias-conocimientos')
        self.assertEqual(status, 200)
        self.assertEqual([item['knowledge_id'] for item in data['references']], ['CON-000001', 'CON-000002'])
        self.assertTrue(all(item['evidence'] for item in data['references']))
        self.assertTrue(all(item['human_selected'] is False for item in data['references']))
        self.assertFalse(data['references_used_by_generator'])

    def test_disabled_by_default(self):
        status, _ = self.call('/api/puestos-ficticios/' + ID + '/referencias-conocimientos', enabled=False)
        self.assertEqual(status, 404)

    def test_rejects_non_fixture_identifier(self):
        status, _ = self.call('/api/puestos-ficticios/9001/referencias-conocimientos')
        self.assertEqual(status, 400)

    def test_rejects_extra_fields(self):
        status, _ = self.call('/api/puestos-ficticios/' + ID + '/referencias-conocimientos', {**VALID, 'revision': '0'})
        self.assertEqual(status, 400)

    def test_rejects_invalid_functions(self):
        status, _ = self.call('/api/puestos-ficticios/' + ID + '/referencias-conocimientos', {**VALID, 'funciones': []})
        self.assertEqual(status, 400)

    def test_does_not_access_store_or_generator(self):
        with patch.object(FakeHandler, 'store', create=True) as store, patch.object(FakeHandler, 'knowledge_generator', create=True) as generator:
            status, _ = self.call('/api/puestos-ficticios/' + ID + '/referencias-conocimientos')
            self.assertEqual(status, 200)
            store.assert_not_called()
            generator.assert_not_called()
            self.assertEqual(store.mock_calls, [])
            self.assertEqual(generator.mock_calls, [])

    def test_catalog_missing_returns_server_error_without_path(self):
        handler = object.__new__(FakeHandler)
        handler.path = '/api/puestos-ficticios/' + ID + '/referencias-conocimientos'
        handler.payload = VALID
        handler.fixture_reference_catalog = ROOT / 'does_not_exist.json'
        handler.response = None
        handler.do_POST()
        self.assertEqual(handler.response[0], 500)
        self.assertNotIn('does_not_exist', handler.response[1]['error'])

    def test_utility_rejects_production_catalog(self):
        with patch('editor_catalogo.fixture_reference_api.retrieve_knowledge', side_effect=CatalogValidationError('contexto inválido')):
            with self.assertRaises(CatalogValidationError):
                query_fixture_references(catalog_path=FIXTURE, position_id=ID, payload=VALID)


if __name__ == '__main__':
    unittest.main()
