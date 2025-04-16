from typing import Any, List, Dict
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from ....core.deps import get_current_user, get_db, get_current_active_user
from ....models.user import User
from ....schemas.user import UserResponse, UserUpdate, UserWithTokenBalance
from ....services.token_service import TokenService
from ....services.stream_service import StreamService

router = APIRouter()

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
) -> Any:
    """
    Get current user information.
    """
    return current_user

@router.get("/me/balance", response_model=UserWithTokenBalance)
async def get_current_user_with_balance(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Get current user with token balance.
    """
    token_service = TokenService(db)
    balance = await token_service.get_user_balance(current_user.id)
    
    user_dict = {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "is_active": current_user.is_active,
        "is_verified": current_user.is_verified,
        "badge": current_user.badge,
        "created_at": current_user.created_at,
        "follower_count": current_user.follower_count,
        "tier": current_user.tier,
        "token_balance": float(balance.amount) if balance else 0.0
    }
    
    return user_dict

@router.patch("/me", response_model=UserResponse)
async def update_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Update current user information.
    """
    # Create a dict of fields to update
    update_data = user_update.dict(exclude_unset=True)
    
    if not update_data:
        return current_user
    
    # Hash password if provided
    if "password" in update_data:
        from ....core.security import get_password_hash
        update_data["hashed_password"] = get_password_hash(update_data.pop("password"))
        
    # TODO: Add logic here to restrict who can update the 'badge' field.
    # For now, allow self-update for demonstration.
    
    # Update user in database
    stmt = (
        update(User)
        .where(User.id == current_user.id)
        .values(**update_data)
        .returning(User)
    )
    result = await db.execute(stmt)
    updated_user = result.scalars().first()
    
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found after update")
        
    await db.commit()
    await db.refresh(updated_user)
    
    return updated_user

@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Delete current user.
    """
    stmt = delete(User).where(User.id == current_user.id)
    await db.execute(stmt)
    await db.commit()
    
    return None

@router.get("/me/analytics", response_model=Dict[str, Any])
async def get_user_analytics(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get analytics for the current user's streams.
    """
    stream_service = StreamService(db)
    analytics_data = await stream_service.get_user_stream_analytics(current_user.id)
    return analytics_data 