import pytest
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.token_service import TokenService
from app.models.token import TokenBalance, TokenTransaction
from app.models.user import User

@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    return db

@pytest.fixture
def user_id():
    return uuid.uuid4()

@pytest.fixture
def token_service(mock_db):
    return TokenService(mock_db)

@pytest.mark.asyncio
async def test_get_user_balance_existing(token_service, mock_db, user_id):
    # Arrange
    mock_token_balance = TokenBalance(user_id=user_id, amount=Decimal("100.00"))
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = mock_token_balance
    mock_db.execute.return_value = mock_result
    
    # Act
    result = await token_service.get_user_balance(user_id)
    
    # Assert
    assert result is mock_token_balance
    mock_db.execute.assert_called_once()

@pytest.mark.asyncio
async def test_get_user_balance_not_existing(token_service, mock_db, user_id):
    # Arrange
    mock_result = AsyncMock()
    mock_result.scalars().first.return_value = None
    mock_db.execute.return_value = mock_result
    
    # Act
    result = await token_service.get_user_balance(user_id)
    
    # Assert
    assert result is None
    mock_db.execute.assert_called_once()

@pytest.mark.asyncio
async def test_add_tokens(token_service, mock_db, user_id):
    # Arrange
    amount = Decimal("50.00")
    transaction_type = "deposit"
    description = "Test deposit"
    
    # Mock get_user_balance to return a balance
    mock_balance = TokenBalance(user_id=user_id, amount=Decimal("100.00"))
    token_service.get_user_balance = AsyncMock(return_value=mock_balance)
    
    # Mock transaction creation
    mock_transaction = TokenTransaction(
        id=uuid.uuid4(),
        user_id=user_id,
        amount=amount,
        type=transaction_type,
        description=description
    )
    
    mock_db.refresh = AsyncMock()
    
    # Act
    with patch('uuid.uuid4', return_value=mock_transaction.id):
        result = await token_service.add_tokens(
            user_id, amount, transaction_type, description
        )
    
    # Assert
    assert result.user_id == user_id
    assert result.amount == amount
    assert result.type == transaction_type
    assert result.description == description
    assert mock_balance.amount == Decimal("150.00")  # 100 + 50
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()

@pytest.mark.asyncio
async def test_remove_tokens_sufficient_balance(token_service, mock_db, user_id):
    # Arrange
    current_balance = Decimal("100.00")
    amount = Decimal("50.00")
    transaction_type = "withdrawal"
    description = "Test withdrawal"
    
    # Mock get_user_balance to return a balance
    mock_balance = TokenBalance(user_id=user_id, amount=current_balance)
    token_service.get_user_balance = AsyncMock(return_value=mock_balance)
    
    # Mock transaction creation
    mock_transaction = TokenTransaction(
        id=uuid.uuid4(),
        user_id=user_id,
        amount=amount,
        type=transaction_type,
        description=description
    )
    
    mock_db.refresh = AsyncMock()
    
    # Act
    with patch('uuid.uuid4', return_value=mock_transaction.id):
        result = await token_service.remove_tokens(
            user_id, amount, transaction_type, description
        )
    
    # Assert
    assert result.user_id == user_id
    assert result.amount == amount
    assert result.type == transaction_type
    assert result.description == description
    assert mock_balance.amount == Decimal("50.00")  # 100 - 50
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()

@pytest.mark.asyncio
async def test_remove_tokens_insufficient_balance(token_service, mock_db, user_id):
    # Arrange
    current_balance = Decimal("30.00")
    amount = Decimal("50.00")
    transaction_type = "withdrawal"
    description = "Test withdrawal"
    
    # Mock get_user_balance to return a balance
    mock_balance = TokenBalance(user_id=user_id, amount=current_balance)
    token_service.get_user_balance = AsyncMock(return_value=mock_balance)
    
    # Act & Assert
    with pytest.raises(ValueError, match="Insufficient balance"):
        await token_service.remove_tokens(
            user_id, amount, transaction_type, description
        )
    
    # Ensure no DB commit was performed
    mock_db.commit.assert_not_called()

@pytest.mark.asyncio
async def test_transfer_tokens(token_service, mock_db):
    # Arrange
    from_user_id = uuid.uuid4()
    to_user_id = uuid.uuid4()
    amount = Decimal("25.00")
    transaction_type = "transfer"
    description = "Test transfer"
    
    # Mock successful removal and addition
    token_service.remove_tokens = AsyncMock(return_value=TokenTransaction(
        id=uuid.uuid4(),
        user_id=from_user_id,
        amount=amount,
        type=transaction_type,
        description=description
    ))
    
    token_service.add_tokens = AsyncMock(return_value=TokenTransaction(
        id=uuid.uuid4(),
        user_id=to_user_id,
        amount=amount,
        type=transaction_type,
        description=description
    ))
    
    # Act
    from_tx, to_tx = await token_service.transfer_tokens(
        from_user_id, to_user_id, amount, transaction_type, description
    )
    
    # Assert
    assert from_tx.user_id == from_user_id
    assert to_tx.user_id == to_user_id
    assert from_tx.amount == amount
    assert to_tx.amount == amount
    token_service.remove_tokens.assert_called_once_with(
        from_user_id, amount, transaction_type, description, None
    )
    token_service.add_tokens.assert_called_once_with(
        to_user_id, amount, transaction_type, description, None
    )

@pytest.mark.asyncio
async def test_grant_initial_tokens(token_service, mock_db, user_id):
    # Arrange
    initial_amount = Decimal("100.0")
    
    # Mock add_tokens
    expected_tx = TokenTransaction(
        id=uuid.uuid4(),
        user_id=user_id,
        amount=initial_amount,
        type="initial_grant",
        description="Initial token grant for new user"
    )
    token_service.add_tokens = AsyncMock(return_value=expected_tx)
    
    # Act
    result = await token_service.grant_initial_tokens(user_id, initial_amount)
    
    # Assert
    assert result is expected_tx
    token_service.add_tokens.assert_called_once_with(
        user_id, initial_amount, "initial_grant", "Initial token grant for new user", None
    ) 