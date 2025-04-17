import json
import asyncio
import logging # Added logger
from typing import Dict, Any, Optional
from uuid import UUID
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException, status # Added status
from sqlalchemy.ext.asyncio import AsyncSession
# from confluent_kafka import Producer, Consumer, KafkaError # Replaced by specific producer/consumer imports
from confluent_kafka import KafkaError
from ..kafka.kafka_setup import get_kafka_consumer, get_kafka_producer # Using setup helpers

from ...core.deps import get_db, get_websocket_user
from ...models.user import User
# from ...services.chat_service import ChatService # Potentially remove if chat handled differently
# from ...services.room_service import RoomService # Potentially remove
from ...schemas.chat import WebSocketMessage # Keep for chat message structure validation maybe?
from ...core.config import settings
from ...core.connection_manager import connection_manager # Use Redis manager
from ...core.kafka_consumer_manager import kafka_consumer_manager # Added
from ...services.signaling_service import SignalingService # Added

logger = logging.getLogger(__name__) # Added logger instance
router = APIRouter()

# --- Kafka Producer (Moved setup to kafka_setup.py, get instance here) ---
producer = get_kafka_producer() # Get producer instance via helper

# Removed local delivery report, assume setup in kafka_setup
# def kafka_delivery_report(err, msg):
#    ...

# Removed local ConnectionManager definition

# --- Kafka Consumer Task --- 
async def kafka_consumer_task(client_id: str):
    """Runs in the background polling Kafka and sending to WebSocket via ConnectionManager."""
    # Use the helper to create a consumer configured for this user/task
    # Subscription logic needs refinement based on actual topic strategy
    # Example: Subscribe to a user-specific outgoing signaling topic
    # and potentially a general status topic (filtering needed)
    # For now, just demonstrating setup for a specific topic
    topic_to_subscribe = settings.KAFKA_TOPIC_WEBRTC_SIGNALING_OUT # Placeholder
    group_id = f'websocket-group-{client_id}'
    
    consumer = get_kafka_consumer(topic_to_subscribe, group_id)
    if not consumer:
        logger.error(f"Failed to create Kafka consumer for {client_id}. Task exiting.")
        return

    try:
        consumer.subscribe([topic_to_subscribe])
        logger.info(f"[{client_id}] Subscribed to Kafka topic: {topic_to_subscribe}")

        while True:
            try:
                msg = consumer.poll(1.0) # Poll for messages
                if msg is None:
                    await asyncio.sleep(0.1) 
                    continue
                
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        pass
                    else:
                        logger.error(f"[{client_id}] Kafka Consumer Error: {msg.error()}")
                        await asyncio.sleep(5) # Basic retry delay
                else:
                    # Proper message - value is already deserialized dict
                    message_data = msg.value()
                    if message_data is None: # Handle potential deserialization errors
                        logger.error(f"[{client_id}] Failed to deserialize message from topic {msg.topic()}: key={msg.key()}")
                        consumer.commit(message=msg, asynchronous=False) # Commit bad message to skip
                        continue
                    
                    logger.debug(f"[{client_id}] Received message from Kafka topic {msg.topic()}: {message_data}")
                    
                    # Forward message using the connection manager
                    # The message_data (dict) needs to be serialized back to JSON string for WebSocket
                    await connection_manager.broadcast_to_user(client_id, json.dumps(message_data))
                    
                    # Commit offset after successful broadcast
                    consumer.commit(message=msg, asynchronous=False) 

            except Exception as e:
                logger.exception(f"[{client_id}] Error processing Kafka message: {e}")
                await asyncio.sleep(1) # Wait after general processing error

            await asyncio.sleep(0.01)
            
    except asyncio.CancelledError:
        logger.info(f"Kafka consumer task cancelled for {client_id}.")
    except Exception as e:
        logger.exception(f"[{client_id}] Kafka consumer task encountered unrecoverable error: {e}")
    finally:
        logger.info(f"Closing Kafka consumer for {client_id}.")
        consumer.close()

