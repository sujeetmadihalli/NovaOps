import os
import unittest
from unittest.mock import patch

from tools import retrieve_knowledge


class RetrieveKnowledgeLogicTests(unittest.TestCase):
    def test_use_local_retrieval_in_eval_mode(self):
        with patch.object(retrieve_knowledge, "LOCAL_EVAL_MODE", True), patch.object(
            retrieve_knowledge, "USE_MOCK", False
        ):
            self.assertTrue(retrieve_knowledge._use_local_retrieval())

    def test_use_local_retrieval_in_mock_mode(self):
        with patch.object(retrieve_knowledge, "LOCAL_EVAL_MODE", False), patch.object(
            retrieve_knowledge, "USE_MOCK", True
        ):
            self.assertTrue(retrieve_knowledge._use_local_retrieval())

    def test_use_managed_kb_when_configured(self):
        with patch.object(retrieve_knowledge, "LOCAL_EVAL_MODE", False), patch.object(
            retrieve_knowledge, "USE_MOCK", False
        ), patch.dict(os.environ, {}, clear=True):
            self.assertTrue(retrieve_knowledge._use_local_retrieval())


if __name__ == "__main__":
    unittest.main()
