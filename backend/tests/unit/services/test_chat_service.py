import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime

from app.services.chat_service import ChatService
from app.models.chat import ChatMessage
from app.models.room import Room, RoomParticipant
from app.models.user import User

@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db

@pytest.fixture
def chat_service(mock_db):
    return ChatService(mock_db)

@pytest.fixture
def uuids():
    return {
        "message_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "moderator_id": uuid.uuid4(),
        "owner_id": uuid.uuid4(),
        "room_id": uuid.uuid4()
    }

@pytest.mark.asyncio
async def test_delete_message_as_sender(chat_service, mock_db, uuids):
    # Arrange
    message_id = uuids["message_id"]
    user_id = uuids["user_id"]
    
    # Create a mock message with the user as sender
    mock_message = ChatMessage(
        id=message_id,
        sender_id=user_id,
        room_id=uuids["room_id"],
        content="Test message",
        is_deleted=False
    )
    
    # Setup mock db response
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_message
    mock_db.execute.return_value = mock_result
    
    # Act
    result = await chat_service.delete_message(message_id, user_id)
    
    # Assert
    assert result is True
    assert mock_message.is_deleted is True
    mock_db.commit.assert_called_once()

@pytest.mark.asyncio
async def test_delete_message_as_moderator(chat_service, mock_db, uuids):
    # Arrange
    message_id = uuids["message_id"]
    moderator_id = uuids["moderator_id"]
    sender_id = uuid.uuid4()  # Different from moderator
    room_id = uuids["room_id"]
    
    # Create a mock message with a different sender
    mock_message = ChatMessage(
        id=message_id,
        sender_id=sender_id,
        room_id=room_id,
        content="Test message",
        is_deleted=False
    )
    
    # Create a mock room participant with moderator role
    mock_participant = RoomParticipant(
        user_id=moderator_id,
        room_id=room_id,
        is_moderator=True
    )
    
    # Setup mock db responses
    mock_message_result = AsyncMock()
    mock_message_result.scalars().first.return_value = mock_message
    
    mock_participant_result = AsyncMock()
    mock_participant_result.scalars().first.return_value = mock_participant
    
    # Configure the db.execute to return different results based on query
    async def mock_execute(query, *args, **kwargs):
        # This is a simplified approach - in a real test we'd need to be more precise
        if "chat_messages" in str(query):
            return mock_message_result
        elif "room_participants" in str(query):
            return mock_participant_result
        return AsyncMock()
    
    mock_db.execute.side_effect = mock_execute
    
    # Act
    result = await chat_service.delete_message(message_id, moderator_id)
    
    # Assert
    assert result is True
    assert mock_message.is_deleted is True
    mock_db.commit.assert_called_once()

@pytest.mark.asyncio
async def test_delete_message_unauthorized(chat_service, mock_db, uuids):
    # Arrange
    message_id = uuids["message_id"]
    sender_id = uuid.uuid4()
    user_id = uuids["user_id"]  # Different from sender
    room_id = uuids["room_id"]
    
    # Create a mock message with a different sender
    mock_message = ChatMessage(
        id=message_id,
        sender_id=sender_id,
        room_id=room_id,
        content="Test message",
        is_deleted=False
    )
    
    # Create a mock room participant without moderator role
    mock_participant = RoomParticipant(
        user_id=user_id,
        room_id=room_id,
        is_moderator=False
    )
    
    # Setup mock db responses
    mock_message_result = AsyncMock()
    mock_message_result.scalars().first.return_value = mock_message
    
    mock_participant_result = AsyncMock()
    mock_participant_result.scalars().first.return_value = mock_participant
    
    # Configure the db.execute to return different results based on query
    async def mock_execute(query, *args, **kwargs):
        if "chat_messages" in str(query):
            return mock_message_result
        elif "room_participants" in str(query):
            return mock_participant_result
        return AsyncMock()
    
    mock_db.execute.side_effect = mock_execute
    
    # Act
    result = await chat_service.delete_message(message_id, user_id)
    
    # Assert
    assert result is False
    assert mock_message.is_deleted is False
    mock_db.commit.assert_not_called()

