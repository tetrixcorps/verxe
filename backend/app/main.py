import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import HTTPException
from fastapi import status
from sqlalchemy import select

# Added Monitoring/Tracing Imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter # Choose exporter (grpc/http)
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from .api.api_v1.api import api_router
from .api.api_v1.websockets import router as websocket_router
from .core.config import settings
from .core.rate_limit import RateLimitMiddleware
from .kafka.consumers import stream_status_consumer_task
from .core.connection_manager import connection_manager
from .core.kafka_consumer_manager import kafka_consumer_manager
from .core.database import SessionLocal
from .kafka.kafka_setup import get_kafka_producer
import redis.asyncio as redis
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler # Added
from apscheduler.triggers.interval import IntervalTrigger # Added
from .core.tracing import setup_tracing, shutdown_tracing, get_tracer # Import tracing utils

# Added import for reconciliation service
from .services.stream_reconciliation_service import StreamReconciliationService 

logger = logging.getLogger(__name__)
producer = get_kafka_producer()
tracer = get_tracer() # Initialize tracer globally if needed elsewhere

# --- Lifespan Management --- 
kafka_consumer_tasks = [] # Note: KafkaConsumerManager handles tasks now
scheduler = AsyncIOScheduler() # Create scheduler instance

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup --- 
    logger.info("Application startup...")
    setup_tracing() # Call setup
    await connection_manager.connect_redis()
    # Consumer tasks started on demand by KafkaConsumerManager
    
    # Schedule reconciliation job
    scheduler.add_job(
        StreamReconciliationService.reconcile_streams,
        trigger=IntervalTrigger(minutes=10), # Run every 10 minutes
        id="stream_reconciliation_job",
        name="Stream Reconciliation Job",
        replace_existing=True
    )
    scheduler.start()
    logger.info("Started Stream Reconciliation Scheduler.")
    
    yield # Application runs here
    
    # --- Shutdown --- 
    logger.info("Application shutdown...")
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shut down.")
    await kafka_consumer_manager.shutdown()
    await connection_manager.disconnect_redis()
    await shutdown_tracing() # Call shutdown

# --- FastAPI App Initialization --- 
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Verxe Chat Application API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add rate limiting middleware
app.add_middleware(RateLimitMiddleware)

# Include routers
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(websocket_router)  # WebSocket router without prefix

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Custom Swagger UI
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        title=f"{settings.PROJECT_NAME} - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )

@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        title=f"{settings.PROJECT_NAME} - ReDoc",
        redoc_js_url="/static/redoc.standalone.js",
    )

# Custom OpenAPI schema
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=settings.PROJECT_NAME,
        version="1.0.0",
        description="Verxe Chat Application API with WebSocket support",
        routes=app.routes,
    )
    # Extended definitions can be included here
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi 

# Instrument FastAPI for Prometheus and OpenTelemetry
Instrumentator().instrument(app).expose(app) # Prometheus /metrics endpoint
FastAPIInstrumentor.instrument_app(app) # OpenTelemetry tracing

# --- Health Check Endpoints --- 
@app.get("/livez", tags=["Health"], status_code=status.HTTP_200_OK)
async def liveness_check():
    """Basic liveness check."""
    return {"status": "ok"}

@app.get("/readyz", tags=["Health"], status_code=status.HTTP_200_OK)
async def readiness_check():
    """Checks if the service and its core dependencies are ready."""
    dependencies_ok = True
    details = {}
    
    # Check DB Connection
    try:
        async with SessionLocal() as db:
            await db.execute(select(1))
        details["database"] = "ready"
    except Exception as e:
        logger.error(f"Readiness check failed: Database connection error: {e}")
        details["database"] = "unhealthy"
        dependencies_ok = False
        
    # Check Redis Connection (using global connection_manager)
    if connection_manager.redis_client:
        try:
            await connection_manager.redis_client.ping()
            details["redis"] = "ready"
        except Exception as e:
            logger.error(f"Readiness check failed: Redis connection error: {e}")
            details["redis"] = "unhealthy"
            dependencies_ok = False
    else:
         details["redis"] = "unhealthy (not connected)"
         dependencies_ok = False
    
    # Check Kafka Producer Connection (simple check)
    if producer: # Using the producer from kafka_setup
        try:
            # Listing topics metadata requires admin privileges usually, 
            # just checking producer instance existence might suffice initially
            # or use a dedicated health check topic if available
            # producer.list_topics(timeout=1.0) # Might fail depending on permissions
            details["kafka_producer"] = "ready (initialized)"
        except Exception as e:
            logger.error(f"Readiness check failed: Kafka producer error: {e}")
            details["kafka_producer"] = "unhealthy"
            dependencies_ok = False
    else:
        details["kafka_producer"] = "unhealthy (not initialized)"
        dependencies_ok = False
        
    if not dependencies_ok:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=details)
        
    return {"status": "ready", "dependencies": details} 