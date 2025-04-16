from fastapi import APIRouter

from .endpoints import auth, users, rooms, chat, streams, tokens

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(rooms.router, prefix="/rooms", tags=["rooms"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(streams.router, prefix="/streams", tags=["streams"])
api_router.include_router(tokens.router, prefix="/tokens", tags=["tokens"]) 