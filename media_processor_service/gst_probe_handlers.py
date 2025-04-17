# media_processor_service/gst_probe_handlers.py

import time
import logging
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from .pipeline_metrics import (
    record_frame_processing, 
    update_video_stats, 
    update_audio_stats
)

logger = logging.getLogger(__name__)

# Track frame processing times
_frame_start_times = {}


def add_probe_handlers(pipeline, stream_id):
    """
    Add probe handlers to the GStreamer pipeline to collect metrics.
    
    Args:
        pipeline: The GStreamer pipeline to add probes to
        stream_id: The stream identifier string
    """
    # Find key elements in the pipeline
    video_encoder = pipeline.get_by_name("video-encoder")
    audio_encoder = pipeline.get_by_name("audio-encoder")
    video_src = pipeline.get_by_name("video-source")
    audio_src = pipeline.get_by_name("audio-source")
    
    # Add probes to measure frame processing time and stats
    if video_encoder:
        # Add probe before encoding (sink pad)
        video_sink_pad = video_encoder.get_static_pad("sink")
        if video_sink_pad:
            video_sink_pad.add_probe(
                Gst.PadProbeType.BUFFER, 
                video_pre_encode_probe_callback, 
                stream_id
            )
        
        # Add probe after encoding (src pad)
        video_src_pad = video_encoder.get_static_pad("src")
        if video_src_pad:
            video_src_pad.add_probe(
                Gst.PadProbeType.BUFFER, 
                video_post_encode_probe_callback, 
                stream_id
            )
    
    if audio_encoder:
        # Add probe before encoding (sink pad)
        audio_sink_pad = audio_encoder.get_static_pad("sink")
        if audio_sink_pad:
            audio_sink_pad.add_probe(
                Gst.PadProbeType.BUFFER, 
                audio_pre_encode_probe_callback, 
                stream_id
            )
        
        # Add probe after encoding (src pad)
        audio_src_pad = audio_encoder.get_static_pad("src")
        if audio_src_pad:
            audio_src_pad.add_probe(
                Gst.PadProbeType.BUFFER, 
                audio_post_encode_probe_callback, 
                stream_id
            )
    
    # Add source element probes to get raw media properties
    if video_src:
        video_src_pad = video_src.get_static_pad("src")
        if video_src_pad:
            video_src_pad.add_probe(
                Gst.PadProbeType.BUFFER | Gst.PadProbeType.EVENT_DOWNSTREAM, 
                video_source_probe_callback, 
                stream_id
            )
    
    if audio_src:
        audio_src_pad = audio_src.get_static_pad("src")
        if audio_src_pad:
            audio_src_pad.add_probe(
                Gst.PadProbeType.BUFFER | Gst.PadProbeType.EVENT_DOWNSTREAM, 
                audio_source_probe_callback, 
                stream_id
            )
    
    logger.info(f"[{stream_id}] Added GStreamer probe handlers for metrics collection")


def video_pre_encode_probe_callback(pad, info, stream_id):
    """Record the start time of video frame processing."""
    buffer = info.get_buffer()
    if buffer:
        pts = buffer.pts
        # Use PTS as unique identifier for this frame
        frame_id = f"{stream_id}:video:{pts}"
        _frame_start_times[frame_id] = time.time()
    return Gst.PadProbeReturn.OK


def video_post_encode_probe_callback(pad, info, stream_id):
    """Calculate processing time for video frame and update metrics."""
    buffer = info.get_buffer()
    if buffer:
        pts = buffer.pts
        frame_id = f"{stream_id}:video:{pts}"
        if frame_id in _frame_start_times:
            start_time = _frame_start_times[frame_id]
            elapsed_ms = (time.time() - start_time) * 1000  # Convert to milliseconds
            
            # Record the frame processing latency
            record_frame_processing(stream_id, "video", elapsed_ms)
            
            # Clean up to avoid memory leak
            del _frame_start_times[frame_id]
            
            # Estimate video bitrate based on buffer size
            size_bits = buffer.get_size() * 8  # Convert bytes to bits
            duration_ns = buffer.get_duration()
            if duration_ns > 0:
                # Calculate bitrate in kbps
                duration_sec = duration_ns / 1e9  # Convert nanoseconds to seconds
                bitrate_kbps = (size_bits / duration_sec) / 1000
                update_video_stats(stream_id, 0, 0, bitrate_kbps)  # Width/height not available here
    
    return Gst.PadProbeReturn.OK


def audio_pre_encode_probe_callback(pad, info, stream_id):
    """Record the start time of audio frame processing."""
    buffer = info.get_buffer()
    if buffer:
        pts = buffer.pts
        # Use PTS as unique identifier for this audio frame
        frame_id = f"{stream_id}:audio:{pts}"
        _frame_start_times[frame_id] = time.time()
    return Gst.PadProbeReturn.OK


def audio_post_encode_probe_callback(pad, info, stream_id):
    """Calculate processing time for audio frame and update metrics."""
    buffer = info.get_buffer()
    if buffer:
        pts = buffer.pts
        frame_id = f"{stream_id}:audio:{pts}"
        if frame_id in _frame_start_times:
            start_time = _frame_start_times[frame_id]
            elapsed_ms = (time.time() - start_time) * 1000  # Convert to milliseconds
            
            # Record the frame processing latency
            record_frame_processing(stream_id, "audio", elapsed_ms)
            
            # Clean up to avoid memory leak
            del _frame_start_times[frame_id]
            
            # Estimate audio bitrate based on buffer size
            size_bits = buffer.get_size() * 8  # Convert bytes to bits
            duration_ns = buffer.get_duration()
            if duration_ns > 0:
                # Calculate bitrate in kbps
                duration_sec = duration_ns / 1e9  # Convert nanoseconds to seconds
                bitrate_kbps = (size_bits / duration_sec) / 1000
                update_audio_stats(stream_id, 0, bitrate_kbps)  # Sample rate not available here
    
    return Gst.PadProbeReturn.OK


def video_source_probe_callback(pad, info, stream_id):
    """Get video resolution from caps event."""
    if info.type == Gst.PadProbeType.EVENT_DOWNSTREAM:
        event = info.get_event()
        if event.type == Gst.EventType.CAPS:
            caps = event.parse_caps()
            structure = caps.get_structure(0)
            
            width = structure.get_value("width")
            height = structure.get_value("height")
            framerate = structure.get_fraction("framerate")
            
            if width and height and framerate:
                fps = framerate.num / framerate.denom
                # Update video resolution metrics
                update_video_stats(stream_id, width, height, 0)  # Bitrate will be updated later
                logger.debug(f"[{stream_id}] Video resolution: {width}x{height} @ {fps} fps")
    
    return Gst.PadProbeReturn.OK


def audio_source_probe_callback(pad, info, stream_id):
    """Get audio sample rate from caps event."""
    if info.type == Gst.PadProbeType.EVENT_DOWNSTREAM:
        event = info.get_event()
        if event.type == Gst.EventType.CAPS:
            caps = event.parse_caps()
            structure = caps.get_structure(0)
            
            rate = structure.get_int("rate")
            channels = structure.get_int("channels")
            
            if rate[0] and channels[0]:  # rate and channels are (value, success) tuples
                # Update audio sample rate metrics
                update_audio_stats(stream_id, rate[0], 0)  # Bitrate will be updated later
                logger.debug(f"[{stream_id}] Audio: {rate[0]} Hz, {channels[0]} channels")
    
    return Gst.PadProbeReturn.OK 