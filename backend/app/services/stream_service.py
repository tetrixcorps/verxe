import os
import json
import uuid
import secrets
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy import select, update, delete, and_, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload
from fastapi import HTTPException
from confluent_kafka import SerializingProducer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.serialization import StringSerializer
import pathlib # To load schema files

# Add tracing imports
from opentelemetry import trace

from ..models.stream import Stream, StreamSession, StreamViewer
from ..models.user import User
from ..models.room import Room, RoomParticipant
from ..core.config import settings
from ..core.tracing import get_tracer # Assuming tracer setup is in core

# Get tracer instance
tracer = get_tracer()

# --- Kafka Producer Setup with Schema Registry --- 

def load_avro_schema(schema_file: str):
    # Assumes schemas are in backend/schemas/avro/
    schema_path = pathlib.Path(__file__).parent.parent / "schemas" / "avro" / schema_file
    with open(schema_path, 'r') as f:
        return f.read()

# Configure Schema Registry client
schema_registry_conf = {'url': settings.SCHEMA_REGISTRY_URL}
schema_registry_client = SchemaRegistryClient(schema_registry_conf)

# Load schemas
stream_control_schema = load_avro_schema('stream_control.avsc')
# Add other schemas if this service produces other types

# Create serializers
string_serializer = StringSerializer('utf_8')
avro_control_serializer = AvroSerializer(
    schema_registry_client,
    stream_control_schema,
    lambda obj, ctx: obj # Simple to_dict function
)

# Configure producer
producer_config = {
    'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
    'client.id': 'backend-stream-service-producer',
    'key.serializer': string_serializer, # Keys are strings (stream_id)
    'value.serializer': avro_control_serializer # Use Avro for value
}
producer = SerializingProducer(producer_config)

def kafka_delivery_report(err, msg):
    """ Callback for Kafka message delivery reports """
    if err is not None:
        print(f'StreamService: Message delivery failed: {err}')
    # else:
    #     print(f'StreamService: Message delivered to {msg.topic()} [{msg.partition()}]')

