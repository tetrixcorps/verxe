import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, Float, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ..core.database import Base

class Stream(Base):
    __tablename__ = "streams"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    stream_key = Column(String, unique=True, nullable=False, index=True)
    rtmp_url = Column(String, nullable=True)
    playlist_url = Column(String, nullable=True)
    status = Column(String, default="offline")  # offline, live, ended
    is_recorded = Column(Boolean, default=False)
    recording_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    room = relationship("Room", back_populates="streams")
    owner = relationship("User", back_populates="streams")
    sessions = relationship("StreamSession", back_populates="stream", cascade="all, delete-orphan")
    viewers = relationship("StreamViewer", back_populates="stream", cascade="all, delete-orphan")

class StreamSession(Base):
    __tablename__ = "stream_sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stream_id = Column(UUID(as_uuid=True), ForeignKey("streams.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    duration = Column(Float, nullable=True)  # in seconds
    peak_viewers = Column(Integer, default=0)
    total_viewers = Column(Integer, default=0)
    
    # Relationships
    stream = relationship("Stream", back_populates="sessions")

class StreamViewer(Base):
    __tablename__ = "stream_viewers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stream_id = Column(UUID(as_uuid=True), ForeignKey("streams.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    left_at = Column(DateTime, nullable=True)
    watch_duration = Column(Float, nullable=True)  # in seconds
    
    # Relationships
    stream = relationship("Stream", back_populates="viewers")
    user = relationship("User", back_populates="stream_views") 