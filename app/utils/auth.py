# app/utils/auth.py - COMPLETE REPLACEMENT
import uuid
from schema.user import UserinDB
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import HTTPException, Depends, status
import os
from dotenv import load_dotenv
from db.db_manager import DatabaseManager, get_database
import logging
from bson import ObjectId
from app.services.token_blacklist_service import get_token_blacklist_service
from concurrent.futures import ThreadPoolExecutor
import asyncio

_password_executor = ThreadPoolExecutor(max_workers=4)

logger = logging.getLogger(__name__)
load_dotenv()

# Password hashing context
pwd_context = CryptContext(
    schemes=['bcrypt'], 
    deprecated="auto",
    bcrypt__rounds=int(os.getenv('BCRYPT_ROUNDS', 10))  # ✅ Configurable, default 14
)

Oauth_2_scheme = OAuth2PasswordBearer(tokenUrl="token")

credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

# ==========================================
# PASSWORD UTILITIES
# ==========================================

def verify_password(plain_pass: str, hash_pass: str) -> bool:
    """Verify password against hash"""
    try:
        return pwd_context.verify(plain_pass, hash_pass)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

def create_pasword_hash(password: str) -> str:
    """
    Hash password using bcrypt with configurable rounds
    Ensures password length is within bcrypt limits
    """
    try:
        # Ensure password is not too long (bcrypt limit is 72 bytes)
        if len(password.encode('utf-8')) > 72:
            password = password[:72]
        
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"Password hashing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password hashing failed"
        )
async def verify_password_async(plain_pass: str, hash_pass: str) -> bool:
    """
    Async password verification - doesn't block event loop
    THIS IS CRITICAL FOR PERFORMANCE!
    """
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(
            _password_executor,
            pwd_context.verify,
            plain_pass,
            hash_pass
        )
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

async def create_password_hash_async(password: str) -> str:
    """
    Async password hashing - doesn't block event loop
    """
    loop = asyncio.get_event_loop()
    try:
        # Ensure password length
        if len(password.encode('utf-8')) > 72:
            password = password[:72]
        
        return await loop.run_in_executor(
            _password_executor,
            pwd_context.hash,
            password
        )
    except Exception as e:
        logger.error(f"Password hashing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password processing failed"
        )
# ==========================================
# TOKEN GENERATION
# ==========================================

def create_access_token(data: dict, exp_time: timedelta = None) -> str:
    """
    Create JWT access token with enhanced security
    Includes: sub, role, jti (for blacklisting), iat, exp
    """
    try:
        to_encode = data.copy()
        
        # Add timestamps
        now = datetime.utcnow()
        expire = now + (exp_time if exp_time else timedelta(minutes=30))
        
        # Add JWT claims
        to_encode.update({
            "exp": expire,
            "iat": now,  # ✅ Issued at time
            "jti": str(uuid.uuid4())  # ✅ JWT ID for blacklisting
        })
        
        token = jwt.encode(
            to_encode, 
            os.getenv('SECRET_KEY'), 
            algorithm=os.getenv('ALGORITHM', 'HS256')
        )
        
        return token
    except Exception as e:
        logger.error(f"Token creation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token generation failed"
        )

async def create_refresh_token(user_id: str, db: DatabaseManager) -> str:
    """
    Create refresh token with database storage
    """
    try:
        jti = str(uuid.uuid4())
        expire = datetime.utcnow() + timedelta(
            days=int(os.getenv('REFRESH_TOKEN_EXPIRE_DAYS', 7))
        )
        
        token_data = {
            "sub": user_id, 
            "jti": jti, 
            "exp": expire,
            "iat": datetime.utcnow(),
            "type": "refresh"  # ✅ Token type
        }
        
        encoded = jwt.encode(
            token_data, 
            os.getenv('SECRET_KEY'), 
            algorithm=os.getenv('ALGORITHM', 'HS256')
        )
        
        # Store refresh token in database
        await db.insert_one("refresh_tokens", {
            "user_id": user_id,
            "jti": jti, 
            "expire": expire,
            "created_at": datetime.utcnow(),
            "revoked": False  # ✅ Track revocation status
        })
        
        logger.info(f"✅ Refresh token created for user {user_id}")
        return encoded
    except Exception as e:
        logger.error(f"Refresh token creation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Refresh token generation failed"
        )

# ==========================================
# TOKEN VALIDATION
# ==========================================

