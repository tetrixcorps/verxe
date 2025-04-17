import secrets
from typing import Any, Dict, List, Optional, Union

from pydantic import AnyHttpUrl, PostgresDsn, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_V1_STR: str = "/api"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    # 60 minutes * 24 hours * 30 days = 30 days
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30
    SERVER_NAME: str = "Verxe Chat"
    SERVER_HOST: AnyHttpUrl = "http://localhost:8000"
    # BACKEND_CORS_ORIGINS is a JSON-formatted list of origins
    # e.g: '["http://localhost", "http://localhost:4200", "http://localhost:3000"]'
    CORS_ORIGINS: List[AnyHttpUrl] = ["http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    PROJECT_NAME: str = "Verxe Chat"
    
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "verxe_db"
    SQLALCHEMY_DATABASE_URI: Optional[PostgresDsn] = None

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    def assemble_db_connection(cls, v: Optional[str], info) -> Any:
        if isinstance(v, str):
            return v
        values = info.data
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=values.get("POSTGRES_USER"),
            password=values.get("POSTGRES_PASSWORD"),
            host=values.get("POSTGRES_SERVER"),
            path=f"/{values.get('POSTGRES_DB') or ''}",
        )
    
    # Streaming settings
    RTMP_SERVER_URL: str = "rtmp://localhost/live"
    HLS_SERVER_URL: str = "http://localhost:8080/hls"
    ENABLE_GSTREAMER: bool = False
    ENABLE_RECORDING: bool = False
    RECORDING_PATH: str = "/tmp/recordings"
    
    # Object storage settings (S3)
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    AWS_BUCKET_NAME: str = "verxe-uploads"
    
    # Rate limiting settings
    RATE_LIMIT_TIER_1: int = 10  # requests per minute for tier 1 (basic)
    RATE_LIMIT_TIER_2: int = 30  # requests per minute for tier 2 (silver)
    RATE_LIMIT_TIER_3: int = 60  # requests per minute for tier 3 (gold)
    RATE_LIMIT_TIER_4: int = 100 # requests per minute for tier 4 (diamond)
    
    # Token settings
    INITIAL_TOKEN_GRANT: float = 100.0  # tokens granted to new users
    
    # Stripe settings
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None

    # Google OAuth settings
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = f"{SERVER_HOST}/api/auth/google/callback" # Default callback URI

    # Kafka settings
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_TOPIC_STREAM_CONTROL: str = "stream_control_events"
    KAFKA_TOPIC_STREAM_STATUS: str = "stream_status_events"
    KAFKA_TOPIC_WEBRTC_SIGNALING_IN: str = "webrtc_signaling_in"
    KAFKA_TOPIC_WEBRTC_SIGNALING_OUT: str = "webrtc_signaling_out"
    # Dead Letter Queue topics
    KAFKA_TOPIC_STREAM_CONTROL_DLQ: str = "stream_control_events_dlq"
    KAFKA_TOPIC_STREAM_STATUS_DLQ: str = "stream_status_events_dlq"
    KAFKA_TOPIC_WEBRTC_SIGNALING_IN_DLQ: str = "webrtc_signaling_in_dlq"
    KAFKA_TOPIC_WEBRTC_SIGNALING_OUT_DLQ: str = "webrtc_signaling_out_dlq"
    KAFKA_TOPIC_CHAT_DLQ: str = "chat_events_dlq"
    SCHEMA_REGISTRY_URL: str = "http://schema-registry:8081"

    # Redis settings
    REDIS_URL: str = "redis://redis:6379/0"

    model_config = {
        "case_sensitive": True,
        "env_file": ".env"
    }


settings = Settings() 