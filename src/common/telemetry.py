import logging
import os
import sys
from pythonjsonlogger import jsonlogger
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def _setup_tracing_provider(service_name: str) -> None:
    # If a tracer provider is already configured (e.g., by auto instrumentation), keep it.
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    insecure = endpoint.startswith("http://")
    normalized_endpoint = endpoint.replace("http://", "").replace("https://", "")

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=normalized_endpoint, insecure=insecure)
        )
    )
    trace.set_tracer_provider(provider)

def setup_telemetry(app, service_name):
    _setup_tracing_provider(service_name)
    LoggingInstrumentor().instrument(set_logging_format=False)
    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    class CustomJsonFormatter(jsonlogger.JsonFormatter):
        def add_fields(self, log_record, record, message_dict):
            super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
            log_record['Severity'] = record.levelname
            log_record['Message'] = record.getMessage()
            log_record['Service'] = service_name
            
            if record.exc_info:
                log_record['Exception'] = record.exc_info[0].__name__
                # Stack trace is handled by default python json logger formatting if exc_info is true
                
            span = trace.get_current_span()
            if span and span.is_recording():
                log_record['TraceID'] = trace.format_trace_id(span.get_span_context().trace_id)
                log_record['SpanID'] = trace.format_span_id(span.get_span_context().span_id)

    logHandler = logging.StreamHandler(sys.stdout)
    formatter = CustomJsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s', rename_fields={"asctime": "Timestamp", "levelname": "level"})
    logHandler.setFormatter(formatter)
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    logger.addHandler(logHandler)

    # FastAPI specifically handles its own access logs via uvicorn, let's configure uvicorn logger as well
    logging.getLogger("uvicorn.access").handlers = [logHandler]
    logging.getLogger("uvicorn.error").handlers = [logHandler]

    return logging.getLogger(service_name)
