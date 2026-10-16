"""Pruebas ficticias del control de revisiones basado en contenido."""
import os
import tempfile
import unittest
from pathlib import Path

from editor_catalogo.editor_catalogo import CatalogStore


class CatalogRevisionTests(unittest.TestCase):
    def test_revision_detects_content_change_with_identical_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / 'fixture.json'
            catalog.write_text('{"registros": []}\n', encoding='utf-8')
            store = CatalogStore(catalog, root / 'salida')
            original = catalog.stat()
            first = store.revision()
            catalog.write_text('{"registros": [{"puesto":"ficticio"}]}\n', encoding='utf-8')
            os.utime(catalog, ns=(original.st_atime_ns, original.st_mtime_ns))
            self.assertEqual(catalog.stat().st_mtime_ns, original.st_mtime_ns)
            self.assertNotEqual(store.revision(), first)

    def test_revision_stable_for_same_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / 'fixture.json'
            catalog.write_text('{"registros": []}\n', encoding='utf-8')
            store = CatalogStore(catalog, root / 'salida')
            self.assertEqual(store.revision(), store.revision())


if __name__ == '__main__':
    unittest.main()
