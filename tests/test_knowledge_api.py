from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from editor_catalogo.editor_catalogo import (  # noqa: E402
    CatalogStore,
    Handler,
    KnowledgeGenerator,
    PendingProposalStore,
)
from editor_catalogo.providers.simulated import SimulatedProvider  # noqa: E402
from editor_catalogo.providers.base import ProviderResult  # noqa: E402


FIXTURE = Path(__file__).with_name("fixtures") / "puestos_ficticios.json"


class DirectHandler(Handler):
    def log_message(self, format, *args):
        pass

    def read_json(self):
        return copy.deepcopy(self.test_payload)

    def send_json(self, data, status=200):
        self.test_response = (int(status), copy.deepcopy(data))

    def send_error(self, status, *args, **kwargs):
        self.test_response = (int(status), {"error": "HTTP error"})


class BlockingSimulatedProvider(SimulatedProvider):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def generate_knowledge(self, **kwargs):
        self.entered.set()
        self.release.wait(timeout=5)
        return super().generate_knowledge(**kwargs)


class KnowledgeApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temporary.name)
        self.catalog = self.root / "puestos_ficticios.json"
        self.catalog.write_bytes(FIXTURE.read_bytes())
        self.output = self.root / "salida"
        self.provider = SimulatedProvider()
        DirectHandler.store = CatalogStore(self.catalog, self.output)
        DirectHandler.knowledge_generator = KnowledgeGenerator(self.provider)
        DirectHandler.proposals = PendingProposalStore(ttl_seconds=60)

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, method, path, payload=None, headers=None):
        handler = object.__new__(DirectHandler)
        handler.path = path
        handler.headers = headers or {}
        handler.test_payload = payload
        handler.test_response = None
        if method == "GET":
            handler.do_GET()
        elif method == "POST":
            handler.do_POST()
        elif method == "PUT":
            handler.do_PUT()
        else:
            raise AssertionError(f"Método de prueba no soportado: {method}")
        return handler.test_response

    def get_record(self):
        status, body = self.request("GET", "/api/puestos/9001")
        self.assertEqual(status, 200)
        return body

    def generate(self, revision, idempotency="test-request"):
        return self.request(
            "POST",
            "/api/puestos/9001/propuestas-conocimientos",
            {
                "revision": revision,
                "funciones": [
                    "Coordinar la integración de reportes mensuales.",
                    "Verificar la correcta organización de expedientes.",
                    " verificar   la correcta organización de expedientes. ",
                ],
            },
            {"Idempotency-Key": idempotency},
        )

    def accept(self, proposal, knowledge=None, extra=None):
        payload = {
            "revision": proposal["revision"],
            "proposal_id": proposal["proposal_id"],
            "source_digest": proposal["source_digest"],
            "conocimientos": knowledge or proposal["texto"],
        }
        if extra:
            payload.update(extra)
        return self.request(
            "PUT", "/api/puestos/9001/conocimientos", payload
        )

    def test_generation_is_read_only_and_idempotent(self):
        before = self.catalog.read_bytes()
        revision = self.get_record()["revision"]

        status, first = self.generate(revision)
        second_status, second = self.generate(revision)

        self.assertEqual((status, second_status), (200, 200))
        self.assertEqual(first["proposal_id"], second["proposal_id"])
        self.assertFalse(first["reutilizada"])
        self.assertTrue(second["reutilizada"])
        self.assertEqual(self.provider.call_count, 1)
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertFalse(DirectHandler.store.backup_dir.exists())
        self.assertEqual(json.loads(self.catalog.read_bytes())["historial_cambios"], [])

    def test_acceptance_changes_only_knowledge_and_creates_backup(self):
        original = json.loads(self.catalog.read_bytes())
        revision = self.get_record()["revision"]
        status, proposal = self.generate(revision)
        self.assertEqual(status, 200)

        status, accepted = self.accept(proposal, "Conocimiento técnico y normativo revisado")

        self.assertEqual(status, 200)
        self.assertEqual(accepted["campos_modificados"], ["conocimientos"])
        updated = json.loads(self.catalog.read_bytes())
        expected_record = copy.deepcopy(original["registros"][0])
        expected_record["conocimientos"] = "Conocimiento técnico y normativo revisado"
        self.assertEqual(updated["registros"][0], expected_record)
        self.assertEqual(len(updated["historial_cambios"]), 1)
        self.assertEqual(updated["historial_cambios"][0]["campos"], ["conocimientos"])
        backups = list(DirectHandler.store.backup_dir.glob("*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), json.dumps(original, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")

        repeated_status, _ = self.accept(proposal)
        self.assertEqual(repeated_status, 409)

    def test_additional_acceptance_field_is_rejected_without_write(self):
        before = self.catalog.read_bytes()
        _, proposal = self.generate(self.get_record()["revision"])

        status, _ = self.accept(proposal, extra={"puesto": "No autorizado"})

        self.assertEqual(status, 400)
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertFalse(DirectHandler.store.backup_dir.exists())

    def test_additional_generation_field_is_rejected_without_provider_call(self):
        before = self.catalog.read_bytes()
        status, _ = self.request(
            "POST",
            "/api/puestos/9001/propuestas-conocimientos",
            {
                "revision": self.get_record()["revision"],
                "funciones": ["Función ficticia"],
                "modelo": "no autorizado",
            },
            {"Idempotency-Key": "extra-field"},
        )

        self.assertEqual(status, 400)
        self.assertEqual(self.provider.call_count, 0)
        self.assertEqual(self.catalog.read_bytes(), before)

    def test_invalid_provider_response_does_not_write(self):
        DirectHandler.knowledge_generator = KnowledgeGenerator(
            SimulatedProvider({"tecnicos": [], "categoria_invalida": []})
        )
        before = self.catalog.read_bytes()

        status, _ = self.generate(self.get_record()["revision"], "invalid-response")

        self.assertEqual(status, 400)
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertFalse(DirectHandler.store.backup_dir.exists())

    def test_accepts_proposal_with_exactly_80_content_words(self):
        response = ProviderResult(
            tecnicos=tuple(f"palabra{i}" for i in range(80)),
            administrativos=(),
            normativos=(),
        )
        DirectHandler.knowledge_generator = KnowledgeGenerator(
            SimulatedProvider(response)
        )
        _, proposal = self.generate(self.get_record()["revision"], "eighty-words")

        status, result = self.accept(proposal)

        self.assertEqual(status, 200)
        self.assertEqual(result["campos_modificados"], ["conocimientos"])

    def test_stale_proposal_is_rejected_after_normal_save(self):
        _, proposal = self.generate(self.get_record()["revision"])
        status, saved = self.request(
            "PUT",
            "/api/puestos/9001",
            {
                "revision": proposal["revision"],
                "puesto": "Coordinación ficticia de archivo actualizada",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(saved["campos_modificados"], ["puesto"])

        stale_status, _ = self.accept(proposal)

        self.assertEqual(stale_status, 409)
        record = json.loads(self.catalog.read_bytes())["registros"][0]
        self.assertIsNone(record["conocimientos"])

    def test_expired_proposal_is_rejected_without_write(self):
        clock = [100.0]
        DirectHandler.proposals = PendingProposalStore(
            ttl_seconds=10, clock=lambda: clock[0]
        )
        before = self.catalog.read_bytes()
        _, proposal = self.generate(self.get_record()["revision"])
        clock[0] = 111.0

        status, _ = self.accept(proposal)

        self.assertEqual(status, 410)
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertFalse(DirectHandler.store.backup_dir.exists())

    def test_two_simultaneous_acceptances_do_not_lose_data(self):
        _, proposal = self.generate(self.get_record()["revision"])
        barrier = threading.Barrier(3)
        results = []

        def worker():
            barrier.wait()
            results.append(self.accept(proposal)[0])

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)

        self.assertCountEqual(results, [200, 409])
        data = json.loads(self.catalog.read_bytes())
        self.assertEqual(len(data["historial_cambios"]), 1)
        self.assertEqual(
            data["historial_cambios"][0]["campos"], ["conocimientos"]
        )
        self.assertEqual(len(list(DirectHandler.store.backup_dir.glob("*.json"))), 1)

    def test_normal_save_still_works(self):
        current = self.get_record()
        status, result = self.request(
            "PUT",
            "/api/puestos/9001",
            {
                "revision": current["revision"],
                "puesto": "Puesto ficticio editado",
                "perfil": "Perfil de prueba",
            },
        )

        self.assertEqual(status, 200)
        self.assertCountEqual(result["campos_modificados"], ["puesto", "perfil"])
        record = json.loads(self.catalog.read_bytes())["registros"][0]
        self.assertEqual(record["puesto"], "Puesto ficticio editado")
        self.assertEqual(record["perfil"], "Perfil de prueba")

    def test_duplicate_in_flight_generation_is_rejected(self):
        provider = BlockingSimulatedProvider()
        DirectHandler.knowledge_generator = KnowledgeGenerator(provider)
        revision = self.get_record()["revision"]
        first_result = []

        thread = threading.Thread(
            target=lambda: first_result.append(self.generate(revision, "first"))
        )
        thread.start()
        self.assertTrue(provider.entered.wait(timeout=5))

        duplicate_status, _ = self.generate(revision, "second")
        provider.release.set()
        thread.join(timeout=5)

        self.assertEqual(duplicate_status, 409)
        self.assertEqual(first_result[0][0], 200)
        self.assertEqual(provider.call_count, 1)


if __name__ == "__main__":
    unittest.main()
