from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....core.deps import get_current_user, get_db, get_current_active_user
from ....models.user import User
from ....services.chat_service import ChatService

router = APIRouter()

@router.post("/messages/{message_id}/delete")
async def delete_message(
    message_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a message (if user is sender, room owner, or moderator)
    """
    chat_service = ChatService(db)
    await chat_service.delete_message(message_id, current_user.id)
    return {"message": "Message deleted successfully"}

@router.post("/rooms/{room_id}/mute/{user_id}")
async def mute_user(
    room_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Mute a user in a room (if current user is room owner or moderator)
    """
    chat_service = ChatService(db)
    await chat_service.mute_user(room_id, user_id, current_user.id)
    return {"message": "User muted successfully"}

@router.post("/rooms/{room_id}/unmute/{user_id}")
async def unmute_user(
    room_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Unmute a user in a room (if current user is room owner or moderator)
    """
    chat_service = ChatService(db)
    await chat_service.unmute_user(room_id, user_id, current_user.id)
    return {"message": "User unmuted successfully"}

@router.post("/rooms/{room_id}/moderators/{user_id}")
async def promote_to_moderator(
    room_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Promote a user to moderator status (if current user is room owner)
    """
    chat_service = ChatService(db)
    await chat_service.promote_to_moderator(room_id, user_id, current_user.id)
    return {"message": "User promoted to moderator successfully"} 