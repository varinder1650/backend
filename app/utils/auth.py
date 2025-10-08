# import uuid
# from schema.user import UserinDB
# from fastapi.security import OAuth2PasswordBearer
# from passlib.context import CryptContext
# from datetime import datetime, timedelta
# from jose import JWTError, jwt
# from fastapi import HTTPException, Depends
# import os
# from dotenv import load_dotenv
# from db.db_manager import DatabaseManager, get_database
# import logging
# from bson import ObjectId

# logger = logging.getLogger(__name__)
# load_dotenv()

# pwd_context = CryptContext(
#     schemes=['bcrypt'], 
#     deprecated="auto",
#     bcrypt__rounds=12
# )
# Oauth_2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# credentials_exception = HTTPException(
#     status_code=401,
#     detail="Could not validate credentials",
#     headers={"WWW-Authenticate": "Bearer"},
# )

# async def get_user(db: DatabaseManager, username: str):
#     """Get user by email"""
#     user = await db.find_one('users', {"email": username})
#     if not user:
#         print("user not registered")
#         return None
#     return user

# async def get_user_by_id(db: DatabaseManager, user_id: str):
#     """Get user by ID"""
#     if not ObjectId.is_valid(user_id):
#         return None
#     user = await db.find_one('users', {"_id": ObjectId(user_id)})
#     return user

# def verify_password(plain_pass: str, hash_pass: str):
#     """Verify password against hash"""
#     return pwd_context.verify(plain_pass, hash_pass)

# def create_pasword_hash(password: str):
#     """Create password hash"""
#     return pwd_context.hash(password)

# def create_access_token(data: dict, exp_time: timedelta):
#     """Create JWT access token"""
#     to_encode = data.copy()
#     expire = datetime.utcnow() + (exp_time if exp_time else timedelta(minutes=15))
#     to_encode.update({"exp": expire})
#     token = jwt.encode(to_encode, os.getenv('SECRET_KEY'), algorithm=os.getenv('ALGORITHM'))
#     return token

# async def create_refresh_token(user_id: str, db: DatabaseManager):
#     jti = str(uuid.uuid4())
#     expire = datetime.utcnow() + timedelta(days = int(os.getenv('REFRESH_TOKEN_EXPIRE_DAYS')))
#     token_data = {"sub": user_id, "jti": jti, "exp": expire}
#     encoded = jwt.encode(token_data, os.getenv('SECRET_KEY'), algorithm=os.getenv('ALGORITHM'))
#     await db.insert_one("refresh_tokens", {"user_id": user_id, "jti": jti, "expire": expire})
#     return encoded

# async def decode_token(token: str, db: DatabaseManager):
#     """Decode and validate JWT token - FIXED VERSION"""
#     try:
#         payload = jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=[os.getenv('ALGORITHM')])
#         user_id: str = payload.get("sub")
#         if user_id is None:
#             raise credentials_exception
#     except JWTError:
#         raise credentials_exception

#     # ✅ Get user by ID instead of email
#     user = await get_user_by_id(db, user_id)
#     if user is None:
#         raise credentials_exception
    
#     return UserinDB(
#         id=str(user["id"]),
#         email=user["email"], 
#         role=user['role'], 
#         name=user.get('name', ''),
#         is_active=user.get('is_active', True)
#     )

# async def current_active_user(
#     token: str = Depends(Oauth_2_scheme), 
#     db: DatabaseManager = Depends(get_database)
# ):
#     """Get current active user from token"""
#     return await decode_token(token, db)

# async def get_current_user(current_user: UserinDB = Depends(current_active_user)):
#     """Get current user with active status check"""
#     if not current_user.is_active:
#         raise HTTPException(status_code=400, detail="Inactive user")
#     return current_user

import uuid
from schema.user import UserinDB
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import HTTPException, Depends
import os
from dotenv import load_dotenv
from db.db_manager import DatabaseManager, get_database
import logging
from bson import ObjectId

logger = logging.getLogger(__name__)
load_dotenv()

pwd_context = CryptContext(
    schemes=['bcrypt'], 
    deprecated="auto",
    bcrypt__rounds=12
)
Oauth_2_scheme = OAuth2PasswordBearer(tokenUrl="token")

