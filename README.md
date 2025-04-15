# Verxe Chat Application

Verxe is a real-time chat application with user authentication, chat rooms, and private messaging functionality.

## Project Structure

The project is divided into two main parts:

### Backend

- Built with FastAPI and SQLAlchemy
- PostgreSQL database for persistent storage
- WebSockets for real-time chat functionality
- JWT-based authentication

### Frontend

- React with TypeScript
- Tailwind CSS for styling
- Context API for state management
- WebSocket connection for real-time updates

## Setting Up Development Environment

### Prerequisites

- Python 3.8+
- Node.js 14+
- PostgreSQL

### Backend Setup

1. Navigate to the backend directory:
   ```
   cd backend
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   Create a `.env` file in the backend directory with:
   ```
   DATABASE_URL=postgresql://user:password@localhost/verxe_db
   SECRET_KEY=your_secret_key
   ```

5. Initialize the database:
   ```
   alembic upgrade head
   ```

6. Run the development server:
   ```
   uvicorn app.main:app --reload
   ```

### Frontend Setup

1. Navigate to the frontend directory:
   ```
   cd frontend
   ```

2. Install dependencies:
   ```
   npm install
   ```

3. Set up environment variables:
   Create a `.env` file in the frontend directory with:
   ```
   REACT_APP_API_URL=http://localhost:8000
   ```

4. Start the development server:
   ```
   npm start
   ```

## Features

- User registration and authentication
- Public and private chat rooms
- Real-time messaging
- User profile management
- Message history

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register a new user
- `POST /api/auth/login` - Login and get access token

### Users
- `GET /api/users/me` - Get current user details
- `PATCH /api/users/me` - Update user profile
- `DELETE /api/users/me` - Delete user account

### Rooms
- `GET /api/rooms` - List available rooms
- `POST /api/rooms` - Create a new room
- `GET /api/rooms/{room_id}` - Get room details
- `GET /api/rooms/{room_id}/messages` - Get room message history

### WebSockets
- `/ws/chat/{room_id}` - WebSocket endpoint for chat messages

## License

MIT 