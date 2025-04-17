# media_processor_service/pipeline_metrics.py

import time
import logging
import threading
import psutil
from typing import Dict, Any, Optional
import asyncio
from datetime import datetime, timedelta

from .metrics import (
    PIPELINE_CPU_USAGE, PIPELINE_MEMORY_USAGE, 
    VIDEO_BITRATE, FRAME_RATE, VIDEO_RESOLUTION,
    AUDIO_BITRATE, AUDIO_SAMPLE_RATE, PIPELINE_HEALTH_SCORE,
    WEBRTC_CONNECTION_TIME, FRAME_PROCESSING_LATENCY
)

logger = logging.getLogger(__name__)

# Track pipeline stats
_pipeline_stats = {}
_metrics_lock = threading.Lock()

# Track connection times
_connection_start_times = {}

# Constants
DEFAULT_METRICS_COLLECTION_INTERVAL = 5  # seconds


def register_pipeline(stream_id: str) -> None:
    """
    Register a new pipeline for metrics collection.
    """
    with _metrics_lock:
        current_process = psutil.Process()
        _pipeline_stats[stream_id] = {
            'process': current_process,
            'start_time': time.time(),
            'last_update': time.time(),
            'cpu_percent': 0.0,
            'memory_usage': 0,
            'video_bitrate': 0,
            'frame_rate': 0,
            'video_width': 0,
            'video_height': 0,
            'audio_bitrate': 0,
            'audio_sample_rate': 0,
            'health_score': 100,  # Start with perfect health
            'frame_count': 0,
            'connection_established': False
        }
        logger.info(f"[{stream_id}] Registered pipeline for metrics collection")


def deregister_pipeline(stream_id: str) -> None:
    """
    Deregister a pipeline from metrics collection.
    """
    with _metrics_lock:
        if stream_id in _pipeline_stats:
            del _pipeline_stats[stream_id]
            logger.info(f"[{stream_id}] Deregistered pipeline from metrics collection")
            
            # Remove metrics from Prometheus to avoid stale metrics
            PIPELINE_CPU_USAGE.remove(stream_id)
            PIPELINE_MEMORY_USAGE.remove(stream_id)
            VIDEO_BITRATE.remove(stream_id)
            FRAME_RATE.remove(stream_id)
            VIDEO_RESOLUTION.remove(stream_id)
            AUDIO_BITRATE.remove(stream_id)
            AUDIO_SAMPLE_RATE.remove(stream_id)
            PIPELINE_HEALTH_SCORE.remove(stream_id)


def start_connection_timer(stream_id: str) -> None:
    """
    Start timing the WebRTC connection establishment process.
    Call this when negotiation is needed.
    """
    with _metrics_lock:
        _connection_start_times[stream_id] = time.time()
        logger.debug(f"[{stream_id}] Started WebRTC connection timer")


def end_connection_timer(stream_id: str) -> None:
    """
    End timing the WebRTC connection establishment process.
    Call this when the connection is fully established (ICE connected).
    """
    with _metrics_lock:
        if stream_id in _connection_start_times:
            start_time = _connection_start_times[stream_id]
            elapsed_time = time.time() - start_time
            WEBRTC_CONNECTION_TIME.labels(stream_id=stream_id).observe(elapsed_time)
            
            # Mark connection as established in pipeline stats
            if stream_id in _pipeline_stats:
                _pipeline_stats[stream_id]['connection_established'] = True
            
            logger.info(f"[{stream_id}] WebRTC connection established in {elapsed_time:.2f} seconds")
            del _connection_start_times[stream_id]


def record_frame_processing(stream_id: str, media_type: str, duration_ms: float) -> None:
    """
    Record the time taken to process a frame.
    
    Args:
        stream_id: The stream identifier
        media_type: Either 'audio' or 'video'
        duration_ms: Processing time in milliseconds
    """
    FRAME_PROCESSING_LATENCY.labels(stream_id=stream_id, media_type=media_type).observe(duration_ms)
    
    # Update frame count in stats
    with _metrics_lock:
        if stream_id in _pipeline_stats:
            _pipeline_stats[stream_id]['frame_count'] += 1
            
            # If this is video, we can estimate frame rate based on recent frames
            if media_type == 'video':
                _pipeline_stats[stream_id]['last_video_frame_time'] = time.time()