class StreamService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.producer = producer # Use the shared producer instance
        # In-memory store of active streams - REMOVED, state should be derived from DB/Kafka
        # if not hasattr(StreamService, '_active_streams'):
        #     StreamService._active_streams: Dict[uuid.UUID, Dict[str, Any]] = {}
    
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
        # TODO: Add logic to filter for "live" streams or based on needs
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
        with tracer.start_as_current_span("StreamService.create_stream") as span:
            span.set_attribute("user_id", str(user_id))
            span.set_attribute("room_id", str(room_id))
            # Verify room exists and user has permission
            room_query = select(Room).where(Room.id == room_id)
            room_result = await self.db.execute(room_query)
            room = room_result.scalars().first()
            
            if not room:
                raise HTTPException(status_code=404, detail="Room not found")
            
            # Check if user is room owner or moderator (permission to create stream)
            can_stream = room.owner_id == user_id
            if not can_stream:
                participant_query = select(RoomParticipant).where(
                    and_(
                        RoomParticipant.room_id == room_id,
                        RoomParticipant.user_id == user_id,
                        RoomParticipant.is_moderator == True
                    )
                )
                participant_result = await self.db.execute(participant_query)
                participant = participant_result.scalars().first()
                if participant:
                    can_stream = True

            if not can_stream:
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
            
            # Add more attributes/events to span if needed
            return stream # Return value inside the span context
    
    async def start_stream(self, stream_id: uuid.UUID, user_id: uuid.UUID) -> Stream:
        with tracer.start_as_current_span("StreamService.start_stream") as span:
            span.set_attribute("stream_id", str(stream_id))
            span.set_attribute("user_id", str(user_id))
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
            
            # --- Send START command to Kafka ---
            command_payload_dict = {
                'command': 'START',
                'stream_id': str(stream.id),
                'stream_key': stream.stream_key,
                'rtmp_url': stream.rtmp_url,
                'is_recorded': stream.is_recorded,
                'user_id': str(user_id),
                'room_id': str(stream.room_id),
                'timestamp': datetime.utcnow().isoformat(),
                'version': 1
            }

            try:
                self.producer.produce(
                    settings.KAFKA_TOPIC_STREAM_CONTROL,
                    key=str(stream.id), # Use stream_id as key for partitioning
                    value=command_payload_dict, # Pass dict for Avro serialization
                    on_delivery=kafka_delivery_report # Use on_delivery with SerializingProducer
                )
                self.producer.poll(0)
            except Exception as e:
                print(f"StreamService: Failed to send START command to Kafka: {e}")
                # Decide if we should rollback DB changes or just log
                raise HTTPException(status_code=500, detail="Failed to initiate stream start")
            # --- End Kafka interaction ---
            
            return stream
    
    async def end_stream(self, stream_id: uuid.UUID, user_id: uuid.UUID) -> Stream:
        with tracer.start_as_current_span("StreamService.end_stream") as span:
            span.set_attribute("stream_id", str(stream_id))
            span.set_attribute("user_id", str(user_id))
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
            
            # Find the latest active session for this stream and update it
            session_query = select(StreamSession).where(
                and_(
                    StreamSession.stream_id == stream.id,
                    StreamSession.ended_at == None
                )
            ).order_by(desc(StreamSession.started_at)) # Get the most recent one
            session_result = await self.db.execute(session_query)
            session = session_result.scalars().first()

            if session:
                end_time = datetime.utcnow()
                session.ended_at = end_time
                session.duration = (end_time - session.started_at).total_seconds()
                # Peak/total viewers should be updated by a separate process consuming media service events

            await self.db.commit()
            await self.db.refresh(stream)

            # --- Send STOP command to Kafka ---
            command_payload_dict = {
                'command': 'STOP',
                'stream_id': str(stream.id),
                'stream_key': stream.stream_key,
                # Set other fields to None or omit if schema allows
                'rtmp_url': None,
                'is_recorded': None,
                'user_id': str(user_id), # Good to know who stopped it
                'room_id': str(stream.room_id),
                'timestamp': datetime.utcnow().isoformat(),
                'version': 1
            }

            try:
                self.producer.produce(
                    settings.KAFKA_TOPIC_STREAM_CONTROL,
                    key=str(stream.id),
                    value=command_payload_dict, # Pass dict for Avro serialization
                    on_delivery=kafka_delivery_report
                )
                self.producer.poll(0)
            except Exception as e:
                # Use structured logging instead of print
                logger.error(f"Failed to send STOP command to Kafka for stream {stream.id}: {e}")
                
                # Implement Outbox Pattern for eventual consistency
                # Create a record in an outbox table for retry processing
                try:
                    from ..models.outbox import OutboxMessage
                    outbox_msg = OutboxMessage(
                        id=uuid.uuid4(),
                        topic=settings.KAFKA_TOPIC_STREAM_CONTROL,
                        key=str(stream.id),
                        value=json.dumps(command_payload_dict),
                        created_at=datetime.utcnow(),
                        status="PENDING"
                    )
                    self.db.add(outbox_msg)
                    await self.db.commit()
                    
                    # Emit metric for monitoring
                    from ..core.metrics import OUTBOX_MESSAGES
                    OUTBOX_MESSAGES.inc({"topic": settings.KAFKA_TOPIC_STREAM_CONTROL, "status": "pending"})
                    
                    logger.info(f"Created outbox message for failed STOP command for stream {stream.id}")
                except Exception as outbox_err:
                    # If outbox also fails, log but don't block the user operation
                    logger.exception(f"Failed to create outbox message for stream {stream.id}: {outbox_err}")
                
                # Record warning in stream history for operations review
                try:
                    from ..models.stream import StreamEvent
                    event = StreamEvent(
                        id=uuid.uuid4(),
                        stream_id=stream.id, 
                        event_type="KAFKA_ERROR",
                        data={"error": str(e), "command": "STOP"},
                        created_at=datetime.utcnow()
                    )
                    self.db.add(event)
                    await self.db.commit()
                except Exception as event_err:
                    logger.exception(f"Failed to record stream event for {stream.id}: {event_err}")
            # --- End Kafka interaction ---
            
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
        ).order_by(desc(StreamViewer.joined_at)) # Find the latest join event
        result = await self.db.execute(query)
        viewer = result.scalars().first()
        
        if not viewer:
            # User might not have an active view record if they joined before this tracking was added
            # Or if they already left. Silently ignore or log?
            return None
        
        # Update leave time and duration
        leave_time = datetime.utcnow()
        viewer.left_at = leave_time
        viewer.watch_duration = (leave_time - viewer.joined_at).total_seconds()
        
        await self.db.commit()
        await self.db.refresh(viewer)
        
        return viewer
    
    async def get_presigned_upload_url(self, user_id: uuid.UUID, filename: str) -> Dict[str, str]:
        """Generate a presigned URL for direct upload to S3"""
        if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
            raise HTTPException(status_code=500, detail="S3 credentials not configured")
        
        try:
            # Initialize S3 client using configured credentials
            session_kwargs = {
                "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
                "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
                "region_name": settings.AWS_REGION
            }
            boto3_session = boto3.Session(**session_kwargs)
            s3_client = boto3_session.client('s3')

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
                "download_url": f"https://{settings.AWS_BUCKET_NAME}.s3.{settings.AWS_REGION}.amazonaws.com/{object_key}" # Use region in URL
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
        with tracer.start_as_current_span("StreamService.get_user_stream_analytics") as span:
            span.set_attribute("user_id", str(user_id))
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