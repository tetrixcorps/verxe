# media_processor_service/main.py

import os
import sys
import signal
import asyncio
import json
import logging
from uuid import UUID
from typing import Dict, Any, Optional
from datetime import datetime

# Environment setup for GStreamer bindings
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')
from gi.repository import Gst, GLib, GObject, GstWebRTC, GstSdp

from confluent_kafka import SerializingProducer, DeserializingConsumer, KafkaError, KafkaException
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer, AvroDeserializer
from confluent_kafka.serialization import StringSerializer, StringDeserializer
import pathlib

from .dlq_handler import DLQHandler
from .dlq_processor import DLQProcessor
from .metrics import (
    start_metrics_server,
    PIPELINE_COUNT, KAFKA_MESSAGES_CONSUMED, KAFKA_MESSAGES_PRODUCED,
    KAFKA_ERRORS, DLQ_MESSAGES_SENT, PIPELINE_EVENTS, WEBRTC_SIGNALS_PROCESSED,
    WEBRTC_CONNECTION_STATE_CHANGES, ICE_CONNECTION_STATE_CHANGES, WEBRTC_CONNECTION_ERRORS,
    DLQ_MESSAGES_PROCESSED, DLQ_RETRY_LATENCY, DLQ_RETRY_ATTEMPTS, DLQ_MAX_RETRIES_EXCEEDED
)
from .tracing import get_tracer, setup_tracing, shutdown_tracing 
from opentelemetry import trace
from .pipeline_metrics import (
    register_pipeline, deregister_pipeline, 
    start_connection_timer, end_connection_timer,
    start_metrics_collection
)
from .gst_probe_handlers import add_probe_handlers

# --- Configuration --- 
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global tracer instance
tracer = get_tracer()

# --- Kafka Configuration ---
KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')
CONTROL_TOPIC = os.environ.get('KAFKA_TOPIC_STREAM_CONTROL', 'stream_control_events')
STATUS_TOPIC = os.environ.get('KAFKA_TOPIC_STREAM_STATUS', 'stream_status_events')
SIGNALING_IN_TOPIC = os.environ.get('KAFKA_TOPIC_WEBRTC_SIGNALING_IN', 'webrtc_signaling_in')
SIGNALING_OUT_TOPIC = os.environ.get('KAFKA_TOPIC_WEBRTC_SIGNALING_OUT', 'webrtc_signaling_out')
SCHEMA_REGISTRY_URL = os.environ.get('SCHEMA_REGISTRY_URL', 'http://schema-registry:8081')
STUN_SERVER = os.environ.get("STUN_SERVER", "stun://stun.l.google.com:19302")
TURN_SERVER_URL = os.environ.get("TURN_SERVER_URL") # e.g., turn:user:pass@host:port

# --- DLQ Configuration ---
DLQ_TOPIC_PATTERN = os.environ.get('DLQ_TOPIC_PATTERN', '.*\.dlq$')
DLQ_MAX_RETRIES = int(os.environ.get('DLQ_MAX_RETRIES', '3'))
DLQ_INITIAL_RETRY_DELAY_MS = int(os.environ.get('DLQ_INITIAL_RETRY_DELAY_MS', '1000'))
DLQ_MAX_RETRY_DELAY_MS = int(os.environ.get('DLQ_MAX_RETRY_DELAY_MS', '30000'))
DLQ_BACKOFF_MULTIPLIER = float(os.environ.get('DLQ_BACKOFF_MULTIPLIER', '2.0'))
DLQ_POLL_INTERVAL_MS = int(os.environ.get('DLQ_POLL_INTERVAL_MS', '500'))

# Global DLQ processor instance
dlq_processor = None

# --- Kafka Setup --- 
def load_avro_schema(schema_file: str):
    schema_path = pathlib.Path(__file__).parent.parent / "backend" / "schemas" / "avro" / schema_file
    if not schema_path.exists():
        logger.error(f"Schema file not found at: {schema_path}")
        return None
    with open(schema_path, 'r') as f:
        return f.read()

schema_registry_conf = {'url': SCHEMA_REGISTRY_URL}
schema_registry_client = SchemaRegistryClient(schema_registry_conf)

control_schema = load_avro_schema('stream_control.avsc')
status_schema = load_avro_schema('stream_status.avsc')
signaling_schema = load_avro_schema('webrtc_signal.avsc')

string_serializer = StringSerializer('utf_8')
string_deserializer = StringDeserializer('utf_8')
avro_status_serializer = AvroSerializer(schema_registry_client, status_schema, lambda obj, ctx: obj)
avro_control_deserializer = AvroDeserializer(schema_registry_client, control_schema, lambda obj, ctx: obj)
avro_signaling_serializer = AvroSerializer(schema_registry_client, signaling_schema, lambda obj, ctx: obj)
avro_signaling_deserializer = AvroDeserializer(schema_registry_client, signaling_schema, lambda obj, ctx: obj)

producer_config = {
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
    'client.id': 'media-processor-producer',
    'key.serializer': string_serializer,
}
kakfa_producer = SerializingProducer(producer_config)

def kafka_delivery_report(err, msg):
    if err is not None:
        logger.error(f"Kafka message delivery failed: {err}")

control_consumer_config = {
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
    'group.id': 'media-processor-control-group',
    'auto.offset.reset': 'earliest',
    'enable.auto.commit': False,
    'key.deserializer': string_deserializer,
    'value.deserializer': avro_control_deserializer 
}
control_kafka_consumer = DeserializingConsumer(control_consumer_config)

signaling_consumer_config = {
    'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
    'group.id': 'media-processor-signaling-group',
    'auto.offset.reset': 'latest',
    'enable.auto.commit': False,
    'key.deserializer': string_deserializer,
    'value.deserializer': avro_signaling_deserializer
}
signaling_kafka_consumer = DeserializingConsumer(signaling_consumer_config)

