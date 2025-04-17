import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.room_service import RoomService
from app.models.room import Room, RoomParticipant
from app.models.user import User
from app.schemas.room import RoomCreate, RoomUpdate

@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db

@pytest.fixture
def room_service(mock_db):
    return RoomService(mock_db)

@pytest.fixture
def uuids():
    return {
        "room_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "participant_id": uuid.uuid4()
    }

@pytest.mark.asyncio
async def test_create_room(room_service, mock_db, uuids):
    # Arrange
    owner_id = uuids["user_id"]
    room_data = RoomCreate(
        name="Test Room",
        description="This is a test room",
        is_private=False
    )
    
    # Mock user
    mock_user = User(
        id=owner_id,
        username="room_owner",
        email="owner@example.com"
    )
    
    # Configure mock responses
    mock_user_result = AsyncMock()
    mock_user_result.scalars().first.return_value = mock_user
    
    # Create expected room that will be returned
    expected_room = Room(
        id=uuid.uuid4(),
        name=room_data.name,
        description=room_data.description,
        owner_id=owner_id,
        is_private=room_data.is_private,
        created_at=MagicMock(),
        participants=[]
    )
    
    # Mock db.execute for the user query
    mock_db.execute.return_value = mock_user_result
    
    # Act
    room = await room_service.create_room(room_data, owner_id)
    
    # Assert
    assert room.name == room_data.name
    assert room.description == room_data.description
    assert room.owner_id == owner_id
    assert room.is_private == room_data.is_private
    
    # Verify db operations
    assert mock_db.add.call_count >= 2  # Room and RoomParticipant
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()

