from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Optional, Any, List


class PipelineState(str, Enum):
    """Enumeration of possible pipeline states."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass
class StreamConfig:
    """Configuration for a stream pipeline.

    Attributes:
        source_type: The type of source (test, rtmp, rtsp, file, webrtc)
        source_url: URL for the source stream
        output_type: The type of output (rtmp, rtsp, file, webrtc)
        output_url: URL for the output stream
        width: Video width in pixels
        height: Video height in pixels
        framerate: Video frame rate
        bitrate: Video bitrate in bps
        audio_enabled: Whether audio is enabled
        audio_bitrate: Audio bitrate in bps
        is_recording: Whether recording is enabled
        recording_path: Path to save recordings
    """
    source_type: str
    source_url: str
    output_type: str
    output_url: str
    width: int = 1280
    height: int = 720
    framerate: int = 30
    bitrate: Optional[int] = None
    audio_enabled: bool = True
    audio_bitrate: int = 128000
    is_recording: bool = False
    recording_path: Optional[str] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> bool:
        """Validate the configuration.
        
        Returns:
            bool: True if configuration is valid, False otherwise
        """
        # Validate source type
        if self.source_type not in ["test", "rtmp", "rtsp", "file", "webrtc"]:
            return False
        
        # Validate output type
        if self.output_type not in ["rtmp", "rtsp", "file", "webrtc"]:
            return False
        
        # Validate source URL
        if not self.source_url and self.source_type != "test":
            return False
        
        # Validate output URL
        if not self.output_url:
            return False
        
        # Validate recording path if recording is enabled
        if self.is_recording and not self.recording_path:
            return False
        
        return True


@dataclass
class StreamStatus:
    """Status of a stream pipeline.
    
    Attributes:
        stream_id: Unique identifier for the stream
        state: Current state of the pipeline
        error_message: Error message if state is ERROR
        stats: Additional statistics about the stream
    """
    stream_id: str
    state: PipelineState
    error_message: Optional[str] = None
    stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WebRTCSignal:
    """WebRTC signaling data.
    
    Attributes:
        type: Signal type (offer, answer, ice-candidate)
        sdp: SDP for offer/answer
        candidate: ICE candidate for ice-candidate type
        stream_id: Stream ID associated with this signal
    """
    type: str
    stream_id: str
    sdp: Optional[str] = None
    candidate: Optional[Dict[str, Any]] = None


@dataclass
class StreamSessionStats:
    """Statistics for a stream session.
    
    Attributes:
        bitrate: Current bitrate in bps
        framerate: Current framerate
        dropped_frames: Number of dropped frames
        latency: End-to-end latency in ms
        uptime: Stream uptime in seconds
        video_resolution: Current video resolution as "WIDTHxHEIGHT"
        audio_stats: Audio-specific statistics
        health_score: Overall health score from 0 to 100
    """
    bitrate: int = 0
    framerate: float = 0.0
    dropped_frames: int = 0
    latency: float = 0.0
    uptime: float = 0.0
    video_resolution: str = "0x0"
    audio_stats: Dict[str, Any] = field(default_factory=dict)
    health_score: float = 100.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StreamSessionStats':
        """Create a StreamSessionStats object from a dictionary.
        
        Args:
            data: Dictionary containing statistics
            
        Returns:
            StreamSessionStats: New instance with the provided data
        """
        return cls(
            bitrate=data.get("bitrate", 0),
            framerate=data.get("framerate", 0.0),
            dropped_frames=data.get("dropped_frames", 0),
            latency=data.get("latency", 0.0),
            uptime=data.get("uptime", 0.0),
            video_resolution=data.get("video_resolution", "0x0"),
            audio_stats=data.get("audio_stats", {}),
            health_score=data.get("health_score", 100.0)
        )


class StreamEvent(Enum):
    """Events that can occur in a stream pipeline."""
    STARTED = auto()
    STOPPED = auto()
    ERROR = auto()
    RECONNECTING = auto()
    BUFFER_UNDERRUN = auto()
    STREAM_EOF = auto()
    CONNECTION_LOST = auto()
    CONNECTION_RESTORED = auto()
    RECORDING_STARTED = auto()
    RECORDING_STOPPED = auto()
    RECORDING_ERROR = auto()
    
    
@dataclass
class StreamCommand:
    """Command to control a stream pipeline.
    
    Attributes:
        action: The action to perform (start, stop, restart, update)
        stream_id: Unique identifier for the stream
        config: Configuration for the stream pipeline (for start/update)
    """
    action: str
    stream_id: str
    config: Optional[StreamConfig] = None 