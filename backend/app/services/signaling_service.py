# backend/app/services/signaling_service.py

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from pydantic import ValidationError # Import for validation

from ..kafka.kafka_setup import get_kafka_producer
from ..core.config import settings
from ..schemas.signaling import WebRTCSignalRequest, WebRTCSignalEvent # Will create schemas

logger = logging.getLogger(__name__)
producer = get_kafka_producer() # Use the shared producer

# Placeholder for room/user validation - replace with actual DB calls via RoomService/UserService
async def verify_room_permission(user_id: str, room_id: str, db_session = None) -> bool:
    logger.warning(f"Placeholder: Verifying if user {user_id} has permission for room {room_id}. Replace with actual DB check.")
    # Example check (requires db session and services):
    # room_service = RoomService(db_session)
    # try:
    #     await room_service.get_room(UUID(room_id), UUID(user_id))
    #     return True
    # except HTTPException:
    #     return False
    return True # Allow all for now

class SignalingService:
    @staticmethod
    async def process_incoming_signal(client_id: str, payload: Dict[str, Any]) -> bool:
        """Process, validate, and forward incoming WebRTC signals to Kafka."""
        
        # 1. Validate payload structure using Pydantic model
        try:
            signal_request = WebRTCSignalRequest(**payload)
        except ValidationError as e:
            logger.warning(f"[{client_id}] Invalid incoming signal format: {e}. Payload: {payload}")
            return False # Indicate failure due to validation
            
        # 2. Check user permissions for the room
        # Inject db session if needed here for the permission check
        has_permission = await verify_room_permission(client_id, signal_request.roomId)
        if not has_permission:
            logger.warning(f"[{client_id}] Permission denied for room {signal_request.roomId}")
            return False # Indicate failure due to permissions

        # 3. Construct the Kafka event payload
        kafka_event_payload = WebRTCSignalEvent(
            type=signal_request.type,
            sender_id=client_id,
            recipient_id=signal_request.recipient_id,
            room_id=signal_request.roomId,
            payload=json.dumps(signal_request.signalData), # Inner payload (SDP/ICE) as JSON string
            timestamp=datetime.utcnow().isoformat(),
            version=1
            # auth_token can be added if needed for media processor validation
        ).dict()

        # 4. Produce to Kafka
        if not producer:
            logger.error("Kafka producer is not initialized. Cannot send signal.")
            return False
            
        try:
            producer.produce(
                topic=settings.KAFKA_TOPIC_WEBRTC_SIGNALING_IN,
                key=signal_request.roomId, # Partition by room_id
                value=kafka_event_payload, # Use the Avro-compatible dict
                # schema = ? - Requires producer to handle multiple schemas or a dedicated one
                on_delivery=lambda err, msg: logger.error(f"Signaling delivery failed: {err}") if err else None
            )
            # producer.poll(0) # Optional: non-blocking poll
            logger.debug(f"[{client_id}] Produced signal to Kafka: {signal_request.type} for room {signal_request.roomId}")
            return True
        except Exception as e:
            logger.exception(f"[{client_id}] Failed to produce signaling message: {e}")
            return False 