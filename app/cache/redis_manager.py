# app/cache/redis_manager.py
import redis.asyncio as redis
import json
import pickle
from typing import Any, Optional, Dict, List
from datetime import datetime, timedelta
import logging
import time
import os

logger = logging.getLogger(__name__)

class RedisManager:
    def __init__(self):
        self.redis = None
        self._pool = None
        # L1 Cache (In-Memory)
        self.memory_cache = {}
        self.memory_cache_ttl = {}
        self.max_memory_items = 100
    
    # async def init_redis_pool(self, redis_url: str = "redis://localhost:6379"):
    #     """Initialize Redis connection pool with optimizations"""
    #     try:
    #         from redis.asyncio import ConnectionPool
    #         import socket
            
    #         # Create connection pool with keepalive
    #         self._pool = ConnectionPool.from_url(
    #             redis_url,
    #             max_connections=int(os.getenv('REDIS_MAX_CONNECTIONS', 50)),
    #             socket_keepalive=True,
    #             socket_keepalive_options={
    #                 socket.TCP_KEEPIDLE: 60,
    #                 socket.TCP_KEEPINTVL: 10,
    #                 socket.TCP_KEEPCNT: 3
    #             },
    #             socket_timeout=int(os.getenv('REDIS_SOCKET_TIMEOUT', 5)),
    #             socket_connect_timeout=int(os.getenv('REDIS_SOCKET_CONNECT_TIMEOUT', 5)),
    #             decode_responses=False,
    #             retry_on_timeout=True,
    #             health_check_interval=30
    #         )
            
    #         self.redis = redis.Redis(connection_pool=self._pool)
            
    #         # Test connection
    #         await self.redis.ping()
            
    #         logger.info("✅ Redis connection pool initialized successfully")
    #         logger.info(f"   - Max connections: {os.getenv('REDIS_MAX_CONNECTIONS', 50)}")
    #         logger.info(f"   - Health check enabled")
            
    #     except Exception as e:
    #         logger.error(f"❌ Redis initialization failed: {e}")
    #         raise
    
    async def init_redis_pool(self, redis_url: str = "redis://localhost:6379"):
        """Initialize Redis connection pool"""
        try:
            # Simple, cross-platform configuration
            self.redis = await redis.from_url(
                redis_url,
                max_connections=20,
                retry_on_timeout=True,
                decode_responses=False
            )
            
            # Test connection
            await self.redis.ping()
            
            logger.info("✅ Redis connection pool initialized")
            
        except Exception as e:
            logger.error(f"❌ Redis initialization failed: {e}")
            raise

    async def close(self):
        """Close Redis connections gracefully"""
        if self.redis:
            await self.redis.close()
            logger.info("✅ Redis connection closed")
        
        if self._pool:
            await self._pool.disconnect()
            logger.info("✅ Redis connection pool closed")
    
    # ==========================================
    # MULTI-LAYER CACHE IMPLEMENTATION
    # ==========================================
    
    async def get(self, key: str, use_l1: bool = True) -> Optional[Any]:
        """
        Get value from multi-layer cache
        L1: Memory (fastest) -> L2: Redis (fast)
        """
        try:
            # L1 Cache check
            if use_l1:
                l1_value = self._get_from_l1(key)
                if l1_value is not None:
                    logger.debug(f"🎯 L1 Cache HIT: {key}")
                    return l1_value
            
            # L2 Redis cache
            if self.redis is None:
                logger.warning("Redis not initialized, skipping L2 cache")
                return None
            
            value = await self.redis.get(key)
            
            if value is None:
                logger.debug(f"❌ Cache MISS: {key}")
                return None
            
            # Deserialize
            try:
                deserialized_value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                deserialized_value = pickle.loads(value)
            
            # Promote to L1 cache
            if use_l1:
                self._set_to_l1(key, deserialized_value, ttl=60)
            
            logger.debug(f"✅ L2 Cache HIT: {key}")
            return deserialized_value
            
        except Exception as e:
            logger.error(f"Redis GET error for key {key}: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: int = 300, use_l1: bool = True) -> bool:
        """
        Set value in multi-layer cache
        Stores in both L1 (memory) and L2 (Redis)
        """
        try:
            # L1 Cache
            if use_l1:
                self._set_to_l1(key, value, ttl=min(ttl, 60))
            
            # L2 Redis cache
            if self.redis is None:
                return False
            
            # Serialize
            try:
                serialized_value = json.dumps(value, default=str)
            except (TypeError, ValueError):
                serialized_value = pickle.dumps(value)
            
            await self.redis.setex(key, ttl, serialized_value)
            logger.debug(f"💾 Cache SET: {key} (TTL: {ttl}s)")
            return True
            
        except Exception as e:
            logger.error(f"Redis SET error for key {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete from all cache layers"""
        try:
            # L1
            self.memory_cache.pop(key, None)
            self.memory_cache_ttl.pop(key, None)
            
            # L2
            if self.redis:
                result = await self.redis.delete(key)
                logger.debug(f"🗑️ Cache DELETE: {key}")
                return bool(result)
            return False
        except Exception as e:
            logger.error(f"Redis DELETE error for key {key}: {e}")
            return False
    
    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        try:
            if not self.redis:
                return 0
            
            # Get all matching keys
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                # Delete from L1
                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    self.memory_cache.pop(key_str, None)
                    self.memory_cache_ttl.pop(key_str, None)
                
                # Delete from L2
                deleted_count = await self.redis.delete(*keys)
                logger.info(f"🗑️ Deleted {deleted_count} keys matching pattern: {pattern}")
                return deleted_count
            
            return 0
        except Exception as e:
            logger.error(f"Redis DELETE PATTERN error for {pattern}: {e}")
            return 0
    
    # ==========================================
    # BATCH OPERATIONS (PIPELINE)
    # ==========================================
    
    async def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """Get multiple keys efficiently using pipeline"""
        try:
            if self.redis is None:
                logger.warning("Redis not initialized, skipping cache")
                return {}
            
            if not keys:
                return {}
            
            # Use pipeline for batch operation
            pipe = self.redis.pipeline()
            for key in keys:
                pipe.get(key)
            
            values = await pipe.execute()
            result = {}
            
            for key, value in zip(keys, values):
                if value is not None:
                    try:
                        result[key] = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        result[key] = pickle.loads(value)
            
            logger.debug(f"📦 Batch GET: {len(keys)} keys, {len(result)} hits")
            return result
            
        except Exception as e:
            logger.error(f"Redis MGET error: {e}")
            return {}
    
    async def set_many(self, items: Dict[str, Any], ttl: int = 300) -> bool:
        """Set multiple keys efficiently using pipeline"""
        try:
            if self.redis is None or not items:
                return False
            
            pipe = self.redis.pipeline()
            
            for key, value in items.items():
                try:
                    serialized_value = json.dumps(value, default=str)
                except (TypeError, ValueError):
                    serialized_value = pickle.dumps(value)
                
                pipe.setex(key, ttl, serialized_value)
            
            await pipe.execute()
            logger.debug(f"📦 Batch SET: {len(items)} keys")
            return True
            
        except Exception as e:
            logger.error(f"Redis batch SET error: {e}")
            return False
    
    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment counter in Redis"""
        try:
            if self.redis is None:
                return 0
            return await self.redis.incrby(key, amount)
        except Exception as e:
            logger.error(f"Redis INCR error for key {key}: {e}")
            return 0
    
    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiration time for key"""
        try:
            if self.redis is None:
                return False
            return await self.redis.expire(key, ttl)
        except Exception as e:
            logger.error(f"Redis EXPIRE error for key {key}: {e}")
            return False
    
    # ==========================================
    # L1 CACHE (IN-MEMORY) HELPERS
    # ==========================================
    
    def _get_from_l1(self, key: str) -> Optional[Any]:
        """Get from L1 memory cache"""
        if key in self.memory_cache:
            if time.time() < self.memory_cache_ttl.get(key, 0):
                return self.memory_cache[key]
            else:
                # Expired
                del self.memory_cache[key]
                del self.memory_cache_ttl[key]
        return None
    
    def _set_to_l1(self, key: str, value: Any, ttl: int):
        """Set in L1 memory cache with LRU eviction"""
        # LRU eviction if cache is full
        if len(self.memory_cache) >= self.max_memory_items:
            # Remove oldest item
            oldest_key = min(self.memory_cache_ttl.keys(), 
                           key=self.memory_cache_ttl.get)
            del self.memory_cache[oldest_key]
            del self.memory_cache_ttl[oldest_key]
        
        self.memory_cache[key] = value
        self.memory_cache_ttl[key] = time.time() + ttl
    
    # ==========================================
    # CACHE STATISTICS
    # ==========================================
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            if not self.redis:
                return {}
            
            info = await self.redis.info()
            
            return {
                "l1_cache_size": len(self.memory_cache),
                "l1_max_size": self.max_memory_items,
                "l2_connected": True,
                "l2_used_memory": info.get('used_memory_human', 'N/A'),
                "l2_connected_clients": info.get('connected_clients', 0),
                "l2_total_commands": info.get('total_commands_processed', 0),
                "l2_keyspace_hits": info.get('keyspace_hits', 0),
                "l2_keyspace_misses": info.get('keyspace_misses', 0),
                "l2_hit_rate": self._calculate_hit_rate(
                    info.get('keyspace_hits', 0),
                    info.get('keyspace_misses', 0)
                )
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {}
    
    def _calculate_hit_rate(self, hits: int, misses: int) -> float:
        """Calculate cache hit rate percentage"""
        total = hits + misses
        if total == 0:
            return 0.0
        return round((hits / total) * 100, 2)

# Global Redis instance
redis_manager = RedisManager()

def get_redis() -> RedisManager:
    return redis_manager