import asyncio
import logging
import os
import signal
import time
import uuid
from typing import Dict, List, Optional, Any

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import (
    API_PORT,
    CORS_ORIGINS,
    SERVICE_NAME,
    DEFAULT_VIDEO_WIDTH,
    DEFAULT_VIDEO_HEIGHT,
    DEFAULT_FRAMERATE,
    MAX_BITRATE,
    get_api_token,
    get_stream_source_url
)
from .models import (
    StreamConfig,
    StreamStatus,
    StreamCommand,
    StreamSessionStats,
    PipelineState
)
from .pipeline import GstPipelineManager

# Setup logging
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="GStreamer Streaming API",
    description="API for controlling GStreamer streaming pipelines",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create pipeline manager
pipeline_manager = GstPipelineManager(status_callback=None)

# Store stream statuses
stream_statuses: Dict[str, StreamStatus] = {}


# API Authentication
async def verify_token(request: Request) -> bool:
    """Verify API token from request header."""
    expected_token = get_api_token()
    if not expected_token:
        # If no token is configured, authentication is disabled
        return True
    
    # Get token from Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return False
    
    # Check if header is in the format "Bearer <token>"
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    
    # Verify token
    token = parts[1]
    return token == expected_token


# Request/Response Models
class CreateStreamRequest(BaseModel):
    """Request model for creating a stream."""
    stream_id: str = Field(..., description="Unique identifier for the stream")
    source_type: str = Field(..., description="Source type (test, rtmp, rtsp, file, webrtc)")
    source_url: Optional[str] = Field(None, description="Source URL (not required for test source)")
    output_type: str = Field(..., description="Output type (rtmp, rtsp, file, webrtc)")
    output_url: str = Field(..., description="Output URL")
    width: int = Field(DEFAULT_VIDEO_WIDTH, description="Video width")
    height: int = Field(DEFAULT_VIDEO_HEIGHT, description="Video height")
    framerate: int = Field(DEFAULT_FRAMERATE, description="Video framerate")
    bitrate: Optional[int] = Field(None, description="Video bitrate in bps")
    audio_enabled: bool = Field(True, description="Whether audio is enabled")
    audio_bitrate: int = Field(128000, description="Audio bitrate in bps")
    is_recording: bool = Field(False, description="Whether recording is enabled")
    recording_path: Optional[str] = Field(None, description="Path to save recordings")
    extra_params: Dict[str, Any] = Field({}, description="Extra parameters for the pipeline")


class StreamResponse(BaseModel):
    """Response model for a stream operation."""
    stream_id: str
    status: str
    message: Optional[str] = None


class StreamStatusResponse(BaseModel):
    """Response model for stream status."""
    stream_id: str
    state: str
    error_message: Optional[str] = None
    stats: Dict[str, Any] = {}
    uptime: float = 0


class StreamListResponse(BaseModel):
    """Response model for listing streams."""
    streams: List[StreamStatusResponse]


# Stream status update callback
def handle_status_update(status: StreamStatus) -> None:
    """Handle status updates from pipeline manager."""
    stream_id = status.stream_id
    stream_statuses[stream_id] = status
    logger.info(f"Stream {stream_id} status updated: {status.state}")


# Set the status callback
pipeline_manager._handle_pipeline_status = handle_status_update


# API Routes
@app.get("/")
async def root() -> Dict[str, str]:
    """Root endpoint, returns basic service info."""
    return {
        "service": SERVICE_NAME,
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    }


@app.post("/streams", status_code=status.HTTP_201_CREATED)
async def create_stream(
    request: CreateStreamRequest,
    background_tasks: BackgroundTasks,
    authenticated: bool = Depends(verify_token)
) -> StreamResponse:
    """Create a new stream pipeline."""
    if not authenticated:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Create stream config
    source_url = request.source_url
    if request.source_type == "test":
        source_url = "videotestsrc"
    elif not source_url:
        # For non-test sources, source_url is required
        if request.source_type != "webrtc":  # WebRTC is created differently
            raise HTTPException(status_code=400, detail="source_url is required for non-test sources")
    
    # For RTMP/RTSP, get the full URL
    if request.source_type in ["rtmp", "rtsp"] and source_url:
        source_url = get_stream_source_url(request.source_type, source_url)
    
    config = StreamConfig(
        source_type=request.source_type,
        source_url=source_url or "",
        output_type=request.output_type,
        output_url=request.output_url,
        width=request.width,
        height=request.height,
        framerate=request.framerate,
        bitrate=request.bitrate or (MAX_BITRATE if request.output_type != "file" else None),
        audio_enabled=request.audio_enabled,
        audio_bitrate=request.audio_bitrate,
        is_recording=request.is_recording,
        recording_path=request.recording_path,
        extra_params=request.extra_params
    )
    
    # Validate config
    if not config.validate():
        raise HTTPException(status_code=400, detail="Invalid stream configuration")
    
    # Create pipeline
    success = pipeline_manager.create_pipeline(request.stream_id, config)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create pipeline")
    
    # Return response
    return StreamResponse(
        stream_id=request.stream_id,
        status="created",
        message="Stream pipeline created successfully"
    )


