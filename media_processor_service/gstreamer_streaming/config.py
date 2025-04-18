import os
from typing import Optional

# Base service configuration
SERVICE_NAME = "gstreamer-streaming"
API_PORT = int(os.getenv("GSTREAMER_API_PORT", 5002))
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# GStreamer configuration
GSTREAMER_VERSION = "1.22"
DEFAULT_VIDEO_WIDTH = 640
DEFAULT_VIDEO_HEIGHT = 480
DEFAULT_FRAMERATE = 30
DEFAULT_VIDEO_FORMAT = "h264"
MAX_BITRATE = 2000000  # 2Mbps

# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
SCHEMA_REGISTRY_URL = os.getenv("SCHEMA_REGISTRY_URL", "http://schema-registry:8081")
KAFKA_TOPIC_STREAM_CONTROL = os.getenv("KAFKA_TOPIC_STREAM_CONTROL", "stream_control_events")
KAFKA_TOPIC_STREAM_STATUS = os.getenv("KAFKA_TOPIC_STREAM_STATUS", "stream_status_events")
KAFKA_TOPIC_WEBRTC_SIGNALING_IN = os.getenv("KAFKA_TOPIC_WEBRTC_SIGNALING_IN", "webrtc_signaling_in")
KAFKA_TOPIC_WEBRTC_SIGNALING_OUT = os.getenv("KAFKA_TOPIC_WEBRTC_SIGNALING_OUT", "webrtc_signaling_out")

# Connection to main Verxe backend
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://backend:8000")

# Stream storage configuration
RECORDING_ENABLED = os.getenv("ENABLE_RECORDING", "False").lower() == "true"
RECORDING_PATH = os.getenv("RECORDING_PATH", "/app/recordings")

# CORS settings
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")

# WebRTC settings
WEBRTC_ICE_SERVERS = [
    {
        "urls": ["stun:stun.l.google.com:19302"]
    }
]
WEBRTC_TIMEOUT_SECONDS = 30

# Function to get stream source URL based on stream type and key
def get_stream_source_url(stream_type: str, stream_key: str) -> str:
    """Generate appropriate source URL based on stream type and key."""
    if stream_type == "rtmp":
        return f"rtmp://localhost:1935/live/{stream_key}"
    elif stream_type == "webrtc":
        return f"webrtc://{stream_key}"
    elif stream_type == "test":
        return "test"
    else:
        return stream_key  # Assume direct URL or device

# Function to get authorized API token for backend communication
def get_api_token() -> Optional[str]:
    """Get API token for communication with Verxe backend."""
    return os.getenv("SERVICE_API_TOKEN") 