credentials_exception = HTTPException(
    status_code=401,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

async def get_user(db: DatabaseManager, username: str):
    """Get user by email"""
    user = await db.find_one('users', {"email": username})
    if not user:
        logger.debug("User not registered")
        return None
    return user

async def get_user_by_id(db: DatabaseManager, user_id: str):
    """
    Get user by custom ID field
    ✅ FIXED: Now uses the 'id' field instead of '_id'
    """
    user = await db.find_one('users', {"id": user_id})
    if not user:
        logger.debug(f"User not found with id: {user_id}")
    return user

def verify_password(plain_pass: str, hash_pass: str):
    """Verify password against hash"""
    return pwd_context.verify(plain_pass, hash_pass)

# def create_pasword_hash(password: str):
#     """Create password hash"""
#     return pwd_context.hash(password)

def create_pasword_hash(password: str) -> str:
    """Hash password using bcrypt"""
    from passlib.context import CryptContext
    
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    # Ensure password is not too long (bcrypt limit is 72 bytes)
    if len(password.encode('utf-8')) > 72:
        password = password[:72]
    
    return pwd_context.hash(password)
    
def create_access_token(data: dict, exp_time: timedelta):
    """
    Create JWT access token
    ✅ The 'sub' field should contain the custom user ID (from 'id' field)
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (exp_time if exp_time else timedelta(minutes=15))
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, os.getenv('SECRET_KEY'), algorithm=os.getenv('ALGORITHM'))
    return token

async def create_refresh_token(user_id: str, db: DatabaseManager):
    """
    Create refresh token
    ✅ FIXED: user_id parameter should be the custom ID (from 'id' field)
    This gets stored in the 'user_id' field of refresh_tokens collection
    """
    jti = str(uuid.uuid4())
    expire = datetime.utcnow() + timedelta(days=int(os.getenv('REFRESH_TOKEN_EXPIRE_DAYS', 7)))
    token_data = {"sub": user_id, "jti": jti, "exp": expire}
    encoded = jwt.encode(token_data, os.getenv('SECRET_KEY'), algorithm=os.getenv('ALGORITHM'))
    
    # Store refresh token with custom user_id
    await db.insert_one("refresh_tokens", {
        "user_id": user_id,  # ✅ This is the custom ID
        "jti": jti, 
        "expire": expire,
        "created_at": datetime.utcnow()
    })
    
    logger.info(f"Created refresh token for user {user_id}")
    return encoded

async def decode_token(token: str, db: DatabaseManager):
    """
    Decode and validate JWT token
    ✅ FIXED: Now properly handles custom user IDs
    """
    try:
        payload = jwt.decode(token, os.getenv('SECRET_KEY'), algorithms=[os.getenv('ALGORITHM')])
        user_id: str = payload.get("sub")  # ✅ This is the custom user ID
        if user_id is None:
            logger.error("Token payload missing 'sub' field")
            raise credentials_exception
    except JWTError as e:
        logger.error(f"JWT decode error: {e}")
        raise credentials_exception

    # ✅ Get user by custom ID (from 'id' field, not '_id')
    user = await get_user_by_id(db, user_id)
    if user is None:
        logger.error(f"User not found for id: {user_id}")
        raise credentials_exception
    
    return UserinDB(
        id=str(user["id"]),  # ✅ Return custom ID
        email=user["email"], 
        role=user['role'], 
        name=user.get('name', ''),
        is_active=user.get('is_active', True)
    )

async def current_active_user(
    token: str = Depends(Oauth_2_scheme), 
    db: DatabaseManager = Depends(get_database)
):
    """Get current active user from token"""
    return await decode_token(token, db)

async def get_current_user(current_user: UserinDB = Depends(current_active_user)):
    """Get current user with active status check"""
    if not current_user.is_active:
        logger.warning(f"Inactive user attempted access: {current_user.email}")
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def verify_refresh_token(refresh_token: str, db: DatabaseManager) -> str:
    """
    Verify refresh token and return user_id
    ✅ NEW: Separate function for cleaner refresh token verification
    """
    try:
        payload = jwt.decode(
            refresh_token, 
            os.getenv('SECRET_KEY'), 
            algorithms=[os.getenv('ALGORITHM')]
        )
        user_id = payload.get("sub")
        jti = payload.get("jti")
        
        if not user_id or not jti:
            raise credentials_exception
        
        # Check if token exists and is valid
        stored_token = await db.find_one("refresh_tokens", {
            "user_id": user_id,
            "jti": jti,
            "expire": {"$gt": datetime.utcnow()}
        })
        
        if not stored_token:
            logger.warning(f"Refresh token not found or expired for user {user_id}")
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired refresh token"
            )
        
        return user_id
        
    except JWTError as e:
        logger.error(f"Refresh token decode error: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token"
        )

async def revoke_refresh_token(jti: str, db: DatabaseManager):
    """
    Revoke a specific refresh token
    ✅ NEW: Helper function for logout
    """
    result = await db.delete_one("refresh_tokens", {"jti": jti})
    if result:
        logger.info(f"Revoked refresh token: {jti}")
    return result

async def revoke_all_user_tokens(user_id: str, db: DatabaseManager):
    """
    Revoke all refresh tokens for a user
    ✅ NEW: Useful for "logout from all devices"
    """
    result = await db.delete_many("refresh_tokens", {"user_id": user_id})
    logger.info(f"Revoked all tokens for user {user_id}")
    return result