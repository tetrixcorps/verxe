from typing import Dict, Optional, Callable
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .config import settings
from ..models.user import User

class RateLimiter:
    """Simple in-memory rate limiter"""
    def __init__(self):
        self.requests: Dict[str, Dict[str, float]] = {}
    
    def is_rate_limited(self, identifier: str, max_requests: int, window: int = 60) -> bool:
        """
        Check if a request should be rate limited
        
        Args:
            identifier: Unique identifier for the client (user ID, IP, etc)
            max_requests: Maximum number of requests allowed in the window
            window: Time window in seconds
            
        Returns:
            bool: True if the request should be rate limited, False otherwise
        """
        current_time = time.time()
        
        # Initialize if first request
        if identifier not in self.requests:
            self.requests[identifier] = {}
        
        # Clean up old requests
        self.requests[identifier] = {
            req_id: timestamp 
            for req_id, timestamp in self.requests[identifier].items() 
            if current_time - timestamp < window
        }
        
        # Check if reached limit
        if len(self.requests[identifier]) >= max_requests:
            return True
        
        # Add new request
        self.requests[identifier][str(current_time)] = current_time
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware for rate limiting API requests based on user tier
    """
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.rate_limiter = RateLimiter()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for certain paths
        if self._should_skip_rate_limiting(request.url.path):
            return await call_next(request)
        
        # Get rate limit by user tier
        user = request.scope.get("user")
        tier = self._get_user_tier(user)
        limit = self._get_rate_limit_for_tier(tier)
        
        # Use IP for anonymous users, user ID for authenticated users
        client_identifier = str(user.id) if user else request.client.host
        
        # Check rate limit
        if self.rate_limiter.is_rate_limited(client_identifier, limit):
            return Response(
                content='{"detail": "Rate limit exceeded"}',
                status_code=429,
                media_type="application/json"
            )
        
        return await call_next(request)
    
    def _should_skip_rate_limiting(self, path: str) -> bool:
        """Determine if rate limiting should be skipped for this path"""
        skip_paths = [
            "/docs", 
            "/redoc", 
            "/openapi.json",
            "/api/auth/login",
            "/api/auth/refresh"
        ]
        return any(path.startswith(skip) for skip in skip_paths)
    
    def _get_user_tier(self, user: Optional[User]) -> int:
        """Get user tier, default to lowest tier for anonymous users"""
        if not user:
            return 1
        return user.tier
    
    def _get_rate_limit_for_tier(self, tier: int) -> int:
        """Get rate limit based on user tier"""
        limits = {
            1: settings.RATE_LIMIT_TIER_1,  # Basic
            2: settings.RATE_LIMIT_TIER_2,  # Silver
            3: settings.RATE_LIMIT_TIER_3,  # Gold
            4: settings.RATE_LIMIT_TIER_4,  # Diamond
        }
        return limits.get(tier, settings.RATE_LIMIT_TIER_1) 