# backend/app/core/metrics.py

from prometheus_client import Counter, Gauge, Histogram, Summary
import logging

logger = logging.getLogger(__name__)

# API Metrics
API_REQUESTS = Counter(
    "verxe_api_requests_total",
    "Total number of API requests",
    ["method", "endpoint", "status_code"]
)

API_REQUEST_DURATION = Histogram(
    "verxe_api_request_duration_seconds",
    "API request duration in seconds",
    ["method", "endpoint"]
)

# Stream Metrics
STREAM_COUNT = Gauge(
    "verxe_stream_count",
    "Current number of active streams",
    ["status"]  # offline, live, ended
)

STREAM_VIEWERS = Gauge(
    "verxe_stream_viewers",
    "Current number of viewers per stream",
    ["stream_id"]
)

STREAM_DURATION = Histogram(
    "verxe_stream_duration_seconds",
    "Stream duration in seconds"
)

# WebSocket Metrics
WEBSOCKET_CONNECTIONS = Gauge(
    "verxe_websocket_connections",
    "Current number of active WebSocket connections"
)

WEBSOCKET_MESSAGES = Counter(
    "verxe_websocket_messages_total",
    "Total number of WebSocket messages",
    ["direction", "message_type"]  # direction: sent, received
)

# Kafka Metrics
KAFKA_MESSAGES = Counter(
    "verxe_kafka_messages_total",
    "Total number of Kafka messages",
    ["operation", "topic"]  # operation: produce, consume
)

KAFKA_ERRORS = Counter(
    "verxe_kafka_errors_total",
    "Total number of Kafka errors",
    ["operation", "topic"]  # operation: produce, consume
)

# Outbox Metrics
OUTBOX_MESSAGES = Counter(
    "verxe_outbox_messages_total",
    "Total number of outbox messages",
    ["topic", "status"]  # status: pending, processed, failed
)

OUTBOX_RETRY_COUNT = Histogram(
    "verxe_outbox_retry_count",
    "Distribution of outbox message retry counts",
    ["topic"]
)

# Database Metrics
DB_QUERY_DURATION = Histogram(
    "verxe_db_query_duration_seconds",
    "Database query duration in seconds",
    ["operation"]  # operation: select, insert, update, delete
)

DB_CONNECTION_POOL = Gauge(
    "verxe_db_connection_pool_size",
    "Current size of the database connection pool",
    ["state"]  # state: total, in_use, idle
)

# Initialize metrics
def init_metrics():
    """
    Initialize metrics with default values.
    """
    try:
        # Set initial values for gauges
        STREAM_COUNT.labels(status="offline").set(0)
        STREAM_COUNT.labels(status="live").set(0)
        STREAM_COUNT.labels(status="ended").set(0)
        WEBSOCKET_CONNECTIONS.set(0)
        
        # Set initial values for database connection pool
        DB_CONNECTION_POOL.labels(state="total").set(0)
        DB_CONNECTION_POOL.labels(state="in_use").set(0)
        DB_CONNECTION_POOL.labels(state="idle").set(0)
        
        logger.info("Initialized metrics with default values")
    except Exception as e:
        logger.error(f"Failed to initialize metrics: {e}")
        
def update_stream_count(db_session):
    """
    Update stream count metrics from the database.
    Should be called periodically.
    """
    from ..models.stream import Stream
    from sqlalchemy import func, select
    
    try:
        # Get stream counts by status
        query = select(Stream.status, func.count()).group_by(Stream.status)
        result = db_session.execute(query).fetchall()
        
        # Reset all counts to zero
        STREAM_COUNT.labels(status="offline").set(0)
        STREAM_COUNT.labels(status="live").set(0)
        STREAM_COUNT.labels(status="ended").set(0)
        
        # Update with actual values
        for status, count in result:
            if status in ["offline", "live", "ended"]:
                STREAM_COUNT.labels(status=status).set(count)
                
        logger.debug("Updated stream count metrics")
    except Exception as e:
        logger.error(f"Failed to update stream count metrics: {e}")
        
def update_websocket_connections_count(connection_count):
    """
    Update WebSocket connections count metric.
    """
    try:
        WEBSOCKET_CONNECTIONS.set(connection_count)
    except Exception as e:
        logger.error(f"Failed to update WebSocket connections count metric: {e}")

# Export metrics for Prometheus
def start_metrics_server(port=8000):
    """
    Start a metrics server for Prometheus.
    """
    from prometheus_client import start_http_server
    
    try:
        start_http_server(port)
        logger.info(f"Started metrics server on port {port}")
    except Exception as e:
        logger.error(f"Failed to start metrics server: {e}")

# Initialize metrics on module import
init_metrics() 