from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....core.deps import get_current_user, get_db, get_current_active_user
from ....models.user import User
from ....schemas.chat import Room, RoomCreate, RoomWithDetails
from ....services.room_service import RoomService

router = APIRouter()

@router.get("/", response_model=List[RoomWithDetails])
async def list_rooms(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all rooms the user can access.
    """
    room_service = RoomService(db)
    return await room_service.get_rooms(current_user.id)

@router.post("/", response_model=Room, status_code=status.HTTP_201_CREATED)
async def create_room(
    room_data: RoomCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new room.
    """
    room_service = RoomService(db)
    return await room_service.create_room(current_user.id, room_data)

@router.get("/{room_id}", response_model=RoomWithDetails)
async def get_room(
    room_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a room by ID.
    """
    room_service = RoomService(db)
    room = await room_service.get_room(room_id, current_user.id)
    
    # Get participant count
    return await room_service.get_rooms(current_user.id)

@router.post("/{room_id}/join")
async def join_room(
    room_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Join a room.
    """
    room_service = RoomService(db)
    await room_service.join_room(room_id, current_user.id)
    return {"message": "Successfully joined room"}

@router.post("/{room_id}/leave")
async def leave_room(
    room_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Leave a room.
    """
    room_service = RoomService(db)
    await room_service.leave_room(room_id, current_user.id)
    return {"message": "Successfully left room"}

@router.get("/{room_id}/messages")
async def get_room_messages(
    room_id: UUID,
    limit: int = 100,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get messages for a room.
    """
    room_service = RoomService(db)
    messages = await room_service.get_room_messages(room_id, current_user.id, limit)
    return messages 