async def decode_token(token: str, db: DatabaseManager) -> UserinDB:
    """
    Decode and validate JWT token with enhanced security checks
    - Validates expiry
    - Checks token blacklist
    - Verifies user exists and is active
    """
    try:
        # Decode token with expiry verification
        payload = jwt.decode(
            token, 
            os.getenv('SECRET_KEY'), 
            algorithms=[os.getenv('ALGORITHM', 'HS256')],
            options={"verify_exp": True}  # ✅ Enforce expiry check
        )
        
        user_id: str = payload.get("sub")
        jti: str = payload.get("jti")
        iat: int = payload.get("iat")
        
        if user_id is None:
            logger.error("Token payload missing 'sub' field")
            raise credentials_exception
        
        # ✅ Check token blacklist
        if jti:
            blacklist_service = get_token_blacklist_service()
            is_blacklisted = await blacklist_service.is_blacklisted(jti)
            
            if is_blacklisted:
                logger.warning(f"⚠️ Blacklisted token used: {jti[:8]}...")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked"
                )
            
            # ✅ Check if all user tokens were revoked
            if iat:
                issued_at = datetime.fromtimestamp(iat)
                are_revoked = await blacklist_service.are_user_tokens_revoked(
                    user_id, issued_at
                )
                
                if are_revoked:
                    logger.warning(f"⚠️ User tokens revoked: {user_id}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="All sessions have been logged out"
                    )
        
        # Get user from database
        user = await get_user_by_id(db, user_id)
        
        if user is None:
            logger.error(f"User not found for id: {user_id}")
            raise credentials_exception
        
        # Check if user is active
        if not user.get('is_active', True):
            logger.warning(f"⚠️ Inactive user attempted access: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive"
            )
        
        return UserinDB(
            id=str(user["id"]),
            email=user["email"], 
            role=user['role'], 
            name=user.get('name', ''),
            is_active=user.get('is_active', True)
        )
        
    except jwt.ExpiredSignatureError:
        logger.warning("⚠️ Expired token used")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
        raise credentials_exception
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        raise credentials_exception

# ==========================================
# USER RETRIEVAL
# ==========================================

async def get_user(db: DatabaseManager, username: str):
    """Get user by email"""
    try:
        user = await db.find_one('users', {"email": username.lower().strip()})
        return user
    except Exception as e:
        logger.error(f"Error fetching user: {e}")
        return None

async def get_user_by_id(db: DatabaseManager, user_id: str):
    """Get user by custom ID field"""
    try:
        user = await db.find_one('users', {"id": user_id})
        return user
    except Exception as e:
        logger.error(f"Error fetching user by id: {e}")
        return None

# ==========================================
# AUTHENTICATION DEPENDENCIES
# ==========================================

async def current_active_user(
    token: str = Depends(Oauth_2_scheme), 
    db: DatabaseManager = Depends(get_database)
) -> UserinDB:
    """Get current active user from token"""
    return await decode_token(token, db)

async def get_current_user(
    current_user: UserinDB = Depends(current_active_user)
) -> UserinDB:
    """
    Get current user with active status check
    Use this dependency for protected routes
    """
    if not current_user.is_active:
        logger.warning(f"⚠️ Inactive user attempted access: {current_user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive"
        )
    return current_user

async def get_current_admin(
    current_user: UserinDB = Depends(get_current_user)
) -> UserinDB:
    """
    Dependency for admin-only routes
    """
    if current_user.role != "admin":
        logger.warning(f"⚠️ Non-admin attempted admin access: {current_user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user

async def get_current_delivery_partner(
    current_user: UserinDB = Depends(get_current_user)
) -> UserinDB:
    """
    Dependency for delivery partner routes
    """
    if current_user.role != "delivery_partner":
        logger.warning(f"⚠️ Non-delivery partner attempted delivery access: {current_user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery partner access required"
        )
    return current_user

# ==========================================
# REFRESH TOKEN OPERATIONS
# ==========================================

async def verify_refresh_token(refresh_token: str, db: DatabaseManager) -> str:
    """
    Verify refresh token and return user_id
    Checks database for token validity
    """
    try:
        payload = jwt.decode(
            refresh_token, 
            os.getenv('SECRET_KEY'), 
            algorithms=[os.getenv('ALGORITHM', 'HS256')],
            options={"verify_exp": True}
        )
        
        user_id = payload.get("sub")
        jti = payload.get("jti")
        token_type = payload.get("type")
        
        if not user_id or not jti or token_type != "refresh":
            raise credentials_exception
        
        # Check if token exists in database and is not revoked
        stored_token = await db.find_one("refresh_tokens", {
            "user_id": user_id,
            "jti": jti,
            "expire": {"$gt": datetime.utcnow()},
            "revoked": False
        })
        
        if not stored_token:
            logger.warning(f"⚠️ Invalid refresh token for user {user_id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token"
            )
        
        return user_id
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired"
        )
    except JWTError as e:
        logger.error(f"Refresh token decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Refresh token verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed"
        )

async def revoke_refresh_token(jti: str, db: DatabaseManager) -> bool:
    """Revoke a specific refresh token"""
    try:
        result = await db.update_one(
            "refresh_tokens",
            {"jti": jti},
            {"$set": {"revoked": True, "revoked_at": datetime.utcnow()}}
        )
        
        if result:
            logger.info(f"✅ Revoked refresh token: {jti[:8]}...")
            return True
        return False
    except Exception as e:
        logger.error(f"Error revoking refresh token: {e}")
        return False

async def revoke_all_user_tokens(user_id: str, db: DatabaseManager) -> bool:
    """Revoke all refresh tokens for a user (logout from all devices)"""
    try:
        result = await db.update_many(
            "refresh_tokens",
            {"user_id": user_id, "revoked": False},
            {"$set": {"revoked": True, "revoked_at": datetime.utcnow()}}
        )
        
        # Also blacklist all active access tokens
        blacklist_service = get_token_blacklist_service()
        await blacklist_service.blacklist_all_user_tokens(user_id)
        
        logger.info(f"✅ Revoked all tokens for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error revoking user tokens: {e}")
        return False

async def get_current_admin(
    current_user: UserinDB = Depends(get_current_user)
) -> UserinDB:
    """
    Dependency for admin-only routes
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user