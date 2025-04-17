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
from ...services.chat_service import ChatService

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
                    logger.info(f"[{client_id}] Received chat message: {payload}")
                    
                    # Validate required fields
                    room_id = payload.get('roomId')
                    content = payload.get('content')
                    
                    if not room_id or not content:
                        logger.warning(f"[{client_id}] Invalid chat message: missing roomId or content")
                        await websocket.send_json({
                            "type": "error",
                            "payload": {"message": "Chat message must include roomId and content"}
                        })
                        continue
                    
                    # Validate user permission for the room
                    try:
                        # Verify user has permission to chat in this room
                        from ...services.signaling_service import verify_room_permission
                        has_permission = await verify_room_permission(client_id, room_id, db)
                        
                        if not has_permission:
                            logger.warning(f"[{client_id}] User not authorized to chat in room {room_id}")
                            await websocket.send_json({
                                "type": "error",
                                "payload": {"message": "Not authorized to chat in this room"}
                            })
                            continue
                        
                        # Process and save the chat message
                        chat_service = ChatService(db)
                        
                        # Process message calls the broadcast internally
                        message_result = await chat_service.process_message(
                            room_id=UUID(room_id),
                            user_id=UUID(client_id),
                            content=content
                        )
                        
                        # No need to send back confirmation as the user will receive 
                        # the message through the broadcast mechanism
                        
                    except Exception as e:
                        logger.exception(f"[{client_id}] Error processing chat message: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "payload": {"message": "Failed to process chat message"}
                        })
                    
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
                    logger.info(f"[{client_id}] Received Stream Control: {payload}")
                    
                    # Extract required stream control parameters
                    command = payload.get('command')
                    stream_id = payload.get('streamId')
                    
                    # Validate required fields
                    if not command or not stream_id:
                        logger.warning(f"[{client_id}] Invalid stream control message: missing command or streamId")
                        await websocket.send_json({
                            "type": "error",
                            "payload": {"message": "Stream control must include command and streamId"}
                        })
                        continue
                    
                    # Validate command type
                    valid_commands = ['START', 'STOP', 'QUERY_STATUS']
                    if command not in valid_commands:
                        logger.warning(f"[{client_id}] Invalid stream control command: {command}")
                        await websocket.send_json({
                            "type": "error",
                            "payload": {"message": f"Invalid command. Must be one of: {', '.join(valid_commands)}"}
                        })
                        continue
                    
                    try:
                        # Verify user has permission to control this stream
                        from ...services.stream_service import StreamService
                        stream_service = StreamService(db)
                        
                        # Get the stream to verify ownership/permissions
                        stream = await stream_service.get_stream(UUID(stream_id))
                        
                        if not stream:
                            logger.warning(f"[{client_id}] Stream not found: {stream_id}")
                            await websocket.send_json({
                                "type": "error",
                                "payload": {"message": "Stream not found"}
                            })
                            continue
                        
                        # Check if user is authorized to control this stream
                        if str(stream.owner_id) != client_id:
                            logger.warning(f"[{client_id}] User not authorized to control stream {stream_id}")
                            await websocket.send_json({
                                "type": "error",
                                "payload": {"message": "Not authorized to control this stream"}
                            })
                            continue
                        
                        # Process the command
                        if command == 'START':
                            # Call the stream service to start the stream
                            result = await stream_service.start_stream(UUID(stream_id), UUID(client_id))
                            await websocket.send_json({
                                "type": "stream_control_response",
                                "payload": {
                                    "status": "success",
                                    "message": "Stream start initiated",
                                    "streamId": stream_id
                                }
                            })
                            
                        elif command == 'STOP':
                            # Call the stream service to end the stream
                            result = await stream_service.end_stream(UUID(stream_id), UUID(client_id))
                            await websocket.send_json({
                                "type": "stream_control_response",
                                "payload": {
                                    "status": "success",
                                    "message": "Stream stop initiated",
                                    "streamId": stream_id
                                }
                            })
                            
                        elif command == 'QUERY_STATUS':
                            # Directly send a Kafka command to query status
                            from ...kafka.kafka_setup import get_kafka_producer
                            from datetime import datetime
                            
                            producer = get_kafka_producer()
                            if producer:
                                # Create a status query command
                                query_command = {
                                    "command": "QUERY_STATUS",
                                    "stream_id": stream_id,
                                    "timestamp": datetime.utcnow().isoformat(),
                                    "version": 1,
                                    # Other fields can be null for this command
                                    "stream_key": None,
                                    "rtmp_url": None,
                                    "is_recorded": None,
                                    "user_id": client_id,
                                    "room_id": str(stream.room_id)
                                }
                                
                                # Produce command to Kafka stream control topic
                                from ...kafka.schema_registry import get_avro_serializer
                                stream_control_serializer = get_avro_serializer("stream_control")
                                
                                producer.produce(
                                    topic=settings.KAFKA_TOPIC_STREAM_CONTROL,
                                    key=stream_id,
                                    value=query_command,
                                    value_serializer=stream_control_serializer,
                                    on_delivery=lambda err, msg: logger.error(f"Status query delivery failed: {err}") if err else None
                                )
                                producer.poll(0)
                                
                                await websocket.send_json({
                                    "type": "stream_control_response",
                                    "payload": {
                                        "status": "success",
                                        "message": "Status query sent",
                                        "streamId": stream_id
                                    }
                                })
                            else:
                                logger.error(f"[{client_id}] Failed to get Kafka producer for status query")
                                await websocket.send_json({
                                    "type": "error",
                                    "payload": {"message": "Failed to send status query"}
                                })
                                
                    except Exception as e:
                        logger.exception(f"[{client_id}] Error processing stream control: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "payload": {"message": "Failed to process stream control command"}
                        })

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