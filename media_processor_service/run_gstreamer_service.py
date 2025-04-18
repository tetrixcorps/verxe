#!/usr/bin/env python3
"""
Runner script for the GStreamer Streaming Service.

This script sets up the appropriate environment variables and launches the GStreamer
streaming service. It handles initialization, command-line arguments, and ensures
proper cleanup on exit.
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("gstreamer-runner")

# Set default GStreamer debug level if not set
if "GST_DEBUG" not in os.environ:
    os.environ["GST_DEBUG"] = "3"

# Ensure GST plugin path includes our custom plugins if any
# if os.path.exists("./gst-plugins"):
#     plugin_path = os.path.abspath("./gst-plugins")
#     os.environ["GST_PLUGIN_PATH"] = f"{plugin_path}:{os.environ.get('GST_PLUGIN_PATH', '')}"

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="GStreamer Streaming Service Runner")
    parser.add_argument(
        "--log-level", 
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level (default: INFO)"
    )
    parser.add_argument(
        "--api-port", 
        type=int, 
        default=None,
        help="Set the API server port (overrides config)"
    )
    parser.add_argument(
        "--kafka-servers", 
        default=None,
        help="Set the Kafka bootstrap servers (overrides config)"
    )
    parser.add_argument(
        "--metrics-port", 
        type=int, 
        default=None,
        help="Set the metrics server port (overrides config)"
    )
    parser.add_argument(
        "--enable-recording", 
        action="store_true",
        help="Enable recording of streams"
    )
    parser.add_argument(
        "--recording-path", 
        default=None,
        help="Path for stream recordings (overrides config)"
    )
    parser.add_argument(
        "--no-kafka", 
        action="store_true",
        help="Disable Kafka integration"
    )
    parser.add_argument(
        "--test-pipeline", 
        action="store_true",
        help="Create a test pipeline at startup"
    )
    parser.add_argument(
        "--gst-debug-level", 
        type=int, 
        default=None,
        help="Set GStreamer debug level (0-9)"
    )
    
    return parser.parse_args()

def setup_environment(args):
    """Set up environment variables based on command line args."""
    # Set log level
    os.environ["LOG_LEVEL"] = args.log_level
    
    # Set API port if specified
    if args.api_port:
        os.environ["API_PORT"] = str(args.api_port)
    
    # Set Kafka bootstrap servers if specified
    if args.kafka_servers:
        os.environ["KAFKA_BOOTSTRAP_SERVERS"] = args.kafka_servers
    
    # Set metrics port if specified
    if args.metrics_port:
        os.environ["METRICS_PORT"] = str(args.metrics_port)
    
    # Set recording options
    if args.enable_recording:
        os.environ["ENABLE_RECORDING"] = "true"
    
    if args.recording_path:
        os.environ["RECORDING_PATH"] = args.recording_path
    
    # Disable Kafka if requested
    if args.no_kafka:
        os.environ["USE_KAFKA"] = "false"
    
    # Set GStreamer debug level if specified
    if args.gst_debug_level is not None:
        os.environ["GST_DEBUG"] = str(args.gst_debug_level)

def run_test_pipeline(port=5002):
    """Create a test pipeline using the API."""
    import http.client
    import json
    import uuid
    
    logger.info("Creating test pipeline...")
    
    try:
        # Generate a unique stream ID
        stream_id = str(uuid.uuid4())
        
        # Create JSON payload
        data = {
            "stream_id": stream_id,
            "source_type": "test",
            "output_type": "file",
            "output_url": f"/tmp/test_stream_{stream_id}.mp4",
            "width": 640,
            "height": 480,
            "framerate": 30
        }
        
        # Wait for API server to start
        time.sleep(2)
        
        # Send request to create pipeline
        conn = http.client.HTTPConnection("localhost", port)
        headers = {"Content-type": "application/json"}
        conn.request("POST", "/streams", json.dumps(data), headers)
        
        response = conn.getresponse()
        if response.status != 201:
            logger.error(f"Failed to create test pipeline: {response.status} {response.reason}")
            return False
        
        # Start the pipeline
        conn.request("POST", f"/streams/{stream_id}/start", "", headers)
        response = conn.getresponse()
        if response.status != 200:
            logger.error(f"Failed to start test pipeline: {response.status} {response.reason}")
            return False
        
        logger.info(f"Test pipeline created and started with ID: {stream_id}")
        return True
    except Exception as e:
        logger.error(f"Error creating test pipeline: {e}")
        return False

def main():
    """Main entry point."""
    args = parse_args()
    
    # Set up environment
    setup_environment(args)
    
    logger.info("Starting GStreamer Streaming Service...")
    
    # Determine the path to the main script
    script_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "gstreamer_streaming",
        "main.py"
    )
    
    # Check if the script exists
    if not os.path.exists(script_path):
        logger.error(f"GStreamer service script not found at {script_path}")
        return 1
    
    # Start the process
    try:
        process = subprocess.Popen([sys.executable, script_path])
        
        # Create test pipeline if requested
        if args.test_pipeline:
            # Wait for the service to start before creating the test pipeline
            time.sleep(3)
            run_test_pipeline(args.api_port or 5002)
        
        # Wait for the process to complete
        process.wait()
        return process.returncode
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, terminating service...")
        process.send_signal(signal.SIGINT)
        try:
            # Wait for graceful shutdown with timeout
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Service did not terminate gracefully, forcing termination...")
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                logger.warning("Service still not terminated, killing...")
                process.kill()
        
        return 0
    except Exception as e:
        logger.error(f"Error running GStreamer service: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 