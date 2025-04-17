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

# --- Configuration --- 
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')
CONTROL_TOPIC = os.environ.get('KAFKA_TOPIC_STREAM_CONTROL', 'stream_control_events')
STATUS_TOPIC = os.environ.get('KAFKA_TOPIC_STREAM_STATUS', 'stream_status_events')
SIGNALING_IN_TOPIC = os.environ.get('KAFKA_TOPIC_WEBRTC_SIGNALING_IN', 'webrtc_signaling_in')
SIGNALING_OUT_TOPIC = os.environ.get('KAFKA_TOPIC_WEBRTC_SIGNALING_OUT', 'webrtc_signaling_out')
SCHEMA_REGISTRY_URL = os.environ.get('SCHEMA_REGISTRY_URL', 'http://schema-registry:8081')
STUN_SERVER = os.environ.get("STUN_SERVER", "stun://stun.l.google.com:19302")
TURN_SERVER_URL = os.environ.get("TURN_SERVER_URL") # e.g., turn:user:pass@host:port

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
    """Builds the core GStreamer pipeline sending media to WebRTCBin."""
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

    logger.info(f"[{stream_id}] Successfully built GStreamer pipeline for room {room_id}.")
    return pipeline, webrtc

def start_pipeline(stream_id: str, stream_key: str, rtmp_url: Optional[str], is_recorded: bool, room_id: str):
    """Creates, starts, and manages a GStreamer pipeline instance for WebRTC."""
    if stream_id in active_pipelines:
        logger.warning(f"[{stream_id}] Pipeline already exists. Ignoring START command.")
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
        logger.info(f"[{stream_id}] Pipeline starting successfully.")
        # Status is implicitly PENDING until offer/answer completes
        publish_status(stream_id, "STARTING") 

    except Exception as e:
        logger.exception(f"[{stream_id}] Failed to start pipeline: {e}")
        publish_status(stream_id, "ERROR_START", {"error": str(e)})

def stop_pipeline(stream_id: str):
    pipeline_info = active_pipelines.pop(stream_id, None)
    if pipeline_info:
        pipeline = pipeline_info.get("pipeline")
        if pipeline:
            logger.info(f"[{stream_id}] Stopping pipeline...")
            pipeline.set_state(Gst.State.NULL)
            logger.info(f"[{stream_id}] Pipeline stopped.")
        else:
             logger.warning(f"[{stream_id}] Stop command received, but pipeline object missing.")
    else:
        logger.warning(f"[{stream_id}] Stop command received, but no active pipeline found.")

# --- GStreamer Message Handlers --- 
def on_error(bus, message, stream_id):
    err, debug = message.parse_error()
    logger.error(f"[{stream_id}] GStreamer Error: {err}, {debug}")
    publish_status(stream_id, "ERROR_RUNTIME", {"error": f"{err} {debug}"})
    GLib.idle_add(stop_pipeline, stream_id) # Ensure stop runs in GLoop thread

def on_eos(bus, message, stream_id):
    logger.info(f"[{stream_id}] End-Of-Stream received.")
    publish_status(stream_id, "ENDED_EOS")
    GLib.idle_add(stop_pipeline, stream_id)

def on_state_changed(bus, message, stream_id):
    pipeline_info = active_pipelines.get(stream_id)
    if pipeline_info and message.src == pipeline_info.get("pipeline"):
        old, new, pending = message.parse_state_changed()
        logger.debug(f"[{stream_id}] Pipeline state changed from {old.value_nick} to {new.value_nick}")
        if new == Gst.State.NULL and old != Gst.State.NULL:
            logger.warning(f"[{stream_id}] Pipeline reached NULL state.")
            # Ensure cleanup if state change happens
            if stream_id in active_pipelines: # Check if not already removed by stop_pipeline
                active_pipelines.pop(stream_id, None)
                publish_status(stream_id, "ENDED") # Generic ended status

# --- WebRTC Signal Handlers --- 
def on_negotiation_needed(webrtcbin, stream_id, room_id):
    logger.info(f"[{stream_id}] WebRTC negotiation needed for room {room_id}, creating offer...")
    GLib.idle_add(emit_create_offer, webrtcbin, stream_id, room_id)

def emit_create_offer(webrtcbin, stream_id, room_id):
    promise = Gst.Promise.new_with_change_func(on_offer_created, webrtcbin, stream_id, room_id)
    webrtcbin.emit("create-offer", None, promise)

def on_offer_created(promise: Gst.Promise, webrtcbin: Gst.Element, stream_id: str, room_id: str):
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

