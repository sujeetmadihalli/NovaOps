import unittest
from unittest.mock import patch

from agents import models


class ModelsLogicTests(unittest.TestCase):
    def test_get_model_returns_mock_model_in_mock_mode(self):
        with patch.dict("os.environ", {"NOVAOPS_USE_MOCK": "1"}, clear=False):
            model = models.get_model("LOW")

        self.assertIsInstance(model, models.MockModel)
        self.assertEqual(model.thinking_tier, "LOW")

    def test_get_model_uses_bedrock_model_outside_mock_mode(self):
        with patch.dict("os.environ", {"NOVAOPS_USE_MOCK": "0", "LOCAL_EVAL_MODE": "0"}, clear=False):
            with patch.object(models, "BedrockModel", autospec=True) as bedrock_model:
                sentinel = object()
                bedrock_model.return_value = sentinel
                model = models.get_model("MEDIUM", temperature=0.4)

        self.assertIs(model, sentinel)
        bedrock_model.assert_called_once()


if __name__ == "__main__":
    unittest.main()
