import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from .api.api_v1.api import api_router
from .api.api_v1.websockets import router as websocket_router
from .core.config import settings
from .core.rate_limit import RateLimitMiddleware
from .kafka.consumers import stream_status_consumer_task
from .core.connection_manager import connection_manager
from .core.kafka_consumer_manager import kafka_consumer_manager

logger = logging.getLogger(__name__)

# --- Lifespan Management --- 
kafka_consumer_tasks = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup --- 
    logger.info("Application startup...")
    # Connect to Redis
    await connection_manager.connect_redis()
    # Start Kafka consumers (managed globally)
    # logger.info("Starting Kafka consumer tasks...")
    # status_task = asyncio.create_task(stream_status_consumer_task()) # Replaced by manager
    # kafka_consumer_tasks.append(status_task)
    # Consumer tasks now started on demand by KafkaConsumerManager
    
    yield # Application runs here
    
    # --- Shutdown --- 
    logger.info("Application shutdown...")
    # Shutdown Kafka Consumer Manager (stops all its tasks)
    await kafka_consumer_manager.shutdown()
    # Disconnect from Redis
    await connection_manager.disconnect_redis()

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