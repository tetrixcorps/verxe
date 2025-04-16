import json
from typing import List, Dict, Optional, Any, Set
from uuid import UUID
from datetime import datetime
from sqlalchemy import select, update, delete, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from fastapi import WebSocket, HTTPException

from ..models.chat import ChatMessage, MessageTranslation
from ..models.user import User
from ..models.room import Room, RoomParticipant
from ..schemas.chat import ChatMessageCreate

class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        # In-memory store of active WebSocket connections
        # In a production environment, this would be stored in Redis or another distributed cache
        if not hasattr(ChatService, '_websocket_connections'):
            ChatService._websocket_connections: Dict[UUID, Dict[UUID, WebSocket]] = {}

    async def delete_message(self, message_id: UUID, user_id: UUID) -> bool:
        """
        Delete (soft delete) a message if the user is the sender or a moderator of the room.
        """
        # Get the message
        query = select(ChatMessage).options(joinedload(ChatMessage.room)).where(ChatMessage.id == message_id)
        result = await self.db.execute(query)
        message = result.scalars().first()
        
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        # Check if user is the sender
        if message.sender_id == user_id:
            message.is_deleted = True
            message.content = "[Message deleted]"
            await self.db.commit()
            return True
        
        # Check if user is room owner or moderator
        room_id = message.room_id
        room = message.room
        
        if room.owner_id == user_id:
            message.is_deleted = True
            message.content = "[Message deleted by moderator]"
            await self.db.commit()
            return True
        
        # Check if user is a moderator
        participant_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == user_id,
                RoomParticipant.is_moderator == True
            )
        )
        participant_result = await self.db.execute(participant_query)
        participant = participant_result.scalars().first()
        
        if participant:
            message.is_deleted = True
            message.content = "[Message deleted by moderator]"
            await self.db.commit()
            return True
        
        raise HTTPException(status_code=403, detail="Not authorized to delete this message")
    
    async def mute_user(self, room_id: UUID, target_user_id: UUID, moderator_id: UUID) -> bool:
        """
        Mute a user in a room if the moderator has permission.
        """
        # Get the room
        room_query = select(Room).where(Room.id == room_id)
        room_result = await self.db.execute(room_query)
        room = room_result.scalars().first()
        
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        # Check if moderator is room owner
        if room.owner_id == moderator_id:
            # Moderator is the owner, they can mute anyone except themselves
            if moderator_id == target_user_id:
                raise HTTPException(status_code=400, detail="Cannot mute yourself")
            
            # Find participant record for target user
            participant_query = select(RoomParticipant).where(
                and_(
                    RoomParticipant.room_id == room_id,
                    RoomParticipant.user_id == target_user_id
                )
            )
            participant_result = await self.db.execute(participant_query)
            participant = participant_result.scalars().first()
            
            if not participant:
                raise HTTPException(status_code=404, detail="User is not a participant in this room")
            
            # Mute the user
            participant.is_muted = True
            await self.db.commit()
            return True
        
        # Check if moderator is a room moderator
        mod_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == moderator_id,
                RoomParticipant.is_moderator == True
            )
        )
        mod_result = await self.db.execute(mod_query)
        mod = mod_result.scalars().first()
        
        if not mod:
            raise HTTPException(status_code=403, detail="Not authorized to mute users in this room")
        
        # Check if target is the room owner or another moderator
        target_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == target_user_id
            )
        )
        target_result = await self.db.execute(target_query)
        target = target_result.scalars().first()
        
        if not target:
            raise HTTPException(status_code=404, detail="User is not a participant in this room")
        
        if target.is_moderator or room.owner_id == target_user_id:
            raise HTTPException(status_code=403, detail="Cannot mute room owner or other moderators")
        
        # Mute the user
        target.is_muted = True
        await self.db.commit()
        return True
    
    async def unmute_user(self, room_id: UUID, target_user_id: UUID, moderator_id: UUID) -> bool:
        """
        Unmute a user in a room if the moderator has permission.
        """
        # Similar logic to mute_user but sets is_muted to False
        # Get the room
        room_query = select(Room).where(Room.id == room_id)
        room_result = await self.db.execute(room_query)
        room = room_result.scalars().first()
        
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        # Check if moderator is room owner or a moderator
        is_owner = room.owner_id == moderator_id
        
        if not is_owner:
            mod_query = select(RoomParticipant).where(
                and_(
                    RoomParticipant.room_id == room_id,
                    RoomParticipant.user_id == moderator_id,
                    RoomParticipant.is_moderator == True
                )
            )
            mod_result = await self.db.execute(mod_query)
            mod = mod_result.scalars().first()
            
            if not mod:
                raise HTTPException(status_code=403, detail="Not authorized to unmute users in this room")
        
        # Find participant record for target user
        participant_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == target_user_id
            )
        )
        participant_result = await self.db.execute(participant_query)
        participant = participant_result.scalars().first()
        
        if not participant:
            raise HTTPException(status_code=404, detail="User is not a participant in this room")
        
        # Unmute the user
        participant.is_muted = False
        await self.db.commit()
        return True
    
    async def promote_to_moderator(self, room_id: UUID, target_user_id: UUID, owner_id: UUID) -> bool:
        """
        Promote a user to moderator status in a room (only room owner can do this).
        """
        # Get the room
        room_query = select(Room).where(Room.id == room_id)
        room_result = await self.db.execute(room_query)
        room = room_result.scalars().first()
        
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        # Check if the requester is the room owner
        if room.owner_id != owner_id:
            raise HTTPException(status_code=403, detail="Only room owner can promote moderators")
        
        # Find participant record for target user
        participant_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == target_user_id
            )
        )
        participant_result = await self.db.execute(participant_query)
        participant = participant_result.scalars().first()
        
        if not participant:
            raise HTTPException(status_code=404, detail="User is not a participant in this room")
        
        # Promote the user to moderator
        participant.is_moderator = True
        await self.db.commit()
        return True
        
    # WebSocket methods
    
    async def connect_websocket(self, websocket: WebSocket, room_id: UUID, user_id: UUID) -> None:
        """
        Connect a WebSocket client to a chat room.
        """
        # Accept the WebSocket connection
        await websocket.accept()
        
        # Initialize room connections dictionary if it doesn't exist
        room_id_str = str(room_id)
        if room_id_str not in ChatService._websocket_connections:
            ChatService._websocket_connections[room_id_str] = {}
        
        # Add the connection
        user_id_str = str(user_id)
        ChatService._websocket_connections[room_id_str][user_id_str] = websocket
        
        # Send a welcome message to the user
        welcome_message = {
            "type": "system",
            "content": f"Welcome to the chat room!",
            "timestamp": datetime.utcnow().isoformat()
        }
        await websocket.send_text(json.dumps(welcome_message))
    
    async def disconnect_websocket(self, room_id: UUID, user_id: UUID) -> None:
        """
        Disconnect a WebSocket client from a chat room.
        """
        room_id_str = str(room_id)
        user_id_str = str(user_id)
        
        if room_id_str in ChatService._websocket_connections:
            if user_id_str in ChatService._websocket_connections[room_id_str]:
                del ChatService._websocket_connections[room_id_str][user_id_str]
            
            # Clean up empty rooms
            if not ChatService._websocket_connections[room_id_str]:
                del ChatService._websocket_connections[room_id_str]
    
    async def broadcast_message(self, room_id: UUID, message: Dict[str, Any]) -> None:
        """
        Broadcast a message to all connected clients in a room.
        """
        room_id_str = str(room_id)
        
        if room_id_str not in ChatService._websocket_connections:
            return
        
        message_json = json.dumps(message)
        
        disconnected_users = []
        for user_id, websocket in ChatService._websocket_connections[room_id_str].items():
            try:
                await websocket.send_text(message_json)
            except Exception:
                disconnected_users.append(user_id)
        
        # Clean up disconnected users
        for user_id in disconnected_users:
            await self.disconnect_websocket(room_id, UUID(user_id))
    
    async def process_message(self, room_id: UUID, user_id: UUID, content: str) -> Dict[str, Any]:
        """
        Process and save a chat message, returning the formatted message for broadcasting.
        """
        # Check if user is a participant and not muted
        participant_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == user_id
            )
        )
        participant_result = await self.db.execute(participant_query)
        participant = participant_result.scalars().first()
        
        if not participant:
            raise HTTPException(status_code=403, detail="User is not a participant in this room")
        
        if participant.is_muted:
            raise HTTPException(status_code=403, detail="User is muted in this room")
        
        # Get user information
        user_query = select(User).where(User.id == user_id)
        user_result = await self.db.execute(user_query)
        user = user_result.scalars().first()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Create and save message
        message = ChatMessage(
            room_id=room_id,
            sender_id=user_id,
            content=content
        )
        
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        
        # Format message for broadcasting
        formatted_message = {
            "id": str(message.id),
            "roomId": str(message.room_id),
            "senderId": str(message.sender_id),
            "content": message.content,
            "timestamp": message.created_at.isoformat(),
            "senderUsername": user.username
        }
        
        return formatted_message 