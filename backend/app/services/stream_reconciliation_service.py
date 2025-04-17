# backend/app/services/stream_reconciliation_service.py

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.stream import Stream # Assuming status is string: "LIVE", "ERROR", etc.
from ..kafka.kafka_setup import get_kafka_producer
from ..core.config import settings
from ..core.database import SessionLocal # Import SessionLocal to create session

logger = logging.getLogger(__name__)
producer = get_kafka_producer() # Use shared producer

def kafka_delivery_report(err, msg):
    if err is not None:
        logger.error(f"Reconciliation Kafka delivery failed: {err}")

class StreamReconciliationService:
    
    # Store timestamps of last query sent for each stream to avoid spamming
    _last_query_sent: Dict[UUID, datetime] = {}
    _query_interval = timedelta(minutes=2) # Don't query more than once every 2 mins
    _unhealthy_threshold = timedelta(minutes=5) # Mark as suspect if no status update for 5 mins
    _resolve_grace_period = timedelta(minutes=1) # Time to wait for response before marking as error

    @staticmethod
    async def reconcile_streams() -> None:
        """Periodically checks for potentially zombie streams and initiates recovery."""
        logger.info("Running Stream Reconciliation Check...")
        async with SessionLocal() as db:
            try:
                # 1. Find streams potentially stuck in LIVE or STARTING state
                potential_zombies_query = select(Stream).where(
                    Stream.status.in_(["LIVE", "STARTING"]) 
                )
                result = await db.execute(potential_zombies_query)
                streams_to_check = result.scalars().all()

                now = datetime.now(timezone.utc)
                streams_queried = 0

                for stream in streams_to_check:
                    # Check when stream status was last updated in DB
                    # Ensure updated_at is timezone-aware or compare consistently
                    last_update = stream.updated_at.replace(tzinfo=timezone.utc) # Assume UTC
                    time_since_update = now - last_update

                    if time_since_update > StreamReconciliationService._unhealthy_threshold:
                        logger.warning(
                            f"[Reconcile] Potential zombie stream detected: {stream.id}, "
                            f"status: {stream.status}, last updated: {time_since_update} ago"
                        )
                        
                        # Avoid querying too frequently
                        last_query = StreamReconciliationService._last_query_sent.get(stream.id)
                        if last_query and (now - last_query) < StreamReconciliationService._query_interval:
                            logger.debug(f"[Reconcile] Already queried stream {stream.id} recently. Skipping.")
                            continue
                            
                        # Send status query command via Kafka
                        await StreamReconciliationService._query_stream_status(stream.id)
                        StreamReconciliationService._last_query_sent[stream.id] = now # Record query time
                        streams_queried += 1
                        
                        # Schedule a check later to see if status updated
                        asyncio.create_task(
                            StreamReconciliationService._check_stream_response(stream.id, now)
                        )
                        
                logger.info(f"Reconciliation check complete. Found {len(streams_to_check)} potentially live streams. Sent queries for {streams_queried} suspect streams.")

            except Exception as e:
                logger.exception(f"Error during stream reconciliation: {e}")

    @staticmethod
    async def _query_stream_status(stream_id: UUID) -> None:
        """Sends a QUERY_STATUS command to the media processor via Kafka."""
        if not producer:
            logger.error(f"[Reconcile] Kafka producer not available for stream {stream_id}")
            return
            
        command = {
            "command": "QUERY_STATUS",
            "stream_id": str(stream_id),
            "timestamp": datetime.utcnow().isoformat(),
            "version": 1,
            # Other fields can be null according to schema
            "stream_key": None, "rtmp_url": None, "is_recorded": None, "user_id": None, "room_id": None
        }
        
        try:
            producer.produce(
                settings.KAFKA_TOPIC_STREAM_CONTROL,
                key=str(stream_id),
                value=command,
                # Producer should be configured with correct Avro serializer
                on_delivery=kafka_delivery_report
            )
            # producer.poll(0) # Avoid blocking in reconcile loop
            logger.info(f"[Reconcile] Sent QUERY_STATUS command for stream {stream_id}")
        except Exception as e:
            logger.exception(f"[Reconcile] Failed to send status query for stream {stream_id}: {e}")

    @staticmethod
    async def _check_stream_response(stream_id: UUID, query_time: datetime) -> None:
        """Checks if a potentially zombie stream has updated its status after a grace period."""
        await asyncio.sleep(StreamReconciliationService._resolve_grace_period.total_seconds())
        
        logger.info(f"[Reconcile] Checking response for stream {stream_id} queried at {query_time}")
        async with SessionLocal() as db:
            try:
                stream = await db.get(Stream, stream_id)
                
                if not stream:
                    logger.warning(f"[Reconcile] Stream {stream_id} no longer exists during response check.")
                    StreamReconciliationService._last_query_sent.pop(stream_id, None) # Clean up query time
                    return
                    
                # Ensure comparison is timezone aware
                last_update = stream.updated_at.replace(tzinfo=timezone.utc)
                query_time_utc = query_time.replace(tzinfo=timezone.utc)

                # If updated since query OR no longer in LIVE/STARTING state, reconciliation worked or state changed
                if last_update > query_time_utc or stream.status not in ["LIVE", "STARTING"]:
                    logger.info(f"[Reconcile] Stream {stream_id} responded or status changed to {stream.status}. Reconciliation successful.")
                else:
                    # If still in LIVE/STARTING state with no updates, mark as ERROR
                    logger.error(f"[Reconcile] Stream {stream_id} did not respond to status query - marking as ERROR")
                    stream.status = "ERROR" # Consider a specific status like "ERROR_ZOMBIE"?
                    stream.updated_at = datetime.utcnow() 
                    await db.commit()
                    
                    # TODO: Optionally send another Kafka event indicating forced state change
                    # publish_event('stream_events', {'type': 'STREAM_ZOMBIED', ...})

            except Exception as e:
                logger.exception(f"[Reconcile] Error checking stream response for {stream_id}: {e}")
            finally:
                 # Clean up query timestamp regardless of outcome for this check cycle
                 StreamReconciliationService._last_query_sent.pop(stream_id, None) 