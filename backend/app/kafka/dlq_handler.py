# backend/app/kafka/dlq_handler.py

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import uuid

from .kafka_setup import get_kafka_producer # Use the shared producer setup
from ..core.config import settings

logger = logging.getLogger(__name__)

def get_message_key(message_data: Dict[str, Any]) -> str:
    """Extracts a string key from message data, with fallback to UUID generation."""
    if isinstance(message_data, dict):
        # Try to get the primary identifier for the message type
        for key_field in ['stream_id', 'id', 'message_id', 'room_id']:
            if key_field in message_data and message_data[key_field]:
                return str(message_data[key_field])
    
    # Fallback to a new UUID if we can't find a good key
    return str(uuid.uuid4())

class DLQHandler:
    # Map of original topics to their corresponding DLQ topics
    _topic_to_dlq_map = {
        settings.KAFKA_TOPIC_STREAM_CONTROL: settings.KAFKA_TOPIC_STREAM_CONTROL_DLQ,
        settings.KAFKA_TOPIC_STREAM_STATUS: settings.KAFKA_TOPIC_STREAM_STATUS_DLQ,
        settings.KAFKA_TOPIC_WEBRTC_SIGNALING_IN: settings.KAFKA_TOPIC_WEBRTC_SIGNALING_IN_DLQ,
        settings.KAFKA_TOPIC_WEBRTC_SIGNALING_OUT: settings.KAFKA_TOPIC_WEBRTC_SIGNALING_OUT_DLQ,
    }

    @staticmethod
    def send_to_dlq(
        original_topic: str,
        failed_message_value: Any, # Can be dict or bytes depending on deserialization stage
        failed_message_key: Optional[bytes],
        error: str,
        consumer_group: str
    ) -> bool:
        """
        Sends a failed message to the appropriate Dead Letter Queue topic.
        
        Args:
            original_topic: The topic where the message failed processing
            failed_message_value: The value of the failed message (can be dict or bytes)
            failed_message_key: The key of the failed message (in bytes)
            error: Description of the error
            consumer_group: The consumer group that encountered the error
            
        Returns:
            bool: True if successfully sent to DLQ, False otherwise
        """
        logger.info(f"Sending failed message to DLQ for topic {original_topic}: {error}")
        
        # Get DLQ producer
        producer = get_kafka_producer()
        if not producer:
            logger.error("Failed to get Kafka producer for DLQ")
            return False
            
        # Get the corresponding DLQ topic
        dlq_topic = DLQHandler._topic_to_dlq_map.get(original_topic)
        if not dlq_topic:
            # Fallback to a naming convention if not explicitly mapped
            dlq_topic = f"{original_topic}_dlq"
            logger.warning(f"No explicit DLQ mapping found for {original_topic}, using {dlq_topic}")
            
        # Prepare metadata wrapper for the failed message
        timestamp = datetime.utcnow().isoformat()
        message_key = failed_message_key.decode('utf-8') if failed_message_key else None
        
        # Create DLQ metadata wrapper
        dlq_message = {
            "original_topic": original_topic,
            "original_key": message_key,
            "error": error,
            "consumer_group": consumer_group,
            "timestamp": timestamp,
            "retry_count": 0,
            "payload": failed_message_value if isinstance(failed_message_value, dict) else None,
            "payload_bytes": failed_message_value if isinstance(failed_message_value, bytes) else None
        }
        
        try:
            # Use the original message key if available, otherwise generate from content
            key = message_key or get_message_key(failed_message_value if isinstance(failed_message_value, dict) else {})
            
            # Produce to DLQ topic
            producer.produce(
                topic=dlq_topic,
                key=key,
                value=dlq_message,
                # For DLQ we can default to string serializer if schema doesn't match
                on_delivery=lambda err, msg: logger.error(f"DLQ delivery failed: {err}") if err else None
            )
            producer.poll(0)  # Non-blocking poll
            return True
        except Exception as e:
            logger.exception(f"Error sending to DLQ: {e}")
            return False

    # TODO: Implement a separate service or script to process DLQ topics
    # staticmethod
    # def process_dlq(dlq_topic: str, max_retries: int = 3):
    #     pass 