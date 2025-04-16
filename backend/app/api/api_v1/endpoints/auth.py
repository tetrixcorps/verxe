from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal
from authlib.integrations.starlette_client import OAuth

from ....core.deps import get_db
from ....core.config import settings
from ....services.user_service import UserService
from ....services.token_service import TokenService
from ....schemas.user import UserCreate, UserResponse, TokenResponse

# Configure Authlib OAuth client
oauth = OAuth()
oauth.register(
    name='google',
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Register a new user.
    """
    user_service = UserService(db)
    token_service = TokenService(db)
    
    # Check if user already exists
    existing_user = await user_service.get_user_by_email(user_in.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )
    
    # Create new user
    user = await user_service.create_user(user_in)
    
    # Grant initial tokens
    initial_amount = Decimal(str(settings.INITIAL_TOKEN_GRANT))
    await token_service.grant_initial_tokens(user.id, initial_amount)
    
    return user

@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Login for access token.
    """
    user_service = UserService(db)
    user = await user_service.authenticate(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = user_service.create_access_token(user.id)
    refresh_token = user_service.create_refresh_token(user.id)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    refresh_token: str,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Refresh access token.
    """
    user_service = UserService(db)
    user_id = await user_service.validate_refresh_token(refresh_token)
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = await user_service.get_user(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    new_access_token = user_service.create_access_token(user.id)
    new_refresh_token = user_service.create_refresh_token(user.id)
    
    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }

# --- Google OAuth Endpoints ---

@router.get("/google/login")
async def google_login(request: Request):
    """
    Redirect the user to Google for authentication.
    """
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/google/callback")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle the callback from Google after authentication.
    Creates or logs in the user and returns tokens.
    """
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Could not authorize Google access: {e}")

    user_info = token.get('userinfo')
    if not user_info:
        raise HTTPException(status_code=400, detail="Could not fetch user info from Google")

    email = user_info.get('email')
    oauth_id = user_info.get('sub') # Google's unique ID for the user
    username = user_info.get('name') or user_info.get('given_name') or email # Fallback username

    if not email or not oauth_id:
        raise HTTPException(status_code=400, detail="Email or Google ID not provided")

    user_service = UserService(db)
    token_service = TokenService(db)

    # Check if user exists with this OAuth ID
    user = await user_service.get_user_by_oauth('google', oauth_id)

    if not user:
        # Check if user exists with this email but different login method
        existing_user_by_email = await user_service.get_user_by_email(email)
        if existing_user_by_email:
            # TODO: Handle account linking or raise error?
            # For now, raise error to prevent duplicate emails
            raise HTTPException(
                status_code=400,
                detail="Email already registered with a different login method. Please log in with your password."
            )
            
        # If user does not exist, create a new one
        # Generate a unique username if the default one is taken
        base_username = username
        count = 1
        while await user_service.get_user_by_username(username):
            username = f"{base_username}{count}"
            count += 1
            
        user_create = UserCreate(
            email=email,
            username=username,
            password=None # No password for OAuth users
        )
        user = await user_service.create_oauth_user(
            user_in=user_create,
            oauth_provider='google',
            oauth_id=oauth_id
        )
        # Grant initial tokens for new OAuth user
        initial_amount = Decimal(str(settings.INITIAL_TOKEN_GRANT))
        await token_service.grant_initial_tokens(user.id, initial_amount)
    
    if not user.is_active:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate tokens for the user
    access_token = user_service.create_access_token(user.id)
    refresh_token = user_service.create_refresh_token(user.id)

    # TODO: Redirect user back to frontend with tokens (e.g., in query params or hash)
    # For simplicity, returning tokens directly here. Frontend needs adjustment.
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer"
    ) 