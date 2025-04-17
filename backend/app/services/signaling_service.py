# backend/app/services/signaling_service.py

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from uuid import UUID

from pydantic import ValidationError
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..kafka.kafka_setup import get_kafka_producer
from ..core.config import settings
from ..schemas.signaling import WebRTCSignalRequest, WebRTCSignalEvent
from .room_service import RoomService
from ..core.database import SessionLocal
from ..core.security import create_signaling_token

logger = logging.getLogger(__name__)
producer = get_kafka_producer()

async def verify_room_permission(user_id: str, room_id: str, db_session = None) -> bool:
    """
    Verifies if a user has permission to access a specific room.
    
    Args:
        user_id: The UUID of the user as a string
        room_id: The UUID of the room as a string
        db_session: Optional DB session, will create a new one if not provided
        
    Returns:
        bool: True if the user has permission, False otherwise
    """
    try:
        if db_session is None:
            async with SessionLocal() as db_session:
                return await _check_room_permission(db_session, user_id, room_id)
        else:
            return await _check_room_permission(db_session, user_id, room_id)
    except Exception as e:
        logger.error(f"Error verifying room permission - user: {user_id}, room: {room_id}. Error: {e}")
        return False

async def _check_room_permission(db_session, user_id: str, room_id: str) -> bool:
    """Internal helper to perform the actual permission check with a DB session"""
    from ..models.room import Room, RoomParticipant
    from sqlalchemy import select, and_
    
    try:
        # Convert string IDs to UUID objects
        user_uuid = UUID(user_id)
        room_uuid = UUID(room_id)
        
        # Check if the room exists and is accessible
        room_query = select(Room).where(Room.id == room_uuid)
        room_result = await db_session.execute(room_query)
        room = room_result.scalars().first()
        
        if not room:
            logger.warning(f"Room {room_id} not found during permission check")
            return False
        
        # If the user is the room owner, they always have permission
        if room.owner_id == user_uuid:
            return True
            
        # For public rooms, check if the user is a participant
        # For private rooms, the user must be an explicit participant
        participant_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_uuid,
                RoomParticipant.user_id == user_uuid
            )
        )
        participant_result = await db_session.execute(participant_query)
        participant = participant_result.scalars().first()
        
        # If it's a public room, anyone can access
        # If it's a private room, only participants can access
        if not room.is_private:
            return True
        
        return participant is not None
        
    except ValueError:
        # Invalid UUID format
        logger.error(f"Invalid UUID format - user: {user_id}, room: {room_id}")
        return False
    except Exception as e:
        logger.exception(f"Database error during room permission check: {e}")
        return False

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
        has_permission = await verify_room_permission(client_id, signal_request.roomId)
        if not has_permission:
            logger.warning(f"[{client_id}] Permission denied for room {signal_request.roomId}")
            return False # Indicate failure due to permissions

        # 3. Construct the Kafka event payload
        # Generate a temporary auth token for the media processor to validate this request
        auth_token = create_signaling_token(client_id, signal_request.roomId)
        
        kafka_event_payload = WebRTCSignalEvent(
            type=signal_request.type,
            sender_id=client_id,
            recipient_id=signal_request.recipient_id,
            room_id=signal_request.roomId,
            payload=json.dumps(signal_request.signalData), # Inner payload (SDP/ICE) as JSON string
            timestamp=datetime.utcnow().isoformat(),
            version=1,
            auth_token=auth_token
        ).dict()

        # 4. Produce to Kafka
        if not producer:
            logger.error("Kafka producer is not initialized. Cannot send signal.")
            return False
            
        try:
            # Producer is configured with a default schema in kafka_setup.py
            # For this specific message, we need to ensure it uses the WebRTC signal schema
            from ..kafka.schema_registry import get_schema_registry_client, load_avro_schema
            from confluent_kafka.schema_registry.avro import AvroSerializer
            
            # Get the WebRTC signal schema
            schema_registry_client = get_schema_registry_client()
            webrtc_schema = load_avro_schema("webrtc_signal.avsc")
            
            # Create a serializer for this specific message
            webrtc_serializer = AvroSerializer(
                schema_registry_client,
                webrtc_schema,
                lambda obj, ctx: obj  # Simple to_dict function
            )
            
            producer.produce(
                topic=settings.KAFKA_TOPIC_WEBRTC_SIGNALING_IN,
                key=signal_request.roomId,  # Partition by room_id
                value=kafka_event_payload,  # Use the Avro-compatible dict
                value_serializer=webrtc_serializer,  # Use the specific serializer for WebRTC signals
                on_delivery=lambda err, msg: logger.error(f"Signaling delivery failed: {err}") if err else None
            )
            producer.poll(0)  # Non-blocking poll to ensure message enters send queue
            logger.debug(f"[{client_id}] Produced signal to Kafka: {signal_request.type} for room {signal_request.roomId}")
            return True
        except Exception as e:
            logger.exception(f"[{client_id}] Failed to produce signaling message: {e}")
            return False 