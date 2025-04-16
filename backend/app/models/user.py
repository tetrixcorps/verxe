import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ..core.database import Base 

class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=True)
    oauth_provider = Column(String, nullable=True)
    oauth_id = Column(String, nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    badge = Column(String, default='none', nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    follower_count = Column(Integer, default=0)
    
    # User tier based on followers
    # 1 = Basic, 2 = Silver, 3 = Gold, 4 = Diamond
    tier = Column(Integer, default=1)
    
    # Relationships
    owned_rooms = relationship("Room", back_populates="owner", foreign_keys="Room.owner_id")
    room_participations = relationship("RoomParticipant", back_populates="user")
    messages = relationship("ChatMessage", back_populates="sender")
    streams = relationship("Stream", back_populates="owner")
    stream_views = relationship("StreamViewer", back_populates="user")
    token_balance = relationship("TokenBalance", back_populates="user", uselist=False)
    token_transactions = relationship("TokenTransaction", back_populates="user")
    # Many-to-many followers relationship
    following = relationship(
        "UserFollower",
        foreign_keys="UserFollower.follower_id",
        back_populates="follower"
    )
    followers = relationship(
        "UserFollower",
        foreign_keys="UserFollower.followed_id",
        back_populates="followed"
    )

class UserFollower(Base):
    __tablename__ = "user_followers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    follower_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    followed_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    follower = relationship("User", foreign_keys=[follower_id], back_populates="following")
    followed = relationship("User", foreign_keys=[followed_id], back_populates="followers") 