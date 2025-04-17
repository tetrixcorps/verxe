# backend/app/kafka/kafka_setup.py
import logging
import pathlib

from confluent_kafka import DeserializingConsumer, SerializingProducer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
from confluent_kafka.serialization import StringDeserializer, StringSerializer

from ..core.config import settings

logger = logging.getLogger(__name__)

# --- Schema Registry and Deserializer Cache --- 
# Avoid re-initializing client and loading schemas repeatedly
_schema_registry_client = None
_avro_deserializers = {}
_kafka_producer = None # Added cache for producer

def get_schema_registry_client():
    global _schema_registry_client
    if _schema_registry_client is None:
        logger.info(f"Initializing Schema Registry client for URL: {settings.SCHEMA_REGISTRY_URL}")
        schema_registry_conf = {'url': settings.SCHEMA_REGISTRY_URL}
        _schema_registry_client = SchemaRegistryClient(schema_registry_conf)
    return _schema_registry_client

def load_avro_schema(schema_file: str):
    schema_path = pathlib.Path(__file__).parent.parent / "schemas" / "avro" / schema_file
    if not schema_path.exists():
        logger.error(f"Schema file not found at: {schema_path}")
        return None
    with open(schema_path, 'r') as f:
        return f.read()

def get_avro_deserializer(schema_name: str):
    if schema_name not in _avro_deserializers:
        schema_str = load_avro_schema(f"{schema_name}.avsc")
        if schema_str:
            sr_client = get_schema_registry_client()
            _avro_deserializers[schema_name] = AvroDeserializer(
                sr_client,
                schema_str,
                lambda obj, ctx: obj # from_dict function (simple pass-through)
            )
        else:
            return None # Schema not found
    return _avro_deserializers[schema_name]

# --- Producer Factory --- 
def get_kafka_producer() -> SerializingProducer | None:
    """Creates and returns a configured Kafka SerializingProducer instance."""
    global _kafka_producer
    if _kafka_producer is None:
        try:
            string_serializer = StringSerializer('utf_8')
            # Get a default value serializer (e.g., for stream_control or make it flexible)
            # This assumes the producer might send different types, requiring schema per message
            # Or we configure a default one here if producer only sends one type
            # Example: Using control schema as default
            value_serializer = AvroSerializer(
                 get_schema_registry_client(),
                 load_avro_schema("stream_control.avsc"), # Default schema
                 lambda obj, ctx: obj
            )

            producer_config = {
                'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
                'client.id': 'backend-producer', # Generic ID
                'key.serializer': string_serializer,
                'value.serializer': value_serializer
            }
            _kafka_producer = SerializingProducer(producer_config)
            logger.info("Initialized Kafka SerializingProducer.")
        except Exception as e:
             logger.exception(f"Failed to create Kafka producer: {e}")
             return None
    return _kafka_producer

# --- Consumer Factory --- 

def get_kafka_consumer(topic: str, group_id: str) -> DeserializingConsumer | None:
    """Creates and returns a configured Kafka DeserializingConsumer."""
    
    # Map topics to their corresponding schema names
    topic_to_schema_map = {
        settings.KAFKA_TOPIC_STREAM_STATUS: "stream_status",
        settings.KAFKA_TOPIC_STREAM_CONTROL: "stream_control",
        settings.KAFKA_TOPIC_WEBRTC_SIGNALING_IN: "webrtc_signal",
        settings.KAFKA_TOPIC_WEBRTC_SIGNALING_OUT: "webrtc_signal",
    }
    
    # Determine schema name based on topic
    schema_name = topic_to_schema_map.get(topic)
    
    if not schema_name:
        logger.error(f"No Avro schema mapping found for topic: {topic}")
        return None
        
    value_deserializer = get_avro_deserializer(schema_name)
    if not value_deserializer:
        logger.error(f"Could not create Avro deserializer for schema: {schema_name}")
        return None
        
    string_deserializer = StringDeserializer('utf_8')
    
    consumer_config = {
        'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': group_id,
        'auto.offset.reset': 'earliest', # Or 'latest' depending on use case
        'enable.auto.commit': False, 
        'key.deserializer': string_deserializer,
        'value.deserializer': value_deserializer
        # 'fetch.min.bytes': 1,
        # 'fetch.wait.max.ms': 100,
    }
    
    try:
        consumer = DeserializingConsumer(consumer_config)
        return consumer
    except Exception as e:
        logger.exception(f"Failed to create Kafka consumer for group {group_id}: {e}")
        return None 