from typing import Optional
from pydantic import BaseModel, EmailStr, UUID4
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    username: str
    
class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    password: Optional[str] = None
    badge: Optional[str] = None

class UserResponse(UserBase):
    id: UUID4
    is_active: bool
    is_verified: bool
    badge: str
    created_at: datetime
    follower_count: int
    tier: int
    
    class Config:
        orm_mode = True

class UserWithTokenBalance(UserResponse):
    token_balance: float
    
    class Config:
        orm_mode = True

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str 