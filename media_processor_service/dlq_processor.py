#!/usr/bin/env python
# media_processor_service/dlq_processor.py

import os
import json
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple, Set, Callable
import re
import uuid

from confluent_kafka import Consumer, Producer, KafkaError, KafkaException, OFFSET_BEGINNING
from opentelemetry import trace

from .metrics import (
    DLQ_MESSAGES_PROCESSED,
    DLQ_RETRY_LATENCY,
    DLQ_MESSAGES_SENT,
    KAFKA_MESSAGES_CONSUMED,
    KAFKA_ERRORS,
    DLQ_RETRY_ATTEMPTS,
    DLQ_RETRY_SUCCESSES,
    DLQ_RETRY_FAILURES,
    DLQ_PROCESSOR_ERRORS
)
from .dlq_handler import DLQHandler

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Configuration constants
MAX_RETRY_ATTEMPTS = int(os.environ.get('DLQ_MAX_RETRY_ATTEMPTS', '3'))
INITIAL_RETRY_DELAY = int(os.environ.get('DLQ_INITIAL_RETRY_DELAY_SEC', '60'))  # 1 minute
MAX_RETRY_DELAY = int(os.environ.get('DLQ_MAX_RETRY_DELAY_SEC', '3600'))  # 1 hour
BACKOFF_MULTIPLIER = float(os.environ.get('DLQ_BACKOFF_MULTIPLIER', '2.0'))
KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')
DLQ_POLL_INTERVAL = float(os.environ.get('DLQ_POLL_INTERVAL_SEC', '5.0'))  # 5 seconds