# --- GStreamer Pipeline Management --- 
active_pipelines: Dict[str, Dict[str, Any]] = {}

def build_webrtc_pipeline(stream_id: str, room_id: str):
    with tracer.start_as_current_span("build_webrtc_pipeline") as span:
        span.set_attribute("stream_id", stream_id)
        span.set_attribute("room_id", room_id)
        pipeline = Gst.Pipeline.new(f"stream-{stream_id}")
        if not pipeline: raise RuntimeError("Failed to create Pipeline")

        # --- Source Elements (Use test sources for now) ---
        video_src = Gst.ElementFactory.make("videotestsrc", "video-source")
        if not video_src: raise RuntimeError("Failed to create videotestsrc")
        video_src.set_property("is-live", True)
        video_src.set_property("pattern", "ball") # Moving pattern

        audio_src = Gst.ElementFactory.make("audiotestsrc", "audio-source")
        if not audio_src: raise RuntimeError("Failed to create audiotestsrc")
        audio_src.set_property("is-live", True)
        audio_src.set_property("wave", "sine") # Sine wave
        audio_src.set_property("freq", 440)

        # --- Encoding and Payload Elements ---
        # Video pipeline: queue -> videoconvert -> vp8enc -> rtpvp8pay
        video_queue = Gst.ElementFactory.make("queue", "video-queue")
        video_convert = Gst.ElementFactory.make("videoconvert", "video-convert")
        video_scale = Gst.ElementFactory.make("videoscale", "video-scale") # Optional scaling
        # Using VP8 for broad compatibility, alternatives: vp9enc, x264enc (requires rtph264pay)
        video_encoder = Gst.ElementFactory.make("vp8enc", "video-encoder") 
        if not video_encoder: raise RuntimeError("Failed to create vp8enc")
        video_encoder.set_property("deadline", 1) # Low latency
        video_pay = Gst.ElementFactory.make("rtpvp8pay", "video-rtp-pay")

        # Audio pipeline: queue -> audioconvert -> opusenc -> rtpopuspay
        audio_queue = Gst.ElementFactory.make("queue", "audio-queue")
        audio_convert = Gst.ElementFactory.make("audioconvert", "audio-convert")
        audio_resample = Gst.ElementFactory.make("audioresample", "audio-resample") # Ensure correct sample rate
        audio_encoder = Gst.ElementFactory.make("opusenc", "audio-encoder")
        if not audio_encoder: raise RuntimeError("Failed to create opusenc")
        audio_pay = Gst.ElementFactory.make("rtpopuspay", "audio-rtp-pay")

        # --- WebRTC Element ---
        webrtc = Gst.ElementFactory.make("webrtcbin", f"webrtc-{stream_id}")
        if not webrtc: raise RuntimeError("Failed to create webrtcbin")

        # --- Add Elements --- 
        elements = [
            video_src, video_queue, video_convert, video_scale, video_encoder, video_pay,
            audio_src, audio_queue, audio_convert, audio_resample, audio_encoder, audio_pay,
            webrtc
        ]
        for el in elements:
            if not el: raise RuntimeError(f"Failed to create an element for {stream_id}")
            pipeline.add(el)

        # --- Link Video Chain --- 
        video_src.link(video_queue)
        video_queue.link(video_convert)
        video_convert.link(video_scale) # Link scaler if used
        # Define video caps after scaler if needed, e.g., scale ! video/x-raw,width=640,height=480 ! vp8enc ...
        video_scale.link(video_encoder) 
        video_encoder.link(video_pay)
        # Link video payloader src pad to a requested sink pad on webrtcbin
        video_pay_src_pad = video_pay.get_static_pad("src")
        webrtc_video_sink_pad = webrtc.get_request_pad("sink_%u")
        if not webrtc_video_sink_pad:
             raise RuntimeError(f"[{stream_id}] Could not request video sink pad from webrtcbin")
        if video_pay_src_pad.link(webrtc_video_sink_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"[{stream_id}] Failed to link video payloader to webrtcbin")
        logger.info(f"[{stream_id}] Linked Video to WebRTCBin sink: {webrtc_video_sink_pad.get_name()}")

        # --- Link Audio Chain --- 
        audio_src.link(audio_queue)
        audio_queue.link(audio_convert)
        audio_convert.link(audio_resample)
        audio_resample.link(audio_encoder)
        audio_encoder.link(audio_pay)
        # Link audio payloader src pad to another requested sink pad on webrtcbin
        audio_pay_src_pad = audio_pay.get_static_pad("src")
        webrtc_audio_sink_pad = webrtc.get_request_pad("sink_%u")
        if not webrtc_audio_sink_pad:
            raise RuntimeError(f"[{stream_id}] Could not request audio sink pad from webrtcbin")
        if audio_pay_src_pad.link(webrtc_audio_sink_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"[{stream_id}] Failed to link audio payloader to webrtcbin")
        logger.info(f"[{stream_id}] Linked Audio to WebRTCBin sink: {webrtc_audio_sink_pad.get_name()}")

        # --- Configure WebRTCBin --- 
        webrtc.set_property("stun-server", STUN_SERVER)
        if TURN_SERVER_URL:
            webrtc.set_property("turn-server", TURN_SERVER_URL)

        # Connect WebRTC signals
        webrtc.connect('on-negotiation-needed', on_negotiation_needed, stream_id, room_id)
        webrtc.connect('on-ice-candidate', on_ice_candidate, stream_id, room_id)
        webrtc.connect('pad-added', on_incoming_decode_pad, stream_id) # Handle incoming decoded media
        
        # Add additional signals for connection state monitoring
        webrtc.connect('on-ice-connection-state-changed', on_ice_connection_state_changed, stream_id)
        webrtc.connect('on-connection-state-changed', on_connection_state_changed, stream_id)

        # Add probe handlers for collecting metrics
        add_probe_handlers(pipeline, stream_id)

        logger.info(f"[{stream_id}] Successfully built GStreamer pipeline for room {room_id}.")
        return pipeline, webrtc

