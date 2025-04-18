# GStreamer Streaming Service

A robust media processing service for handling live video streams, built with GStreamer.

## Overview

The GStreamer Streaming Service is a flexible solution for:

- Processing live RTMP, RTSP, and WebRTC streams
- Transcoding between different streaming formats
- Recording streams to disk
- Integrating with Kafka for event-driven architecture
- Exposing REST API for stream management
- Monitoring stream health and performance

## Prerequisites

- **Python 3.8+**
- **GStreamer 1.18+** with required plugins:
  - Base plugins (`gstreamer1.0-plugins-base`)
  - Good plugins (`gstreamer1.0-plugins-good`)
  - Bad plugins (`gstreamer1.0-plugins-bad`)
  - Ugly plugins (`gstreamer1.0-plugins-ugly`) - for some codecs
  - Additional plugins: `gstreamer1.0-libav`, `gstreamer1.0-rtsp`
- **NVIDIA GPU** (optional, for hardware acceleration)
  - With appropriate NVIDIA drivers
  - CUDA Toolkit
  - GStreamer NVIDIA plugins (`gstreamer1.0-nvidia`)

## Installation

### System Dependencies (Ubuntu/Debian)

```bash
# Install GStreamer and plugins
sudo apt-get update
sudo apt-get install -y \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    gstreamer1.0-rtsp \
    gstreamer1.0-gl \
    python3-gi \
    python3-gst-1.0

# For NVIDIA GPU support (if available)
sudo apt-get install -y gstreamer1.0-vaapi

# Install Python development headers
sudo apt-get install -y python3-dev python3-pip
```

### Python Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt
```

## Configuration

Configuration is handled through environment variables and the `config.py` file.

### Key Configuration Options:

- **API_PORT**: Port for the REST API (default: 5002)
- **KAFKA_BOOTSTRAP_SERVERS**: Kafka servers for event integration
- **ENABLE_RECORDING**: Enable stream recording (true/false)
- **RECORDING_PATH**: Directory for saving recordings
- **CORS_ORIGINS**: Allowed origins for CORS
- **GST_DEBUG**: GStreamer debug level (0-9)

## Usage

### Starting the Service

```bash
# Start with default configuration
python run_gstreamer_service.py

# Start with custom configuration
python run_gstreamer_service.py --api-port 5005 --enable-recording --recording-path /data/recordings
```

### Command Line Options

```
usage: run_gstreamer_service.py [-h] [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}]
                                [--api-port API_PORT] [--kafka-servers KAFKA_SERVERS]
                                [--metrics-port METRICS_PORT] [--enable-recording]
                                [--recording-path RECORDING_PATH] [--no-kafka]
                                [--test-pipeline] [--gst-debug-level GST_DEBUG_LEVEL]

GStreamer Streaming Service Runner

optional arguments:
  -h, --help            show this help message and exit
  --log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
                        Set the logging level (default: INFO)
  --api-port API_PORT   Set the API server port (overrides config)
  --kafka-servers KAFKA_SERVERS
                        Set the Kafka bootstrap servers (overrides config)
  --metrics-port METRICS_PORT
                        Set the metrics server port (overrides config)
  --enable-recording    Enable recording of streams
  --recording-path RECORDING_PATH
                        Path for stream recordings (overrides config)
  --no-kafka            Disable Kafka integration
  --test-pipeline       Create a test pipeline at startup
  --gst-debug-level GST_DEBUG_LEVEL
                        Set GStreamer debug level (0-9)
```

## REST API

The service exposes a REST API for stream management. Key endpoints:

### Stream Management

```
POST /streams                       # Create a new stream
GET /streams                        # List all streams
GET /streams/{stream_id}/status     # Get stream status
POST /streams/{stream_id}/start     # Start a stream
POST /streams/{stream_id}/stop      # Stop a stream
DELETE /streams/{stream_id}         # Delete a stream
```

### Example: Creating a Stream

```bash
curl -X POST http://localhost:5002/streams \
  -H "Content-Type: application/json" \
  -d '{
    "stream_id": "test-stream-1",
    "source_type": "rtmp",
    "source_url": "live/mystream",
    "output_type": "rtmp",
    "output_url": "rtmp://target-server/live/mystream",
    "width": 1280,
    "height": 720,
    "framerate": 30,
    "bitrate": 2000000,
    "is_recording": true
  }'
```

## Monitoring

The service exposes Prometheus metrics at `/metrics` endpoint on the metrics port.

Key metrics:
- Active pipelines count
- Pipeline errors
- Buffer statistics
- CPU/memory usage
- Pipeline latency

## Integration with Kafka

The service integrates with Kafka for control and status events.

### Stream Control Topic

Used to control streams remotely:
- START command - Creates and starts a pipeline
- STOP command - Stops a pipeline
- QUERY_STATUS command - Returns the current status

### Stream Status Topic

Publishes status updates for streams:
- State changes (starting, running, error, stopped)
- Error details
- Performance metrics

## Architecture

The service consists of the following components:

1. **REST API Server**: Provides endpoints for stream management
2. **GStreamer Pipeline Manager**: Creates and manages GStreamer pipelines
3. **Kafka Integration**: For control and status events
4. **Metrics Collection**: For monitoring

## Troubleshooting

### Common Issues:

1. **Missing GStreamer Elements**:
   - Error: "could not link..."
   - Solution: Install required GStreamer plugins

2. **Permission Issues with Recording**:
   - Error: "Could not open file for writing"
   - Solution: Ensure recording directory has correct permissions

3. **RTMP/RTSP Connection Issues**:
   - Error: "Could not connect to server"
   - Solution: Verify network connectivity and URLs

4. **High CPU Usage**:
   - Cause: Software encoding with high resolution/framerate
   - Solution: Use hardware acceleration or lower resolution/framerate

### Debugging:

```bash
# Run with increased GStreamer debug level
python run_gstreamer_service.py --gst-debug-level 5 --log-level DEBUG
```

## License

This project is licensed under the MIT License - see the LICENSE file for details. 