# --- Main WebSocket Endpoint --- 
@router.websocket("/ws/{client_id}") 
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: str, 
    token: str = Query(...),
    db: AsyncSession = Depends(get_db) # Keep DB dependency if needed for auth/other logic
):
    """
    WebSocket endpoint for bi-directional communication (chat, signaling, events).
    Uses client_id (e.g., user_id) for routing.
    """
    # 1. Authenticate User
    user = await get_websocket_user(token, db)
    if not user or str(user.id) != client_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 2. Register Connection (Handles accept)
    try:
        connection_id = await connection_manager.register_connection(client_id, websocket)
    except ConnectionError as e:
        logger.error(f"Failed to register WS connection for {client_id} due to Redis error: {e}")
        # Close without sending message if accept failed implicitly
        # await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Connection backend unavailable")
        return
    except Exception as e: 
        logger.error(f"Failed to accept/register WS connection for {client_id}: {e}")
        return 
        
    logger.info(f"WebSocket connected: client_id={client_id}, connection_id={connection_id}")

    # --- Define message handler for this connection --- 
    async def handle_kafka_message(topic: str, message: Dict) -> None:
        """Handler callback for processing Kafka messages for this specific client."""
        # Ensure the connection is still active locally
        if connection_id not in connection_manager.local_connections:
             # logger.debug(f"Local connection {connection_id} no longer active for client {client_id}, skipping Kafka message handling.")
             # Optionally, tell the manager to remove this specific handler?
             # await kafka_consumer_manager.remove_subscriber(client_id, topic)
             return 
             
        logger.debug(f"[{client_id}] Handler received message from Kafka topic {topic}: {message}")
        # Forward message using the connection manager (which checks local first)
        await connection_manager.broadcast_to_user(client_id, json.dumps(message))

    # --- Subscribe to relevant topics using the manager --- 
    topics_to_subscribe = [
        settings.KAFKA_TOPIC_WEBRTC_SIGNALING_OUT, 
        settings.KAFKA_TOPIC_STREAM_STATUS
        # Add more topics as needed (e.g., room chat, notifications)
    ]
    try:
        for topic in topics_to_subscribe:
            await kafka_consumer_manager.add_subscriber(client_id, topic, handle_kafka_message)
        logger.info(f"[{client_id}] Subscribed to topics via KafkaConsumerManager: {topics_to_subscribe}")
    except Exception as e:
        logger.error(f"[{client_id}] Failed to subscribe via KafkaConsumerManager: {e}")
        await connection_manager.disconnect(connection_id, client_id)
        return # Close connection if subscription fails

    # 4. Main Loop: Receive messages from client and handle/produce to Kafka
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message_data = json.loads(data)
                message_type = message_data.get('type')
                payload = message_data.get('payload', {})

                # --- Handle different message types --- 
                if message_type == 'chat':
                    logger.info(f"[{client_id}] Received chat message (TODO): {payload}")
                    # TODO: Produce to chat topic, handle via ChatService?
                    
                elif message_type == 'webrtc_signal':
                    logger.debug(f"[{client_id}] Received WebRTC signal: {payload}")
                    # Use the SignalingService to process and forward
                    success = await SignalingService.process_incoming_signal(client_id, payload)
                    if not success:
                        # Optionally notify client of processing failure
                        try:
                            await websocket.send_json({
                                "type": "error",
                                "payload": {"message": "Failed to process signaling message"}
                            })
                        except Exception as send_err:
                             logger.warning(f"[{client_id}] Failed to send signaling error to client: {send_err}")

                elif message_type == 'stream_control':
                     logger.info(f"[{client_id}] Received Stream Control (TODO): {payload}")
                     # TODO: Validate user permission before producing control command?
                     # command = payload.get('command') 
                     # stream_id = payload.get('streamId') 
                     # Produce control command to KAFKA_TOPIC_STREAM_CONTROL (as done in StreamService)
                     # Might require a different producer with stream_control schema

                else:
                    logger.warning(f"[{client_id}] Unknown message type received: {message_type}")
                
            except json.JSONDecodeError:
                logger.warning(f"[{client_id}] Received invalid JSON: {data}")
            except Exception as e:
                logger.exception(f"[{client_id}] Error processing client message: {e}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: client_id={client_id}, connection_id={connection_id}")
    except Exception as e:
        logger.exception(f"WebSocket Error for {client_id}: {e}")
    finally:
        logger.info(f"Cleaning up connection for client_id={client_id}, connection_id={connection_id}")
        # Disconnect Redis entry
        await connection_manager.disconnect(connection_id, client_id)
        # Remove subscriptions from Kafka Consumer Manager
        await kafka_consumer_manager.remove_subscriber(client_id) # Remove from all topics
        logger.info(f"Cleanup complete for {client_id}") 