class DLQProcessor:
    """
    Processes messages from Dead Letter Queue topics and handles retries.
    
    This class is responsible for:
    1. Discovering DLQ topics matching a pattern
    2. Consuming messages from these topics
    3. Determining if messages should be retried based on retry count and policy
    4. Performing retries with exponential backoff
    5. Managing metrics for DLQ processing
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic_pattern: str,
        consumer_group: str,
        max_retries: int,
        initial_retry_delay_ms: int,
        max_retry_delay_ms: int,
        backoff_multiplier: float,
        poll_interval_ms: int
    ):
        """
        Initialize the DLQ processor.
        
        Args:
            bootstrap_servers: Kafka bootstrap servers
            topic_pattern: Regex pattern to match DLQ topics
            consumer_group: Consumer group ID for the DLQ processor
            max_retries: Maximum number of retry attempts
            initial_retry_delay_ms: Initial delay before first retry in milliseconds
            max_retry_delay_ms: Maximum delay between retries in milliseconds
            backoff_multiplier: Multiplier for exponential backoff
            poll_interval_ms: How often to poll for new topics in milliseconds
        """
        self.bootstrap_servers = bootstrap_servers
        self.topic_pattern = re.compile(topic_pattern)
        self.consumer_group = consumer_group
        self.max_retries = max_retries
        self.initial_retry_delay_ms = initial_retry_delay_ms
        self.max_retry_delay_ms = max_retry_delay_ms
        self.backoff_multiplier = backoff_multiplier
        self.poll_interval_ms = poll_interval_ms
        
        self.running = False
        self.subscribed_topics: Set[str] = set()
        
        # Kafka consumer configuration
        self.consumer_config = {
            'bootstrap.servers': bootstrap_servers,
            'group.id': consumer_group,
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': True,
            'auto.commit.interval.ms': 5000,
            'client.id': f'dlq-processor-{uuid.uuid4()}'
        }
        
        # Producer configuration for sending retried messages
        self.producer_config = {
            'bootstrap.servers': bootstrap_servers,
            'client.id': f'dlq-retry-producer-{uuid.uuid4()}'
        }
        
        self.consumer = None
        self.producer = None
        self.dlq_handler = None
        
        logger.info(
            "DLQ Processor initialized with: topic_pattern=%s, max_retries=%d, "
            "initial_delay=%dms, max_delay=%dms, backoff=%f",
            topic_pattern, max_retries, initial_retry_delay_ms, 
            max_retry_delay_ms, backoff_multiplier
        )
    
    async def start(self):
        """Start the DLQ processor."""
        if self.running:
            logger.warning("DLQ Processor already running")
            return
        
        self.running = True
        self.consumer = Consumer(self.consumer_config)
        self.producer = Producer(self.producer_config)
        self.dlq_handler = DLQHandler(self.bootstrap_servers)
        
        logger.info("DLQ Processor started")
        
        # Main processing loop
        try:
            while self.running:
                try:
                    # Check for new DLQ topics
                    await self._discover_dlq_topics()
                    
                    # Process messages if we have subscribed topics
                    if self.subscribed_topics:
                        await self._process_messages()
                    
                    # Wait before checking for new topics again
                    await asyncio.sleep(self.poll_interval_ms / 1000)
                    
                except Exception as e:
                    DLQ_PROCESSOR_ERRORS.inc()
                    logger.error("Error in DLQ processor main loop: %s", str(e), exc_info=True)
                    await asyncio.sleep(1)  # Short delay to avoid tight error loops
        finally:
            self._cleanup()
    
    async def stop(self):
        """Stop the DLQ processor."""
        logger.info("Stopping DLQ Processor")
        self.running = False
    
    async def _discover_dlq_topics(self):
        """Discover DLQ topics matching the configured pattern."""
        try:
            # Get metadata for all topics
            metadata = self.consumer.list_topics(timeout=10)
            
            # Find topics matching our DLQ pattern
            new_dlq_topics = set()
            for topic in metadata.topics.keys():
                if self.topic_pattern.match(topic):
                    new_dlq_topics.add(topic)
            
            # Check if we have new topics to subscribe to
            if new_dlq_topics != self.subscribed_topics:
                added = new_dlq_topics - self.subscribed_topics
                removed = self.subscribed_topics - new_dlq_topics
                
                if added:
                    logger.info("Discovered new DLQ topics: %s", added)
                if removed:
                    logger.info("DLQ topics removed: %s", removed)
                
                self.subscribed_topics = new_dlq_topics
                
                # Update subscription if we have topics
                if self.subscribed_topics:
                    self.consumer.subscribe(list(self.subscribed_topics))
                    logger.info("Subscribed to DLQ topics: %s", self.subscribed_topics)
                else:
                    self.consumer.unsubscribe()
                    logger.info("No DLQ topics to subscribe to")
        
        except Exception as e:
            logger.error("Error discovering DLQ topics: %s", str(e))
    
    async def _process_messages(self):
        """Process messages from subscribed DLQ topics."""
        try:
            # Poll for messages with a timeout
            msg = self.consumer.poll(timeout=1.0)
            
            if msg is None:
                return
            
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("Consumer error: %s", msg.error())
                return
            
            # Process the message
            try:
                topic = msg.topic()
                value = msg.value()
                
                # Increment processed messages counter
                DLQ_MESSAGES_PROCESSED.inc()
                
                # Parse the DLQ message
                dlq_message = json.loads(value.decode('utf-8'))
                original_message = dlq_message.get("original_message", {})
                error_info = dlq_message.get("error", {})
                metadata = dlq_message.get("metadata", {})
                
                retry_count = metadata.get("retry_count", 0)
                original_topic = metadata.get("original_topic")
                
                # Extract the original topic from DLQ topic name if not in metadata
                if not original_topic:
                    # Assuming DLQ topic naming follows pattern: originaltopic.dlq
                    original_topic_match = re.match(r'(.+)\.dlq$', topic)
                    if original_topic_match:
                        original_topic = original_topic_match.group(1)
                    else:
                        logger.warning("Could not determine original topic for message in %s", topic)
                        return
                
                # Check if we should retry
                if retry_count >= self.max_retries:
                    logger.warning(
                        "Message has reached max retries (%d): topic=%s, error=%s", 
                        self.max_retries, original_topic, error_info.get("message")
                    )
                    return
                
                # Calculate backoff delay using exponential backoff with jitter
                delay_ms = min(
                    self.initial_retry_delay_ms * (self.backoff_multiplier ** retry_count),
                    self.max_retry_delay_ms
                )
                
                # Log retry attempt
                logger.info(
                    "Retrying message from %s (attempt %d/%d) after %dms delay",
                    original_topic, retry_count + 1, self.max_retries, delay_ms
                )
                
                # Increment retry attempts counter
                DLQ_RETRY_ATTEMPTS.inc()
                
                # Wait for backoff delay
                await asyncio.sleep(delay_ms / 1000)
                
                # Send message back to original topic
                try:
                    # Prepare message for retry
                    retry_value = json.dumps(original_message).encode('utf-8')
                    
                    # Send to original topic
                    self.producer.produce(
                        original_topic,
                        retry_value,
                        callback=lambda err, msg: self._retry_callback(err, msg, topic, retry_count)
                    )
                    self.producer.poll(0)  # Trigger delivery reports
                    
                    logger.info(
                        "Message sent back to original topic %s (retry %d/%d)",
                        original_topic, retry_count + 1, self.max_retries
                    )
                except Exception as e:
                    logger.error("Error retrying message: %s", str(e))
                    DLQ_RETRY_FAILURES.inc()
                    
                    # Send back to DLQ with incremented retry count
                    metadata["retry_count"] = retry_count + 1
                    self.dlq_handler.send_to_dlq(
                        topic,
                        original_message,
                        e,
                        retry_count + 1,
                        original_topic
                    )
            
            except json.JSONDecodeError as e:
                logger.error("Error decoding DLQ message: %s", str(e))
                DLQ_PROCESSOR_ERRORS.inc()
            except Exception as e:
                logger.error("Error processing DLQ message: %s", str(e), exc_info=True)
                DLQ_PROCESSOR_ERRORS.inc()
        
        except Exception as e:
            logger.error("Error in message processing loop: %s", str(e), exc_info=True)
            DLQ_PROCESSOR_ERRORS.inc()
    
    def _retry_callback(self, err, msg, dlq_topic, retry_count):
        """Callback for retry message delivery."""
        if err is not None:
            logger.error("Retry delivery failed: %s", err)
            DLQ_RETRY_FAILURES.inc()
        else:
            logger.debug(
                "Retry delivered to %s [%d] at offset %d",
                msg.topic(), msg.partition(), msg.offset()
            )
            DLQ_RETRY_SUCCESSES.inc()
    
    def _cleanup(self):
        """Clean up resources used by the DLQ processor."""
        logger.info("Cleaning up DLQ Processor resources")
        
        if self.consumer:
            try:
                self.consumer.close()
            except Exception as e:
                logger.error("Error closing consumer: %s", str(e))
        
        if self.producer:
            try:
                self.producer.flush()
            except Exception as e:
                logger.error("Error flushing producer: %s", str(e))
        
        if self.dlq_handler:
            try:
                self.dlq_handler.close()
            except Exception as e:
                logger.error("Error closing DLQ handler: %s", str(e))
        
        logger.info("DLQ Processor resources cleaned up") 