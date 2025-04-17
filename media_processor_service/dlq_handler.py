# media_processor_service/dlq_handler.py

"""
Dead Letter Queue (DLQ) Handler for the Media Processor Service.

This module provides functionality to handle messages that could not be 
processed normally and need to be sent to a dead letter queue.
"""

import json
import logging
from typing import Dict, Any, Optional, Callable
from confluent_kafka import Producer, KafkaError, KafkaException
import time
from datetime import datetime
import uuid

from .metrics import DLQ_MESSAGES_SENT

logger = logging.getLogger(__name__)

class DLQHandler:
    """
    Handler for sending messages to Dead Letter Queue topics.
    
    This class provides methods to send failed messages to DLQ topics with 
    appropriate metadata for later processing.
    """
    
    def __init__(self, bootstrap_servers: str):
        """
        Initialize the DLQ handler.
        
        Args:
            bootstrap_servers: Kafka bootstrap servers
        """
        self.producer_config = {
            'bootstrap.servers': bootstrap_servers,
            'client.id': f'dlq-handler-{uuid.uuid4()}'
        }
        self.producer = Producer(self.producer_config)
        logger.info("DLQ Handler initialized with bootstrap servers: %s", bootstrap_servers)
    
    def send_to_dlq(
        self, 
        topic: str, 
        message: Dict[str, Any], 
        error: Exception, 
        retry_count: int = 0,
        original_topic: Optional[str] = None
    ) -> None:
        """
        Send a failed message to the corresponding DLQ topic.
        
        Args:
            topic: The DLQ topic to send to
            message: The original message that failed processing
            error: The error that caused the message to be sent to DLQ
            retry_count: The number of times this message has been retried
            original_topic: The original topic the message was from
        """
        # Ensure message is in the right format
        if isinstance(message, bytes):
            try:
                message = json.loads(message.decode('utf-8'))
            except json.JSONDecodeError:
                logger.warning("Failed to decode message as JSON, sending raw bytes to DLQ")
                message = {"raw_content": str(message)}
        
        # Create DLQ message with metadata
        dlq_message = {
            "original_message": message,
            "error": {
                "type": error.__class__.__name__,
                "message": str(error)
            },
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "retry_count": retry_count,
                "original_topic": original_topic
            }
        }
        
        # Encode the message
        encoded_message = json.dumps(dlq_message).encode('utf-8')
        
        # Send to DLQ topic
        try:
            self.producer.produce(
                topic, 
                encoded_message,
                callback=self._delivery_callback
            )
            # Increment the DLQ messages sent metric
            DLQ_MESSAGES_SENT.inc()
            self.producer.poll(0)  # Trigger delivery reports
            logger.info(
                "Message sent to DLQ topic %s (retry=%d): %s", 
                topic, retry_count, error.__class__.__name__
            )
        except KafkaException as e:
            logger.error("Failed to send message to DLQ topic %s: %s", topic, str(e))
    
    def _delivery_callback(self, err, msg):
        """Callback for delivery reports from Kafka Producer."""
        if err is not None:
            logger.error('DLQ message delivery failed: %s', err)
        else:
            logger.debug('DLQ message delivered to %s [%d] at offset %d',
                        msg.topic(), msg.partition(), msg.offset())
    
    def close(self):
        """Close the producer and flush any outstanding messages."""
        logger.info("Closing DLQ Handler and flushing messages")
        self.producer.flush() 