import json
from typing import List, Dict, Optional, Any, Set
from uuid import UUID
from datetime import datetime
from sqlalchemy import select, update, delete, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from fastapi import WebSocket

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

// ... existing code ... 