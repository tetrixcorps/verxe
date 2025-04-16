from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from fastapi import HTTPException

from ..models.room import Room, RoomParticipant
from ..models.chat import ChatMessage
from ..models.user import User
from ..schemas.chat import RoomCreate, RoomWithDetails

class RoomService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_rooms(self, user_id: UUID) -> List[RoomWithDetails]:
        """
        Get all rooms accessible to the user.
        Public rooms and rooms the user is a participant in.
        """
        # Query for rooms the user can access:
        # 1. Public rooms
        # 2. Private rooms the user is a participant in
        query = select(Room).outerjoin(
            RoomParticipant,
            and_(
                Room.id == RoomParticipant.room_id,
                RoomParticipant.user_id == user_id
            )
        ).where(
            # Public rooms OR rooms the user participates in
            (Room.is_private == False) | (RoomParticipant.user_id == user_id)
        ).order_by(Room.created_at.desc())
        
        result = await self.db.execute(query)
        rooms = result.scalars().all()
        
        # Get participant count for each room
        rooms_with_details = []
        for room in rooms:
            participant_count_query = select(func.count(RoomParticipant.id)).where(
                RoomParticipant.room_id == room.id
            )
            participant_count_result = await self.db.execute(participant_count_query)
            participant_count = participant_count_result.scalar() or 0
            
            # Create RoomWithDetails
            room_with_details = RoomWithDetails(
                id=room.id,
                name=room.name,
                description=room.description,
                is_private=room.is_private,
                owner_id=room.owner_id,
                created_at=room.created_at,
                updated_at=room.updated_at,
                participant_count=participant_count
            )
            rooms_with_details.append(room_with_details)
        
        return rooms_with_details
    
    async def get_room(self, room_id: UUID, user_id: UUID) -> Room:
        """
        Get a room by ID if the user has access to it.
        """
        room_query = select(Room).where(Room.id == room_id)
        room_result = await self.db.execute(room_query)
        room = room_result.scalars().first()
        
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        # If room is private, check if user is a participant
        if room.is_private and room.owner_id != user_id:
            participant_query = select(RoomParticipant).where(
                and_(
                    RoomParticipant.room_id == room_id,
                    RoomParticipant.user_id == user_id
                )
            )
            participant_result = await self.db.execute(participant_query)
            participant = participant_result.scalars().first()
            
            if not participant:
                raise HTTPException(status_code=403, detail="You don't have access to this room")
        
        return room
    
    async def create_room(self, user_id: UUID, room_data: RoomCreate) -> Room:
        """
        Create a new room with the given user as owner.
        """
        # Create room
        room = Room(
            name=room_data.name,
            description=room_data.description,
            is_private=room_data.is_private,
            owner_id=user_id
        )
        
        self.db.add(room)
        
        # Add owner as a participant and moderator
        room_participant = RoomParticipant(
            room_id=room.id,
            user_id=user_id,
            is_moderator=True
        )
        
        self.db.add(room_participant)
        await self.db.commit()
        await self.db.refresh(room)
        
        return room
    
    async def join_room(self, room_id: UUID, user_id: UUID) -> RoomParticipant:
        """
        Add a user as a participant to a room.
        """
        # Check if room exists
        room_query = select(Room).where(Room.id == room_id)
        room_result = await self.db.execute(room_query)
        room = room_result.scalars().first()
        
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        # If room is private, only the owner can add participants (not implemented here)
        if room.is_private and room.owner_id != user_id:
            raise HTTPException(status_code=403, detail="Cannot join private room without invitation")
        
        # Check if already a participant
        participant_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == user_id
            )
        )
        participant_result = await self.db.execute(participant_query)
        participant = participant_result.scalars().first()
        
        if participant:
            # Update last read time
            participant.last_read_at = datetime.utcnow()
            await self.db.commit()
            return participant
        
        # Add as participant
        new_participant = RoomParticipant(
            room_id=room_id,
            user_id=user_id,
            is_moderator=False,
            is_muted=False
        )
        
        self.db.add(new_participant)
        await self.db.commit()
        await self.db.refresh(new_participant)
        
        return new_participant
    
    async def leave_room(self, room_id: UUID, user_id: UUID) -> bool:
        """
        Remove a user as a participant from a room.
        """
        # Cannot leave room if you're the owner
        room_query = select(Room).where(Room.id == room_id)
        room_result = await self.db.execute(room_query)
        room = room_result.scalars().first()
        
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        if room.owner_id == user_id:
            raise HTTPException(status_code=400, detail="Room owner cannot leave room")
        
        # Delete participant record
        participant_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == user_id
            )
        )
        participant_result = await self.db.execute(participant_query)
        participant = participant_result.scalars().first()
        
        if not participant:
            raise HTTPException(status_code=404, detail="User is not a participant in this room")
        
        await self.db.delete(participant)
        await self.db.commit()
        
        return True
    
    async def get_room_messages(self, room_id: UUID, user_id: UUID, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get messages for a room with sender information.
        """
        # Verify access to room
        await self.get_room(room_id, user_id)
        
        # Get messages with sender information
        query = select(
            ChatMessage, User.username
        ).join(
            User, ChatMessage.sender_id == User.id
        ).where(
            ChatMessage.room_id == room_id
        ).order_by(
            ChatMessage.created_at
        ).limit(limit)
        
        result = await self.db.execute(query)
        rows = result.all()
        
        messages = []
        for msg, username in rows:
            messages.append({
                "id": str(msg.id),
                "roomId": str(msg.room_id),
                "senderId": str(msg.sender_id),
                "content": msg.content,
                "is_deleted": msg.is_deleted,
                "timestamp": msg.created_at.isoformat(),
                "senderUsername": username
            })
        
        # Update last read time for the participant
        participant_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == user_id
            )
        )
        participant_result = await self.db.execute(participant_query)
        participant = participant_result.scalars().first()
        
        if participant:
            participant.last_read_at = datetime.utcnow()
            await self.db.commit()
        
        return messages
    
    async def save_message(self, room_id: UUID, user_id: UUID, content: str) -> ChatMessage:
        """
        Save a message to the database.
        """
        # Verify access to room
        await self.get_room(room_id, user_id)
        
        # Check if user is muted
        participant_query = select(RoomParticipant).where(
            and_(
                RoomParticipant.room_id == room_id,
                RoomParticipant.user_id == user_id
            )
        )
        participant_result = await self.db.execute(participant_query)
        participant = participant_result.scalars().first()
        
        if participant and participant.is_muted:
            raise HTTPException(status_code=403, detail="You are muted in this room")
        
        # Create and save message
        message = ChatMessage(
            room_id=room_id,
            sender_id=user_id,
            content=content
        )
        
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        
        return message 