def start_pipeline(stream_id: str, stream_key: str, rtmp_url: Optional[str], is_recorded: bool, room_id: str):
    with tracer.start_as_current_span("start_pipeline") as span:
        span.set_attribute("stream_id", stream_id)
        span.set_attribute("room_id", room_id)
        if stream_id in active_pipelines:
            span.add_event("pipeline_already_exists")
            logger.warning(f"[{stream_id}] Pipeline already running. Ignoring START command.")
            # Optional: Re-publish current status if needed?
            # publish_status(stream_id, "LIVE") # Or STARTING depending on state machine
            return

        logger.info(f"[{stream_id}] Starting WebRTC pipeline for room {room_id}...")
        try:
            # Build the pipeline with webrtcbin (rtmp_url might not be needed here)
            pipeline, webrtc = build_webrtc_pipeline(stream_id, room_id)

            bus = pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect("message::error", on_error, stream_id)
            bus.connect("message::eos", on_eos, stream_id)
            bus.connect("message::state-changed", on_state_changed, stream_id)

            pipeline.set_state(Gst.State.PLAYING)
            active_pipelines[stream_id] = {"pipeline": pipeline, "webrtc": webrtc, "room_id": room_id}
            
            # Register pipeline for metrics collection
            register_pipeline(stream_id)
            
            PIPELINE_COUNT.inc() # Increment active pipeline gauge
            PIPELINE_EVENTS.labels(stream_id=stream_id, event_type='start').inc()
            span.add_event("pipeline_started")
            logger.info(f"[{stream_id}] Pipeline starting successfully.")
            # Status is implicitly PENDING until offer/answer completes
            publish_status(stream_id, "STARTING") 

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            PIPELINE_EVENTS.labels(stream_id=stream_id, event_type='start_error').inc()
            logger.exception(f"[{stream_id}] Failed to start pipeline: {e}")
            publish_status(stream_id, "ERROR_START", {"error": str(e)})

def stop_pipeline(stream_id: str):
    with tracer.start_as_current_span("stop_pipeline") as span:
        span.set_attribute("stream_id", stream_id)
        pipeline_info = active_pipelines.get(stream_id)
        if not pipeline_info:
            span.add_event("pipeline_not_found")
            logger.warning(f"[{stream_id}] Stop command received, but no active pipeline found.")
            return # Nothing to stop
        
        pipeline = pipeline_info.get("pipeline")
        if pipeline:
            current_state, _, _ = pipeline.get_state(timeout=Gst.SECOND / 10) # Check current state (short timeout)
            if current_state == Gst.State.NULL:
                 logger.info(f"[{stream_id}] Pipeline already stopped.")
                 active_pipelines.pop(stream_id, None) # Ensure cleanup if somehow missed
                 
                 # Deregister pipeline from metrics collection
                 deregister_pipeline(stream_id)
                 
                 PIPELINE_COUNT.dec() # Decrement active pipeline gauge
                 PIPELINE_EVENTS.labels(stream_id=stream_id, event_type='stopped_null').inc()
                 publish_status(stream_id, "ENDED") # Generic ended status
                 return
             
            logger.info(f"[{stream_id}] Stopping pipeline (current state: {current_state.value_nick})...")
            # Setting state to NULL triggers cleanup via state change handler
            res = pipeline.set_state(Gst.State.NULL)
            if res == Gst.StateChangeReturn.FAILURE:
                logger.error(f"[{stream_id}] Failed to set pipeline state to NULL.")
                # Still remove from active list, but log error
                active_pipelines.pop(stream_id, None)
                # Deregister pipeline from metrics collection
                deregister_pipeline(stream_id)
            elif res == Gst.StateChangeReturn.ASYNC:
                 logger.info(f"[{stream_id}] Pipeline stopping asynchronously...")
                 # State change handler will eventually remove it
            # else (SUCCESS or NO_PREROLL): Handler will remove it when NULL is reached
            # logger.info(f"[{stream_id}] Pipeline stopped.") # Logging moved to state change handler
        else:
            logger.warning(f"[{stream_id}] Stop command: active entry exists but pipeline object missing.")
            active_pipelines.pop(stream_id, None) # Clean up inconsistent entry
            # Deregister pipeline from metrics collection
            deregister_pipeline(stream_id)
        PIPELINE_EVENTS.labels(stream_id=stream_id, event_type='stop_command').inc()

# --- GStreamer Message Handlers --- 
def on_error(bus, message, stream_id):
    with tracer.start_as_current_span("on_pipeline_error") as span:
        err, debug = message.parse_error()
        span.set_attribute("stream_id", stream_id)
        span.set_attribute("error.message", str(err))
        span.set_attribute("error.debug", str(debug))
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(err)))
        logger.error(f"[{stream_id}] GStreamer Error: {err}, {debug}")
        PIPELINE_EVENTS.labels(stream_id=stream_id, event_type='error').inc()
        publish_status(stream_id, "ERROR_RUNTIME", {"error": f"{err} {debug}"})
        GLib.idle_add(stop_pipeline, stream_id) # Ensure stop runs in GLoop thread

