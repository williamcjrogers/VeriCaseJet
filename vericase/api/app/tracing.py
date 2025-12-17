from __future__ import annotations

import os
import threading
from typing import Any

_lock = threading.Lock()
_initialized = False


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def tracing_enabled() -> bool:
    """Gate tracing behind a single explicit flag.

    This keeps local/dev behavior unchanged unless you opt in.
    """

    return _is_truthy(os.getenv("OTEL_TRACING_ENABLED"))


def setup_tracing(default_service_name: str) -> bool:
    """Initialize OpenTelemetry tracing once per process.

    - Enabled only when `OTEL_TRACING_ENABLED=true`.
    - Exports spans to OTLP/HTTP when `OTEL_EXPORTER_OTLP_ENDPOINT` (or
      `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`) is set.
    - Otherwise falls back to Console exporter (useful for quick local debugging).
    """

    if not tracing_enabled():
        return False

    global _initialized
    with _lock:
        if _initialized:
            return True

        service_name = os.getenv("OTEL_SERVICE_NAME", default_service_name)
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT"
        )

        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint)
        else:
            exporter = ConsoleSpanExporter()

        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))

        # Avoid hard failures if something else already configured tracing.
        try:
            trace.set_tracer_provider(provider)
        except Exception:
            pass

        _initialized = True
        return True


def instrument_fastapi(app: Any) -> None:
    if not tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        # Keep startup resilient; tracing must never block the service.
        return


def instrument_requests() -> None:
    if not tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        RequestsInstrumentor().instrument()
    except Exception:
        return


def instrument_sqlalchemy(engine: Any) -> None:
    if not tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine)
    except Exception:
        return


def instrument_celery() -> None:
    if not tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()
    except Exception:
        return
