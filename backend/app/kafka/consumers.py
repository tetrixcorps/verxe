# backend/app/kafka/consumers.py

import asyncio
import logging
from uuid import UUID
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from confluent_kafka import DeserializingConsumer, KafkaError, KafkaException

from ..core.config import settings
from ..core.database import SessionLocal # To create sessions for updates
from ..services.stream_service import StreamService
from .kafka_setup import get_kafka_consumer # We will create this helper
from .dlq_handler import DLQHandler # Added DLQ handler

logger = logging.getLogger(__name__)

async def update_stream_status_in_db(stream_id_str: str, status: str, metadata: dict = None):
    """Helper function to update stream status in a new DB session."""
    async with SessionLocal() as db:
        try:
            stream_service = StreamService(db)
            stream_id = UUID(stream_id_str)
            stream = await stream_service.get_stream(stream_id)
            if not stream:
                logger.warning(f"[StatusConsumer] Stream {stream_id} not found, cannot update status.")
                return # Cannot update non-existent stream

            # Idempotency Check Example:
            if stream.status == status:
                logger.debug(f"[StatusConsumer] Stream {stream_id} already in status {status}. Skipping update.")
                return
            # Avoid overwriting terminal states with non-terminal?
            if stream.status in ["ENDED", "ERROR_RUNTIME", "ENDED_EOS", "ENDED_UNEXPECTED"] and status == "LIVE":
                 logger.warning(f"[StatusConsumer] Attempted to set stream {stream_id} to LIVE, but it's already in terminal state {stream.status}. Ignoring.")
                 return

            logger.info(f"[StatusConsumer] Updating stream {stream_id} from {stream.status} to {status}")
            stream.status = status
            stream.updated_at = datetime.utcnow() # Explicitly update timestamp
            # TODO: Add more logic based on status (e.g., save error message from metadata)

            await db.commit()
            # logger.info(f"[StatusConsumer] Updated stream {stream_id} status to {status}") # Moved log up

        except ValueError: # Invalid UUID
             logger.warning(f"[StatusConsumer] Received invalid stream_id format: {stream_id_str}")
        except Exception as e:
            logger.exception(f"[StatusConsumer] Error updating stream status in DB for {stream_id_str}: {e}")
            await db.rollback() # Rollback on error

async def stream_status_consumer_task():
    """Async task to consume stream status events from Kafka."""
    logger.info("Starting Stream Status Kafka Consumer Task...")
    group_id = 'stream-status-group' # Define group_id
    consumer = get_kafka_consumer(settings.KAFKA_TOPIC_STREAM_STATUS, group_id)
    if not consumer:
        logger.error("Failed to create Kafka consumer for stream status. Task exiting.")
        return

    try:
        consumer.subscribe([settings.KAFKA_TOPIC_STREAM_STATUS])
        logger.info(f"Subscribed to Kafka status topic: {settings.KAFKA_TOPIC_STREAM_STATUS}")

        while True:
            processed_successfully = False # Flag to control commit
            msg = None # Ensure msg is defined for commit call
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
                    # Send to DLQ before committing
                    DLQHandler.send_to_dlq(msg.topic(), msg.value(), msg.key(), "Deserialization Error", group_id)
                    consumer.commit(message=msg, asynchronous=False) # Commit bad message to skip
                    continue

                stream_id = status_data.get('stream_id')
                status = status_data.get('status')
                metadata = status_data.get('metadata') # Optional
                
                if not stream_id or not status:
                    logger.warning(f"[StatusConsumer] Ignoring status message with missing fields: {status_data}")
                    DLQHandler.send_to_dlq(msg.topic(), status_data, msg.key(), "Missing stream_id or status", group_id)
                    consumer.commit(message=msg, asynchronous=False) # Commit to skip
                    continue
                
                logger.info(f"[StatusConsumer] Received status '{status}' for stream: {stream_id}")
                
                # Process the status update (DB call)
                await update_stream_status_in_db(stream_id, status, metadata)
                processed_successfully = True # Mark as processed

            except KafkaException as e:
                # Specific Kafka errors during poll/consume - likely needs retry/reconnect
                logger.error(f"[StatusConsumer] KafkaException: {e}")
                await asyncio.sleep(5) 
            except Exception as e:
                # Errors during message processing (DB update, etc.)
                logger.exception(f"[StatusConsumer] Error processing status message: {e}")
                # Send to DLQ on processing failure
                if msg:
                    DLQHandler.send_to_dlq(msg.topic(), msg.value(), msg.key(), str(e), group_id)
                # Commit offset *after* sending to DLQ to avoid reprocessing
                # If DLQ send fails, we might retry or log heavily, but likely still commit
                processed_successfully = True # Mark as processed (by sending to DLQ)
            finally:
                if msg and processed_successfully:
                    try:
                        consumer.commit(message=msg, asynchronous=False)
                    except Exception as commit_err:
                         logger.exception(f"[StatusConsumer] CRITICAL: Failed to commit Kafka offset after processing/DLQ: {commit_err}")
                         
            await asyncio.sleep(0.01) # Yield control

    except asyncio.CancelledError:
        logger.info("Stream Status Consumer Task cancelled.")
    except Exception as e:
        logger.exception(f"[StatusConsumer] Unexpected error in consumer task: {e}") # Log exception traceback
    finally:
        logger.info("Closing Stream Status Kafka Consumer.")
        consumer.close() 