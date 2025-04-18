#!/usr/bin/env python3
import asyncio
import logging
import os
import signal
import sys
import threading
import time
from typing import Dict, Optional, Any, List

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import GStreamer modules
try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstRtspServer', '1.0')
    from gi.repository import Gst
except ImportError as e:
    print(f"Error importing GStreamer: {e}")
    print("Please make sure GStreamer and its Python bindings are installed.")
    sys.exit(1)

# Import local modules
from gstreamer_streaming.api import start_api_server
from gstreamer_streaming.config import (
    SERVICE_NAME,
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_TOPIC_STREAM_CONTROL,
    KAFKA_TOPIC_WEBRTC_SIGNALING_IN,
    KAFKA_TOPIC_STREAM_STATUS,
    KAFKA_TOPIC_WEBRTC_SIGNALING_OUT
)
from gstreamer_streaming.models import StreamConfig, StreamStatus, StreamCommand
from gstreamer_streaming.pipeline import GstPipelineManager

# Setup logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("gstreamer_service")

# Create a pipeline manager
pipeline_manager = GstPipelineManager()

# Flag for graceful shutdown
shutdown_requested = False

# Kafka consumer/producer setup placeholder
try:
    from confluent_kafka import Consumer, Producer, KafkaError, KafkaException
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from confluent_kafka.schema_registry.avro import AvroSerializer, AvroDeserializer
    kafka_available = True
except ImportError:
    logger.warning("Confluent Kafka library not available. Kafka integration disabled.")
    kafka_available = False

# Kafka producer for status updates
producer = None

# Avro schemas
control_schema = None
status_schema = None
webrtc_signal_schema = None

# Metrics and monitoring
try:
    from .. import metrics
    metrics_available = True
except ImportError:
    logger.warning("Metrics module not available. Metrics collection disabled.")
    metrics_available = False


def setup_kafka() -> bool:
    """Set up Kafka producer and schema registry."""
    global producer, control_schema, status_schema, webrtc_signal_schema
    
    if not kafka_available:
        return False
    
    try:
        # Create Kafka producer
        producer_config = {
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
            'client.id': f'{SERVICE_NAME}-{os.getpid()}'
        }
        producer = Producer(producer_config)
        
        # Load schema registry (placeholder - implement based on your schema registry setup)
        # schema_registry_client = SchemaRegistryClient({'url': SCHEMA_REGISTRY_URL})
        # control_schema = ...
        # status_schema = ...
        # webrtc_signal_schema = ...
        
        return True
    except Exception as e:
        logger.error(f"Failed to set up Kafka: {e}")
        return False


def delivery_report(err, msg):
    """Delivery callback for Kafka producer."""
    if err is not None:
        logger.error(f"Message delivery failed: {err}")
    else:
        logger.debug(f"Message delivered to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")


def publish_status(stream_id: str, state: str, error_message: Optional[str] = None, stats: Dict[str, Any] = None):
    """Publish stream status to Kafka."""
    if not kafka_available or producer is None:
        return
    
    # Create status message
    message = {
        "stream_id": stream_id,
        "status": state,
        "service_id": f"{SERVICE_NAME}-{os.getpid()}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metadata": {"error": error_message} if error_message else {},
        "version": 1
    }
    
    if stats:
        for key, value in stats.items():
            if isinstance(value, (str, int, float, bool)):
                message["metadata"][key] = str(value)
    
    try:
        # Serialize and send (simplified - would use Avro serialization with schema registry)
        import json
        producer.produce(
            KAFKA_TOPIC_STREAM_STATUS,
            key=stream_id,
            value=json.dumps(message).encode('utf-8'),
            callback=delivery_report
        )
        producer.poll(0)  # Trigger delivery reports
    except Exception as e:
        logger.error(f"Failed to publish status for stream {stream_id}: {e}")


def handle_stream_status(status: StreamStatus):
    """Handle stream status updates from pipeline manager."""
    logger.info(f"Stream {status.stream_id} status: {status.state}")
    
    # Publish to Kafka
    error_message = status.error_message if status.state == "error" else None
    publish_status(status.stream_id, status.state, error_message, status.stats)
    
    # Update metrics if available
    if metrics_available:
        # Example metric updates based on pipeline state
        state_str = str(status.state)
        if state_str == "running":
            metrics.ACTIVE_PIPELINES.inc()
        elif state_str in ["stopped", "error"]:
            metrics.ACTIVE_PIPELINES.dec()
        
        if state_str == "error":
            metrics.PIPELINE_ERRORS.inc()


# Set the status callback
pipeline_manager._handle_pipeline_status = handle_stream_status