def on_ice_candidate(webrtcbin, mline_index, candidate_str, stream_id, room_id):
    logger.debug(f"[{stream_id}] ICE candidate generated for room {room_id}")
    publish_webrtc_signal(
        signal_type='ice-candidate',
        room_id=room_id,
        sender_id=stream_id,
        payload={'candidate': candidate_str, 'sdpMLineIndex': mline_index}
    )

def on_incoming_decode_pad(webrtcbin, pad, stream_id):
     # This handles the decoded media received from the peer
     # In a send-only scenario, we might not expect remote tracks
     # but webrtcbin might create pads anyway.
     logger.info(f"[{stream_id}] Pad added: {pad.get_name()}")
     # If this were a viewer, you'd link this pad to decodebin ! autovideosink etc.
     # For a sender, we usually ignore these unless doing bi-directional checks.

# --- Kafka Interaction --- 
def publish_status(stream_id: str, status: str, details: Optional[dict] = None):
    payload_dict = {
        'stream_id': stream_id,
        'status': status,
        'timestamp': datetime.utcnow().isoformat(),
        'service_id': 'media-processor-instance-1', 
        'metadata': details,
        'version': 1
    }
    try:
        kakfa_producer.produce(
            topic=STATUS_TOPIC,
            key=stream_id,
            value=payload_dict,
            value_serializer=avro_status_serializer, # Use correct serializer
            on_delivery=kafka_delivery_report
        )
        kakfa_producer.poll(0)
    except BufferError:
        logger.error(f"[{stream_id}] Kafka producer queue is full trying to send status.")
    except Exception as e:
        logger.error(f"[{stream_id}] Failed to publish status '{status}' to Kafka: {e}")

def publish_webrtc_signal(signal_type: str, room_id: str, sender_id: str, payload: dict, recipient_id: Optional[str] = None):
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
        logger.debug(f"Published {signal_type} signal for room {room_id} from {sender_id}")
    except BufferError:
        logger.error(f"Kafka producer queue is full trying to send {signal_type} signal for room {room_id}.")
    except Exception as e:
        logger.exception(f"Failed to publish {signal_type} signal for room {room_id}: {e}")

# --- Kafka Consumer Loops --- 
async def consume_control_commands():
    """Consumes commands from the control topic using Avro."""
    control_kafka_consumer.subscribe([CONTROL_TOPIC])
    logger.info(f"Subscribed to Kafka control topic: {CONTROL_TOPIC}")
    while True:
        try:
            msg = control_kafka_consumer.poll(1.0)
            if msg is None: await asyncio.sleep(0.1); continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF: continue
                logger.error(f"Control Consumer Error: {msg.error()}")
                await asyncio.sleep(5)
                continue
            
            command_data = msg.value()
            if command_data is None:
                logger.error(f"Failed to deserialize control message from topic {msg.topic()}")
                control_kafka_consumer.commit(message=msg)
                continue
                
            command = command_data.get('command')
            stream_id = command_data.get('stream_id')
            stream_key = command_data.get('stream_key')
            rtmp_url = command_data.get('rtmp_url')
            is_recorded = command_data.get('is_recorded', False)
            room_id = command_data.get('room_id')

            if not stream_id or not room_id:
                logger.warning("Ignoring command with missing stream_id or room_id")
                control_kafka_consumer.commit(message=msg)
                continue
                
            logger.info(f"Received command: {command} for stream: {stream_id} in room: {room_id}")
                
            if command == 'START':
                GLib.idle_add(start_pipeline, stream_id, stream_key, rtmp_url, is_recorded, room_id)
            elif command == 'STOP':
                GLib.idle_add(stop_pipeline, stream_id)
            else:
                logger.warning(f"[{stream_id}] Unknown control command received: {command}")
            
            control_kafka_consumer.commit(message=msg)
        except Exception as e:
            logger.exception(f"Error processing control command: {e}")
            await asyncio.sleep(1)
        await asyncio.sleep(0.01)

