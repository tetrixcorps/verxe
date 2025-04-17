import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.stream_service import StreamService
from app.models.stream import Stream
from app.models.user import User
from app.kafka.producer import KafkaProducer

@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db

@pytest.fixture
def mock_kafka():
    kafka = AsyncMock(spec=KafkaProducer)
    return kafka

@pytest.fixture
def stream_service(mock_db, mock_kafka):
    return StreamService(mock_db, mock_kafka)

@pytest.fixture
def uuids():
    return {
        "stream_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "room_id": uuid.uuid4()
    }

@pytest.mark.asyncio
async def test_create_stream(stream_service, mock_db, mock_kafka, uuids):
    # Arrange
    user_id = uuids["user_id"]
    title = "Test Stream"
    description = "This is a test stream"
    is_private = False
    
    # Mock user
    mock_user = User(
        id=user_id,
        username="streamer",
        email="streamer@example.com"
    )
    
    # Setup expected stream to be created
    expected_stream = Stream(
        id=uuid.uuid4(),  # We'll use a different ID since we can't predict what UUID will be generated
        title=title,
        description=description,
        user_id=user_id,
        is_private=is_private,
        is_active=True,
        started_at=MagicMock(),  # The exact datetime will be hard to match
        viewer_count=0
    )
    
    # Configure mock responses
    mock_user_result = AsyncMock()
    mock_user_result.scalars().first.return_value = mock_user
    
    # Mock db.execute for the user query
    mock_db.execute.return_value = mock_user_result
    
    # Act
    stream = await stream_service.create_stream(user_id, title, description, is_private)
    
    # Assert
    assert stream.title == title
    assert stream.description == description
    assert stream.user_id == user_id
    assert stream.is_private == is_private
    assert stream.is_active is True
    assert stream.viewer_count == 0
    
    # Verify db operations
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()
    
    # Verify Kafka message was sent
    mock_kafka.send_message.assert_called_once()
    # Check the details of the Kafka message
    call_args = mock_kafka.send_message.call_args[0]
    assert call_args[0] == "stream_started"  # topic
    message = call_args[1]  # message payload
    assert message["stream_id"] == str(stream.id)
    assert message["user_id"] == str(user_id)
    assert message["username"] == "streamer"
    assert message["title"] == title
    assert message["is_private"] == is_private

@pytest.mark.asyncio
async def test_end_stream(stream_service, mock_db, mock_kafka, uuids):
    # Arrange
    stream_id = uuids["stream_id"]
    user_id = uuids["user_id"]
    
    # Create a mock active stream
    mock_stream = Stream(
        id=stream_id,
        title="Test Stream",
        description="This is a test stream",
        user_id=user_id,
        is_private=False,
        is_active=True,
        started_at=datetime.utcnow(),
        viewer_count=10
    )
    
    # Configure mock responses
    mock_stream_result = AsyncMock()
    mock_stream_result.scalars().first.return_value = mock_stream
    
    # Mock db.execute for the stream query
    mock_db.execute.return_value = mock_stream_result
    
    # Act
    result = await stream_service.end_stream(stream_id, user_id)
    
    # Assert
    assert result is True
    assert mock_stream.is_active is False
    assert mock_stream.ended_at is not None
    
    # Verify db operation
    mock_db.commit.assert_called_once()
    
    # Verify Kafka message was sent
    mock_kafka.send_message.assert_called_once()
    # Check the details of the Kafka message
    call_args = mock_kafka.send_message.call_args[0]
    assert call_args[0] == "stream_ended"  # topic
    message = call_args[1]  # message payload
    assert message["stream_id"] == str(stream_id)
    assert message["user_id"] == str(user_id)
    assert "duration_seconds" in message

@pytest.mark.asyncio
async def test_end_stream_unauthorized(stream_service, mock_db, mock_kafka, uuids):
    # Arrange
    stream_id = uuids["stream_id"]
    stream_owner_id = uuids["user_id"]
    different_user_id = uuid.uuid4()  # Different from the stream owner
    
    # Create a mock active stream
    mock_stream = Stream(
        id=stream_id,
        title="Test Stream",
        description="This is a test stream",
        user_id=stream_owner_id,  # Owner is different from the requester
        is_private=False,
        is_active=True,
        started_at=datetime.utcnow(),
        viewer_count=10
    )
    
    # Configure mock responses
    mock_stream_result = AsyncMock()
    mock_stream_result.scalars().first.return_value = mock_stream
    
    # Mock db.execute for the stream query
    mock_db.execute.return_value = mock_stream_result
    
    # Act
    result = await stream_service.end_stream(stream_id, different_user_id)
    
    # Assert
    assert result is False
    assert mock_stream.is_active is True  # Stream should still be active
    assert not hasattr(mock_stream, 'ended_at') or mock_stream.ended_at is None
    
    # Verify db and Kafka were not used
    mock_db.commit.assert_not_called()
    mock_kafka.send_message.assert_not_called()

