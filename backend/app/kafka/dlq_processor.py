# backend/app/kafka/dlq_processor.py

import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from confluent_kafka import Consumer, KafkaError, Producer

from ..core.config import settings
from .kafka_setup import get_kafka_producer

logger = logging.getLogger(__name__)

def requeue_message(topic: str, key: bytes, value: bytes):
    """
    Requeues a message to its original topic
    
    Args:
        topic: The original topic to requeue the message to
        key: Message key as bytes
        value: Message value as bytes
    """
    producer = get_kafka_producer()
    if not producer:
        logger.error(f"Failed to get Kafka producer for requeuing to {topic}")
        return False
        
    try:
        producer.produce(
            topic=topic,
            key=key,
            value=value,
            on_delivery=lambda err, msg: logger.error(f"Requeue delivery failed: {err}") if err else None
        )
        producer.poll(0)  # Non-blocking poll
        return True
    except Exception as e:
        logger.exception(f"Error requeuing message to {topic}: {e}")
        return False

async def process_dlq_messages():
    """
    Process messages from Dead Letter Queue topics, with retry logic
    
    This function should be run periodically (e.g., every 5-15 minutes)
    to retry processing messages that have failed.
    """
    logger.info("Starting DLQ processor task")
    
    # List of DLQ topics to process
    dlq_topics = [
        settings.KAFKA_TOPIC_STREAM_CONTROL_DLQ,
        settings.KAFKA_TOPIC_STREAM_STATUS_DLQ,
        settings.KAFKA_TOPIC_WEBRTC_SIGNALING_IN_DLQ,
        settings.KAFKA_TOPIC_WEBRTC_SIGNALING_OUT_DLQ,
        settings.KAFKA_TOPIC_CHAT_DLQ
    ]
    
    # Map DLQ topics back to their original topics
    dlq_to_original_map = {
        settings.KAFKA_TOPIC_STREAM_CONTROL_DLQ: settings.KAFKA_TOPIC_STREAM_CONTROL,
        settings.KAFKA_TOPIC_STREAM_STATUS_DLQ: settings.KAFKA_TOPIC_STREAM_STATUS,
        settings.KAFKA_TOPIC_WEBRTC_SIGNALING_IN_DLQ: settings.KAFKA_TOPIC_WEBRTC_SIGNALING_IN,
        settings.KAFKA_TOPIC_WEBRTC_SIGNALING_OUT_DLQ: settings.KAFKA_TOPIC_WEBRTC_SIGNALING_OUT,
        # Add more mappings as needed
    }
    
    # Create a kafka consumer for the DLQ topics
    consumer_config = {
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': 'dlq-processor-group',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': False,
    }
    
    # Create a permanent error topic producer
    # Messages that exceed max retries go here for manual inspection
    perm_error_topic = "permanent_errors"
    
    try:
        consumer = Consumer(consumer_config)
        consumer.subscribe(dlq_topics)
        logger.info(f"DLQ processor subscribed to topics: {dlq_topics}")
        
        # Maximum number of messages to process in one batch
        max_messages = 100
        # Maximum retries for a message
        max_retries = 3
        # Time to wait between retries (increases with retry count)
        retry_backoff_base = 15  # minutes
        
        message_count = 0
        
        # Process messages until reaching max or no more messages
        while message_count < max_messages:
            msg = consumer.poll(1.0)
            
            if msg is None:
                await asyncio.sleep(0.1)
                continue
                
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error(f"DLQ Consumer Error: {msg.error()}")
                await asyncio.sleep(5)
                continue
                
            # Process the DLQ message
            try:
                # Parse the DLQ message
                dlq_topic = msg.topic()
                dlq_message = json.loads(msg.value())
                
                # Extract metadata
                original_topic = dlq_message.get("original_topic")
                error = dlq_message.get("error")
                retry_count = dlq_message.get("retry_count", 0)
                timestamp = dlq_message.get("timestamp")
                
                # Get the payload (could be in 'payload' or 'payload_bytes')
                payload = dlq_message.get("payload")
                payload_bytes = dlq_message.get("payload_bytes")
                
                # Get original message key
                original_key = dlq_message.get("original_key")
                if original_key:
                    original_key = original_key.encode('utf-8')
                else:
                    original_key = msg.key()
                
                logger.info(f"Processing DLQ message from {dlq_topic}, original topic: {original_topic}, retry count: {retry_count}")
                
                # Check if we should retry based on retry count and timestamp
                if retry_count >= max_retries:
                    logger.warning(f"Message exceeded max retries ({max_retries}), moving to permanent error topic")
                    # Add to permanent error topic
                    dlq_message["final_error"] = f"Exceeded maximum retry count of {max_retries}"
                    requeue_message(perm_error_topic, original_key, json.dumps(dlq_message).encode('utf-8'))
                else:
                    # Check if enough time has passed since last retry (exponential backoff)
                    backoff_minutes = retry_backoff_base * (2 ** retry_count)
                    if timestamp:
                        last_attempt = datetime.fromisoformat(timestamp)
                        now = datetime.utcnow()
                        time_since_last = now - last_attempt
                        
                        if time_since_last < timedelta(minutes=backoff_minutes):
                            logger.info(f"Not enough time elapsed for retry #{retry_count+1}, skipping for now")
                            # Skip this message for now, we'll process it later
                            consumer.commit(message=msg)
                            continue
                    
                    # Attempt to requeue to the original topic
                    logger.info(f"Retrying message, attempt #{retry_count+1}")
                    
                    # Get the mapped original topic or use the one from the message
                    mapped_topic = dlq_to_original_map.get(dlq_topic, original_topic)
                    
                    # Prepare the message for requeuing
                    if payload:
                        # If we have a dict payload, requeue it
                        requeue_message(mapped_topic, original_key, json.dumps(payload).encode('utf-8'))
                    elif payload_bytes:
                        # If we have bytes, requeue as is
                        requeue_message(mapped_topic, original_key, payload_bytes.encode('utf-8') if isinstance(payload_bytes, str) else payload_bytes)
                    else:
                        logger.error(f"No valid payload found in DLQ message")
                        # Move to permanent error topic
                        dlq_message["final_error"] = "No valid payload found for requeuing"
                        requeue_message(perm_error_topic, original_key, json.dumps(dlq_message).encode('utf-8'))
                    
                    # Increment the retry count for future attempts
                    dlq_message["retry_count"] = retry_count + 1
                    dlq_message["timestamp"] = datetime.utcnow().isoformat()
                    
                    # Put back in DLQ with updated retry count
                    requeue_message(dlq_topic, original_key, json.dumps(dlq_message).encode('utf-8'))
                
                # Commit the message offset
                consumer.commit(message=msg)
                message_count += 1
                
            except Exception as e:
                logger.exception(f"Error processing DLQ message: {e}")
                # Skip this message for now
                consumer.commit(message=msg)
                
        logger.info(f"DLQ processor completed batch, processed {message_count} messages")
        
    except Exception as e:
        logger.exception(f"Error in DLQ processor: {e}")
    finally:
        if 'consumer' in locals():
            consumer.close()
        logger.info("DLQ processor task completed")

if __name__ == "__main__":
    # This allows running the script standalone
    logger.info("Starting Standalone DLQ Processor...")
    # Add signal handling for graceful shutdown if needed
    try:
        asyncio.run(process_dlq_messages())
    except KeyboardInterrupt:
        logger.info("DLQ Processor stopped manually.") 