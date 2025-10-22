# app/services/token_blacklist_service.py
"""
Token blacklist service for logout and security
Prevents use of revoked tokens
"""
from typing import Optional
from datetime import datetime, timedelta
import logging
from app.cache.redis_manager import get_redis

logger = logging.getLogger(__name__)

class TokenBlacklistService:
    """
    Manage blacklisted JWT tokens
    Uses Redis for fast lookups
    """
    def __init__(self):
        self.redis = get_redis()
        self.prefix = "token_blacklist:"
    
    async def blacklist_token(self, jti: str, exp_time: datetime):
        """
        Add token to blacklist
        Auto-expires when token would naturally expire
        """
        try:
            # Calculate TTL until token expires
            ttl = int((exp_time - datetime.utcnow()).total_seconds())
            
            if ttl > 0:
                key = f"{self.prefix}{jti}"
                await self.redis.set(key, "blacklisted", ttl)
                logger.info(f"✅ Token blacklisted: {jti[:8]}... (TTL: {ttl}s)")
                return True
            
            return False
        except Exception as e:
            logger.error(f"❌ Error blacklisting token: {e}")
            return False
    
    async def is_blacklisted(self, jti: str) -> bool:
        """Check if token is blacklisted"""
        try:
            key = f"{self.prefix}{jti}"
            result = await self.redis.get(key)
            return result is not None
        except Exception as e:
            logger.error(f"❌ Error checking blacklist: {e}")
            return False
    
    async def blacklist_all_user_tokens(self, user_id: str, expiry_hours: int = 24):
        """
        Blacklist all tokens for a user (logout from all devices)
        """
        try:
            key = f"user_tokens_revoked:{user_id}"
            ttl = expiry_hours * 3600
            await self.redis.set(key, datetime.utcnow().isoformat(), ttl)
            logger.info(f"✅ All tokens revoked for user: {user_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error revoking user tokens: {e}")
            return False
    
    async def are_user_tokens_revoked(self, user_id: str, token_issued_at: datetime) -> bool:
        """
        Check if user's tokens issued before a certain time are revoked
        """
        try:
            key = f"user_tokens_revoked:{user_id}"
            revoked_at_str = await self.redis.get(key)
            
            if revoked_at_str:
                revoked_at = datetime.fromisoformat(revoked_at_str)
                return token_issued_at < revoked_at
            
            return False
        except Exception as e:
            logger.error(f"❌ Error checking user token revocation: {e}")
            return False

# Global instance
token_blacklist_service = TokenBlacklistService()

def get_token_blacklist_service():
    return token_blacklist_service