def on_eos(bus, message, stream_id):
    with tracer.start_as_current_span("on_pipeline_eos") as span:
        span.set_attribute("stream_id", stream_id)
        logger.info(f"[{stream_id}] End-Of-Stream received.")
        PIPELINE_EVENTS.labels(stream_id=stream_id, event_type='eos').inc()
        publish_status(stream_id, "ENDED_EOS")
        GLib.idle_add(stop_pipeline, stream_id)

def on_state_changed(bus, message, stream_id):
    pipeline_info = active_pipelines.get(stream_id)
    if pipeline_info and message.src == pipeline_info.get("pipeline"):
        old, new, pending = message.parse_state_changed()
        logger.debug(f"[{stream_id}] Pipeline state changed from {old.value_nick} to {new.value_nick}")
        if new == Gst.State.NULL and old != Gst.State.NULL:
            with tracer.start_as_current_span("on_pipeline_null_state") as span:
                span.set_attribute("stream_id", stream_id)
                span.set_attribute("old_state", old.value_nick)
                logger.warning(f"[{stream_id}] Pipeline reached NULL state.")
                if stream_id in active_pipelines: # Check if not already removed by stop_pipeline
                    active_pipelines.pop(stream_id, None)
                    # Deregister pipeline from metrics collection
                    deregister_pipeline(stream_id)
                    PIPELINE_COUNT.dec() # Decrement active pipeline gauge
                    PIPELINE_EVENTS.labels(stream_id=stream_id, event_type='stopped_null').inc()
                    publish_status(stream_id, "ENDED") # Generic ended status

# --- WebRTC Signal Handlers --- 
def on_negotiation_needed(webrtcbin, stream_id, room_id):
    with tracer.start_as_current_span("on_negotiation_needed") as span:
        span.set_attribute("stream_id", stream_id)
        logger.info(f"[{stream_id}] WebRTC negotiation needed for room {room_id}, creating offer...")
        # Start timing for WebRTC connection establishment
        start_connection_timer(stream_id)
        GLib.idle_add(emit_create_offer, webrtcbin, stream_id, room_id)

def emit_create_offer(webrtcbin, stream_id, room_id):
    with tracer.start_as_current_span("emit_create_offer") as span:
        span.set_attribute("stream_id", stream_id)
        span.set_attribute("room_id", room_id)
        promise = Gst.Promise.new_with_change_func(on_offer_created, webrtcbin, stream_id, room_id)
        webrtcbin.emit("create-offer", None, promise)

def on_offer_created(promise: Gst.Promise, webrtcbin: Gst.Element, stream_id: str, room_id: str):
    with tracer.start_as_current_span("on_offer_created", kind=trace.SpanKind.INTERNAL) as span:
        promise.wait() 
        reply = promise.get_reply()
        if not reply or not reply.has_field("offer"):
            logger.error(f"[{stream_id}] Failed to get offer from promise reply.")
            return
        offer = reply.get_value("offer")
        if not offer:
            logger.error(f"[{stream_id}] Failed to create SDP offer (offer is null).")
            return

        logger.info(f"[{stream_id}] Setting local description (offer)...")
        promise_set = Gst.Promise.new()
        GLib.idle_add(webrtcbin.emit, "set-local-description", offer, promise_set)
        promise_set.interrupt() 

        sdp_text = offer.sdp.as_text()
        logger.debug(f"[{stream_id}] Sending offer SDP via Kafka")
        publish_webrtc_signal(
            signal_type='offer',
            room_id=room_id,
            sender_id=stream_id, 
            payload={"type": "offer", "sdp": sdp_text}
        )
        WEBRTC_SIGNALS_PROCESSED.labels(stream_id=stream_id, signal_type='offer', direction='outgoing').inc()

def on_ice_candidate(webrtcbin, mline_index, candidate_str, stream_id, room_id):
    with tracer.start_as_current_span("on_ice_candidate", kind=trace.SpanKind.INTERNAL) as span:
        span.set_attribute("stream_id", stream_id)
        span.set_attribute("sdpMLineIndex", mline_index)
        span.set_attribute("candidate", candidate_str)
        logger.debug(f"[{stream_id}] ICE candidate generated for room {room_id}")
        publish_webrtc_signal(
            signal_type='ice-candidate',
            room_id=room_id,
            sender_id=stream_id,
            payload={'candidate': candidate_str, 'sdpMLineIndex': mline_index}
        )
        WEBRTC_SIGNALS_PROCESSED.labels(stream_id=stream_id, signal_type='ice-candidate', direction='outgoing').inc()

def on_incoming_decode_pad(webrtcbin, pad, stream_id):
     # This handles the decoded media received from the peer
     # In a send-only scenario, we might not expect remote tracks
     # but webrtcbin might create pads anyway.
     with tracer.start_as_current_span("on_incoming_decode_pad") as span:
         span.set_attribute("stream_id", stream_id)
         span.set_attribute("pad_name", pad.get_name())
         logger.info(f"[{stream_id}] Pad added: {pad.get_name()}")
         # If this were a viewer, you'd link this pad to decodebin ! autovideosink etc.
         # For a sender, we usually ignore these unless doing bi-directional checks.