@pytest.mark.asyncio
async def test_mute_user_as_moderator(chat_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    target_user_id = uuids["user_id"]
    moderator_id = uuids["moderator_id"]
    
    # Mock the room participants
    mock_target = RoomParticipant(
        user_id=target_user_id,
        room_id=room_id,
        is_moderator=False,
        is_muted=False
    )
    
    mock_moderator = RoomParticipant(
        user_id=moderator_id,
        room_id=room_id,
        is_moderator=True
    )
    
    # Setup mock db responses
    mock_target_result = AsyncMock()
    mock_target_result.scalars().first.return_value = mock_target
    
    mock_moderator_result = AsyncMock()
    mock_moderator_result.scalars().first.return_value = mock_moderator
    
    # Mock execution for different queries
    call_count = 0
    async def mock_execute(query, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # First call - get target
            return mock_target_result
        elif call_count == 2:  # Second call - get moderator
            return mock_moderator_result
        return AsyncMock()
    
    mock_db.execute.side_effect = mock_execute
    
    # Act
    result = await chat_service.mute_user(room_id, target_user_id, moderator_id)
    
    # Assert
    assert result is True
    assert mock_target.is_muted is True
    mock_db.commit.assert_called_once()

@pytest.mark.asyncio
async def test_mute_user_unauthorized(chat_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    target_user_id = uuids["user_id"]
    non_moderator_id = uuid.uuid4()
    
    # Mock the room participants
    mock_target = RoomParticipant(
        user_id=target_user_id,
        room_id=room_id,
        is_moderator=False,
        is_muted=False
    )
    
    mock_non_moderator = RoomParticipant(
        user_id=non_moderator_id,
        room_id=room_id,
        is_moderator=False
    )
    
    # Setup mock db responses
    mock_target_result = AsyncMock()
    mock_target_result.scalars().first.return_value = mock_target
    
    mock_non_moderator_result = AsyncMock()
    mock_non_moderator_result.scalars().first.return_value = mock_non_moderator
    
    # Mock execution for different queries
    call_count = 0
    async def mock_execute(query, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # First call - get target
            return mock_target_result
        elif call_count == 2:  # Second call - get moderator
            return mock_non_moderator_result
        return AsyncMock()
    
    mock_db.execute.side_effect = mock_execute
    
    # Act
    result = await chat_service.mute_user(room_id, target_user_id, non_moderator_id)
    
    # Assert
    assert result is False
    assert mock_target.is_muted is False
    mock_db.commit.assert_not_called()

@pytest.mark.asyncio
async def test_promote_to_moderator_as_owner(chat_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    target_user_id = uuids["user_id"]
    owner_id = uuids["owner_id"]
    
    # Mock the room and participant
    mock_room = Room(
        id=room_id,
        owner_id=owner_id,
        name="Test Room"
    )
    
    mock_target = RoomParticipant(
        user_id=target_user_id,
        room_id=room_id,
        is_moderator=False
    )
    
    # Setup mock db responses
    mock_room_result = AsyncMock()
    mock_room_result.scalars().first.return_value = mock_room
    
    mock_target_result = AsyncMock()
    mock_target_result.scalars().first.return_value = mock_target
    
    # Mock execution for different queries
    call_count = 0
    async def mock_execute(query, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # First call - get room
            return mock_room_result
        elif call_count == 2:  # Second call - get target participant
            return mock_target_result
        return AsyncMock()
    
    mock_db.execute.side_effect = mock_execute
    
    # Act
    result = await chat_service.promote_to_moderator(room_id, target_user_id, owner_id)
    
    # Assert
    assert result is True
    assert mock_target.is_moderator is True
    mock_db.commit.assert_called_once()

@pytest.mark.asyncio
async def test_promote_to_moderator_unauthorized(chat_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    target_user_id = uuids["user_id"]
    owner_id = uuids["owner_id"]
    non_owner_id = uuid.uuid4()  # Different from owner
    
    # Mock the room and participant
    mock_room = Room(
        id=room_id,
        owner_id=owner_id,  # Real owner, not the requester
        name="Test Room"
    )
    
    mock_target = RoomParticipant(
        user_id=target_user_id,
        room_id=room_id,
        is_moderator=False
    )
    
    # Setup mock db responses
    mock_room_result = AsyncMock()
    mock_room_result.scalars().first.return_value = mock_room
    
    # Mock execution for different queries
    mock_db.execute.return_value = mock_room_result
    
    # Act
    result = await chat_service.promote_to_moderator(room_id, target_user_id, non_owner_id)
    
    # Assert
    assert result is False
    assert mock_target.is_moderator is False
    mock_db.commit.assert_not_called()

@pytest.mark.asyncio
async def test_connect_websocket(chat_service):
    # Arrange
    websocket = MagicMock(spec=WebSocket)
    room_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    # Mock the active_connections dictionary
    chat_service.active_connections = {}
    
    # Act
    await chat_service.connect_websocket(websocket, room_id, user_id)
    
    # Assert
    assert str(room_id) in chat_service.active_connections
    assert str(user_id) in chat_service.active_connections[str(room_id)]
    assert chat_service.active_connections[str(room_id)][str(user_id)] == websocket
    websocket.accept.assert_called_once()

@pytest.mark.asyncio
async def test_disconnect_websocket(chat_service):
    # Arrange
    websocket = MagicMock(spec=WebSocket)
    room_id = uuid.uuid4()
    user_id = uuid.uuid4()
    
    # Setup active connections
    chat_service.active_connections = {
        str(room_id): {
            str(user_id): websocket
        }
    }
    
    # Act
    await chat_service.disconnect_websocket(room_id, user_id)
    
    # Assert
    assert str(room_id) in chat_service.active_connections
    assert str(user_id) not in chat_service.active_connections[str(room_id)]

@pytest.mark.asyncio
async def test_broadcast_message(chat_service):
    # Arrange
    room_id = uuid.uuid4()
    
    # Create multiple mock websockets
    websocket1 = MagicMock(spec=WebSocket)
    websocket2 = MagicMock(spec=WebSocket)
    websocket3 = MagicMock(spec=WebSocket)
    
    # Setup connections for different users
    chat_service.active_connections = {
        str(room_id): {
            "user1": websocket1,
            "user2": websocket2,
            "user3": websocket3
        }
    }
    
    # Prepare a test message
    test_message = {"id": "msg1", "content": "Hello, world!"}
    
    # Mock send_json to simulate a disconnected client for user2
    websocket1.send_json = AsyncMock()
    websocket2.send_json = AsyncMock(side_effect=WebSocketDisconnect())
    websocket3.send_json = AsyncMock()
    
    # Act
    await chat_service.broadcast_message(room_id, test_message)
    
    # Assert
    websocket1.send_json.assert_called_once_with(test_message)
    websocket2.send_json.assert_called_once_with(test_message)
    websocket3.send_json.assert_called_once_with(test_message)
    
    # Check that the disconnected user was removed
    assert "user2" not in chat_service.active_connections[str(room_id)]
    
@pytest.mark.asyncio
async def test_process_message(chat_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    user_id = uuids["user_id"]
    content = "Hello, world!"
    
    # Mock user
    mock_user = User(
        id=user_id,
        username="testuser",
        email="test@example.com"
    )
    
    # Mock the saved message
    mock_message = ChatMessage(
        id=uuid.uuid4(),
        room_id=room_id,
        sender_id=user_id,
        content=content,
        created_at="2023-01-01T00:00:00Z"
    )
    
    # Setup mock responses
    mock_user_result = AsyncMock()
    mock_user_result.scalars().first.return_value = mock_user
    
    # Configure the db.execute for different queries
    call_count = 0
    async def mock_execute(query, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # Check if the user is muted
            return AsyncMock(scalars=AsyncMock(first=AsyncMock(return_value=RoomParticipant(is_muted=False))))
        elif call_count == 2:  # Get the user
            return mock_user_result
        return AsyncMock()
    
    mock_db.execute.side_effect = mock_execute
    
    # Mock the save_message method with our own return
    chat_service.save_message = AsyncMock(return_value=mock_message)
    
    # Act
    message = await chat_service.process_message(room_id, user_id, content)
    
    # Assert
    assert message["id"] == str(mock_message.id)
    assert message["content"] == content
    assert message["senderId"] == str(user_id)
    assert message["senderUsername"] == "testuser"
    chat_service.save_message.assert_called_once_with(room_id, user_id, content) 