# media_processor_service/metrics.py

import logging
import os
import threading
import psutil  # Added for CPU/memory metrics
import time

from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server

logger = logging.getLogger(__name__)

# --- Metric Definitions ---

PIPELINE_COUNT = Gauge(
    'media_processor_active_pipelines', 
    'Number of active GStreamer pipelines'
)

KAFKA_MESSAGES_CONSUMED = Counter(
    'media_processor_kafka_messages_consumed_total', 
    'Total number of Kafka messages consumed', 
    ['topic', 'consumer_group']
)

KAFKA_MESSAGES_PRODUCED = Counter(
    'media_processor_kafka_messages_produced_total', 
    'Total number of Kafka messages produced', 
    ['topic']
)

KAFKA_ERRORS = Counter(
    'media_processor_kafka_errors_total',
    'Total number of Kafka errors encountered',
    ['operation', 'topic'] # e.g., operation=consume/produce/commit
)

DLQ_MESSAGES_SENT = Counter(
    'media_processor_dlq_messages_sent_total',
    'Total number of messages sent to DLQ',
    ['original_topic']
)

PIPELINE_EVENTS = Counter(
    'media_processor_pipeline_events_total',
    'Total number of pipeline lifecycle events',
    ['stream_id', 'event_type'] # e.g., start, stop, error, eos
)

WEBRTC_SIGNALS_PROCESSED = Counter(
    'media_processor_webrtc_signals_processed_total',
    'Total number of WebRTC signals processed',
    ['stream_id', 'signal_type', 'direction'] # direction=incoming/outgoing
)

# --- New metrics for CPU, memory, connection time, and media quality ---

# CPU usage per pipeline
PIPELINE_CPU_USAGE = Gauge(
    'media_processor_pipeline_cpu_usage',
    'CPU usage percentage per pipeline',
    ['stream_id']
)

# Memory usage per pipeline
PIPELINE_MEMORY_USAGE = Gauge(
    'media_processor_pipeline_memory_usage_bytes',
    'Memory usage in bytes per pipeline',
    ['stream_id']
)

# WebRTC connection establishment time
WEBRTC_CONNECTION_TIME = Histogram(
    'media_processor_webrtc_connection_time_seconds',
    'Time taken to establish WebRTC connections in seconds',
    ['stream_id'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0]  # Time buckets in seconds
)

# Frame processing latency
FRAME_PROCESSING_LATENCY = Histogram(
    'media_processor_frame_processing_latency_ms',
    'Time taken to process a frame in milliseconds',
    ['stream_id', 'media_type'],  # media_type: 'audio' or 'video'
    buckets=[1, 5, 10, 20, 50, 100, 200, 500, 1000]  # Time buckets in milliseconds
)

# Video quality metrics
VIDEO_BITRATE = Gauge(
    'media_processor_video_bitrate_kbps',
    'Video bitrate in kilobits per second',
    ['stream_id']
)

FRAME_RATE = Gauge(
    'media_processor_frame_rate_fps',
    'Video frame rate in frames per second',
    ['stream_id']
)

VIDEO_RESOLUTION = Gauge(
    'media_processor_video_resolution',
    'Video resolution in pixels (width * height)',
    ['stream_id']
)

# Audio quality metrics
AUDIO_BITRATE = Gauge(
    'media_processor_audio_bitrate_kbps',
    'Audio bitrate in kilobits per second',
    ['stream_id']
)

AUDIO_SAMPLE_RATE = Gauge(
    'media_processor_audio_sample_rate_hz',
    'Audio sample rate in Hz',
    ['stream_id']
)

# Overall pipeline health score (composite metric from 0-100)
PIPELINE_HEALTH_SCORE = Gauge(
    'media_processor_pipeline_health_score',
    'Overall pipeline health score (0-100)',
    ['stream_id']
)

# WebRTC connection metrics
WEBRTC_CONNECTION_STATE_CHANGES = Counter(
    'media_processor_webrtc_connection_state_changes_total',
    'Number of WebRTC connection state changes',
    ['stream_id', 'state']
)

ICE_CONNECTION_STATE_CHANGES = Counter(
    'media_processor_ice_connection_state_changes_total',
    'Number of ICE connection state changes',
    ['stream_id', 'state']
)