async def consume_stream_control():
    """Consume messages from the stream control topic."""
    if not kafka_available:
        logger.warning("Kafka integration disabled. Stream control via Kafka not available.")
        return
    
    # Create consumer
    consumer_config = {
        'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
        'group.id': f'{SERVICE_NAME}-control',
        'auto.offset.reset': 'latest',
        'enable.auto.commit': True
    }
    
    consumer = Consumer(consumer_config)
    consumer.subscribe([KAFKA_TOPIC_STREAM_CONTROL])
    
    logger.info(f"Started Kafka consumer for {KAFKA_TOPIC_STREAM_CONTROL}")
    
    try:
        while not shutdown_requested:
            try:
                # Poll for messages
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        # End of partition event - not an error
                        continue
                    logger.error(f"Kafka error: {msg.error()}")
                    continue
                
                # Process message
                try:
                    # Deserialize message (simplified - would use Avro deserialization)
                    import json
                    value = json.loads(msg.value().decode('utf-8'))
                    
                    # Extract command
                    command = value.get("command")
                    stream_id = value.get("stream_id")
                    
                    if not command or not stream_id:
                        logger.warning(f"Invalid control message: {value}")
                        continue
                    
                    # Process command
                    if command == "START":
                        # Create stream config
                        config = StreamConfig(
                            source_type=value.get("source_type", "rtmp"),
                            source_url=value.get("stream_key", ""),
                            output_type=value.get("output_type", "rtmp"),
                            output_url=value.get("rtmp_url", ""),
                            is_recording=value.get("is_recorded", False)
                        )
                        
                        # Check if pipeline exists
                        if stream_id in pipeline_manager.pipelines:
                            # Start existing pipeline
                            success = pipeline_manager.start_pipeline(stream_id)
                        else:
                            # Create and start new pipeline
                            success = pipeline_manager.create_pipeline(stream_id, config)
                            if success:
                                success = pipeline_manager.start_pipeline(stream_id)
                        
                        logger.info(f"START command for stream {stream_id}: {'success' if success else 'failed'}")
                        
                    elif command == "STOP":
                        # Stop pipeline
                        success = pipeline_manager.stop_pipeline(stream_id)
                        logger.info(f"STOP command for stream {stream_id}: {'success' if success else 'failed'}")
                        
                    elif command == "QUERY_STATUS":
                        # Get pipeline status
                        status = pipeline_manager.get_pipeline_status(stream_id)
                        if status:
                            # Publish status to Kafka
                            error_message = status.error_message if status.state == "error" else None
                            publish_status(stream_id, status.state, error_message, status.stats)
                        else:
                            # No pipeline found
                            publish_status(stream_id, "not_found")
                        
                        logger.info(f"QUERY_STATUS command for stream {stream_id}")
                    
                    else:
                        logger.warning(f"Unknown command: {command}")
                
                except Exception as e:
                    logger.error(f"Error processing control message: {e}")
            
            except Exception as e:
                logger.error(f"Error polling Kafka: {e}")
                await asyncio.sleep(1)  # Wait before retrying
        
        # Clean shutdown
        consumer.close()
        logger.info("Stream control consumer closed")
        
    except Exception as e:
        logger.error(f"Fatal error in control consumer: {e}")
        if consumer:
            consumer.close()


async def consume_webrtc_signaling():
    """Consume messages from the WebRTC signaling topic."""
    if not kafka_available:
        logger.warning("Kafka integration disabled. WebRTC signaling via Kafka not available.")
        return
    
    # NOTE: WebRTC signaling would be implemented here, but is more complex and
    # outside the scope of this implementation. This would handle incoming signals
    # like SDP offers/answers and ICE candidates.
    
    logger.info("WebRTC signaling consumer not implemented in this version")
    
    # Placeholder loop to keep the task alive
    while not shutdown_requested:
        await asyncio.sleep(10)


def signal_handler(sig, frame):
    """Handle signals for graceful shutdown."""
    global shutdown_requested
    logger.info(f"Received signal {sig}, initiating shutdown...")
    shutdown_requested = True


async def main():
    """Main entry point for the GStreamer streaming service."""
    global shutdown_requested
    
    logger.info(f"Starting {SERVICE_NAME}")
    
    # Initialize GStreamer
    Gst.init(None)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Set up Kafka if available
    if kafka_available:
        kafka_ok = setup_kafka()
        logger.info(f"Kafka integration {'enabled' if kafka_ok else 'disabled'}")
    
    # Set up metrics if available
    if metrics_available:
        try:
            metrics.start_metrics_server()
            logger.info("Metrics server started")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
    
    # Start API server in a separate thread
    api_thread = threading.Thread(target=start_api_server, daemon=True)
    api_thread.start()
    logger.info("API server started")
    
    # Start Kafka consumers
    tasks = []
    if kafka_available:
        tasks.append(asyncio.create_task(consume_stream_control()))
        tasks.append(asyncio.create_task(consume_webrtc_signaling()))
    
    # Wait for shutdown or error
    try:
        while not shutdown_requested:
            await asyncio.sleep(1)
            
            # Check if API thread is alive
            if not api_thread.is_alive():
                logger.error("API server thread died")
                break
    except Exception as e:
        logger.error(f"Error in main loop: {e}")
    finally:
        # Cancel all tasks
        logger.info("Shutting down...")
        for task in tasks:
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Shutdown pipeline manager
        pipeline_manager.shutdown()
        
        # Flush Kafka producer
        if producer:
            producer.flush()
        
        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1) 