# --- GStreamer Operations (Called via GLib.idle_add) ---
def query_pipeline_status(stream_id: str):
    """Checks the status of an active pipeline and publishes it."""
    with tracer.start_as_current_span("query_pipeline_status") as span:
        span.set_attribute("stream_id", stream_id)
        logger.debug(f"[{stream_id}] Received status query.")
        pipeline_info = active_pipelines.get(stream_id)
        if not pipeline_info or not pipeline_info.get("pipeline"):
            logger.warning(f"[{stream_id}] Status query received, but no active pipeline found.")
            span.add_event("pipeline_not_found")
            publish_status(stream_id, "NOT_FOUND") # Explicitly report not found
            return False # Don't repeat idle_add call
            
        pipeline = pipeline_info["pipeline"]
        # Get current state (non-blocking)
        current_state, _, _ = pipeline.get_state(timeout=0)
        status_to_report = "UNKNOWN" # Default
        
        if current_state == Gst.State.PLAYING:
            status_to_report = "LIVE"
        elif current_state == Gst.State.PAUSED:
            status_to_report = "PAUSED"
        elif current_state == Gst.State.READY:
            status_to_report = "READY"
        elif current_state == Gst.State.NULL:
            status_to_report = "ENDED"
            if stream_id in active_pipelines:
                logger.warning(f"[{stream_id}] Pipeline found in NULL state during query, cleaning up.")
                span.add_event("pipeline_cleanup", {"reason": "null_state"})
                active_pipelines.pop(stream_id, None)
        else:
            status_to_report = current_state.value_nick
            
        span.set_attribute("pipeline.status", status_to_report)
        span.set_attribute("pipeline.state", current_state.value_nick)
        logger.info(f"[{stream_id}] Responding to status query. Current state: {current_state.value_nick}, Reporting status: {status_to_report}")
        publish_status(stream_id, status_to_report)
        return False # Do not call again

def apply_remote_answer(webrtcbin, sdp_text, stream_id):
    with tracer.start_as_current_span("apply_remote_answer") as span:
        span.set_attribute("stream_id", stream_id)
        logger.info(f"[{stream_id}] Applying remote description (answer)...")
        try:
            res, sdp = GstSdp.SDPMessage.new_from_text(sdp_text)
            if res != GstSdp.SDPResult.OK:
                error_msg = f"[{stream_id}] Failed to parse remote SDP answer."
                logger.error(error_msg)
                span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                return False
                
            answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdp)
            promise = Gst.Promise.new()
            webrtcbin.emit("set-remote-description", answer, promise)
            promise.interrupt() 
            logger.info(f"[{stream_id}] Applied remote answer description.")
            span.add_event("remote_description_applied")
            
            # End timing for WebRTC connection establishment
            # This happens when we've received and applied an answer
            end_connection_timer(stream_id)
        except Exception as e:
            logger.exception(f"[{stream_id}] Error applying remote answer: {e}")
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
        return False

def apply_ice_candidate(webrtcbin, mline_index, candidate_str, stream_id):
    with tracer.start_as_current_span("apply_ice_candidate") as span:
        span.set_attribute("stream_id", stream_id)
        span.set_attribute("sdpMLineIndex", mline_index)
        span.set_attribute("candidate", candidate_str)
        logger.debug(f"[{stream_id}] Applying remote ICE candidate...")
        try:
            webrtcbin.emit('add-ice-candidate', mline_index, candidate_str)
        except Exception as e:
            logger.exception(f"[{stream_id}] Error applying ICE candidate: {e}")
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
        return False

# --- Kafka Interaction --- 
def publish_status(stream_id: str, status: str, details: Optional[dict] = None):
    with tracer.start_as_current_span("publish_kafka_status", kind=trace.SpanKind.PRODUCER) as span:
        payload_dict = {
            'stream_id': stream_id,
            'status': status,
            'timestamp': datetime.utcnow().isoformat(),
            'service_id': 'media-processor-instance-1', 
            'metadata': details,
            'version': 1
        }
        span.set_attribute("messaging.system", "kafka")
        span.set_attribute("messaging.destination.name", STATUS_TOPIC)
        span.set_attribute("messaging.message.key", stream_id)
        span.set_attribute("stream.status", status)
        try:
            kakfa_producer.produce(
                topic=STATUS_TOPIC,
                key=stream_id,
                value=payload_dict,
                value_serializer=avro_status_serializer, # Use correct serializer
                on_delivery=kafka_delivery_report
            )
            kakfa_producer.poll(0)
            KAFKA_MESSAGES_PRODUCED.labels(topic=STATUS_TOPIC).inc()
        except BufferError:
            error_msg = f"[{stream_id}] Kafka producer queue is full trying to send status."
            logger.error(error_msg)
            span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
            KAFKA_ERRORS.labels(operation="produce", topic=STATUS_TOPIC).inc()
        except Exception as e:
            error_msg = f"[{stream_id}] Failed to publish status '{status}' to Kafka: {e}"
            logger.error(error_msg)
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
            KAFKA_ERRORS.labels(operation="produce", topic=STATUS_TOPIC).inc()

def publish_webrtc_signal(signal_type: str, room_id: str, sender_id: str, payload: dict, recipient_id: Optional[str] = None):
    with tracer.start_as_current_span("publish_webrtc_signal", kind=trace.SpanKind.PRODUCER) as span:
        span.set_attribute("messaging.system", "kafka")
        span.set_attribute("messaging.destination.name", SIGNALING_OUT_TOPIC)
        span.set_attribute("messaging.message.key", room_id)
        span.set_attribute("signal.type", signal_type)
        span.set_attribute("signal.sender_id", sender_id)
        if recipient_id:
            span.set_attribute("signal.recipient_id", recipient_id)
            
        event_payload = {
            "type": signal_type,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "room_id": room_id,
            "payload": json.dumps(payload), 
            "timestamp": datetime.utcnow().isoformat(),
            "version": 1
        }
        try:
            kakfa_producer.produce(
                topic=SIGNALING_OUT_TOPIC,
                key=room_id,
                value=event_payload,
                value_serializer=avro_signaling_serializer, # Use correct serializer
                on_delivery=kafka_delivery_report
            )
            kakfa_producer.poll(0)
            KAFKA_MESSAGES_PRODUCED.labels(topic=SIGNALING_OUT_TOPIC).inc()
            logger.debug(f"Published {signal_type} signal for room {room_id} from {sender_id}")
        except BufferError:
            KAFKA_ERRORS.labels(operation="produce", topic=SIGNALING_OUT_TOPIC).inc()
            logger.error(f"Kafka producer queue is full trying to send {signal_type} signal for room {room_id}.")
            span.set_status(trace.Status(trace.StatusCode.ERROR, "Kafka producer queue full"))
        except Exception as e:
            KAFKA_ERRORS.labels(operation="produce", topic=SIGNALING_OUT_TOPIC).inc()
            logger.exception(f"Failed to publish {signal_type} signal for room {room_id}: {e}")
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))

