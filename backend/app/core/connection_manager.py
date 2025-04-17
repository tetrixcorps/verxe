# backend/app/core/connection_manager.py

import asyncio
import json
import logging
import threading
import uuid
from typing import Dict, Optional

import redis.asyncio as redis # Use async redis client
from fastapi import WebSocket

from .config import settings

logger = logging.getLogger(__name__)

class RedisConnectionManager:
    """Manages WebSocket connections across multiple backend instances using Redis."""
    def __init__(self):
        self.instance_id: str = str(uuid.uuid4())
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub_listener_task: Optional[asyncio.Task] = None
        # Local connections managed by this specific instance
        self.local_connections: Dict[str, WebSocket] = {}
        logger.info(f"Initializing ConnectionManager for instance: {self.instance_id}")

    async def connect_redis(self):
        """Establishes connection to Redis."""
        try:
            self.redis_client = redis.Redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True # Decode responses automatically
            )
            await self.redis_client.ping()
            logger.info("Successfully connected to Redis.")
        except Exception as e:
            logger.exception(f"Failed to connect to Redis: {e}")
            self.redis_client = None

    async def disconnect_redis(self):
        """Closes the Redis connection."""
        if self.pubsub_listener_task and not self.pubsub_listener_task.done():
            self.pubsub_listener_task.cancel()
            try:
                await self.pubsub_listener_task
            except asyncio.CancelledError:
                logger.info("Redis Pub/Sub listener task cancelled.")
        
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed.")

    async def register_connection(self, user_id: str, websocket: WebSocket) -> str:
        """Registers a new WebSocket connection locally and in Redis."""
        if not self.redis_client:
            logger.error("Redis not connected. Cannot register connection.")
            raise ConnectionError("Redis connection not available")
            
        connection_id = str(uuid.uuid4())
        await websocket.accept()
        self.local_connections[connection_id] = websocket
        logger.info(f"WebSocket accepted for user {user_id}, connection_id {connection_id}")

        try:
            # Use a pipeline for atomic operations
            async with self.redis_client.pipeline(transaction=True) as pipe:
                redis_key = f"user:{user_id}:connection"
                pipe.hset(redis_key, mapping={
                    "instance_id": self.instance_id,
                    "connection_id": connection_id
                })
                pipe.expire(redis_key, 3600) # Expire after 1 hour (needs refresh mechanism)
                await pipe.execute()
            logger.info(f"Registered user {user_id} connection {connection_id} to instance {self.instance_id} in Redis.")
            
            # Start the pub/sub listener if it's not running
            if self.pubsub_listener_task is None or self.pubsub_listener_task.done():
                await self.start_pubsub_listener()
                
            return connection_id
        except Exception as e:
            logger.exception(f"Failed to register connection in Redis for user {user_id}: {e}")
            # Clean up local connection if Redis registration failed
            if connection_id in self.local_connections:
                del self.local_connections[connection_id]
            raise # Re-raise the exception

    async def disconnect(self, connection_id: str, user_id: str):
        """Removes a connection locally and from Redis."""
        logger.info(f"Disconnecting connection {connection_id} for user {user_id}")
        if connection_id in self.local_connections:
            del self.local_connections[connection_id]
        
        if self.redis_client:
            try:
                await self.redis_client.delete(f"user:{user_id}:connection")
                logger.info(f"Removed connection info from Redis for user {user_id}")
            except Exception as e:
                logger.exception(f"Failed to remove connection info from Redis for user {user_id}: {e}")
        
        # Consider stopping the pubsub listener if no local connections remain?
        # if not self.local_connections and self.pubsub_listener_task and not self.pubsub_listener_task.done():
        #     self.pubsub_listener_task.cancel()
        #     self.pubsub_listener_task = None 

    async def start_pubsub_listener(self):
        """Starts the background task listening to Redis Pub/Sub for this instance."""
        if not self.redis_client:
            logger.error("Cannot start Pub/Sub listener: Redis not connected.")
            return
            
        if self.pubsub_listener_task and not self.pubsub_listener_task.done():
            logger.warning("Pub/Sub listener task already running.")
            return

        self.pubsub_listener_task = asyncio.create_task(self._pubsub_listener())
        logger.info("Started Redis Pub/Sub listener task.")

    async def _pubsub_listener(self):
        """Listens for messages on the instance-specific Redis channel and relays them."""
        if not self.redis_client: return
        
        pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)
        channel_name = f"websocket_relay:{self.instance_id}"
        try:
            await pubsub.subscribe(channel_name)
            logger.info(f"Subscribed to Redis relay channel: {channel_name}")
            
            while True:
                message = await pubsub.get_message(timeout=1.0) # Use timeout
                if message is not None:
                    try:
                        data = json.loads(message["data"])
                        target_connection_id = data.get('connection_id')
                        payload_str = data.get('payload') # Assume payload is already JSON string
                        
                        if target_connection_id and payload_str:
                            await self._send_to_local_connection(target_connection_id, payload_str)
                        else:
                            logger.warning(f"Received invalid relay message: {data}")
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode JSON from relay message: {message['data']}")
                    except Exception as e:
                        logger.exception(f"Error processing relay message: {e}")
                # Check cancellation periodically
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            logger.info("Pub/Sub listener task is stopping.")
        except Exception as e:
            logger.exception(f"Redis Pub/Sub listener error: {e}")
        finally:
            try:
                if pubsub:
                    await pubsub.unsubscribe(channel_name)
                    await pubsub.close()
                logger.info(f"Unsubscribed from Redis relay channel: {channel_name}")
            except Exception as e:
                logger.exception(f"Error during pubsub cleanup: {e}")

    async def _send_to_local_connection(self, connection_id: str, message: str):
        """Sends a message to a WebSocket connection handled by this instance."""
        websocket = self.local_connections.get(connection_id)
        if websocket:
            try:
                await websocket.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send message to local connection {connection_id}: {e}. Removing connection.")
                # Clean up potentially dead connection
                user_id = await self._find_user_for_connection(connection_id) # Helper needed
                if user_id:
                    await self.disconnect(connection_id, user_id)
                else:
                     # Fallback if user mapping not found (should not happen)
                     if connection_id in self.local_connections:
                        del self.local_connections[connection_id]
        # else: logger.warning(f"Local connection {connection_id} not found for relay message.")

    async def broadcast_to_user(self, user_id: str, message: str):
        """Sends a message to a specific user, relaying via Redis if necessary."""
        if not self.redis_client:
            logger.error("Redis not connected. Cannot broadcast message.")
            return False

        try:
            user_conn_info = await self.redis_client.hgetall(f"user:{user_id}:connection")
            if not user_conn_info:
                # logger.debug(f"User {user_id} not connected. Cannot broadcast message.")
                return False # User not connected anywhere

            target_instance_id = user_conn_info.get('instance_id')
            target_connection_id = user_conn_info.get('connection_id')

            if not target_instance_id or not target_connection_id:
                logger.error(f"Incomplete connection info in Redis for user {user_id}")
                return False

            if target_instance_id == self.instance_id:
                # Connection is local to this instance
                await self._send_to_local_connection(target_connection_id, message)
            else:
                # Connection is on another instance, relay via Redis Pub/Sub
                relay_message = json.dumps({
                    "connection_id": target_connection_id,
                    "payload": message # Message should already be JSON string
                })
                await self.redis_client.publish(f"websocket_relay:{target_instance_id}", relay_message)
                # logger.debug(f"Relayed message to user {user_id} via instance {target_instance_id}")
            return True

        except Exception as e:
            logger.exception(f"Error broadcasting to user {user_id}: {e}")
            return False

    async def _find_user_for_connection(self, connection_id_to_find: str) -> Optional[str]:
        """(Helper/Expensive) Finds user ID associated with a local connection ID.
           Avoid using this frequently. Better to pass user_id to disconnect."""
        if not self.redis_client:
            return None
        # This requires scanning keys, which is inefficient for production
        # A reverse index (connection_id -> user_id) in Redis might be needed if 
        # user_id isn't available during disconnect cleanup initiated by send errors.
        logger.warning("Attempting inefficient reverse lookup for connection_id - consider passing user_id to disconnect.")
        async for key in self.redis_client.scan_iter("user:*:connection"):
            conn_info = await self.redis_client.hgetall(key)
            if conn_info.get('instance_id') == self.instance_id and \
               conn_info.get('connection_id') == connection_id_to_find:
                # Extract user_id from the key user:<user_id>:connection
                parts = key.split(':')
                if len(parts) == 3:
                    return parts[1]
        return None

# Global instance (or manage via dependency injection)
connection_manager = RedisConnectionManager() 