@pytest.mark.asyncio
async def test_get_active_streams(stream_service, mock_db):
    # Arrange
    mock_streams = [
        Stream(
            id=uuid.uuid4(),
            title="Stream 1",
            user_id=uuid.uuid4(),
            is_active=True,
            is_private=False,
            viewer_count=15
        ),
        Stream(
            id=uuid.uuid4(),
            title="Stream 2",
            user_id=uuid.uuid4(),
            is_active=True,
            is_private=False,
            viewer_count=20
        )
    ]
    
    # Configure mock response for the query
    mock_result = AsyncMock()
    mock_result.scalars().all.return_value = mock_streams
    mock_db.execute.return_value = mock_result
    
    # Act
    streams = await stream_service.get_active_streams()
    
    # Assert
    assert len(streams) == 2
    assert streams[0].title == "Stream 1"
    assert streams[1].title == "Stream 2"
    assert all(stream.is_active for stream in streams)
    
    # Verify the query was executed
    mock_db.execute.assert_called_once()

@pytest.mark.asyncio
async def test_get_stream(stream_service, mock_db, uuids):
    # Arrange
    stream_id = uuids["stream_id"]
    
    # Create a mock stream
    mock_stream = Stream(
        id=stream_id,
        title="Test Stream",
        description="This is a test stream",
        user_id=uuids["user_id"],
        is_private=False,
        is_active=True,
        started_at=datetime.utcnow(),
        viewer_count=10
    )
    
    # Configure mock response
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_stream
    mock_db.execute.return_value = mock_result
    
    # Act
    stream = await stream_service.get_stream(stream_id)
    
    # Assert
    assert stream == mock_stream
    assert stream.id == stream_id
    
    # Verify query execution
    mock_db.execute.assert_called_once()

@pytest.mark.asyncio
async def test_join_stream(stream_service, mock_db, mock_kafka, uuids):
    # Arrange
    stream_id = uuids["stream_id"]
    user_id = uuids["user_id"]
    
    # Create a mock stream
    mock_stream = Stream(
        id=stream_id,
        title="Test Stream",
        description="This is a test stream",
        user_id=uuid.uuid4(),  # A different user is the stream owner
        is_private=False,
        is_active=True,
        started_at=datetime.utcnow(),
        viewer_count=10
    )
    
    # Configure mock response
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_stream
    mock_db.execute.return_value = mock_result
    
    # Act
    result = await stream_service.join_stream(stream_id, user_id)
    
    # Assert
    assert result is True
    assert mock_stream.viewer_count == 11  # Viewer count should be incremented
    
    # Verify db operation
    mock_db.commit.assert_called_once()
    
    # Verify Kafka message
    mock_kafka.send_message.assert_called_once()
    call_args = mock_kafka.send_message.call_args[0]
    assert call_args[0] == "stream_joined"  # topic
    message = call_args[1]  # message payload
    assert message["stream_id"] == str(stream_id)
    assert message["user_id"] == str(user_id)
    assert message["viewer_count"] == 11

@pytest.mark.asyncio
async def test_leave_stream(stream_service, mock_db, mock_kafka, uuids):
    # Arrange
    stream_id = uuids["stream_id"]
    user_id = uuids["user_id"]
    
    # Create a mock stream
    mock_stream = Stream(
        id=stream_id,
        title="Test Stream",
        description="This is a test stream",
        user_id=uuid.uuid4(),  # A different user is the stream owner
        is_private=False,
        is_active=True,
        started_at=datetime.utcnow(),
        viewer_count=10
    )
    
    # Configure mock response
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_stream
    mock_db.execute.return_value = mock_result
    
    # Act
    result = await stream_service.leave_stream(stream_id, user_id)
    
    # Assert
    assert result is True
    assert mock_stream.viewer_count == 9  # Viewer count should be decremented
    
    # Verify db operation
    mock_db.commit.assert_called_once()
    
    # Verify Kafka message
    mock_kafka.send_message.assert_called_once()
    call_args = mock_kafka.send_message.call_args[0]
    assert call_args[0] == "stream_left"  # topic
    message = call_args[1]  # message payload
    assert message["stream_id"] == str(stream_id)
    assert message["user_id"] == str(user_id)
    assert message["viewer_count"] == 9

@pytest.mark.asyncio
async def test_get_stream_by_user(stream_service, mock_db, uuids):
    # Arrange
    user_id = uuids["user_id"]
    
    # Create a mock active stream
    mock_stream = Stream(
        id=uuid.uuid4(),
        title="User's Stream",
        description="This is a user's active stream",
        user_id=user_id,
        is_private=False,
        is_active=True,
        started_at=datetime.utcnow(),
        viewer_count=5
    )
    
    # Configure mock response
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_stream
    mock_db.execute.return_value = mock_result
    
    # Act
    stream = await stream_service.get_stream_by_user(user_id)
    
    # Assert
    assert stream == mock_stream
    assert stream.user_id == user_id
    assert stream.is_active is True
    
    # Verify query execution
    mock_db.execute.assert_called_once() 