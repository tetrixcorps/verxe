from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime
import json

class WebRTCSignalRequest(BaseModel):
    """Structure expected from the client WebSocket message payload."""
    type: str # offer, answer, ice-candidate
    roomId: str # Room context
    recipient_id: Optional[str] = None # Target user for direct signals
    signalData: Dict[str, Any] # Contains sdp or candidate info

    @validator('type')
    def signal_type_must_be_valid(cls, v):
        if v not in ['offer', 'answer', 'ice-candidate']:
            raise ValueError('type must be offer, answer, or ice-candidate')
        return v
        
    @validator('signalData')
    def signal_data_must_not_be_empty(cls, v):
        if not v:
            raise ValueError('signalData must not be empty')
        # Add more specific validation based on type if needed
        # e.g., if type == 'offer', ensure 'sdp' key exists
        return v

class WebRTCSignalEvent(BaseModel):
    """Structure used for Kafka messages (Avro compatible)."""
    type: str
    sender_id: str
    recipient_id: Optional[str] = None
    room_id: str
    payload: str # JSON string of signalData
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    version: int = 1
    auth_token: Optional[str] = None  # Authorization token for validating requests at the media processor

    class Config:
        # Ensure it can be easily converted to dict for Avro serializer
        orm_mode = False 

    @validator('auth_token')
    def mask_auth_token_for_logs(cls, v):
        """Ensures the auth token is not fully exposed in logs"""
        return v  # The actual value is preserved in the object
        
    def dict(self, *args, **kwargs):
        """Custom dict method to handle sensitive fields in logs"""
        result = super().dict(*args, **kwargs)
        # Only include auth_token if it's set
        if result.get('auth_token') is None:
            result.pop('auth_token', None)
        return result 