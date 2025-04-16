from typing import Optional
from uuid import UUID
from decimal import Decimal
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.token import TokenBalance, TokenTransaction
from ..models.user import User
from ..schemas.token import TokenTransactionCreate

class TokenService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_user_balance(self, user_id: UUID) -> Optional[TokenBalance]:
        """Get a user's token balance"""
        query = select(TokenBalance).where(TokenBalance.user_id == user_id)
        result = await self.db.execute(query)
        balance = result.scalars().first()
        
        # Create balance if it doesn't exist
        if not balance:
            balance = TokenBalance(user_id=user_id, amount=0)
            self.db.add(balance)
            await self.db.commit()
            await self.db.refresh(balance)
        
        return balance
    
    async def add_tokens(self, user_id: UUID, amount: Decimal, type: str, description: Optional[str] = None, reference_id: Optional[UUID] = None) -> TokenTransaction:
        """Add tokens to a user's balance"""
        # Get or create user balance
        balance = await self.get_user_balance(user_id)
        
        # Update balance
        balance.amount += amount
        
        # Create transaction record
        transaction = TokenTransaction(
            user_id=user_id,
            amount=amount,
            type=type,
            description=description,
            reference_id=reference_id
        )
        
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)
        
        return transaction
    
    async def remove_tokens(self, user_id: UUID, amount: Decimal, type: str, description: Optional[str] = None, reference_id: Optional[UUID] = None) -> TokenTransaction:
        """Remove tokens from a user's balance (if sufficient)"""
        # Get balance
        balance = await self.get_user_balance(user_id)
        
        # Check if sufficient balance
        if balance.amount < amount:
            raise ValueError("Insufficient token balance")
        
        # Update balance
        balance.amount -= amount
        
        # Create transaction record (with negative amount)
        transaction = TokenTransaction(
            user_id=user_id,
            amount=-amount,  # Store as negative for withdrawals
            type=type,
            description=description,
            reference_id=reference_id
        )
        
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)
        
        return transaction
    
    async def transfer_tokens(self, from_user_id: UUID, to_user_id: UUID, amount: Decimal, type: str, description: Optional[str] = None, reference_id: Optional[UUID] = None) -> tuple[TokenTransaction, TokenTransaction]:
        """Transfer tokens from one user to another"""
        # Remove from sender
        sender_tx = await self.remove_tokens(
            from_user_id, 
            amount, 
            type, 
            f"{description} - Transfer to user {to_user_id}", 
            reference_id
        )
        
        # Add to receiver
        receiver_tx = await self.add_tokens(
            to_user_id, 
            amount, 
            type, 
            f"{description} - Transfer from user {from_user_id}", 
            reference_id
        )
        
        return (sender_tx, receiver_tx)
    
    async def get_user_transactions(self, user_id: UUID, limit: int = 100, offset: int = 0) -> list[TokenTransaction]:
        """Get a user's transaction history"""
        query = select(TokenTransaction).where(
            TokenTransaction.user_id == user_id
        ).order_by(
            TokenTransaction.created_at.desc()
        ).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def grant_initial_tokens(self, user_id: UUID, amount: Decimal = Decimal("100.0")) -> TokenTransaction:
        """Grant initial tokens to a new user"""
        return await self.add_tokens(
            user_id,
            amount,
            "initial_grant",
            "Initial token grant for new user"
        ) 