# --- Kafka Consumer Loops --- 
async def consume_control_commands():
    group_id = 'media-processor-control-group'
    control_kafka_consumer.subscribe([CONTROL_TOPIC])
    logger.info(f"Subscribed to Kafka control topic: {CONTROL_TOPIC}")
    while True:
        processed_successfully = False
        msg = None
        try:
            msg = control_kafka_consumer.poll(1.0)
            if msg is None: await asyncio.sleep(0.1); continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF: continue
                logger.error(f"Control Consumer Error: {msg.error()}")
                KAFKA_ERRORS.labels(operation="consume", topic=CONTROL_TOPIC).inc()
                await asyncio.sleep(5)
                continue
            
            # Message received successfully
            KAFKA_MESSAGES_CONSUMED.labels(topic=CONTROL_TOPIC, consumer_group=group_id).inc()
            
            with tracer.start_as_current_span("process_control_command", kind=trace.SpanKind.CONSUMER) as span:
                span.set_attribute("messaging.system", "kafka")
                span.set_attribute("messaging.source.name", CONTROL_TOPIC)
                span.set_attribute("messaging.consumer_group", group_id)
                if msg.key():
                    span.set_attribute("messaging.message.key", msg.key())
                
                command_data = msg.value()
                if command_data is None:
                    error_msg = f"Failed to deserialize control message from topic {msg.topic()}"
                    logger.error(error_msg)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                    DLQHandler.send_to_dlq(msg.topic(), msg.value(), msg.key(), "Deserialization Error", group_id)
                    DLQ_MESSAGES_SENT.labels(original_topic=msg.topic()).inc()
                    control_kafka_consumer.commit(message=msg)
                    continue
                    
                command = command_data.get('command')
                stream_id = command_data.get('stream_id')
                stream_key = command_data.get('stream_key')
                rtmp_url = command_data.get('rtmp_url')
                is_recorded = command_data.get('is_recorded', False)
                room_id = command_data.get('room_id')

                span.set_attribute("command", command)
                if stream_id:
                    span.set_attribute("stream_id", stream_id)
                if room_id:
                    span.set_attribute("room_id", room_id)

                if not stream_id or not room_id:
                    error_msg = "Ignoring control command with missing stream_id or room_id"
                    logger.warning(error_msg)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                    DLQHandler.send_to_dlq(msg.topic(), command_data, msg.key(), "Missing stream_id or room_id", group_id)
                    DLQ_MESSAGES_SENT.labels(original_topic=msg.topic()).inc()
                    control_kafka_consumer.commit(message=msg)
                    continue
                    
                logger.info(f"Received command: {command} for stream: {stream_id} in room: {room_id}")
                span.add_event("command_received", {"command": command, "stream_id": stream_id, "room_id": room_id})
                    
                if command == 'START':
                    # Idempotency is handled inside start_pipeline
                    GLib.idle_add(start_pipeline, stream_id, stream_key, rtmp_url, is_recorded, room_id)
                elif command == 'STOP':
                    # Idempotency is handled inside stop_pipeline
                    GLib.idle_add(stop_pipeline, stream_id)
                elif command == 'QUERY_STATUS': # Handle the new command
                     GLib.idle_add(query_pipeline_status, stream_id)
                else:
                    error_msg = f"[{stream_id}] Unknown control command received: {command}"
                    logger.warning(error_msg)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                    # Optionally send to DLQ if unknown commands are problematic
                
                processed_successfully = True # Mark command as processed
                
        except KafkaException as e:
             logger.error(f"Control Consumer KafkaException: {e}")
             KAFKA_ERRORS.labels(operation="consume", topic=CONTROL_TOPIC).inc()
             await asyncio.sleep(5)
        except Exception as e:
            logger.exception(f"Error processing control command: {e}")
            if msg:
                DLQHandler.send_to_dlq(msg.topic(), msg.value(), msg.key(), str(e), group_id)
                DLQ_MESSAGES_SENT.labels(original_topic=msg.topic()).inc()
            processed_successfully = True # Mark as handled (sent to DLQ)
        finally:
            if msg and processed_successfully:
                try:
                    control_kafka_consumer.commit(message=msg)
                except Exception as commit_err:
                    logger.exception(f"[ControlConsumer] CRITICAL: Failed to commit Kafka offset: {commit_err}")
                    KAFKA_ERRORS.labels(operation="commit", topic=CONTROL_TOPIC).inc()
            
        await asyncio.sleep(0.01)

