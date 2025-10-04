from datetime import datetime
from typing import Optional
from app.cache.redis_manager import get_redis
import uuid
import json
import os
from db.db_manager import DatabaseManager

class SessionService:
    def __init__(self):
        self.redis = get_redis()
    
    async def create_session(self, user_id: str, device_info: dict = None) -> str:
        """Create new session in Redis"""
        session_id = str(uuid.uuid4())
        session_key = f"session:{session_id}"
        
        session_data = {
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat(),
            "device_info": device_info or {},
            "is_active": True
        }
        
        # Store session with 24 hour TTL
        await self.redis.set(session_key, session_data, 86400)
        
        # Track user's active sessions
        user_sessions_key = f"user_sessions:{user_id}"
        await self.redis.sadd(user_sessions_key, session_id)
        await self.redis.expire(user_sessions_key, 86400)
        
        return session_id
    
    async def validate_session(self, session_id: str) -> Optional[dict]:
        """Validate and refresh session"""
        session_key = f"session:{session_id}"
        session_data = await self.redis.get(session_key)
        
        if not session_data or not session_data.get('is_active'):
            return None
        
        # Update last activity
        session_data['last_activity'] = datetime.utcnow().isoformat()
        await self.redis.set(session_key, session_data, 86400)
        
        return session_data
    
    async def invalidate_session(self, session_id: str, user_id: str = None):
        """Invalidate specific session"""
        session_key = f"session:{session_id}"
        
        if not user_id:
            # Get user_id from session if not provided
            session_data = await self.redis.get(session_key)
            if session_data:
                user_id = session_data.get('user_id')
        
        # Remove from Redis
        await self.redis.delete(session_key)
        
        # Remove from user's session list
        if user_id:
            user_sessions_key = f"user_sessions:{user_id}"
            await self.redis.srem(user_sessions_key, session_id)
    
    async def invalidate_all_user_sessions(self, user_id: str):
        """Invalidate all sessions for a user (useful for logout everywhere)"""
        user_sessions_key = f"user_sessions:{user_id}"
        session_ids = await self.redis.smembers(user_sessions_key)
        
        # Delete all sessions
        if session_ids:
            session_keys = [f"session:{sid}" for sid in session_ids]
            await self.redis.delete(*session_keys)
        
        # Clear the user sessions set
        await self.redis.delete(user_sessions_key)

# Update your auth.py to use sessions
session_service = SessionService()

async def decode_token_with_session(token: str, db: DatabaseManager):
    """Enhanced token validation with session checking"""
    try:
        # Decode JWT
        payload = jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=[os.getenv('ALGORITHM')])
        user_id: str = payload.get("sub")
        session_id: str = payload.get("session_id")  # Add session_id to JWT payload
        
        if not user_id or not session_id:
            raise credentials_exception
        
        # Validate session in Redis
        session_data = await session_service.validate_session(session_id)
        if not session_data or session_data.get('user_id') != user_id:
            raise credentials_exception
        
        # Get user from database
        user = await get_user_by_id(db, user_id)
        if user is None:
            raise credentials_exception
        
        return UserinDB(
            id=str(user["_id"]),
            email=user["email"], 
            role=user['role'], 
            name=user.get('name', ''),
            is_active=user.get('is_active', True)
        )
        
    except JWTError:
        raise credentials_exception