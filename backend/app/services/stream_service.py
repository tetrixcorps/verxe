import os
import json
import uuid
import subprocess
import secrets
import boto3
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import select, update, delete, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from fastapi import HTTPException

from ..models.stream import Stream, StreamSession, StreamViewer
from ..models.user import User
from ..models.room import Room
from ..core.config import settings

class StreamService:
    def __init__(self, db: AsyncSession):
        self.db = db
        # In-memory store of active streams
        if not hasattr(StreamService, '_active_streams'):
            StreamService._active_streams: Dict[uuid.UUID, Dict[str, Any]] = {}
    
    async def get_stream(self, stream_id: uuid.UUID) -> Optional[Stream]:
        """Get a stream by ID"""
        query = select(Stream).where(Stream.id == stream_id)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def get_stream_by_key(self, stream_key: str) -> Optional[Stream]:
        """Get a stream by stream key"""
        query = select(Stream).where(Stream.stream_key == stream_key)
        result = await self.db.execute(query)
        return result.scalars().first()
    
    async def get_room_streams(self, room_id: uuid.UUID) -> List[Stream]:
        """Get all streams for a room"""
        query = select(Stream).where(Stream.room_id == room_id).order_by(desc(Stream.created_at))
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def get_user_streams(self, user_id: uuid.UUID) -> List[Stream]:
        """Get all streams for a user"""
        query = select(Stream).where(Stream.owner_id == user_id).order_by(desc(Stream.created_at))
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    def _generate_stream_key(self) -> str:
        """Generate a unique stream key"""
        return secrets.token_urlsafe(16)
    
    async def create_stream(self, user_id: uuid.UUID, room_id: uuid.UUID, title: str, description: Optional[str] = None, is_recorded: bool = False) -> Stream:
        """Create a new stream"""
        # Verify room exists and user has permission
        room_query = select(Room).where(Room.id == room_id)
        room_result = await self.db.execute(room_query)
        room = room_result.scalars().first()
        
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        
        # Check if user is room owner or moderator
        if room.owner_id != user_id:
            # Check if user is a moderator
            participant_query = select(RoomParticipant).where(
                and_(
                    RoomParticipant.room_id == room_id,
                    RoomParticipant.user_id == user_id,
                    RoomParticipant.is_moderator == True
                )
            )
            participant_result = await self.db.execute(participant_query)
            participant = participant_result.scalars().first()
            
            if not participant:
                raise HTTPException(status_code=403, detail="User does not have permission to stream in this room")
        
        # Generate a unique stream key
        stream_key = self._generate_stream_key()
        
        # Create the stream
        stream = Stream(
            id=uuid.uuid4(),
            title=title,
            description=description,
            room_id=room_id,
            owner_id=user_id,
            stream_key=stream_key,
            rtmp_url=f"{settings.RTMP_SERVER_URL}/{stream_key}",
            playlist_url=f"{settings.HLS_SERVER_URL}/{stream_key}/playlist.m3u8",
            status="offline",
            is_recorded=is_recorded
        )
        
        self.db.add(stream)
        await self.db.commit()
        await self.db.refresh(stream)
        
        return stream
    
    async def start_stream(self, stream_id: uuid.UUID, user_id: uuid.UUID) -> Stream:
        """Start a stream"""
        # Get the stream
        stream = await self.get_stream(stream_id)
        if not stream:
            raise HTTPException(status_code=404, detail="Stream not found")
        
        # Verify ownership
        if stream.owner_id != user_id:
            raise HTTPException(status_code=403, detail="User does not own this stream")
        
        # Check if already streaming
        if stream.status == "live":
            raise HTTPException(status_code=400, detail="Stream is already live")
        
        # Update stream status
        stream.status = "live"
        
        # Create a stream session
        session = StreamSession(
            id=uuid.uuid4(),
            stream_id=stream.id,
            started_at=datetime.utcnow()
        )
        
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(stream)
        await self.db.refresh(session)
        
        # Store active session in memory
        StreamService._active_streams[stream.id] = {
            "session_id": session.id,
            "start_time": datetime.utcnow(),
            "viewers": set()
        }
        
        # Start GStreamer pipeline if running on server
        if settings.ENABLE_GSTREAMER:
            try:
                self._start_gstreamer_pipeline(stream.stream_key)
            except Exception as e:
                # Log the error but don't fail the request
                print(f"Error starting GStreamer pipeline: {str(e)}")
        
        return stream
    
    async def end_stream(self, stream_id: uuid.UUID, user_id: uuid.UUID) -> Stream:
        """End a stream"""
        # Get the stream
        stream = await self.get_stream(stream_id)
        if not stream:
            raise HTTPException(status_code=404, detail="Stream not found")
        
        # Verify ownership
        if stream.owner_id != user_id:
            raise HTTPException(status_code=403, detail="User does not own this stream")
        
        # Check if streaming
        if stream.status != "live":
            raise HTTPException(status_code=400, detail="Stream is not live")
        
        # Update stream status
        stream.status = "ended"
        
        # Get active session
        active_stream = StreamService._active_streams.get(stream.id)
        if active_stream:
            session_id = active_stream["session_id"]
            
            # Update session end time and stats
            session_query = select(StreamSession).where(StreamSession.id == session_id)
            session_result = await self.db.execute(session_query)
            session = session_result.scalars().first()
            
            if session:
                end_time = datetime.utcnow()
                session.ended_at = end_time
                session.duration = (end_time - session.started_at).total_seconds()
                session.peak_viewers = len(active_stream["viewers"])
                session.total_viewers = len(active_stream["viewers"])
            
            # Clean up in-memory state
            del StreamService._active_streams[stream.id]
        
        await self.db.commit()
        if stream.is_recorded and settings.ENABLE_RECORDING:
            # Upload recording to object storage
            recording_url = await self._upload_recording(stream.stream_key)
            if recording_url:
                stream.recording_url = recording_url
                await self.db.commit()
        
        # Stop GStreamer pipeline if running on server
        if settings.ENABLE_GSTREAMER:
            try:
                self._stop_gstreamer_pipeline(stream.stream_key)
            except Exception as e:
                # Log the error but don't fail the request
                print(f"Error stopping GStreamer pipeline: {str(e)}")
        
        await self.db.refresh(stream)
        return stream
    
    async def join_stream(self, stream_id: uuid.UUID, user_id: uuid.UUID) -> StreamViewer:
        """Record a user joining a stream"""
        # Get the stream
        stream = await self.get_stream(stream_id)
        if not stream:
            raise HTTPException(status_code=404, detail="Stream not found")
        
        # Check if stream is live
        if stream.status != "live":
            raise HTTPException(status_code=400, detail="Stream is not live")
        
        # Create viewer record
        viewer = StreamViewer(
            id=uuid.uuid4(),
            stream_id=stream_id,
            user_id=user_id,
            joined_at=datetime.utcnow()
        )
        
        self.db.add(viewer)
        await self.db.commit()
        await self.db.refresh(viewer)
        
        # Update in-memory active viewers
        active_stream = StreamService._active_streams.get(stream_id)
        if active_stream:
            active_stream["viewers"].add(user_id)
        
        return viewer
    
    async def leave_stream(self, stream_id: uuid.UUID, user_id: uuid.UUID) -> Optional[StreamViewer]:
        """Record a user leaving a stream"""
        # Find the active viewer record
        query = select(StreamViewer).where(
            and_(
                StreamViewer.stream_id == stream_id,
                StreamViewer.user_id == user_id,
                StreamViewer.left_at == None
            )
        )
        result = await self.db.execute(query)
        viewer = result.scalars().first()
        
        if not viewer:
            return None
        
        # Update leave time and duration
        leave_time = datetime.utcnow()
        viewer.left_at = leave_time
        viewer.watch_duration = (leave_time - viewer.joined_at).total_seconds()
        
        await self.db.commit()
        await self.db.refresh(viewer)
        
        # Update in-memory active viewers
        active_stream = StreamService._active_streams.get(stream_id)
        if active_stream and user_id in active_stream["viewers"]:
            active_stream["viewers"].remove(user_id)
        
        return viewer
    
    def _start_gstreamer_pipeline(self, stream_key: str) -> None:
        """Start a GStreamer pipeline for broadcasting"""
        # Example GStreamer pipeline for streaming webcam to RTMP
        # This is a simple example - actual implementation would be more complex
        cmd = [
            "gst-launch-1.0", "-e",
            "v4l2src device=/dev/video0 ! video/x-raw,width=1280,height=720 ! videoconvert ! x264enc tune=zerolatency ! flvmux ! rtmpsink location=rtmp://localhost/live/" + stream_key
        ]
        
        # Start process in background
        subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    def _stop_gstreamer_pipeline(self, stream_key: str) -> None:
        """Stop a GStreamer pipeline"""
        # In a real implementation, you would track the process ID and terminate it
        # This simplified implementation uses pkill to find and kill the process
        cmd = ["pkill", "-f", stream_key]
        subprocess.run(cmd)
    
    async def _upload_recording(self, stream_key: str) -> Optional[str]:
        """Upload recording to object storage (S3)"""
        if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
            return None
        
        try:
            recording_path = f"{settings.RECORDING_PATH}/{stream_key}.flv"
            if not os.path.exists(recording_path):
                return None
            
            # Initialize S3 client
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
            
            # Upload file
            object_key = f"recordings/{stream_key}/{datetime.utcnow().strftime('%Y-%m-%d-%H-%M-%S')}.flv"
            s3_client.upload_file(recording_path, settings.AWS_BUCKET_NAME, object_key)
            
            # Generate URL
            url = f"https://{settings.AWS_BUCKET_NAME}.s3.amazonaws.com/{object_key}"
            
            # Clean up local file
            os.remove(recording_path)
            
            return url
        except Exception as e:
            print(f"Error uploading recording: {str(e)}")
            return None
    
    async def get_presigned_upload_url(self, user_id: uuid.UUID, filename: str) -> Dict[str, str]:
        """Generate a presigned URL for direct upload to S3"""
        if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
            raise HTTPException(status_code=500, detail="S3 credentials not configured")
        
        try:
            # Initialize S3 client
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
            
            # Generate object key
            ext = os.path.splitext(filename)[1]
            object_key = f"uploads/{user_id}/{uuid.uuid4()}{ext}"
            
            # Generate presigned URL
            presigned_url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': settings.AWS_BUCKET_NAME,
                    'Key': object_key,
                    'ContentType': self._get_content_type(ext)
                },
                ExpiresIn=3600  # URL valid for 1 hour
            )
            
            return {
                "upload_url": presigned_url,
                "download_url": f"https://{settings.AWS_BUCKET_NAME}.s3.amazonaws.com/{object_key}"
            }
        except Exception as e:
            print(f"Error generating presigned URL: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")
    
    def _get_content_type(self, extension: str) -> str:
        """Map file extension to content type"""
        content_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.mp4': 'video/mp4',
            '.mov': 'video/quicktime',
            '.flv': 'video/x-flv',
            '.webm': 'video/webm'
        }
        return content_types.get(extension.lower(), 'application/octet-stream')
    
    async def get_user_stream_analytics(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """Get aggregated analytics for a user's streams."""
        
        # Get all streams owned by the user
        stream_query = select(Stream.id).where(Stream.owner_id == user_id)
        stream_result = await self.db.execute(stream_query)
        stream_ids = [row[0] for row in stream_result.all()]
        
        if not stream_ids:
            return {
                "total_streams": 0,
                "total_sessions": 0,
                "total_watch_time_seconds": 0,
                "total_peak_viewers": 0,
                "total_unique_viewers": 0,
                "streams_summary": []
            }
        
        # Aggregate session data
        session_query = select(
            func.count(StreamSession.id).label("total_sessions"),
            func.sum(StreamSession.duration).label("total_duration"),
            func.sum(StreamSession.peak_viewers).label("total_peak_viewers"),
            func.sum(StreamSession.total_viewers).label("total_viewers") # Approx unique, needs refinement
        ).where(StreamSession.stream_id.in_(stream_ids))
        
        session_result = await self.db.execute(session_query)
        session_stats = session_result.first()
        
        # Aggregate viewer data (more accurate unique viewers)
        viewer_query = select(
            func.count(func.distinct(StreamViewer.user_id)).label("total_unique_viewers"),
            func.sum(StreamViewer.watch_duration).label("total_watch_time_seconds")
        ).where(
            StreamViewer.stream_id.in_(stream_ids),
            StreamViewer.watch_duration != None
        )
        
        viewer_result = await self.db.execute(viewer_query)
        viewer_stats = viewer_result.first()

        # Get summary per stream
        stream_summary_query = select(
            Stream.id, Stream.title, Stream.created_at,
            func.count(StreamSession.id).label("session_count"),
            func.sum(StreamSession.duration).label("total_duration"),
            func.sum(StreamSession.peak_viewers).label("peak_viewers")
        ).select_from(Stream).outerjoin(StreamSession, Stream.id == StreamSession.stream_id)\
        .where(Stream.id.in_(stream_ids))\
        .group_by(Stream.id, Stream.title, Stream.created_at)\
        .order_by(Stream.created_at.desc())
        
        stream_summary_result = await self.db.execute(stream_summary_query)
        streams_summary = [\
            {
                "id": str(row.id),
                "title": row.title,
                "created_at": row.created_at.isoformat(),
                "session_count": row.session_count or 0,
                "total_duration_seconds": float(row.total_duration or 0),
                "peak_viewers": row.peak_viewers or 0
            }\
            for row in stream_summary_result.all()\
        ]
        
        return {
            "total_streams": len(stream_ids),
            "total_sessions": session_stats.total_sessions or 0,
            "total_watch_time_seconds": float(viewer_stats.total_watch_time_seconds or 0),
            "total_peak_viewers": session_stats.total_peak_viewers or 0,
            "total_unique_viewers": viewer_stats.total_unique_viewers or 0,
            "streams_summary": streams_summary
        } 