import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, Integer, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from ..core.database import Base

class OutboxMessage(Base):
    """
    Outbox pattern model for reliable message delivery.
    Messages are stored here before being sent to Kafka.
    A separate process reads and processes these messages.
    """
    __tablename__ = "outbox_messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic = Column(String, nullable=False, index=True)
    key = Column(String, nullable=True)
    value = Column(Text, nullable=False)  # JSON string of the message payload
    status = Column(String, default="PENDING", nullable=False, index=True)  # PENDING, PROCESSED, FAILED
    retry_count = Column(Integer, default=0, nullable=False)
    error = Column(Text, nullable=True)  # Error message if failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True) 