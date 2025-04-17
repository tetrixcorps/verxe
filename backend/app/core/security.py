from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union
from jose import jwt
from passlib.context import CryptContext
from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(
    subject: Union[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"exp": expire, "sub": str(subject), "type": "access"}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt

def create_refresh_token(
    subject: Union[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh"}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt

def create_signaling_token(
    user_id: str, room_id: str, expires_delta: Optional[timedelta] = None
) -> str:
    """
    Creates a short-lived token for WebRTC signaling authentication
    
    Args:
        user_id: User ID as string
        room_id: Room ID as string
        expires_delta: Optional expiration time delta, defaults to 5 minutes
        
    Returns:
        JWT token as string
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # Short-lived token for signaling - 5 minutes
        expire = datetime.utcnow() + timedelta(minutes=5)
        
    to_encode = {
        "exp": expire,
        "sub": str(user_id), 
        "room": str(room_id),
        "type": "signaling"
    }
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt

def verify_signaling_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verifies a WebRTC signaling token
    
    Args:
        token: JWT token string
        
    Returns:
        Dict containing token claims if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        # Verify it's a signaling token
        if payload.get("type") != "signaling":
            return None
            
        return payload
    except jwt.JWTError:
        return None 