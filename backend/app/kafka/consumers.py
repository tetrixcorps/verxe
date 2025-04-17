# backend/app/kafka/consumers.py

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from confluent_kafka import DeserializingConsumer, KafkaError, KafkaException

from ..core.config import settings
from ..core.database import SessionLocal # To create sessions for updates
from ..services.stream_service import StreamService
from .kafka_setup import get_kafka_consumer # We will create this helper

logger = logging.getLogger(__name__)

async def update_stream_status_in_db(stream_id_str: str, status: str, metadata: dict = None):
    """Helper function to update stream status in a new DB session."""
    async with SessionLocal() as db:
        try:
            stream_service = StreamService(db)
            stream_id = UUID(stream_id_str)
            stream = await stream_service.get_stream(stream_id)
            if not stream:
                logger.warning(f"[StatusConsumer] Stream not found in DB: {stream_id}, cannot update status to {status}")
                return

            # Update logic based on status
            # Avoid overwriting a terminal state like ERROR/ENDED with LIVE?
            # Current simple approach: just update to the latest received status
            stream.status = status
            # Potentially update other fields based on status/metadata (e.g., recording_url on ENDED)
            
            await db.commit()
            logger.info(f"[StatusConsumer] Updated stream {stream_id} status to {status}")

        except ValueError: # Invalid UUID
             logger.warning(f"[StatusConsumer] Received invalid stream_id format: {stream_id_str}")
        except Exception as e:
            logger.exception(f"[StatusConsumer] Error updating stream status in DB for {stream_id_str}: {e}")
            await db.rollback() # Rollback on error

async def stream_status_consumer_task():
    """Async task to consume stream status events from Kafka."""
    logger.info("Starting Stream Status Kafka Consumer Task...")
    consumer = get_kafka_consumer(settings.KAFKA_TOPIC_STREAM_STATUS, 'stream-status-group')
    if not consumer:
        logger.error("Failed to create Kafka consumer for stream status. Task exiting.")
        return

    try:
        consumer.subscribe([settings.KAFKA_TOPIC_STREAM_STATUS])
        logger.info(f"Subscribed to Kafka status topic: {settings.KAFKA_TOPIC_STREAM_STATUS}")

        while True:
            try:
                msg = consumer.poll(1.0)

                if msg is None:
                    await asyncio.sleep(0.1)
                    continue
                
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        logger.error(f"[StatusConsumer] Kafka Error: {msg.error()}")
                        # Implement proper backoff/retry later
                        await asyncio.sleep(5) 
                        continue

                status_data = msg.value()
                if status_data is None: # Deserialization error
                    logger.error(f"[StatusConsumer] Failed to deserialize message from topic {msg.topic()}: key={msg.key()}")
                    # Commit offset to skip bad message
                    consumer.commit(message=msg, asynchronous=False)
                    continue

                stream_id = status_data.get('stream_id')
                status = status_data.get('status')
                metadata = status_data.get('metadata') # Optional
                
                if not stream_id or not status:
                    logger.warning(f"[StatusConsumer] Ignoring status message with missing stream_id or status: {status_data}")
                    consumer.commit(message=msg, asynchronous=False)
                    continue
                
                logger.info(f"[StatusConsumer] Received status '{status}' for stream: {stream_id}")
                
                # Process the status update (e.g., update DB)
                await update_stream_status_in_db(stream_id, status, metadata)

                # Commit offset after processing
                consumer.commit(message=msg, asynchronous=False) # Use synchronous commit for simplicity here

            except KafkaException as e:
                logger.error(f"[StatusConsumer] KafkaException: {e}")
                await asyncio.sleep(5) # Wait before continuing
            except Exception as e:
                logger.exception(f"[StatusConsumer] Error processing status message: {e}")
                # Decide if we should commit offset or not depending on error
                await asyncio.sleep(1)
            
            await asyncio.sleep(0.01) # Yield control

    except asyncio.CancelledError:
        logger.info("Stream Status Consumer Task cancelled.")
    except Exception as e:
        logger.exception(f"[StatusConsumer] Unexpected error in consumer task: {e}") # Log exception traceback
    finally:
        logger.info("Closing Stream Status Kafka Consumer.")
        consumer.close() 