async def consume_signaling_commands():
    group_id = 'media-processor-signaling-group'
    signaling_kafka_consumer.subscribe([SIGNALING_IN_TOPIC])
    logger.info(f"Subscribed to Kafka signaling topic: {SIGNALING_IN_TOPIC}")
    
    while True:
        processed_successfully = False
        msg = None
        try:
            msg = signaling_kafka_consumer.poll(1.0)
            if msg is None: await asyncio.sleep(0.1); continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF: continue
                logger.error(f"Signaling Consumer Error: {msg.error()}")
                KAFKA_ERRORS.labels(operation="consume", topic=SIGNALING_IN_TOPIC).inc()
                await asyncio.sleep(5)
                continue
            
            # Message received successfully
            KAFKA_MESSAGES_CONSUMED.labels(topic=SIGNALING_IN_TOPIC, consumer_group=group_id).inc()
            
            with tracer.start_as_current_span("process_signaling_command", kind=trace.SpanKind.CONSUMER) as span:
                span.set_attribute("messaging.system", "kafka")
                span.set_attribute("messaging.source.name", SIGNALING_IN_TOPIC)
                span.set_attribute("messaging.consumer_group", group_id)
                if msg.key():
                    span.set_attribute("messaging.message.key", msg.key())
                
                signal_data = msg.value()
                if signal_data is None:
                    error_msg = f"Failed to deserialize signaling message from topic {msg.topic()}"
                    logger.error(error_msg)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                    DLQHandler.send_to_dlq(msg.topic(), msg.value(), msg.key(), "Deserialization Error", group_id)
                    DLQ_MESSAGES_SENT.labels(original_topic=msg.topic()).inc()
                    signaling_kafka_consumer.commit(message=msg)
                    continue
                    
                signal_type = signal_data.get('type')
                recipient_id = signal_data.get('recipient_id')
                target_stream_id = recipient_id # Assume recipient_id is the target stream
                
                span.set_attribute("signal.type", signal_type)
                if recipient_id:
                    span.set_attribute("signal.recipient_id", recipient_id)
                    span.set_attribute("target_stream_id", target_stream_id)
                
                if not target_stream_id or target_stream_id not in active_pipelines:
                    span.add_event("ignored_signal", {"reason": "Target stream not active"})
                    signaling_kafka_consumer.commit(message=msg) # Commit ignorable message
                    continue
                
                pipeline_info = active_pipelines.get(target_stream_id)
                webrtcbin = pipeline_info["webrtc"]
                payload_str = signal_data.get('payload')

                # Parse JSON payload inside try-except
                try:
                    signal_payload = json.loads(payload_str)
                    span.set_attribute("signal.payload_parsed", True)
                except json.JSONDecodeError as json_err:
                    error_msg = f"[{target_stream_id}] Failed to parse JSON payload in signaling message: {payload_str}. Error: {json_err}"
                    logger.error(error_msg)
                    span.record_exception(json_err)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                    DLQHandler.send_to_dlq(msg.topic(), signal_data, msg.key(), f"JSON Parse Error: {json_err}", group_id)
                    DLQ_MESSAGES_SENT.labels(original_topic=msg.topic()).inc()
                    signaling_kafka_consumer.commit(message=msg) # Commit bad message
                    continue

                # Schedule GStreamer operations
                if signal_type == 'answer':
                    sdp_text = signal_payload.get('sdp')
                    if sdp_text:
                        span.add_event("processing_answer", {"target_stream_id": target_stream_id})
                        GLib.idle_add(apply_remote_answer, webrtcbin, sdp_text, target_stream_id)
                    else:
                        error_msg = f"[{target_stream_id}] Received answer signal with missing SDP."
                        logger.warning(error_msg)
                        span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                        
                elif signal_type == 'ice-candidate':
                    candidate_str = signal_payload.get('candidate')
                    mline_index = signal_payload.get('sdpMLineIndex')
                    if candidate_str is not None and mline_index is not None:
                        span.add_event("processing_ice_candidate", {"target_stream_id": target_stream_id})
                        GLib.idle_add(apply_ice_candidate, webrtcbin, mline_index, candidate_str, target_stream_id)
                    else:
                        error_msg = f"[{target_stream_id}] Received invalid ICE candidate signal: {signal_payload}"
                        logger.warning(error_msg)
                        span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                else:
                    error_msg = f"[{target_stream_id}] Received unknown signal type: {signal_type}"
                    logger.warning(error_msg)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))
                
                processed_successfully = True
                     
        except KafkaException as e:
            logger.error(f"Signaling Consumer KafkaException: {e}")
            KAFKA_ERRORS.labels(operation="consume", topic=SIGNALING_IN_TOPIC).inc()
            await asyncio.sleep(5)
        except Exception as e:
            logger.exception(f"Error processing signaling command: {e}")
            
            # Send to DLQ if message exists
            if msg:
                try:
                    DLQHandler.send_to_dlq(
                        original_topic=msg.topic(),
                        failed_message_value=msg.value(),
                        failed_message_key=msg.key(),
                        error=str(e),
                        consumer_group=group_id
                    )
                    logger.info(f"Sent failed signaling message to DLQ (key: {msg.key()})")
                    
                    # Track DLQ metrics
                    DLQ_MESSAGES_SENT.labels(original_topic=msg.topic()).inc()
                    
                    # Mark as processed since we've handled the error via DLQ
                    processed_successfully = True
                except Exception as dlq_err:
                    logger.exception(f"Failed to send signaling message to DLQ: {dlq_err}")
                    # Don't commit in this case - let it be retried
                    processed_successfully = False
            
        # Ensure we commit successfully processed messages, including those sent to DLQ
        if msg and processed_successfully:
            try:
                signaling_kafka_consumer.commit(message=msg)
            except Exception as commit_err:
                logger.exception(f"[SignalingConsumer] CRITICAL: Failed to commit Kafka offset: {commit_err}")
                KAFKA_ERRORS.labels(operation="commit", topic=SIGNALING_IN_TOPIC).inc()
                
        await asyncio.sleep(0.01)

