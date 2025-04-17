# Verxe - Chat, Streaming, and Community Platform

Verxe is a modern real-time chat, streaming, and community platform that enables users to create and join chat rooms, stream content, and build communities.

## Features

- **Real-time Chat**: Create and join chat rooms with WebSocket-based messaging
- **Live Streaming**: Stream content with WebRTC and RTMP support
- **User Management**: User authentication, follows, and profile management
- **Token Economy**: In-platform token for tips and purchases
- **Moderation Tools**: Built-in moderation features for room management

## Architecture

Verxe is built using a microservices architecture with the following components:

- **Frontend**: React.js with TypeScript and TailwindCSS
- **Backend API**: FastAPI with SQLAlchemy and async database access
- **Media Processing**: GStreamer-based media processing for streams
- **Real-time Communication**: Kafka for event streaming and WebSockets for direct messaging
- **Schema Registry**: Avro schema management for event consistency
- **LLM and Speech Services**: AI-powered features for content analysis and generation

## Requirements

- Docker and Docker Compose
- Node.js 16+ (for local frontend development)
- Python 3.9+ (for local backend development)
- PostgreSQL 14+ (when running without Docker)
- Redis 6+ (when running without Docker)
- Kafka (when running without Docker)

## Setup and Installation

### Using Docker (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/verxe.git
   cd verxe
   ```

2. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

3. Start the application using Docker Compose:
   ```bash
   docker-compose up -d
   ```

4. Access the application:
   - Frontend: http://localhost:80
   - Backend API: http://localhost:8000
   - API Documentation: http://localhost:8000/docs

### Local Development

#### Backend

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the FastAPI server:
   ```bash
   uvicorn app.main:app --reload
   ```

#### Frontend

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm run start
   ```

## Project Structure

```
verxe/
├── backend/               # FastAPI backend
│   ├── app/               # Application code
│   │   ├── api/           # API endpoints
│   │   ├── core/          # Core functionality
│   │   ├── kafka/         # Kafka event handling
│   │   ├── models/        # Database models
│   │   ├── schemas/       # Pydantic schemas
│   │   └── services/      # Business logic
│   ├── migrations/        # Alembic migrations
│   └── tests/             # Unit and integration tests
├── frontend/              # React frontend
│   ├── public/            # Static assets
│   └── src/               # Application code
│       ├── components/    # React components
│       ├── contexts/      # Context providers
│       ├── pages/         # Page components
│       └── services/      # API service clients
├── media_processor_service/ # GStreamer-based media processing
├── schemas/               # Avro schemas
└── docker-compose.yml     # Docker Compose configuration
```

## Running Tests

### Backend Tests

```bash
cd backend
pytest
```

### Frontend Tests

```bash
cd frontend
npm test
```

## Deployment

See the [Deployment Guide](docs/deployment.md) for detailed instructions on deploying Verxe to production environments.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

