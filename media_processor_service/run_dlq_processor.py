#!/usr/bin/env python
"""
Dead Letter Queue (DLQ) Processor script for handling failed Kafka messages.
This service attempts to reprocess messages that failed in the main media processor pipeline.
"""
import os
import sys
import time
import json
import logging
import random
from typing import Dict, List, Optional, Any
import asyncio
from datetime import datetime
import signal

from confluent_kafka import Consumer, Producer, KafkaError, KafkaException
from prometheus_client import start_http_server

from media_processor_service.metrics import (
    DLQ_MESSAGES_PROCESSED,
    DLQ_MESSAGES_REPROCESSED,
    DLQ_MESSAGES_FAILED,
    DLQ_PROCESSING_DURATION,
    DLQ_TOPICS_DISCOVERED,
    DLQ_BACKOFF_DELAY,
    DLQ_MAX_RETRIES_EXCEEDED,
    start_metrics_server
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("dlq_processor")

# Configuration
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
DLQ_TOPIC_PREFIX = os.environ.get("DLQ_TOPIC_PREFIX", "dlq-")
OUTPUT_TOPIC_PREFIX = os.environ.get("OUTPUT_TOPIC_PREFIX", "")
GROUP_ID = os.environ.get("DLQ_CONSUMER_GROUP_ID", "dlq-processor-group")
MAX_RETRIES = int(os.environ.get("DLQ_MAX_RETRIES", "3"))
MIN_BACKOFF_MS = int(os.environ.get("DLQ_MIN_BACKOFF_MS", "1000"))
MAX_BACKOFF_MS = int(os.environ.get("DLQ_MAX_BACKOFF_MS", "30000"))
METRICS_PORT = int(os.environ.get("METRICS_PORT", "8001"))
POLL_TIMEOUT_MS = int(os.environ.get("POLL_TIMEOUT_MS", "1000"))
HEALTH_CHECK_INTERVAL_S = int(os.environ.get("HEALTH_CHECK_INTERVAL_S", "60"))

# Global flags and state
running = True
last_successful_process_time = datetime.now()
dlq_topics: List[str] = []


class DLQProcessor:
    """
    A processor for handling messages in Dead Letter Queues.
    Attempts to reprocess failed messages with exponential backoff retry logic.
    """
    
    def __init__(self):
        self.consumer = self._create_consumer()
        self.producer = self._create_producer()
        self.discover_dlq_topics()
        
    def _create_consumer(self) -> Consumer:
        """Create and configure a Kafka consumer."""
        config = {
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
            'group.id': GROUP_ID,
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False,
        }
        return Consumer(config)
    
    def _create_producer(self) -> Producer:
        """Create and configure a Kafka producer."""
        config = {
            'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
        }
        return Producer(config)
        
    def discover_dlq_topics(self) -> None:
        """Discover all DLQ topics in Kafka cluster."""
        global dlq_topics
        cluster_metadata = self.consumer.list_topics(timeout=10)
        
        dlq_topics = [topic for topic in cluster_metadata.topics if topic.startswith(DLQ_TOPIC_PREFIX)]
        logger.info(f"Discovered DLQ topics: {dlq_topics}")
        
        if dlq_topics:
            self.consumer.subscribe(dlq_topics)
            DLQ_TOPICS_DISCOVERED.set(len(dlq_topics))
        else:
            logger.warning(f"No DLQ topics found with prefix '{DLQ_TOPIC_PREFIX}'")
            DLQ_TOPICS_DISCOVERED.set(0)
    
    def delivery_callback(self, err, msg) -> None:
        """Callback executed when a message is successfully produced or fails."""
        if err:
            logger.error(f"Message delivery failed: {err}")
            DLQ_MESSAGES_FAILED.inc()
        else:
            logger.info(f"Message delivered to {msg.topic()} [{msg.partition()}] at offset {msg.offset()}")
            DLQ_MESSAGES_REPROCESSED.inc()
    
    def _get_retry_count(self, headers: List[Dict]) -> int:
        """Extract retry count from message headers."""
        if not headers:
            return 0
            
        for header in headers:
            if header[0] == "retry_count":
                try:
                    return int(header[1].decode("utf-8"))
                except (ValueError, AttributeError):
                    return 0
        return 0
        
    def _get_original_topic(self, dlq_topic: str) -> str:
        """Determine the original topic from the DLQ topic name."""
        # Remove the DLQ prefix to get the original topic
        if dlq_topic.startswith(DLQ_TOPIC_PREFIX):
            return dlq_topic[len(DLQ_TOPIC_PREFIX):]
        return dlq_topic
    
    def _calculate_backoff(self, retry_count: int) -> int:
        """Calculate backoff time using exponential backoff algorithm."""
        # Exponential backoff with jitter
        backoff = min(MAX_BACKOFF_MS, MIN_BACKOFF_MS * (2 ** retry_count))
        # Add jitter (±25%)
        jitter = random.uniform(0.75, 1.25)
        return int(backoff * jitter)
        
    def process_message(self, msg) -> None:
        """Process a single message from the DLQ."""
        global last_successful_process_time
        
        if msg is None:
            return
            
        # Update health check timestamp
        last_successful_process_time = datetime.now()
            
        start_time = time.time()
        
        try:
            # Extract message details
            dlq_topic = msg.topic()
            headers = msg.headers() or []
            retry_count = self._get_retry_count(headers)
            original_topic = self._get_original_topic(dlq_topic)
            
            # Handle destination topic prefixing if configured
            destination_topic = f"{OUTPUT_TOPIC_PREFIX}{original_topic}" if OUTPUT_TOPIC_PREFIX else original_topic
            
            logger.info(f"Processing message from {dlq_topic}, retry {retry_count}, sending to {destination_topic}")
            
            DLQ_MESSAGES_PROCESSED.inc()
            
            # Check if max retries exceeded
            if retry_count >= MAX_RETRIES:
                logger.warning(f"Max retries exceeded for message, dropping: {msg.key()}")
                DLQ_MAX_RETRIES_EXCEEDED.inc()
                self.consumer.commit(message=msg)
                return
                
            # Calculate backoff if needed
            backoff_ms = self._calculate_backoff(retry_count)
            DLQ_BACKOFF_DELAY.observe(backoff_ms)
            
            # If backoff needed, sleep
            if retry_count > 0 and backoff_ms > 0:
                logger.info(f"Backing off for {backoff_ms}ms before retrying")
                time.sleep(backoff_ms / 1000)  # Convert to seconds
            
            # Update headers for the next retry if needed
            updated_headers = [h for h in headers if h[0] != "retry_count"]
            updated_headers.append(("retry_count", str(retry_count + 1).encode()))
            
            # Produce to original topic
            self.producer.produce(
                destination_topic,
                key=msg.key(),
                value=msg.value(),
                headers=updated_headers,
                callback=self.delivery_callback
            )
            
            # Flush to ensure message is sent
            self.producer.flush(timeout=5)
            
            # Commit the offset
            self.consumer.commit(message=msg)
            
        except Exception as e:
            logger.error(f"Error processing DLQ message: {e}", exc_info=True)
            DLQ_MESSAGES_FAILED.inc()
        finally:
            processing_time = time.time() - start_time
            DLQ_PROCESSING_DURATION.observe(processing_time)
            
    def run(self) -> None:
        """Main processing loop for the DLQ processor."""
        global running
        
        try:
            while running:
                msg = self.consumer.poll(timeout=POLL_TIMEOUT_MS/1000)
                
                if msg is None:
                    continue
                    
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        logger.debug(f"Reached end of partition: {msg.topic()} [{msg.partition()}]")
                    else:
                        logger.error(f"Kafka error: {msg.error()}")
                    continue
                    
                self.process_message(msg)
                
                # Periodically check for new DLQ topics
                if random.random() < 0.01:  # 1% chance each loop
                    self.discover_dlq_topics()
                    
        except KeyboardInterrupt:
            logger.info("Interrupted, shutting down...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
        finally:
            self.shutdown()
            
    def shutdown(self) -> None:
        """Clean shutdown of Kafka connections."""
        if self.consumer:
            self.consumer.close()
        if self.producer:
            self.producer.flush()
            
            
def health_check() -> bool:
    """Check if the processor is healthy."""
    # Consider the process unhealthy if it hasn't processed a message in too long
    time_since_last_process = (datetime.now() - last_successful_process_time).total_seconds()
    return time_since_last_process < HEALTH_CHECK_INTERVAL_S


def handle_signals() -> None:
    """Set up signal handlers for graceful shutdown."""
    global running
    
    def handler(signum, frame):
        global running
        logger.info(f"Received signal {signum}, shutting down...")
        running = False
        
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


async def serve_health_endpoint() -> None:
    """Serve a health endpoint for container health checks."""
    from aiohttp import web
    
    app = web.Application()
    
    async def health_handler(request):
        if health_check():
            return web.Response(text="healthy")
        return web.Response(status=503, text="unhealthy")
    
    app.router.add_get('/health', health_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8001)
    await site.start()
    
    logger.info("Health check server started on port 8001")


async def main() -> None:
    """Main entry point for the DLQ processor service."""
    global running
    
    # Start metrics server
    start_metrics_server(port=METRICS_PORT)
    logger.info(f"Metrics server started on port {METRICS_PORT}")
    
    # Start health check server
    asyncio.create_task(serve_health_endpoint())
    
    # Set up signal handlers
    handle_signals()
    
    # Start DLQ processor
    processor = DLQProcessor()
    
    # Run in a separate thread to allow asyncio to continue
    import threading
    processor_thread = threading.Thread(target=processor.run)
    processor_thread.daemon = True
    processor_thread.start()
    
    # Keep main thread alive until shutdown
    while running:
        await asyncio.sleep(1)
        
    logger.info("DLQ processor shutdown complete")


if __name__ == "__main__":
    asyncio.run(main()) 