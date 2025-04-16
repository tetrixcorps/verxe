# MCP-Server

This repository contains the backend server for the MCP (Messaging and Communication Platform) application.

## Features

- RESTful API for user authentication and authorization
- Real-time messaging with WebSocket support
- Room-based chat system with moderation capabilities
- User management and profile functionality

## Prerequisites

- Python 3.9+
- PostgreSQL
- Redis (for WebSocket message queuing)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/MCP-Server.git
cd MCP-Server
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install the dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file based on the example:
```bash
cp .env.example .env
```
Then edit the `.env` file with your configuration values.

5. Set up the database:
```bash
# Create the database in PostgreSQL
# Then run migrations (command depends on the migration tool used)
```

## Running the Server

For development:
```bash
uvicorn app.main:app --reload
```

For production:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API Documentation

Once the server is running, you can access the API documentation at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Project Structure

```
MCP-Server/
├── app/
│   ├── api/                 # API endpoints
│   ├── core/                # Core functionality, config
│   ├── db/                  # Database models and setup
│   ├── schemas/             # Pydantic schemas
│   ├── services/            # Business logic
│   ├── utils/               # Utility functions
│   └── main.py              # Application entry point
├── tests/                   # Test suite
├── .env                     # Environment variables
├── .env.example             # Example environment file
├── requirements.txt         # Project dependencies
└── README.md                # This file
```

## Testing

Run the test suite:
```bash
pytest
```

## License

[MIT License](LICENSE) 