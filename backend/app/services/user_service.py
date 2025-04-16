from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt
from pydantic import EmailStr

from ..core.security import get_password_hash, verify_password, ALGORITHM
from ..core.config import settings
from ..models.user import User
from ..schemas.user import UserCreate, TokenPayload

class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user(self, user_id: UUID) -> Optional[User]:
        return await self.db.get(User, user_id)

    async def get_user_by_email(self, email: EmailStr) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalars().first()

    async def get_user_by_username(self, username: str) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalars().first()
        
    async def get_user_by_oauth(self, provider: str, oauth_id: str) -> Optional[User]:
        """Get user by OAuth provider and ID."""
        result = await self.db.execute(
            select(User).where(
                User.oauth_provider == provider,
                User.oauth_id == oauth_id
            )
        )
        return result.scalars().first()

    async def create_user(self, user_in: UserCreate) -> User:
        hashed_password = get_password_hash(user_in.password)
        user = User(
            username=user_in.username,
            email=user_in.email,
            hashed_password=hashed_password,
            is_verified=False, # Default for password registration
            badge='none' # Default badge
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user
        
    async def create_oauth_user(self, user_in: UserCreate, oauth_provider: str, oauth_id: str) -> User:
        """Create a user coming from an OAuth provider."""
        user = User(
            username=user_in.username,
            email=user_in.email,
            hashed_password=None, # No password for OAuth users
            oauth_provider=oauth_provider,
            oauth_id=oauth_id,
            is_verified=True, # Typically verified via OAuth provider
            badge='none' # Default badge
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ... existing authenticate, create_access_token, etc. ...

    def create_access_token(
        self, user_id: UUID, expires_delta: Optional[timedelta] = None
    ) -> str:
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(
                minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )
        to_encode = {"exp": expire, "sub": str(user_id)}
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt

    def create_refresh_token(
        self, user_id: UUID, expires_delta: Optional[timedelta] = None
    ) -> str:
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(
                minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES
            )
        to_encode = {"exp": expire, "sub": str(user_id)}
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt

    async def validate_refresh_token(self, token: str) -> Optional[UUID]:
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[ALGORITHM]
            )
            token_data = TokenPayload(**payload)
            if token_data.exp < datetime.utcnow().timestamp():
                return None # Token expired
            return token_data.sub
        except (jwt.JWTError, ValidationError):
            return None 