# --- Main Application Logic --- 
async def main():
    logger.info("Starting Media Processor Service...")
    
    # Set up tracing and metrics
    setup_tracing()
    start_metrics_server()
    
    Gst.init(None)

    loop = GLib.MainLoop()
    loop_thread = asyncio.to_thread(loop.run)

    # Start the metrics collection task
    metrics_task = await start_metrics_collection()
    
    # Initialize and start DLQ processor
    global dlq_processor
    dlq_processor = DLQProcessor(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        dlq_topic_pattern=DLQ_TOPIC_PATTERN,
        max_retries=DLQ_MAX_RETRIES,
        initial_retry_delay_ms=DLQ_INITIAL_RETRY_DELAY_MS,
        max_retry_delay_ms=DLQ_MAX_RETRY_DELAY_MS,
        backoff_multiplier=DLQ_BACKOFF_MULTIPLIER,
        poll_interval_ms=DLQ_POLL_INTERVAL_MS
    )
    dlq_processor_task = asyncio.create_task(dlq_processor.start())
    logger.info("DLQ Processor started successfully")
    
    control_consumer_task = asyncio.create_task(consume_control_commands())
    signaling_consumer_task = asyncio.create_task(consume_signaling_commands())

    logger.info("Media Processor Service running.")
    await asyncio.gather(
        control_consumer_task, 
        signaling_consumer_task, 
        metrics_task,
        dlq_processor_task,
        loop_thread, 
        return_exceptions=True
    )

    # Cleanup on exit
    logger.info("Shutting down Media Processor Service...")
    control_kafka_consumer.close()
    signaling_kafka_consumer.close()
    
    # Stop DLQ processor
    if dlq_processor:
        await dlq_processor.stop()
    
    # Cancel metrics collection task
    metrics_task.cancel()
    
    pipelines_to_stop = list(active_pipelines.keys())
    for stream_id in pipelines_to_stop:
        GLib.idle_add(stop_pipeline, stream_id)
    # Give some time for stop commands to be processed by GLoop
    await asyncio.sleep(1) 
        
    kakfa_producer.flush(timeout=5)
    
    await shutdown_tracing()
    
    if loop.is_running():
        loop.quit()

def handle_shutdown_signal(sig, frame):
    logger.info(f"Received signal {sig}, initiating shutdown...")
    # Find the main task and cancel it to trigger cleanup
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()

# Add these new signal handlers after the existing WebRTC signal handlers

def on_ice_connection_state_changed(webrtcbin, stream_id):
    """Track ICE connection state changes."""
    with tracer.start_as_current_span("on_ice_connection_state_changed") as span:
        ice_state = webrtcbin.get_property("ice-connection-state")
        span.set_attribute("stream_id", stream_id)
        span.set_attribute("ice_state", str(ice_state))
        
        state_name = "UNKNOWN"
        if ice_state == GstWebRTC.WebRTCICEConnectionState.NEW:
            state_name = "NEW"
        elif ice_state == GstWebRTC.WebRTCICEConnectionState.CHECKING:
            state_name = "CHECKING"
        elif ice_state == GstWebRTC.WebRTCICEConnectionState.CONNECTED:
            state_name = "CONNECTED"
            # ICE connected is a good indicator of successful connection
            end_connection_timer(stream_id)
        elif ice_state == GstWebRTC.WebRTCICEConnectionState.COMPLETED:
            state_name = "COMPLETED"
        elif ice_state == GstWebRTC.WebRTCICEConnectionState.FAILED:
            state_name = "FAILED"
            WEBRTC_CONNECTION_ERRORS.labels(stream_id=stream_id, error_type="ice_connection_failed").inc()
        elif ice_state == GstWebRTC.WebRTCICEConnectionState.DISCONNECTED:
            state_name = "DISCONNECTED"
        elif ice_state == GstWebRTC.WebRTCICEConnectionState.CLOSED:
            state_name = "CLOSED"
        
        # Increment the counter for this state change
        ICE_CONNECTION_STATE_CHANGES.labels(stream_id=stream_id, state=state_name).inc()
        logger.info(f"[{stream_id}] ICE connection state changed to: {state_name}")

def on_connection_state_changed(webrtcbin, stream_id):
    """Track overall WebRTC connection state changes."""
    with tracer.start_as_current_span("on_connection_state_changed") as span:
        conn_state = webrtcbin.get_property("connection-state")
        span.set_attribute("stream_id", stream_id)
        span.set_attribute("connection_state", str(conn_state))
        
        state_name = "UNKNOWN"
        if conn_state == GstWebRTC.WebRTCPeerConnectionState.NEW:
            state_name = "NEW"
        elif conn_state == GstWebRTC.WebRTCPeerConnectionState.CONNECTING:
            state_name = "CONNECTING"
        elif conn_state == GstWebRTC.WebRTCPeerConnectionState.CONNECTED:
            state_name = "CONNECTED"
        elif conn_state == GstWebRTC.WebRTCPeerConnectionState.DISCONNECTED:
            state_name = "DISCONNECTED"
        elif conn_state == GstWebRTC.WebRTCPeerConnectionState.FAILED:
            state_name = "FAILED"
            # If connection fails, record this as a failed state
            # This helps track issues with establishment
            WEBRTC_CONNECTION_ERRORS.labels(stream_id=stream_id, error_type="peer_connection_failed").inc()
            publish_status(stream_id, "ERROR_CONNECTION", {"error": f"WebRTC connection failed"})
        elif conn_state == GstWebRTC.WebRTCPeerConnectionState.CLOSED:
            state_name = "CLOSED"
        
        # Increment the counter for this state change
        WEBRTC_CONNECTION_STATE_CHANGES.labels(stream_id=stream_id, state=state_name).inc()
        logger.info(f"[{stream_id}] WebRTC connection state changed to: {state_name}")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        logger.info("Main task cancelled, exiting.") 