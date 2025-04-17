# backend/app/core/kafka_consumer_manager.py

import asyncio
import logging
import json
from typing import Dict, List, Set, Optional, Callable, Awaitable
from functools import partial

from confluent_kafka import KafkaError

from ..kafka.kafka_setup import get_kafka_consumer
from ..core.config import settings

logger = logging.getLogger(__name__)

class KafkaConsumerManager:
    """Manages shared Kafka consumers for specific topics, dispatching messages to handlers."""
    def __init__(self):
        self.consumer_tasks: Dict[str, asyncio.Task] = {}
        # topic -> client_id -> handler
        self.message_handlers: Dict[str, Dict[str, Callable[[str, Dict], Awaitable[None]]]] = {}
        self.shutdown_event = asyncio.Event()

    async def add_subscriber(self, client_id: str, topic: str,
                           handler: Callable[[str, Dict], Awaitable[None]]) -> None:
        """Add a client subscription handler for a specific topic."""
        if topic not in self.message_handlers:
            self.message_handlers[topic] = {}
            # Start consumer task if not already running for this topic
            if topic not in self.consumer_tasks or self.consumer_tasks[topic].done():
                logger.info(f"Starting consumer task for new topic: {topic}")
                self.consumer_tasks[topic] = asyncio.create_task(
                    self._run_consumer(topic)
                )
            else:
                 logger.debug(f"Consumer task already running for topic: {topic}")

        # Store the handler associated with the client_id
        self.message_handlers[topic][client_id] = handler
        logger.info(f"Added subscriber handler for {client_id} on topic {topic}")

    async def remove_subscriber(self, client_id: str, topic: Optional[str] = None) -> None:
        """Remove a client's handler from a specific topic or all topics."""
        topics_to_check = [topic] if topic else list(self.message_handlers.keys())
        
        for t in topics_to_check:
            if t in self.message_handlers and client_id in self.message_handlers[t]:
                del self.message_handlers[t][client_id]
                logger.info(f"Removed subscriber handler for {client_id} from topic {t}")
                
                # Check if topic has any subscribers left
                if not self.message_handlers[t]:
                    logger.info(f"No subscribers left for topic {t}. Cleaning up.")
                    del self.message_handlers[t]
                    # Cancel consumer task if it exists and is running
                    if t in self.consumer_tasks and not self.consumer_tasks[t].done():
                        logger.info(f"Cancelling consumer task for topic {t}")
                        self.consumer_tasks[t].cancel()
                        try:
                            await self.consumer_tasks[t]
                        except asyncio.CancelledError:
                            logger.info(f"Consumer task for topic {t} cancelled successfully.")
                        except Exception as e:
                            logger.exception(f"Error during cancellation cleanup for topic {t}: {e}")
                        # Remove task entry
                        if t in self.consumer_tasks:
                            del self.consumer_tasks[t]
                    elif t in self.consumer_tasks:
                         # Remove task entry if already done
                         del self.consumer_tasks[t]

    async def shutdown(self) -> None:
        """Shutdown all running consumer tasks."""
        logger.info("Shutting down Kafka Consumer Manager...")
        self.shutdown_event.set()
        tasks_to_await = []
        for topic, task in self.consumer_tasks.items():
            if task and not task.done():
                task.cancel()
                tasks_to_await.append(task)
            logger.info(f"Signaled cancellation for consumer task on topic {topic}")
            
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)
        logger.info("All Kafka consumer tasks shut down.")

    async def _run_consumer(self, topic: str) -> None:
        """Runs a shared Kafka consumer for a specific topic, dispatching to handlers."""
        group_id = f'websocket-shared-group-{topic}' # Shared group for the topic
        
        # Backoff parameters
        base_delay = 1.0
        max_delay = 30.0
        current_delay = base_delay

        consumer = None
        while not self.shutdown_event.is_set():
            try:
                if consumer is None:
                    consumer = get_kafka_consumer(topic, group_id)
                    if not consumer:
                        logger.error(f"Failed to create Kafka consumer for topic {topic}. Retrying in {current_delay}s...")
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * 2, max_delay)
                        continue
                    consumer.subscribe([topic])
                    logger.info(f"Kafka consumer subscribed to topic: {topic} with group: {group_id}")
                    current_delay = base_delay # Reset delay on successful connection

                msg = consumer.poll(1.0)
                if msg is None:
                    await asyncio.sleep(0.01)
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        logger.error(f"Kafka Consumer Error for topic {topic}: {msg.error()}")
                        # Basic backoff for consumer errors
                        consumer.close()
                        consumer = None
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * 2, max_delay)
                        continue # Retry connection and subscription
                
                # Process message
                message_data = msg.value()
                if message_data is None:
                    logger.error(f"Failed to deserialize message from topic {topic}")
                    consumer.commit(message=msg, asynchronous=False) # Skip bad message
                    continue

                # Dispatch to relevant handlers based on recipient or broadcast
                recipient_id = message_data.get('recipient_id')
                handlers_to_run = []

                if topic in self.message_handlers:
                    if recipient_id:
                        # Targeted message
                        handler = self.message_handlers[topic].get(recipient_id)
                        if handler:
                            handlers_to_run.append(asyncio.create_task(handler(topic, message_data)))
                        # else: logger.debug(f"No handler found for recipient {recipient_id} on topic {topic}")
                    else:
                        # Broadcast message to all subscribers on this topic
                        for client_id, handler in self.message_handlers[topic].items():
                            handlers_to_run.append(asyncio.create_task(handler(topic, message_data)))
                
                if handlers_to_run:
                    # Wait for all handlers associated with this message to complete
                    results = await asyncio.gather(*handlers_to_run, return_exceptions=True)
                    # Log any errors from handlers
                    for result in results:
                        if isinstance(result, Exception):
                            logger.error(f"Error in message handler for topic {topic}: {result}")
                            # Decide if the message should be retried or sent to DLQ based on handler errors
                # else: logger.debug(f"No handlers registered for topic {topic} or recipient {recipient_id}")

                # Commit offset after dispatching (and potentially waiting for handlers)
                consumer.commit(message=msg, asynchronous=False)

            except asyncio.CancelledError:
                logger.info(f"Consumer task for topic {topic} received cancellation signal.")
                break # Exit loop on cancellation
            except Exception as e:
                logger.exception(f"Unexpected error in Kafka consumer loop for topic {topic}: {e}")
                # Consider more robust error handling, potentially break/restart consumer
                await asyncio.sleep(5) # Wait before continuing after generic error

        if consumer:
            consumer.close()
        logger.info(f"Closed Kafka consumer for topic {topic}.")

# Singleton instance of the manager
kafka_consumer_manager = KafkaConsumerManager() 