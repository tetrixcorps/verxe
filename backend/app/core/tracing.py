import logging
import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter # Added Console for debugging
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

# Assuming settings are accessible or passed in
# from .config import settings 
# For simplicity, using os.environ directly here

logger = logging.getLogger(__name__)

_tracer = None
_tracer_provider = None

def setup_tracing():
    """Initializes the OpenTelemetry TracerProvider and sets the global tracer."""
    global _tracer, _tracer_provider
    if _tracer:
        return # Already initialized
        
    try:
        service_name = os.environ.get("OTEL_SERVICE_NAME", "verxe-backend")
        otlp_endpoint = os.environ.get("OTLP_ENDPOINT", "http://localhost:4317") # Default for local collector
        otlp_insecure = os.environ.get("OTLP_INSECURE", "true").lower() == "true"
        
        resource = Resource(attributes={
            SERVICE_NAME: service_name
        })
        
        _tracer_provider = TracerProvider(resource=resource)
        
        # OTLP Exporter (preferred for production)
        otlp_exporter = OTLPSpanExporter(
            endpoint=otlp_endpoint, 
            insecure=otlp_insecure
            # credentials=... # Add credentials if needed
            # headers=... # Add headers if needed
        )
        otlp_processor = BatchSpanProcessor(otlp_exporter)
        _tracer_provider.add_span_processor(otlp_processor)
        
        # Console Exporter (useful for local debugging)
        console_exporter = ConsoleSpanExporter()
        console_processor = BatchSpanProcessor(console_exporter)
        _tracer_provider.add_span_processor(console_processor)
        
        # Set the global tracer provider
        trace.set_tracer_provider(_tracer_provider)
        
        # Get the tracer instance
        _tracer = trace.get_tracer(service_name)
        
        logger.info(f"OpenTelemetry tracing initialized for service '{service_name}', exporting to {otlp_endpoint}")
        
    except Exception as e:
        logger.exception(f"Failed to initialize OpenTelemetry tracing: {e}")
        # Prevent application crash if tracing fails to initialize
        _tracer = trace.get_tracer("fallback_tracer") # Provide a no-op tracer

def get_tracer():
    """Returns the initialized tracer instance."""
    global _tracer
    if _tracer is None:
        setup_tracing() # Initialize on first call if not done by lifespan
    return _tracer

async def shutdown_tracing():
    """Shuts down the tracer provider gracefully."""
    global _tracer_provider
    if _tracer_provider and hasattr(_tracer_provider, 'shutdown'):
        logger.info("Shutting down OpenTelemetry tracer provider...")
        _tracer_provider.shutdown()
        logger.info("OpenTelemetry tracer provider shut down.") 