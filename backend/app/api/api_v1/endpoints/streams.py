from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ....core.deps import get_current_user, get_db
from ....models.user import User
from ....schemas.stream import Stream, StreamCreate, StreamWithDetails
from ....services.stream_service import StreamService

router = APIRouter()

@router.post("/", response_model=Stream, status_code=status.HTTP_201_CREATED)
async def create_stream(
    stream_in: StreamCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new stream.
    """
    stream_service = StreamService(db)
    return await stream_service.create_stream(
        user_id=current_user.id,
        room_id=stream_in.room_id,
        title=stream_in.title,
        description=stream_in.description,
        is_recorded=stream_in.is_recorded
    )

@router.get("/", response_model=List[StreamWithDetails])
async def list_streams(
    room_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List streams, optionally filtered by room.
    """
    stream_service = StreamService(db)
    if room_id:
        streams = await stream_service.get_room_streams(room_id)
    else:
        streams = await stream_service.get_user_streams(current_user.id)
    
    # This is simplified - the actual implementation would need to fetch additional data
    # to populate the StreamWithDetails response model
    return streams

@router.get("/{stream_id}", response_model=StreamWithDetails)
async def get_stream(
    stream_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a stream by ID.
    """
    stream_service = StreamService(db)
    stream = await stream_service.get_stream(stream_id)
    
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")
    
    # Simplified - actual implementation would include additional data
    return stream

@router.post("/{stream_id}/start", response_model=Stream)
async def start_stream(
    stream_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Start a stream.
    """
    stream_service = StreamService(db)
    return await stream_service.start_stream(stream_id, current_user.id)

@router.post("/{stream_id}/end", response_model=Stream)
async def end_stream(
    stream_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    End a stream.
    """
    stream_service = StreamService(db)
    return await stream_service.end_stream(stream_id, current_user.id)

@router.post("/{stream_id}/join")
async def join_stream(
    stream_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Join a stream as a viewer.
    """
    stream_service = StreamService(db)
    await stream_service.join_stream(stream_id, current_user.id)
    return {"message": "Joined stream successfully"}

@router.post("/{stream_id}/leave")
async def leave_stream(
    stream_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Leave a stream as a viewer.
    """
    stream_service = StreamService(db)
    await stream_service.leave_stream(stream_id, current_user.id)
    return {"message": "Left stream successfully"}

@router.get("/upload-url")
async def get_upload_url(
    filename: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a pre-signed URL for uploading files to object storage.
    """
    stream_service = StreamService(db)
    return await stream_service.get_presigned_upload_url(current_user.id, filename) 