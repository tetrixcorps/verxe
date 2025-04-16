from typing import Optional, List
from pydantic import BaseModel, UUID4
from datetime import datetime

# Base Stream Schema
class StreamBase(BaseModel):
    title: str
    description: Optional[str] = None
    room_id: UUID4
    is_recorded: Optional[bool] = False

# Create Stream Schema
class StreamCreate(StreamBase):
    pass

# Stream Response Schema (includes generated fields)
class Stream(StreamBase):
    id: UUID4
    owner_id: UUID4
    stream_key: str
    rtmp_url: Optional[str] = None
    playlist_url: Optional[str] = None
    status: str
    recording_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

# Stream with Relations
class StreamWithDetails(Stream):
    viewer_count: int = 0
    owner_username: str
    
    class Config:
        orm_mode = True

# Stream Session
class StreamSession(BaseModel):
    id: UUID4
    stream_id: UUID4
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration: Optional[float] = None
    peak_viewers: int
    total_viewers: int
    
    class Config:
        orm_mode = True

# Stream Viewer
class StreamViewer(BaseModel):
    id: UUID4
    stream_id: UUID4
    user_id: UUID4
    joined_at: datetime
    left_at: Optional[datetime] = None
    watch_duration: Optional[float] = None
    
    class Config:
        orm_mode = True 