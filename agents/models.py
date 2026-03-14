"""Model provider configuration for NovaOps v2."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from strands.models import BedrockModel

# Load .env for credentials
load_dotenv()

# Nova 2 Lite model ID
NOVA_MODEL_ID = os.environ.get("NOVA_MODEL_ID", "us.amazon.nova-2-lite-v1:0")

# Thinking budget tiers per agent role
THINKING_BUDGET = {
    "LOW": 1024,      # Triage, Critic, Executor
    "MEDIUM": 4096,   # Analysts, RemediationPlanner
    "HIGH": 8192,     # RootCauseReasoner
}


def get_model(thinking_tier: str = "MEDIUM", temperature: float = 0.2) -> BedrockModel:
    """Create a runtime model, or a mock placeholder in offline mode."""
    if _use_mock_models():
        return MockModel(thinking_tier=thinking_tier, temperature=temperature)

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    return BedrockModel(
        model_id=NOVA_MODEL_ID,
        region_name=region,
        temperature=temperature,
    )


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _use_mock_models() -> bool:
    return _env_bool("NOVAOPS_USE_MOCK", True) or _env_bool("LOCAL_EVAL_MODE", False)


@dataclass
class MockModel:
    """Offline placeholder model used to signal mock graph execution."""

    thinking_tier: str = "MEDIUM"
    temperature: float = 0.2
