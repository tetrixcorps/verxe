from typing import Optional, List
from pydantic import BaseModel, UUID4
from datetime import datetime

# Message Schema
class ChatMessageBase(BaseModel):
    content: str

class ChatMessageCreate(ChatMessageBase):
    room_id: UUID4

class ChatMessage(ChatMessageBase):
    id: UUID4
    room_id: UUID4
    sender_id: UUID4
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True
        
class ChatMessageResponse(ChatMessage):
    sender_username: str

# Room Schema
class RoomBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_private: bool = False
    
class RoomCreate(RoomBase):
    pass

class Room(RoomBase):
    id: UUID4
    owner_id: UUID4
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True
        
class RoomWithDetails(Room):
    participant_count: int
    
    class Config:
        orm_mode = True
        
# Room Participant Schema
class RoomParticipantBase(BaseModel):
    room_id: UUID4
    user_id: UUID4
    
class RoomParticipant(RoomParticipantBase):
    id: UUID4
    is_moderator: bool = False
    is_muted: bool = False
    joined_at: datetime
    last_read_at: datetime
    
    class Config:
        orm_mode = True

# WebSocket Message Schema
class WebSocketMessage(BaseModel):
    roomId: UUID4
    content: str 