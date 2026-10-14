from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


EDITOR_HTML = Path(__file__).resolve().parents[1] / "editor_catalogo" / "editor.html"


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.elements[attributes["id"]] = (tag, attributes)


class EditorFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = EDITOR_HTML.read_text(encoding="utf-8")
        cls.parser = IdCollector()
        cls.parser.feed(cls.html)
        match = re.search(r"<script>(.*)</script>", cls.html, re.DOTALL)
        if match is None:
            raise AssertionError("No se encontró el script del editor")
        cls.script = match.group(1)

    def test_review_controls_exist_and_are_non_submitting_buttons(self):
        expected = {
            "generateKnowledge": "button",
            "knowledgeProposal": "section",
            "proposalText": "textarea",
            "proposalWordCount": "span",
            "proposalStatus": "p",
            "acceptProposal": "button",
            "discardProposal": "button",
        }
        for element_id, tag in expected.items():
            self.assertIn(element_id, self.parser.elements)
            self.assertEqual(self.parser.elements[element_id][0], tag)
        for element_id in ("generateKnowledge", "acceptProposal", "discardProposal"):
            self.assertEqual(self.parser.elements[element_id][1].get("type"), "button")

    def test_frontend_uses_only_specific_knowledge_endpoints(self):
        self.assertIn("/propuestas-conocimientos", self.script)
        self.assertIn("+'/conocimientos'", self.script)
        self.assertIn("method:'POST'", self.script)
        self.assertIn("method:'PUT'", self.script)

    def test_idempotency_key_is_uuid_and_is_reused_from_attempt(self):
        self.assertIn("function newIdempotencyKey()", self.script)
        self.assertIn("crypto.randomUUID()", self.script)
        self.assertIn("crypto.getRandomValues", self.script)
        self.assertIn("key:newIdempotencyKey()", self.script)
        self.assertIn("'Idempotency-Key':a.key", self.script)
        self.assertIn("generationAttempt?'Reintentar generación'", self.script)

    def test_generated_content_uses_safe_text_properties(self):
        self.assertIn("proposalText.value=d.texto??''", self.script)
        self.assertIn("proposalStatus.textContent", self.script)
        self.assertIn("proposalWordCount.textContent", self.script)
        self.assertNotIn("proposalText.innerHTML", self.script)
        self.assertNotIn("proposalStatus.innerHTML", self.script)

    def test_generation_does_not_write_definitive_knowledge(self):
        generation = self.script.split("async function generateKnowledge()", 1)[1]
        generation = generation.split("async function acceptKnowledge()", 1)[0]
        self.assertNotIn("form.elements.conocimientos.value", generation)
        self.assertNotIn("/conocimientos'", generation)

    def test_acceptance_uses_specific_payload_and_preserves_dirty_state(self):
        acceptance = self.script.split("async function acceptKnowledge()", 1)[1]
        acceptance = acceptance.split("function discardKnowledgeProposal()", 1)[0]
        self.assertIn(
            "proposal_id:proposal.proposalId,source_digest:proposal.sourceDigest,conocimientos:text",
            acceptance,
        )
        self.assertIn("form.elements.conocimientos.value=text", acceptance)
        self.assertNotIn("dirty=false", acceptance)
        self.assertNotIn("saveCurrent", acceptance)

    def test_discard_does_not_call_api(self):
        discard = self.script.split("function discardKnowledgeProposal()", 1)[1]
        discard = discard.split("function clearPendingAIBeforeWrite()", 1)[0]
        self.assertNotIn("api(", discard)
        self.assertIn("clearProposal()", discard)

    def test_pending_proposal_guards_selection_and_function_changes(self):
        self.assertIn("Existe una propuesta o solicitud de IA pendiente", self.script)
        self.assertIn("functionsChanged", self.script)
        self.assertIn("proposal.functionsChanged", self.script)
        self.assertIn("proposal.positionId!==current", self.script)

    def test_word_limit_is_checked_before_acceptance(self):
        self.assertIn("countProposalWords", self.script)
        self.assertIn("count===0||count>80", self.script)
        self.assertIn("${count}/80 palabras", self.script)

    def test_error_states_are_explicit(self):
        for status in ("status===400", "status===409", "status===410"):
            self.assertIn(status, self.script)
        self.assertIn("e.connection=true", self.script)


if __name__ == "__main__":
    unittest.main()