WEBRTC_CONNECTION_ERRORS = Counter(
    'media_processor_webrtc_connection_errors_total',
    'Number of WebRTC connection errors',
    ['stream_id', 'error_type']
)

# --- DLQ Processor Specific Metrics ---
# Main DLQ processor metrics
DLQ_MESSAGES_PROCESSED = Counter(
    'dlq_processor_messages_processed_total',
    'Total number of DLQ messages processed'
)

DLQ_MESSAGES_REPROCESSED = Counter(
    'dlq_processor_messages_reprocessed_total',
    'Total number of messages successfully reprocessed from DLQ'
)

DLQ_MESSAGES_FAILED = Counter(
    'dlq_processor_messages_failed_total',
    'Total number of messages that failed to be reprocessed from DLQ'
)

DLQ_PROCESSING_DURATION = Histogram(
    'dlq_processor_message_processing_duration_seconds',
    'Time taken to process a message from DLQ',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0]
)

DLQ_TOPICS_DISCOVERED = Counter(
    'dlq_processor_topics_discovered_total',
    'Total number of DLQ topics discovered'
)

DLQ_TOPICS_MONITORED = Gauge(
    'dlq_processor_topics_monitored',
    'Number of DLQ topics currently being monitored'
)

DLQ_BACKOFF_DELAY = Gauge(
    'dlq_processor_backoff_delay_seconds',
    'Current backoff delay for message retries'
)

DLQ_MAX_RETRIES_EXCEEDED = Counter(
    'dlq_processor_max_retries_exceeded_total',
    'Number of messages that exceeded maximum retry attempts'
)

# Pipeline health metrics
PIPELINE_HEALTH = Gauge(
    'media_processor_pipeline_health_score',
    'Health score of pipelines (0-100)',
    ['stream_id']
)

# WebRTC connection metrics
WEBRTC_CONNECTION_DURATION = Histogram(
    'media_processor_webrtc_connection_duration_seconds',
    'Duration of WebRTC connections'
)

PIPELINE_CREATION_TIME = Histogram(
    'media_processor_pipeline_creation_time_seconds',
    'Time taken to create a GStreamer pipeline'
)

PIPELINE_STARTUP_TIME = Histogram(
    'media_processor_pipeline_startup_time_seconds',
    'Time taken for a pipeline to start streaming'
)

PIPELINE_ERROR_COUNT = Counter(
    'media_processor_pipeline_errors_total',
    'Total number of pipeline errors',
    ['error_type']
)

PROCESSING_LATENCY = Histogram(
    'media_processor_signal_processing_latency_seconds',
    'Time taken to process a signaling message'
)

# CPU and memory usage
CPU_USAGE = Gauge(
    'media_processor_process_cpu_usage_percent',
    'CPU usage percentage of the process'
)

MEMORY_USAGE = Gauge(
    'media_processor_process_memory_usage_bytes',
    'Memory usage of the process in bytes'
)

# Video quality metrics
FRAMES_DROPPED = Counter(
    'media_processor_frames_dropped_total',
    'Total number of frames dropped',
    ['stream_id', 'reason']
)

BUFFER_LEVEL = Gauge(
    'media_processor_buffer_level_bytes',
    'Buffer occupancy in bytes',
    ['stream_id', 'element']
)

PACKET_LOSS = Gauge(
    'media_processor_packet_loss_percent',
    'WebRTC packet loss percentage',
    ['stream_id', 'media_type']
)

# --- Metrics Server --- 

_metrics_server_started = False
_lock = threading.Lock()

def start_metrics_server(port=None):
    """Starts the Prometheus metrics HTTP server if not already started."""
    global _metrics_server_started
    with _lock:
        if not _metrics_server_started:
            try:
                metrics_port = port or int(os.environ.get("METRICS_PORT", "8001")) # Use different port than main app
                start_http_server(metrics_port)
                logger.info(f"Prometheus metrics server started on port {metrics_port}")
                _metrics_server_started = True
            except Exception as e:
                logger.exception(f"Failed to start Prometheus metrics server: {e}")
    return _metrics_server_started 