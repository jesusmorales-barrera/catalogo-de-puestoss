from __future__ import annotations

import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from editor_catalogo.knowledge_generator import (  # noqa: E402
    KnowledgeGenerator,
    WordLimitExceededError,
)
from editor_catalogo.providers.base import ProviderResult  # noqa: E402
from editor_catalogo.providers.ollama import (  # noqa: E402
    DEFAULT_MODEL,
    OllamaConfig,
    OllamaConfigurationError,
    OllamaConnectionError,
    OllamaHTTPError,
    OllamaHTTPResponse,
    OllamaProvider,
    OllamaResponseError,
    OllamaTimeoutError,
)


FUNCTIONS = (
    "Organizar expedientes ficticios.",
    "Preparar reportes de prueba.",
)


def response_for(data: object, *, status: int = 200) -> OllamaHTTPResponse:
    envelope = {"response": json.dumps(data, ensure_ascii=False), "done": True}
    return OllamaHTTPResponse(
        status=status,
        headers={"content-type": "application/json"},
        body=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
    )


class FakeTransport:
    def __init__(self, response: object):
        self.response = response
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class OllamaProviderTests(unittest.TestCase):
    def valid_result(self):
        return {
            "tecnicos": ["Gestión documental"],
            "administrativos": ["Análisis y presentación de información"],
            "normativos": ["Protección de datos"],
        }

    def provider(self, response):
        transport = FakeTransport(response)
        return OllamaProvider(OllamaConfig(), transport=transport), transport

    def test_builds_local_structured_request_without_real_socket(self):
        provider, transport = self.provider(response_for(self.valid_result()))
        with patch("socket.create_connection") as create_connection:
            result = provider.generate_knowledge(
                position_name="Puesto ficticio",
                functions=FUNCTIONS,
                max_words=80,
            )

        self.assertIsInstance(result, ProviderResult)
        self.assertEqual(len(transport.calls), 1)
        create_connection.assert_not_called()
        request = transport.calls[0]
        decoded_body = request.body.decode("utf-8")
        self.assertEqual(
            (request.host, request.port, request.path),
            ("127.0.0.1", 11434, "/api/generate"),
        )
        body = json.loads(decoded_body)
        self.assertEqual(body["model"], "qwen3:4b-instruct")
        self.assertFalse(body["stream"])
        self.assertFalse(body["think"])
        self.assertEqual(
            set(body["format"]["properties"]),
            {"tecnicos", "administrativos", "normativos"},
        )
        self.assertFalse(body["format"]["additionalProperties"])
        for category in ("tecnicos", "administrativos", "normativos"):
            self.assertNotIn("minItems", body["format"]["properties"][category])
        self.assertNotIn(FUNCTIONS[0], body["system"])
        self.assertIn(FUNCTIONS[0], body["prompt"])
        self.assertIn("Una función es una actividad realizada", body["system"])
        self.assertIn("área de dominio", body["system"])
        self.assertIn("frases nominales breves", body["prompt"])
        self.assertIn(
            "no copies, resumas ni reformules superficialmente",
            body["prompt"],
        )
        self.assertIn("como técnicos", body["prompt"])
        self.assertIn("como administrativos", body["prompt"])
        self.assertIn("como normativos", body["prompt"])
        self.assertIn("No inventes nombres de leyes", body["prompt"])
        self.assertIn("Usa un arreglo vacío", body["prompt"])
        self.assertIn("es incorrecto", body["prompt"])
        self.assertIn("es correcto", body["prompt"])
        self.assertIn("contenido no confiable", body["prompt"])
        self.assertIn("nombre del puesto", body["system"])
        self.assertIn("máximo 80 palabras", body["prompt"])
        self.assertIn("técnicos", decoded_body)
        self.assertEqual(body["options"]["temperature"], 0)

    def test_default_model_and_environment_configuration(self):
        self.assertEqual(OllamaConfig().model, DEFAULT_MODEL)
        config = OllamaConfig.from_env(
            {
                "CATALOGO_OLLAMA_URL": "http://[::1]:11434/api/generate",
                "CATALOGO_OLLAMA_MODEL": "qwen3:4b-instruct",
                "CATALOGO_OLLAMA_TIMEOUT_SECONDS": "45",
            }
        )
        self.assertEqual(config.timeout_seconds, 45)

    def test_rejects_external_urls_credentials_and_cloud_models(self):
        invalid_urls = (
            "https://127.0.0.1:11434/api/generate",
            "http://localhost:11434/api/generate",
            "http://192.168.1.10:11434/api/generate",
            "http://user:pass@127.0.0.1:11434/api/generate",
            "http://127.0.0.1:11434/api/generate?x=1",
            "http://127.0.0.1:11434/api/chat",
        )
        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(OllamaConfigurationError):
                OllamaConfig(url=url)
        with self.assertRaises(OllamaConfigurationError):
            OllamaConfig(model="qwen3:4b-instruct:cloud")

    def test_one_request_and_no_retry_on_timeout_connection_or_http_error(self):
        cases = (
            (socket.timeout(), OllamaTimeoutError),
            (ConnectionRefusedError(), OllamaConnectionError),
            (
                OllamaHTTPResponse(
                    503, {"content-type": "text/plain"}, b"error"
                ),
                OllamaHTTPError,
            ),
            (
                OllamaHTTPResponse(
                    302, {"location": "https://ollama.com"}, b""
                ),
                OllamaHTTPError,
            ),
        )
        for response, error in cases:
            with self.subTest(error=error.__name__):
                provider, transport = self.provider(response)
                with self.assertRaises(error):
                    provider.generate_knowledge(
                        position_name="Puesto ficticio",
                        functions=FUNCTIONS,
                        max_words=80,
                    )
                self.assertEqual(len(transport.calls), 1)

    def test_rejects_malformed_incomplete_and_oversized_responses(self):
        malformed = (
            OllamaHTTPResponse(
                200, {"content-type": "application/json"}, b"not-json"
            ),
            OllamaHTTPResponse(200, {"content-type": "text/plain"}, b"{}"),
            OllamaHTTPResponse(
                200,
                {"content-type": "application/json"},
                b'{"done":false,"response":"{}"}',
            ),
            response_for({"tecnicos": [], "administrativos": []}),
            response_for(
                {
                    "tecnicos": "texto",
                    "administrativos": [],
                    "normativos": [],
                }
            ),
        )
        for response in malformed:
            with self.subTest(response=response), self.assertRaises(
                OllamaResponseError
            ):
                self.provider(response)[0].generate_knowledge(
                    position_name="Puesto ficticio",
                    functions=FUNCTIONS,
                    max_words=80,
                )
        config = OllamaConfig(max_response_bytes=1024)
        oversized = OllamaHTTPResponse(
            200, {"content-type": "application/json"}, b"x" * 1025
        )
        with self.assertRaises(OllamaResponseError):
            OllamaProvider(
                config, transport=FakeTransport(oversized)
            ).generate_knowledge(
                position_name="Puesto ficticio", functions=FUNCTIONS, max_words=80
            )

    def test_converts_valid_response_to_provider_result(self):
        provider, _ = self.provider(response_for(self.valid_result()))
        result = provider.generate_knowledge(
            position_name="Puesto ficticio", functions=FUNCTIONS, max_words=80
        )
        self.assertEqual(
            result,
            ProviderResult(
                tecnicos=("Gestión documental",),
                administrativos=("Análisis y presentación de información",),
                normativos=("Protección de datos",),
            ),
        )

    def test_generator_accepts_200_words_and_rejects_201_without_retry(self):
        for count, error in ((200, None), (201, WordLimitExceededError)):
            data = {
                "tecnicos": [" ".join(f"palabra{i}" for i in range(count))],
                "administrativos": [],
                "normativos": [],
            }
            provider, transport = self.provider(response_for(data))
            generator = KnowledgeGenerator(provider)
            if error is None:
                proposal = generator.generate("9001", "Puesto ficticio", FUNCTIONS)
                self.assertEqual(proposal.word_count, 200)
            else:
                with self.assertRaises(error):
                    generator.generate("9001", "Puesto ficticio", FUNCTIONS)
            self.assertEqual(len(transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
