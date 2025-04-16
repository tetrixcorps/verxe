import json
from typing import Dict, Any, Optional
from uuid import UUID
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_websocket_user
from ...models.user import User
from ...services.chat_service import ChatService
from ...services.room_service import RoomService
from ...schemas.chat import WebSocketMessage

router = APIRouter()

@router.websocket("/ws/chat/{room_id}")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    room_id: UUID,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    WebSocket endpoint for chat messages.
    """
    # Authenticate the user
    user = await get_websocket_user(token, db)
    if not user:
        await websocket.close(code=1008)  # Policy violation
        return
    
    # Create services
    chat_service = ChatService(db)
    room_service = RoomService(db)
    
    try:
        # Verify user has access to room
        try:
            await room_service.get_room(room_id, user.id)
        except HTTPException:
            await websocket.close(code=1003)  # Unauthorized
            return
        
        # Join the room as a participant
        await room_service.join_room(room_id, user.id)
        
        # Connect WebSocket
        await chat_service.connect_websocket(websocket, room_id, user.id)
        
        # Listen for messages
        try:
            while True:
                # Receive message from client
                data = await websocket.receive_text()
                message_data = json.loads(data)
                
                # Validate message format
                try:
                    message = WebSocketMessage(**message_data)
                except Exception:
                    # Invalid message format, ignore
                    continue
                
                # Process message
                try:
                    formatted_message = await chat_service.process_message(
                        room_id, user.id, message.content
                    )
                    
                    # Broadcast message to all clients in the room
                    await chat_service.broadcast_message(room_id, formatted_message)
                except HTTPException as e:
                    # Send error message to client
                    error_message = {
                        "type": "error",
                        "content": e.detail
                    }
                    await websocket.send_text(json.dumps(error_message))
                    
        except WebSocketDisconnect:
            # Clean up connection when client disconnects
            await chat_service.disconnect_websocket(room_id, user.id)
            
    except Exception as e:
        # Handle unexpected errors
        await websocket.close(code=1011)  # Internal error
        print(f"WebSocket error: {str(e)}")
    finally:
        # Make sure connection is properly cleaned up
        try:
            await chat_service.disconnect_websocket(room_id, user.id)
        except Exception:
            pass 