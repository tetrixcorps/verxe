# DLQ Processor

This service processes messages from Dead Letter Queues (DLQ) by attempting to reprocess failed messages and reintroduce them to their original topics.

## Overview

The DLQ Processor automatically discovers DLQ topics following a configured naming pattern, consumes failed messages from these queues, and attempts to reprocess them. If reprocessing succeeds, the message is published back to its original destination topic.

## Features

- Automatic DLQ topic discovery
- Configurable retry strategy with exponential backoff
- Metrics exposure via HTTP endpoint
- Graceful shutdown handling
- Configurable via environment variables or command-line arguments

## Running the DLQ Processor

### Using Docker

```bash
docker build -t dlq-processor -f Dockerfile.dlq_processor .
docker run -p 8001:8001 \
  -e KAFKA_BOOTSTRAP_SERVERS=kafka:9092 \
  -e KAFKA_CONSUMER_GROUP=dlq-processor \
  -e DLQ_TOPIC_PATTERN=".*\.dlq" \
  dlq-processor
```

### Using Python directly

```bash
python run_dlq_processor.py --bootstrap-servers kafka:9092 --consumer-group dlq-processor --dlq-topic-pattern ".*\.dlq"
```

## Configuration Options

The DLQ processor can be configured using command-line arguments or environment variables:

| Argument | Environment Variable | Description | Default |
|----------|----------------------|-------------|---------|
| `--bootstrap-servers` | `KAFKA_BOOTSTRAP_SERVERS` | Kafka bootstrap servers | `localhost:9092` |
| `--consumer-group` | `KAFKA_CONSUMER_GROUP` | Consumer group ID | `dlq-processor` |
| `--dlq-topic-pattern` | `DLQ_TOPIC_PATTERN` | Regex pattern to identify DLQ topics | `.*\.dlq` |
| `--max-retries` | `MAX_RETRIES` | Maximum number of retry attempts | `5` |
| `--base-delay` | `BASE_DELAY` | Base delay for exponential backoff (seconds) | `1.0` |
| `--max-delay` | `MAX_DELAY` | Maximum delay between retries (seconds) | `60.0` |
| `--topic-refresh-interval` | `TOPIC_REFRESH_INTERVAL` | Interval to refresh DLQ topic list (seconds) | `300` |
| `--metrics-port` | `METRICS_PORT` | Port for the metrics HTTP server | `8001` |

## Metrics

The DLQ processor exposes the following metrics at `http://localhost:8001/metrics`:

- `dlq_messages_processed_total`: Total number of DLQ messages processed
- `dlq_messages_reprocessed_total`: Total number of messages successfully reprocessed
- `dlq_messages_failed_total`: Total number of messages that failed reprocessing after max retries
- `dlq_processing_duration_seconds`: Histogram of message processing times

## Logging

The DLQ processor logs information about its operation to stdout. The log level can be configured using the `LOG_LEVEL` environment variable.

## Health Check

A health endpoint is available at `http://localhost:8001/-/healthy` which returns a 200 status code if the service is running properly. 