async def consume_signaling_commands():
    """Consumes incoming signaling messages (answer, candidate) from Kafka."""
    signaling_kafka_consumer.subscribe([SIGNALING_IN_TOPIC])
    logger.info(f"Subscribed to Kafka signaling topic: {SIGNALING_IN_TOPIC}")
    
    while True:
        try:
            msg = signaling_kafka_consumer.poll(1.0)
            if msg is None: await asyncio.sleep(0.1); continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF: continue
                logger.error(f"Signaling Consumer Error: {msg.error()}")
                await asyncio.sleep(5)
                continue
                
            signal_data = msg.value()
            if signal_data is None:
                logger.error(f"Failed to deserialize signaling message from topic {msg.topic()}")
                signaling_kafka_consumer.commit(message=msg)
                continue
                
            signal_type = signal_data.get('type')
            sender_id = signal_data.get('sender_id')
            room_id = signal_data.get('room_id')
            payload_str = signal_data.get('payload')
            recipient_id = signal_data.get('recipient_id') 
            
            # Target the specific stream based on recipient_id (which should be stream_id)
            target_stream_id = recipient_id
            
            if not target_stream_id or target_stream_id not in active_pipelines:
                # If no direct target, maybe log or ignore if not relevant to this processor
                # logger.debug(f"No active pipeline found for recipient {recipient_id} from signal sender {sender_id}")
                signaling_kafka_consumer.commit(message=msg)
                continue
                
            pipeline_info = active_pipelines.get(target_stream_id)
            if not pipeline_info or not pipeline_info.get("webrtc"):
                 logger.warning(f"[{target_stream_id}] Received signal but webrtcbin not found.")
                 signaling_kafka_consumer.commit(message=msg)
                 continue

            webrtcbin = pipeline_info["webrtc"]
            logger.debug(f"[{target_stream_id}] Processing {signal_type} signal from {sender_id}")

            try:
                signal_payload = json.loads(payload_str)
            except json.JSONDecodeError:
                logger.error(f"[{target_stream_id}] Failed to parse JSON payload in signaling message: {payload_str}")
                signaling_kafka_consumer.commit(message=msg)
                continue

            # Schedule GStreamer operations on the main loop thread
            if signal_type == 'answer':
                sdp_text = signal_payload.get('sdp')
                if sdp_text:
                    GLib.idle_add(apply_remote_answer, webrtcbin, sdp_text, target_stream_id)
                else:
                    logger.warning(f"[{target_stream_id}] Received answer signal with missing SDP.")
                    
            elif signal_type == 'ice-candidate':
                candidate_str = signal_payload.get('candidate')
                mline_index = signal_payload.get('sdpMLineIndex')
                if candidate_str is not None and mline_index is not None:
                     GLib.idle_add(apply_ice_candidate, webrtcbin, mline_index, candidate_str, target_stream_id)
                else:
                    logger.warning(f"[{target_stream_id}] Received invalid ICE candidate signal: {signal_payload}")
            else:
                 logger.warning(f"[{target_stream_id}] Received unknown signal type: {signal_type}")
                 
            signaling_kafka_consumer.commit(message=msg)
            
        except Exception as e:
            logger.exception(f"Error processing signaling command: {e}")
            # Consider not committing and retrying or moving to a dead-letter queue
        await asyncio.sleep(0.01)

# --- GStreamer Operations (Called via GLib.idle_add) --- 
def apply_remote_answer(webrtcbin, sdp_text, stream_id):
    logger.info(f"[{stream_id}] Applying remote description (answer)...")
    res, sdp = GstSdp.SDPMessage.new_from_text(sdp_text)
    if res != GstSdp.SDPResult.OK:
        logger.error(f"[{stream_id}] Failed to parse remote SDP answer.")
        return False # Return value for idle_add indicates if it should be called again (False = no)
        
    answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdp)
    promise = Gst.Promise.new()
    webrtcbin.emit("set-remote-description", answer, promise)
    # Wait for the promise to resolve? Or handle potential errors via promise change func?
    # For simplicity, we interrupt. Error handling might be needed.
    promise.interrupt() 
    logger.info(f"[{stream_id}] Applied remote answer description.")
    return False # Do not call again

def apply_ice_candidate(webrtcbin, mline_index, candidate_str, stream_id):
    logger.debug(f"[{stream_id}] Applying remote ICE candidate...")
    webrtcbin.emit('add-ice-candidate', mline_index, candidate_str)
    return False # Do not call again

# --- Main Application Logic --- 
async def main():
    logger.info("Starting Media Processor Service...")
    Gst.init(None)

    loop = GLib.MainLoop()
    loop_thread = asyncio.to_thread(loop.run)

    control_consumer_task = asyncio.create_task(consume_control_commands())
    signaling_consumer_task = asyncio.create_task(consume_signaling_commands())

    logger.info("Media Processor Service running.")
    await asyncio.gather(control_consumer_task, signaling_consumer_task, loop_thread, return_exceptions=True)

    # Cleanup on exit
    logger.info("Shutting down Media Processor Service...")
    control_kafka_consumer.close()
    signaling_kafka_consumer.close()
    
    pipelines_to_stop = list(active_pipelines.keys())
    for stream_id in pipelines_to_stop:
        GLib.idle_add(stop_pipeline, stream_id)
    # Give some time for stop commands to be processed by GLoop
    await asyncio.sleep(1) 
        
    kakfa_producer.flush(timeout=5) 
    if loop.is_running():
        loop.quit()

def handle_shutdown_signal(sig, frame):
    logger.info(f"Received signal {sig}, initiating shutdown...")
    # Find the main task and cancel it to trigger cleanup
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        logger.info("Main task cancelled, exiting.") 