@app.post("/streams/{stream_id}/start")
async def start_stream(
    stream_id: str,
    authenticated: bool = Depends(verify_token)
) -> StreamResponse:
    """Start a stream pipeline."""
    if not authenticated:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Start pipeline
    success = pipeline_manager.start_pipeline(stream_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to start pipeline")
    
    # Return response
    return StreamResponse(
        stream_id=stream_id,
        status="starting",
        message="Stream pipeline starting"
    )


@app.post("/streams/{stream_id}/stop")
async def stop_stream(
    stream_id: str,
    authenticated: bool = Depends(verify_token)
) -> StreamResponse:
    """Stop a stream pipeline."""
    if not authenticated:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Stop pipeline
    success = pipeline_manager.stop_pipeline(stream_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop pipeline")
    
    # Return response
    return StreamResponse(
        stream_id=stream_id,
        status="stopping",
        message="Stream pipeline stopping"
    )


@app.delete("/streams/{stream_id}")
async def delete_stream(
    stream_id: str,
    authenticated: bool = Depends(verify_token)
) -> StreamResponse:
    """Delete a stream pipeline."""
    if not authenticated:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Remove pipeline
    success = pipeline_manager.remove_pipeline(stream_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete pipeline")
    
    # Remove from status map
    if stream_id in stream_statuses:
        del stream_statuses[stream_id]
    
    # Return response
    return StreamResponse(
        stream_id=stream_id,
        status="deleted",
        message="Stream pipeline deleted"
    )


@app.get("/streams/{stream_id}/status")
async def get_stream_status(
    stream_id: str,
    authenticated: bool = Depends(verify_token)
) -> StreamStatusResponse:
    """Get status of a stream pipeline."""
    if not authenticated:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Get pipeline status
    status = pipeline_manager.get_pipeline_status(stream_id)
    if not status:
        # Check if we have a stored status
        status = stream_statuses.get(stream_id)
        if not status:
            raise HTTPException(status_code=404, detail="Stream not found")
    
    # Calculate uptime if running
    uptime = 0.0
    pipeline = pipeline_manager.pipelines.get(stream_id)
    if pipeline and pipeline.state == PipelineState.RUNNING and pipeline.last_buffer_time > 0:
        uptime = time.time() - pipeline.last_buffer_time
    
    # Return response
    return StreamStatusResponse(
        stream_id=status.stream_id,
        state=status.state,
        error_message=status.error_message,
        stats=status.stats,
        uptime=uptime
    )


@app.get("/streams")
async def list_streams(
    authenticated: bool = Depends(verify_token)
) -> StreamListResponse:
    """List all stream pipelines."""
    if not authenticated:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Get all pipeline statuses
    statuses = pipeline_manager.get_all_stream_statuses()
    
    # Convert to response model
    streams = []
    for status in statuses:
        # Calculate uptime if running
        uptime = 0.0
        pipeline = pipeline_manager.pipelines.get(status.stream_id)
        if pipeline and pipeline.state == PipelineState.RUNNING and pipeline.last_buffer_time > 0:
            uptime = time.time() - pipeline.last_buffer_time
        
        streams.append(StreamStatusResponse(
            stream_id=status.stream_id,
            state=status.state,
            error_message=status.error_message,
            stats=status.stats,
            uptime=uptime
        ))
    
    # Return response
    return StreamListResponse(streams=streams)


@app.post("/streams/{stream_id}/restart")
async def restart_stream(
    stream_id: str,
    authenticated: bool = Depends(verify_token)
) -> StreamResponse:
    """Restart a stream pipeline."""
    if not authenticated:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Get pipeline
    pipeline = pipeline_manager.pipelines.get(stream_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Stream not found")
    
    # Restart pipeline
    success = pipeline.restart()
    if not success:
        raise HTTPException(status_code=500, detail="Failed to restart pipeline")
    
    # Return response
    return StreamResponse(
        stream_id=stream_id,
        status="restarting",
        message="Stream pipeline restarting"
    )


@app.put("/streams/{stream_id}/config")
async def update_stream_config(
    stream_id: str,
    request: CreateStreamRequest,
    authenticated: bool = Depends(verify_token)
) -> StreamResponse:
    """Update configuration of a stream pipeline."""
    if not authenticated:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Verify stream ID matches
    if stream_id != request.stream_id:
        raise HTTPException(status_code=400, detail="Stream ID in path must match stream ID in request body")
    
    # Create stream config
    config = StreamConfig(
        source_type=request.source_type,
        source_url=request.source_url or "",
        output_type=request.output_type,
        output_url=request.output_url,
        width=request.width,
        height=request.height,
        framerate=request.framerate,
        bitrate=request.bitrate,
        audio_enabled=request.audio_enabled,
        audio_bitrate=request.audio_bitrate,
        is_recording=request.is_recording,
        recording_path=request.recording_path,
        extra_params=request.extra_params
    )
    
    # Validate config
    if not config.validate():
        raise HTTPException(status_code=400, detail="Invalid stream configuration")
    
    # Update pipeline config
    success = pipeline_manager.update_pipeline_config(stream_id, config)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update pipeline configuration")
    
    # Return response
    return StreamResponse(
        stream_id=stream_id,
        status="updated",
        message="Stream pipeline configuration updated"
    )


# Shutdown event handler
@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown event handler."""
    logger.info("Shutting down GStreamer pipeline manager")
    pipeline_manager.shutdown()


# Run the API server
def start_api_server():
    """Start the API server."""
    uvicorn.run(
        "gstreamer_streaming.api:app",
        host="0.0.0.0",
        port=API_PORT,
        log_level="info",
        reload=False
    )


if __name__ == "__main__":
    start_api_server() 