@pytest.mark.asyncio
async def test_get_room(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    
    # Create a mock room
    mock_room = Room(
        id=room_id,
        name="Test Room",
        description="This is a test room",
        owner_id=uuids["user_id"],
        is_private=False,
        created_at=datetime.utcnow(),
        participants=[]
    )
    
    # Configure mock response
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_room
    mock_db.execute.return_value = mock_result
    
    # Act
    room = await room_service.get_room(room_id)
    
    # Assert
    assert room == mock_room
    assert room.id == room_id
    
    # Verify query execution
    mock_db.execute.assert_called_once()

@pytest.mark.asyncio
async def test_get_rooms_for_user(room_service, mock_db, uuids):
    # Arrange
    user_id = uuids["user_id"]
    
    # Create mock rooms
    mock_rooms = [
        Room(
            id=uuid.uuid4(),
            name="Room 1",
            description="First test room",
            owner_id=user_id,
            is_private=False,
            created_at=datetime.utcnow()
        ),
        Room(
            id=uuid.uuid4(),
            name="Room 2",
            description="Second test room",
            owner_id=uuid.uuid4(),  # Different owner
            is_private=False,
            created_at=datetime.utcnow()
        )
    ]
    
    # Configure mock response for the query
    mock_result = AsyncMock()
    mock_result.scalars().all.return_value = mock_rooms
    mock_db.execute.return_value = mock_result
    
    # Act
    rooms = await room_service.get_rooms_for_user(user_id)
    
    # Assert
    assert len(rooms) == 2
    assert rooms[0].name == "Room 1"
    assert rooms[1].name == "Room 2"
    
    # Verify the query was executed
    mock_db.execute.assert_called_once()

@pytest.mark.asyncio
async def test_update_room(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    owner_id = uuids["user_id"]
    
    # Create update data
    room_update = RoomUpdate(
        name="Updated Room Name",
        description="Updated room description",
        is_private=True
    )
    
    # Create a mock room owned by the user
    mock_room = Room(
        id=room_id,
        name="Original Room Name",
        description="Original description",
        owner_id=owner_id,
        is_private=False,
        created_at=datetime.utcnow()
    )
    
    # Configure mock response
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_room
    mock_db.execute.return_value = mock_result
    
    # Act
    updated_room = await room_service.update_room(room_id, room_update, owner_id)
    
    # Assert
    assert updated_room == mock_room
    assert updated_room.name == room_update.name
    assert updated_room.description == room_update.description
    assert updated_room.is_private == room_update.is_private
    
    # Verify db operation
    mock_db.commit.assert_called_once()

@pytest.mark.asyncio
async def test_update_room_unauthorized(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    owner_id = uuids["user_id"]
    different_user_id = uuid.uuid4()  # Not the owner
    
    # Create update data
    room_update = RoomUpdate(
        name="Updated Room Name",
        description="Updated room description",
        is_private=True
    )
    
    # Create a mock room owned by a different user
    mock_room = Room(
        id=room_id,
        name="Original Room Name",
        description="Original description",
        owner_id=owner_id,  # This is not the requester
        is_private=False,
        created_at=datetime.utcnow()
    )
    
    # Configure mock response
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_room
    mock_db.execute.return_value = mock_result
    
    # Act
    updated_room = await room_service.update_room(room_id, room_update, different_user_id)
    
    # Assert
    assert updated_room is None
    
    # Verify db operation was not called
    mock_db.commit.assert_not_called()

@pytest.mark.asyncio
async def test_delete_room(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    owner_id = uuids["user_id"]
    
    # Create a mock room owned by the user
    mock_room = Room(
        id=room_id,
        name="Room to Delete",
        description="This room will be deleted",
        owner_id=owner_id,
        is_private=False,
        created_at=datetime.utcnow()
    )
    
    # Configure mock response
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_room
    mock_db.execute.return_value = mock_result
    
    # Act
    result = await room_service.delete_room(room_id, owner_id)
    
    # Assert
    assert result is True
    
    # Verify db operations
    mock_db.delete.assert_called_once_with(mock_room)
    mock_db.commit.assert_called_once()

@pytest.mark.asyncio
async def test_delete_room_unauthorized(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    owner_id = uuids["user_id"]
    different_user_id = uuid.uuid4()  # Not the owner
    
    # Create a mock room owned by a different user
    mock_room = Room(
        id=room_id,
        name="Room to Delete",
        description="This room will not be deleted due to unauthorized access",
        owner_id=owner_id,  # This is not the requester
        is_private=False,
        created_at=datetime.utcnow()
    )
    
    # Configure mock response
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_room
    mock_db.execute.return_value = mock_result
    
    # Act
    result = await room_service.delete_room(room_id, different_user_id)
    
    # Assert
    assert result is False
    
    # Verify db operations were not called
    mock_db.delete.assert_not_called()
    mock_db.commit.assert_not_called()

@pytest.mark.asyncio
async def test_join_room(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    user_id = uuids["user_id"]
    
    # Create a mock room
    mock_room = Room(
        id=room_id,
        name="Room to Join",
        description="This room will be joined",
        owner_id=uuid.uuid4(),  # Different user as owner
        is_private=False,
        created_at=datetime.utcnow()
    )
    
    # Mock db queries
    mock_room_result = AsyncMock()
    mock_room_result.scalars().first.return_value = mock_room
    
    # Mock participant check (user not yet in room)
    mock_participant_result = AsyncMock()
    mock_participant_result.scalars().first.return_value = None
    
    # Set up db.execute to return different results for each call
    mock_db.execute.side_effect = [mock_room_result, mock_participant_result]
    
    # Act
    result = await room_service.join_room(room_id, user_id)
    
    # Assert
    assert result is True
    
    # Verify operations
    assert mock_db.add.call_count == 1  # Adding RoomParticipant
    mock_db.commit.assert_called_once()

@pytest.mark.asyncio
async def test_join_room_already_joined(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    user_id = uuids["user_id"]
    
    # Create a mock room
    mock_room = Room(
        id=room_id,
        name="Room Already Joined",
        description="User already part of this room",
        owner_id=uuid.uuid4(),
        is_private=False,
        created_at=datetime.utcnow()
    )
    
    # Create a mock participant record (user already in room)
    mock_participant = RoomParticipant(
        id=uuids["participant_id"],
        room_id=room_id,
        user_id=user_id,
        is_moderator=False,
        joined_at=datetime.utcnow()
    )
    
    # Mock db queries
    mock_room_result = AsyncMock()
    mock_room_result.scalars().first.return_value = mock_room
    
    mock_participant_result = AsyncMock()
    mock_participant_result.scalars().first.return_value = mock_participant
    
    # Set up db.execute to return different results for each call
    mock_db.execute.side_effect = [mock_room_result, mock_participant_result]
    
    # Act
    result = await room_service.join_room(room_id, user_id)
    
    # Assert
    assert result is False
    
    # Verify operations were not performed
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()

@pytest.mark.asyncio
async def test_leave_room(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    user_id = uuids["user_id"]
    
    # Create a mock participant record
    mock_participant = RoomParticipant(
        id=uuids["participant_id"],
        room_id=room_id,
        user_id=user_id,
        is_moderator=False,
        joined_at=datetime.utcnow()
    )
    
    # Mock db queries
    mock_participant_result = AsyncMock()
    mock_participant_result.scalars().first.return_value = mock_participant
    
    # Set up db.execute response
    mock_db.execute.return_value = mock_participant_result
    
    # Act
    result = await room_service.leave_room(room_id, user_id)
    
    # Assert
    assert result is True
    
    # Verify operations
    mock_db.delete.assert_called_once_with(mock_participant)
    mock_db.commit.assert_called_once()

@pytest.mark.asyncio
async def test_leave_room_not_joined(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    user_id = uuids["user_id"]
    
    # Mock db queries (participant not found)
    mock_participant_result = AsyncMock()
    mock_participant_result.scalars().first.return_value = None
    
    # Set up db.execute response
    mock_db.execute.return_value = mock_participant_result
    
    # Act
    result = await room_service.leave_room(room_id, user_id)
    
    # Assert
    assert result is False
    
    # Verify operations were not performed
    mock_db.delete.assert_not_called()
    mock_db.commit.assert_not_called()

@pytest.mark.asyncio
async def test_get_room_participants(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    
    # Create mock participants
    mock_participants = [
        User(
            id=uuids["user_id"],
            username="user1",
            email="user1@example.com"
        ),
        User(
            id=uuid.uuid4(),
            username="user2",
            email="user2@example.com"
        )
    ]
    
    # Configure mock response
    mock_result = AsyncMock()
    mock_result.scalars().all.return_value = mock_participants
    mock_db.execute.return_value = mock_result
    
    # Act
    participants = await room_service.get_room_participants(room_id)
    
    # Assert
    assert len(participants) == 2
    assert participants[0].username == "user1"
    assert participants[1].username == "user2"
    
    # Verify query execution
    mock_db.execute.assert_called_once()

@pytest.mark.asyncio
async def test_check_user_in_room(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    user_id = uuids["user_id"]
    
    # Create a mock participant record
    mock_participant = RoomParticipant(
        id=uuids["participant_id"],
        room_id=room_id,
        user_id=user_id,
        is_moderator=False,
        joined_at=datetime.utcnow()
    )
    
    # Mock db query
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_participant
    mock_db.execute.return_value = mock_result
    
    # Act
    is_in_room = await room_service.check_user_in_room(room_id, user_id)
    
    # Assert
    assert is_in_room is True
    
    # Verify query execution
    mock_db.execute.assert_called_once()

@pytest.mark.asyncio
async def test_check_user_not_in_room(room_service, mock_db, uuids):
    # Arrange
    room_id = uuids["room_id"]
    user_id = uuids["user_id"]
    
    # Mock db query (participant not found)
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = None
    mock_db.execute.return_value = mock_result
    
    # Act
    is_in_room = await room_service.check_user_in_room(room_id, user_id)
    
    # Assert
    assert is_in_room is False
    
    # Verify query execution
    mock_db.execute.assert_called_once() 