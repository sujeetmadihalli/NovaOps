import os
import unittest
from unittest.mock import patch

from tools import retrieve_knowledge


class RetrieveKnowledgeLogicTests(unittest.TestCase):
    def test_use_local_retrieval_in_hackathon_mode(self):
        with patch.object(retrieve_knowledge, "HACKATHON_MODE", True), patch.object(
            retrieve_knowledge, "USE_MOCK", False
        ), patch.dict(os.environ, {"KNOWLEDGE_BASE_ID": "kb-123"}, clear=False):
            self.assertTrue(retrieve_knowledge._use_local_retrieval())

    def test_use_managed_retrieval_only_when_explicitly_enabled(self):
        with patch.object(retrieve_knowledge, "HACKATHON_MODE", False), patch.object(
            retrieve_knowledge, "USE_MOCK", False
        ), patch.dict(os.environ, {"KNOWLEDGE_BASE_ID": "kb-123"}, clear=False):
            self.assertFalse(retrieve_knowledge._use_local_retrieval())

    def test_use_local_retrieval_without_kb_id(self):
        with patch.object(retrieve_knowledge, "HACKATHON_MODE", False), patch.object(
            retrieve_knowledge, "USE_MOCK", False
        ), patch.dict(os.environ, {}, clear=True):
            self.assertTrue(retrieve_knowledge._use_local_retrieval())


if __name__ == "__main__":
    unittest.main()
