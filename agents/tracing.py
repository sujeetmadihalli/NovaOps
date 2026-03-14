"""OpenTelemetry tracing — Strands-native instrumentation.

Configures tracing to export to AWS X-Ray or local JSON files.
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger(__name__)

PLANS_DIR = Path(__file__).parent.parent / "plans"

_initialized = False


def init_tracing():
    """Initialize OpenTelemetry tracing. Call once at startup."""
    global _initialized
    if _initialized:
        return

    resource = Resource.create({
        "service.name": "novaops-v2",
        "service.version": "2.0.0",
    })

    provider = TracerProvider(resource=resource)

    # Export to console in dev mode
    if os.environ.get("OTEL_EXPORTER", "console") == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _initialized = True
    logger.info("OpenTelemetry tracing initialized")


def get_tracer(name: str = "novaops"):
    """Get a tracer instance."""
    return trace.get_tracer(name)


def save_trace(incident_id: str, trace_data: dict):
    """Save trace data to investigation directory."""
    inv_dir = PLANS_DIR / incident_id
    if inv_dir.exists():
        trace_path = inv_dir / "trace.json"
        trace_path.write_text(
            json.dumps(trace_data, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info(f"Trace saved: {trace_path}")
