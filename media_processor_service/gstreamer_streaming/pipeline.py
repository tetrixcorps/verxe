import gi
import logging
import os
import threading
import time
from typing import Dict, Optional, List, Callable

# Set GStreamer environment variables
os.environ["GST_DEBUG"] = os.getenv("GST_DEBUG", "3")

# Import GStreamer modules
gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GLib, GstRtspServer

# Import local modules
from .config import (
    DEFAULT_VIDEO_WIDTH, 
    DEFAULT_VIDEO_HEIGHT, 
    DEFAULT_FRAMERATE,
    DEFAULT_VIDEO_FORMAT,
    MAX_BITRATE
)
from .models import StreamConfig, PipelineState, StreamStatus

# Setup logging
logger = logging.getLogger(__name__)

class GstPipeline:
    """GStreamer Pipeline Manager for video streaming.
    
    This class manages the creation, control, and monitoring of GStreamer pipelines
    for various video streaming sources and outputs.
    """
    
    def __init__(self, stream_id: str, config: StreamConfig, status_callback: Optional[Callable] = None):
        """Initialize GStreamer Pipeline for a specific stream.
        
        Args:
            stream_id: Unique identifier for the stream
            config: Configuration for the stream pipeline
            status_callback: Optional callback for status updates
        """
        # Initialize GStreamer if not already done
        Gst.init(None)
        
        self.stream_id = stream_id
        self.config = config
        self.status_callback = status_callback
        self.pipeline = None
        self.bus = None
        self.loop = None
        self.loop_thread = None
        self.state = PipelineState.STOPPED
        self.error_message = None
        self.last_buffer_time = 0
        self.stats = {}
        
        # Input elements
        self.source = None
        
        # Create GLib main loop for handling GStreamer messages
        self.loop = GLib.MainLoop()
    
    def build_pipeline(self) -> bool:
        """Build the GStreamer pipeline based on configuration.
        
        Returns:
            bool: True if pipeline built successfully, False otherwise
        """
        try:
            # Create a new pipeline
            self.pipeline = Gst.Pipeline.new(f"pipeline-{self.stream_id}")
            
            # Create source element based on stream type
            if self.config.source_type == "test":
                # Test source for development and testing
                self.source = Gst.ElementFactory.make("videotestsrc", "source")
                self.source.set_property("pattern", "ball")  # Moving ball pattern
            elif self.config.source_type == "rtmp":
                # RTMP source
                self.source = Gst.ElementFactory.make("rtmpsrc", "source")
                self.source.set_property("location", self.config.source_url)
            elif self.config.source_type == "rtsp":
                # RTSP source
                self.source = Gst.ElementFactory.make("rtspsrc", "source")
                self.source.set_property("location", self.config.source_url)
                self.source.set_property("latency", 0)
            elif self.config.source_type == "file":
                # File source
                self.source = Gst.ElementFactory.make("filesrc", "source")
                self.source.set_property("location", self.config.source_url)
            elif self.config.source_type == "webrtc":
                # WebRTC source - this is more complex and should be implemented separately
                logger.warning("WebRTC source not fully implemented in this pipeline")
                return False
            else:
                logger.error(f"Unsupported source type: {self.config.source_type}")
                return False
            
            # Add source to pipeline
            self.pipeline.add(self.source)
            
            # Create common elements
            depay = None
            if self.config.source_type == "rtsp":
                # For RTSP, we need to handle different depay elements based on the incoming stream
                # This is simplified - in a real implementation, you would handle caps negotiation
                depay = Gst.ElementFactory.make("rtph264depay", "depay")
                self.pipeline.add(depay)
                self.source.connect("pad-added", self._on_pad_added, depay)
            
            # Create decoding elements
            parser = Gst.ElementFactory.make("h264parse", "parser")
            decoder = Gst.ElementFactory.make("avdec_h264", "decoder")
            
            # Create video processing elements
            videoconvert = Gst.ElementFactory.make("videoconvert", "videoconvert")
            videoscale = Gst.ElementFactory.make("videoscale", "videoscale")
            
            # Create encoding elements
            encoder = Gst.ElementFactory.make("x264enc", "encoder")
            encoder.set_property("tune", "zerolatency")
            encoder.set_property("speed-preset", "superfast")
            encoder.set_property("bitrate", self.config.bitrate or MAX_BITRATE // 1000)  # kbps
            
            # Create output elements based on output type
            if self.config.output_type == "rtmp":
                # RTMP output
                mux = Gst.ElementFactory.make("flvmux", "mux")
                mux.set_property("streamable", True)
                sink = Gst.ElementFactory.make("rtmpsink", "sink")
                sink.set_property("location", self.config.output_url)
            elif self.config.output_type == "rtsp":
                # RTSP server will be implemented separately
                logger.warning("RTSP server not fully implemented in this pipeline")
                return False
            elif self.config.output_type == "file":
                # File output
                mux = Gst.ElementFactory.make("mp4mux", "mux")
                sink = Gst.ElementFactory.make("filesink", "sink")
                sink.set_property("location", self.config.output_url)
            elif self.config.output_type == "webrtc":
                # WebRTC output - this is more complex and should be implemented separately
                logger.warning("WebRTC output not fully implemented in this pipeline")
                return False
            else:
                logger.error(f"Unsupported output type: {self.config.output_type}")
                return False
            
            # Add all elements to pipeline
            elements = [parser, decoder, videoconvert, videoscale, encoder]
            if "mux" in locals():
                elements.append(locals()["mux"])
            elements.append(sink)
            
            for element in elements:
                self.pipeline.add(element)
            
            # Link elements
            if depay:
                # For RTSP, linking happens in the pad-added callback
                Gst.Element.link_many(depay, parser, decoder, videoconvert, videoscale, encoder)
            else:
                # Direct linking for other source types
                Gst.Element.link_many(self.source, parser, decoder, videoconvert, videoscale, encoder)
                
            # Link final elements
            if "mux" in locals():
                Gst.Element.link_many(encoder, locals()["mux"], sink)
            else:
                Gst.Element.link(encoder, sink)
            
            # Setup bus watch for messages
            self.bus = self.pipeline.get_bus()
            self.bus.add_signal_watch()
            self.bus.connect("message", self._on_bus_message)
            
            return True
        
        except Exception as e:
            logger.error(f"Error building pipeline: {str(e)}")
            self.error_message = str(e)
            self.state = PipelineState.ERROR
            return False
    
    def _on_pad_added(self, src, new_pad, depay):
        """Handle dynamic pad creation for elements like rtspsrc."""
        sink_pad = depay.get_static_pad("sink")
        if sink_pad.is_linked():
            return
        
        # Check for compatible caps
        new_pad_caps = new_pad.get_current_caps()
        if not new_pad_caps:
            return
        
        new_pad_struct = new_pad_caps.get_structure(0)
        name = new_pad_struct.get_name()
        
        # Only link video pads (could also handle audio if needed)
        if name.startswith("application/x-rtp"):
            # Link the pads
            ret = new_pad.link(sink_pad)
            if ret != Gst.PadLinkReturn.OK:
                logger.error(f"Link failed: {ret}")
    
    def _on_bus_message(self, bus, message):
        """Handle pipeline bus messages."""
        t = message.type
        
        if t == Gst.MessageType.EOS:
            logger.info(f"Stream {self.stream_id}: End of stream")
            self.state = PipelineState.STOPPED
            self._update_status()
            self.stop()
            
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error(f"Stream {self.stream_id}: Error: {err.message}")
            logger.debug(f"Debug info: {debug}")
            self.error_message = err.message
            self.state = PipelineState.ERROR
            self._update_status()
            self.stop()
            
        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old_state, new_state, pending_state = message.parse_state_changed()
                if new_state == Gst.State.PLAYING:
                    self.state = PipelineState.RUNNING
                    self._update_status()
                    logger.info(f"Stream {self.stream_id}: Pipeline is PLAYING")
                
        elif t == Gst.MessageType.BUFFERING:
            percent = message.parse_buffering()
            logger.debug(f"Stream {self.stream_id}: Buffering {percent}%")
            self.stats["buffering"] = percent
    
    def _update_status(self):
        """Update status and trigger callback if provided."""
        if self.status_callback:
            status = StreamStatus(
                stream_id=self.stream_id,
                state=self.state,
                error_message=self.error_message,
                stats=self.stats
            )
            self.status_callback(status)
    
    def start(self) -> bool:
        """Start the pipeline.
        
        Returns:
            bool: True if started successfully, False otherwise
        """
        if not self.pipeline:
            success = self.build_pipeline()
            if not success:
                return False
        
        logger.info(f"Starting stream {self.stream_id}")
        self.state = PipelineState.STARTING
        self._update_status()
        
        # Start pipeline
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error(f"Failed to start pipeline for stream {self.stream_id}")
            self.state = PipelineState.ERROR
            self.error_message = "Failed to start pipeline"
            self._update_status()
            return False
        
        # Start main loop in a separate thread
        if not self.loop_thread or not self.loop_thread.is_alive():
            self.loop_thread = threading.Thread(target=self._run_loop)
            self.loop_thread.daemon = True
            self.loop_thread.start()
        
        self.last_buffer_time = time.time()
        return True
    
    def _run_loop(self):
        """Run the GLib main loop."""
        try:
            self.loop.run()
        except Exception as e:
            logger.error(f"Error in GLib main loop: {str(e)}")
            self.error_message = str(e)
            self.state = PipelineState.ERROR
            self._update_status()
    
    def stop(self) -> bool:
        """Stop the pipeline.
        
        Returns:
            bool: True if stopped successfully, False otherwise
        """
        if not self.pipeline:
            return True
        
        logger.info(f"Stopping stream {self.stream_id}")
        self.state = PipelineState.STOPPING
        self._update_status()
        
        # Stop pipeline
        self.pipeline.set_state(Gst.State.NULL)
        
        # Quit main loop
        if self.loop and self.loop.is_running():
            self.loop.quit()
        
        # Wait for thread to finish
        if self.loop_thread and self.loop_thread.is_alive():
            self.loop_thread.join(timeout=5)
        
        self.state = PipelineState.STOPPED
        self._update_status()
        
        return True
    
    def restart(self) -> bool:
        """Restart the pipeline.
        
        Returns:
            bool: True if restarted successfully, False otherwise
        """
        self.stop()
        time.sleep(1)  # Short delay to ensure cleanup
        return self.start()
    
    def update_config(self, config: StreamConfig) -> bool:
        """Update pipeline configuration and restart if necessary.
        
        Args:
            config: New configuration
            
        Returns:
            bool: True if updated successfully, False otherwise
        """
        was_running = self.state == PipelineState.RUNNING
        self.stop()
        
        # Update config
        self.config = config
        
        # Rebuild pipeline
        if self.build_pipeline() and was_running:
            return self.start()
        return True


class GstPipelineManager:
    """Manager for multiple GStreamer pipelines."""
    
    def __init__(self, status_callback: Optional[Callable] = None):
        """Initialize the pipeline manager.
        
        Args:
            status_callback: Optional callback for status updates
        """
        self.pipelines: Dict[str, GstPipeline] = {}
        self.status_callback = status_callback
        
        # Initialize GStreamer
        Gst.init(None)
        
        # Initialize RTSP server
        self.rtsp_server = GstRtspServer.RTSPServer()
        self.rtsp_server.set_service(str(8554))  # RTSP port
        self.rtsp_mounts = self.rtsp_server.get_mount_points()
        self.rtsp_server_id = self.rtsp_server.attach(None)
        
        logger.info("GStreamer Pipeline Manager initialized")
    
    def _handle_pipeline_status(self, status: StreamStatus):
        """Handle pipeline status updates and relay to client if callback provided."""
        if self.status_callback:
            self.status_callback(status)
    
    def create_pipeline(self, stream_id: str, config: StreamConfig) -> bool:
        """Create a new pipeline for the given stream ID.
        
        Args:
            stream_id: Unique identifier for the stream
            config: Configuration for the stream pipeline
            
        Returns:
            bool: True if created successfully, False otherwise
        """
        if stream_id in self.pipelines:
            logger.warning(f"Pipeline {stream_id} already exists")
            return False
        
        # Create pipeline
        pipeline = GstPipeline(
            stream_id=stream_id,
            config=config,
            status_callback=self._handle_pipeline_status
        )
        
        # Store pipeline
        self.pipelines[stream_id] = pipeline
        
        # Build pipeline
        success = pipeline.build_pipeline()
        if not success:
            logger.error(f"Failed to build pipeline {stream_id}")
            del self.pipelines[stream_id]
            return False
        
        logger.info(f"Created pipeline {stream_id}")
        return True
    
    def start_pipeline(self, stream_id: str) -> bool:
        """Start the pipeline for the given stream ID.
        
        Args:
            stream_id: Unique identifier for the stream
            
        Returns:
            bool: True if started successfully, False otherwise
        """
        if stream_id not in self.pipelines:
            logger.error(f"Pipeline {stream_id} not found")
            return False
        
        return self.pipelines[stream_id].start()
    
    def stop_pipeline(self, stream_id: str) -> bool:
        """Stop the pipeline for the given stream ID.
        
        Args:
            stream_id: Unique identifier for the stream
            
        Returns:
            bool: True if stopped successfully, False otherwise
        """
        if stream_id not in self.pipelines:
            logger.warning(f"Pipeline {stream_id} not found")
            return True  # Already gone, consider success
        
        return self.pipelines[stream_id].stop()
    
    def remove_pipeline(self, stream_id: str) -> bool:
        """Remove the pipeline for the given stream ID.
        
        Args:
            stream_id: Unique identifier for the stream
            
        Returns:
            bool: True if removed successfully, False otherwise
        """
        if stream_id not in self.pipelines:
            logger.warning(f"Pipeline {stream_id} not found")
            return True  # Already gone, consider success
        
        # Stop pipeline
        self.pipelines[stream_id].stop()
        
        # Remove pipeline
        del self.pipelines[stream_id]
        
        logger.info(f"Removed pipeline {stream_id}")
        return True
    
    def update_pipeline_config(self, stream_id: str, config: StreamConfig) -> bool:
        """Update the configuration for the given stream ID.
        
        Args:
            stream_id: Unique identifier for the stream
            config: Configuration for the stream pipeline
            
        Returns:
            bool: True if updated successfully, False otherwise
        """
        if stream_id not in self.pipelines:
            logger.error(f"Pipeline {stream_id} not found")
            return False
        
        return self.pipelines[stream_id].update_config(config)
    
    def get_pipeline_status(self, stream_id: str) -> Optional[StreamStatus]:
        """Get the status for the given stream ID.
        
        Args:
            stream_id: Unique identifier for the stream
            
        Returns:
            Optional[StreamStatus]: Status of the pipeline, None if not found
        """
        if stream_id not in self.pipelines:
            return None
        
        pipeline = self.pipelines[stream_id]
        return StreamStatus(
            stream_id=stream_id,
            state=pipeline.state,
            error_message=pipeline.error_message,
            stats=pipeline.stats
        )
    
    def get_all_stream_statuses(self) -> List[StreamStatus]:
        """Get the status for all streams.
        
        Returns:
            List[StreamStatus]: Status of all pipelines
        """
        return [
            StreamStatus(
                stream_id=stream_id,
                state=pipeline.state,
                error_message=pipeline.error_message,
                stats=pipeline.stats
            )
            for stream_id, pipeline in self.pipelines.items()
        ]
    
    def shutdown(self):
        """Shutdown all pipelines and cleanup resources."""
        # Stop all pipelines
        for stream_id in list(self.pipelines.keys()):
            self.remove_pipeline(stream_id)
        
        # Stop RTSP server
        if self.rtsp_server_id:
            GLib.source_remove(self.rtsp_server_id)
            self.rtsp_server_id = None
        
        logger.info("GStreamer Pipeline Manager shutdown complete") 