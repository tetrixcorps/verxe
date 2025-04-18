# GStreamer Streaming Integration for Verxe

This module provides GStreamer-based streaming capabilities for the Verxe platform, enabling real-time video processing, WebRTC, and RTMP streaming.

## Architecture

The GStreamer streaming component integrates with the Verxe platform in the following ways:

1. **Media Processor Service Extension**: Extends the existing media processor service with GStreamer pipeline capabilities
2. **Kafka Integration**: Consumes stream control events and publishes stream status events via Kafka
3. **WebSocket Bridge**: Provides a WebSocket interface for real-time stream control and viewing
4. **HTTP API**: Offers REST endpoints for stream management

## Integration Points

- **Stream Service**: Connects to `backend/app/services/stream_service.py` for stream management
- **Signaling Service**: Interacts with `backend/app/services/signaling_service.py` for WebRTC signaling
- **Kafka Pipeline**: Uses existing Kafka topics for stream control and status events
- **Frontend Components**: Provides components for stream viewing in the React frontend

## Usage

The GStreamer streaming component can be used through:

1. Direct HTTP API calls to `/stream/*` endpoints
2. WebSocket connections to `/ws/stream` and `/ws/control`
3. Kafka messages to the stream control topic
4. Integration with the frontend UI components

## Configuration

Configuration is managed through environment variables and the `.env` file.

## Dependencies

- GStreamer 1.22 and plugins
- FastAPI for HTTP and WebSocket APIs
- Kafka for event streaming
- OpenCV for frame processing

## License

This component is licensed under the same license as the Verxe platform. 