def update_video_stats(stream_id: str, width: int, height: int, bitrate_kbps: float) -> None:
    """
    Update video statistics for a pipeline.
    """
    with _metrics_lock:
        if stream_id in _pipeline_stats:
            _pipeline_stats[stream_id]['video_width'] = width
            _pipeline_stats[stream_id]['video_height'] = height
            _pipeline_stats[stream_id]['video_bitrate'] = bitrate_kbps
            
            # Update prometheus metrics immediately
            VIDEO_BITRATE.labels(stream_id=stream_id).set(bitrate_kbps)
            VIDEO_RESOLUTION.labels(stream_id=stream_id).set(width * height)


def update_audio_stats(stream_id: str, sample_rate: int, bitrate_kbps: float) -> None:
    """
    Update audio statistics for a pipeline.
    """
    with _metrics_lock:
        if stream_id in _pipeline_stats:
            _pipeline_stats[stream_id]['audio_sample_rate'] = sample_rate
            _pipeline_stats[stream_id]['audio_bitrate'] = bitrate_kbps
            
            # Update prometheus metrics immediately
            AUDIO_BITRATE.labels(stream_id=stream_id).set(bitrate_kbps)
            AUDIO_SAMPLE_RATE.labels(stream_id=stream_id).set(sample_rate)


def calculate_health_score(stats: Dict[str, Any]) -> float:
    """
    Calculate an overall health score (0-100) based on pipeline metrics.
    Higher is better.
    """
    score = 100.0
    
    # Penalize for high CPU usage (>80% is concerning)
    if stats['cpu_percent'] > 80:
        score -= (stats['cpu_percent'] - 80) * 2
    
    # Penalize for low frame rate (if we have frame count and time elapsed)
    if stats.get('frame_rate', 0) < 15 and stats.get('frame_rate', 0) > 0:
        score -= (15 - stats['frame_rate']) * 3
    
    # Penalize for no frames processed recently
    if 'last_video_frame_time' in stats:
        time_since_last_frame = time.time() - stats['last_video_frame_time']
        if time_since_last_frame > 5:  # No frames in 5 seconds is bad
            score -= min(50, time_since_last_frame * 10)
    
    # Connection not established is a major penalty
    if not stats.get('connection_established', False):
        # If it's been more than 30 seconds and no connection, big penalty
        if (time.time() - stats['start_time']) > 30:
            score -= 50
    
    # Ensure score is between 0 and 100
    return max(0, min(100, score))


async def collect_process_metrics() -> None:
    """
    Background task to periodically collect process-level metrics.
    """
    logger.info("Starting pipeline metrics collection task")
    
    while True:
        try:
            with _metrics_lock:
                for stream_id, stats in _pipeline_stats.items():
                    process = stats['process']
                    
                    # Update CPU and memory metrics
                    try:
                        # Update CPU usage (may need multiple samples for accuracy)
                        cpu_percent = process.cpu_percent(interval=0.1)
                        memory_info = process.memory_info()
                        memory_usage = memory_info.rss  # Resident Set Size in bytes
                        
                        # Store in stats dictionary
                        stats['cpu_percent'] = cpu_percent
                        stats['memory_usage'] = memory_usage
                        
                        # Calculate frame rate based on frame count and time elapsed
                        now = time.time()
                        if 'last_metrics_time' in stats:
                            elapsed = now - stats['last_metrics_time']
                            frame_delta = stats['frame_count'] - stats.get('last_frame_count', 0)
                            if elapsed > 0:
                                stats['frame_rate'] = frame_delta / elapsed
                        
                        stats['last_metrics_time'] = now
                        stats['last_frame_count'] = stats['frame_count']
                        
                        # Calculate overall health score
                        stats['health_score'] = calculate_health_score(stats)
                        
                        # Update Prometheus metrics
                        PIPELINE_CPU_USAGE.labels(stream_id=stream_id).set(cpu_percent)
                        PIPELINE_MEMORY_USAGE.labels(stream_id=stream_id).set(memory_usage)
                        FRAME_RATE.labels(stream_id=stream_id).set(stats['frame_rate'])
                        PIPELINE_HEALTH_SCORE.labels(stream_id=stream_id).set(stats['health_score'])
                        
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                        logger.warning(f"[{stream_id}] Failed to collect process metrics: {e}")
                    except Exception as e:
                        logger.exception(f"[{stream_id}] Unexpected error collecting metrics: {e}")
        
        except Exception as e:
            logger.exception(f"Error in metrics collection task: {e}")
        
        # Sleep before collecting metrics again
        await asyncio.sleep(DEFAULT_METRICS_COLLECTION_INTERVAL)


async def start_metrics_collection() -> asyncio.Task:
    """
    Start the background metrics collection.
    Returns the asyncio task that can be cancelled to stop collection.
    """
    task = asyncio.create_task(collect_process_metrics())
    return task 