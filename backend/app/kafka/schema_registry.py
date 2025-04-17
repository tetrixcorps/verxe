# backend/app/kafka/schema_registry.py

import logging
import pathlib
from typing import Dict, Optional, Any, Callable

from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
from confluent_kafka.serialization import StringDeserializer, StringSerializer

from ..core.config import settings

logger = logging.getLogger(__name__)

# Singletons
_schema_registry_client = None
_avro_serializers = {}
_avro_deserializers = {}

def get_schema_registry_client() -> SchemaRegistryClient:
    """
    Returns a schema registry client instance.
    Reuses an existing instance if available.
    """
    global _schema_registry_client
    if _schema_registry_client is None:
        logger.info(f"Initializing Schema Registry client for URL: {settings.SCHEMA_REGISTRY_URL}")
        schema_registry_conf = {'url': settings.SCHEMA_REGISTRY_URL}
        _schema_registry_client = SchemaRegistryClient(schema_registry_conf)
    return _schema_registry_client

def load_avro_schema(schema_file: str) -> Optional[str]:
    """
    Loads an Avro schema from the file system.
    
    Args:
        schema_file: The name of the schema file (e.g., "stream_control.avsc")
        
    Returns:
        The schema as a string, or None if not found
    """
    schema_path = pathlib.Path(__file__).parent.parent / "schemas" / "avro" / schema_file
    if not schema_path.exists():
        logger.error(f"Schema file not found at: {schema_path}")
        return None
    with open(schema_path, 'r') as f:
        return f.read()

def get_avro_serializer(schema_name: str, to_dict_function: Optional[Callable[[Any, Any], Dict]] = None) -> Optional[AvroSerializer]:
    """
    Returns an AvroSerializer for a given schema name.
    Reuses an existing serializer if available.
    
    Args:
        schema_name: The name of the schema (e.g., "stream_control")
        to_dict_function: Optional function to convert an object to a dict
        
    Returns:
        An AvroSerializer, or None if the schema is not found
    """
    global _avro_serializers
    
    # Use default to_dict function if not provided
    if to_dict_function is None:
        to_dict_function = lambda obj, ctx: obj
    
    # Use cached serializer if available
    cache_key = f"{schema_name}_serializer"
    if cache_key in _avro_serializers:
        return _avro_serializers[cache_key]
    
    # Load the schema
    schema_str = load_avro_schema(f"{schema_name}.avsc")
    if not schema_str:
        return None
    
    # Create and cache the serializer
    sr_client = get_schema_registry_client()
    _avro_serializers[cache_key] = AvroSerializer(
        sr_client,
        schema_str,
        to_dict_function
    )
    
    return _avro_serializers[cache_key]

def get_avro_deserializer(schema_name: str, from_dict_function: Optional[Callable[[Dict, Any], Any]] = None) -> Optional[AvroDeserializer]:
    """
    Returns an AvroDeserializer for a given schema name.
    Reuses an existing deserializer if available.
    
    Args:
        schema_name: The name of the schema (e.g., "stream_control")
        from_dict_function: Optional function to convert a dict to an object
        
    Returns:
        An AvroDeserializer, or None if the schema is not found
    """
    global _avro_deserializers
    
    # Use default from_dict function if not provided
    if from_dict_function is None:
        from_dict_function = lambda obj, ctx: obj
    
    # Use cached deserializer if available
    cache_key = f"{schema_name}_deserializer"
    if cache_key in _avro_deserializers:
        return _avro_deserializers[cache_key]
    
    # Load the schema
    schema_str = load_avro_schema(f"{schema_name}.avsc")
    if not schema_str:
        return None
    
    # Create and cache the deserializer
    sr_client = get_schema_registry_client()
    _avro_deserializers[cache_key] = AvroDeserializer(
        sr_client,
        schema_str,
        from_dict_function
    )
    
    return _avro_deserializers[cache_key]

def get_string_serializer() -> StringSerializer:
    """Returns a string serializer."""
    return StringSerializer('utf_8')

def get_string_deserializer() -> StringDeserializer:
    """Returns a string deserializer."""
    return StringDeserializer('utf_8') 