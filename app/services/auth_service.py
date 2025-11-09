from fastapi import HTTPException, status
from app.utils.auth import create_password_hash_async, get_user, verify_password_async, create_access_token, create_refresh_token
from db.db_manager import DatabaseManager
from schema.user import UserCreate
from bson import ObjectId
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import logging
import uuid
import time
from app.utils.get_time import get_ist_datetime_for_db

load_dotenv()
logger = logging.getLogger(__name__)

class AuthService:
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def create_unverified_user(self, user_data: UserCreate, id: str = None):
        """Create user with unverified email status"""
        try:
            logger.info(f"Creating unverified user with email: {user_data.email}")
            
            # Check if email already exists
            existing_email = await self.db.find_one('users', {"email": user_data.email.lower()})
            if existing_email:
                logger.warning(f"Email {user_data.email} already exists")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already exists"
                )
            
            # Hash password
            hashed_password = await create_password_hash_async(user_data.password)
            
            ist_time = get_ist_datetime_for_db()
            # Create user document
            user_doc = {
                "id": id,
                "name": user_data.name,
                "email": user_data.email.lower(),
                "hashed_password": hashed_password,
                "provider": "local",
                "email_verified": False,  # Not verified yet
                "created_at": ist_time['ist_string'],
                "is_active": True,
                "role": getattr(user_data, 'role', 'customer')
            }
            
            # Don't add phone yet - will be added after verification
            logger.info("Inserting unverified user into database...")
            
            user_id = await self.db.insert_one("users", user_doc)
            logger.info(f"Unverified user created with ID: {user_id}")
            
            return {
                "success": True,
                "message": "User created, awaiting email verification"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"User creation error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create user: {str(e)}"
            )

    # async def authenticate_user(self, db, username, password):
    #     """Authenticate user with email and password"""
    #     try:
    #         logger.info(f"Authenticating user: {username}")
    #         auth = await get_user(db, username)
            
    #         if not auth:
    #             logger.warning(f"User {username} not found")
    #             return None
                
    #         if not verify_password(password, auth['hashed_password']):
    #             logger.warning(f"Invalid password for user {username}")
    #             return None
            
    #         if not auth.get('is_active', True):
    #             logger.warning("User is inactive")
    #             return None

    #         logger.info(f"User {username} authenticated successfully")
    #         return auth
            
    #     except Exception as e:
    #         logger.error(f"Authentication error: {str(e)}")
    #         return None

    async def authenticate_user(self, db, username, password):
        """Authenticate with async password verification"""
        try:
            logger.info(f"Authenticating user: {username}")
            auth = await get_user(db, username)
            
            if not auth:
                logger.warning(f"User {username} not found")
                return None
            
            # ✅ ASYNC PASSWORD VERIFICATION (was blocking before!)
            is_valid = await verify_password_async(password, auth['hashed_password'])
            
            if not is_valid:
                logger.warning(f"Invalid password for user {username}")
                return None
            
            if not auth.get('is_active', True):
                logger.warning("User is inactive")
                return None

            logger.info(f"User {username} authenticated successfully")
            return auth
            
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return None

    async def update_user_phone_permanently(self, user_id: str, phone: str):
        """Update user's phone number and mark as permanently set"""
        try:
            logger.info(f"Permanently updating phone for user {user_id}")
            
            # Check if phone already exists for another user
            existing_phone = await self.db.find_one("users", {
                "phone": phone,
                "id": {"$ne": user_id},
                "phone_is_temporary": {"$ne": True}  # Exclude temp phones
            })
            
            if existing_phone:
                logger.warning(f"Phone {phone} already exists for another user")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phone number already exists"
                )
            ist_time = get_ist_datetime_for_db()
            # ✅ FIXED: Use only $set, remove $unset conflict
            await self.db.update_one(
                "users",
                {"id": user_id},
                {
                    "$set": {
                        "phone": phone,
                        "phone_verified": False,
                        "phone_is_temporary": False,  # ✅ Set to False (not unset)
                        "requires_phone_update": False,
                        "phone_updated_at": ist_time['ist_string']
                    }
                }
            )
            
            # Get updated user
            updated_user = await self.db.find_one("users", {"id": user_id})
            logger.info(f"Phone permanently set for user {user_id}")
            return updated_user
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Phone update error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update phone number"
            )

    async def create_or_get_google_user(self, email: str, name: str, google_id: str, id: str):
        """Create or get Google user - no email verification needed"""
        try:
            logger.info(f"Processing Google user: {email}")
            
            # Check if user exists
            existing_user = await self.db.find_one("users", {"email": email.lower()})
            
            if existing_user:
                logger.info(f"Google user {email} already exists")
                
                # ✅ Check if phone is PERMANENTLY set
                has_permanent_phone = (
                    existing_user.get("phone") and 
                    not existing_user.get("phone", "").startswith("TEMP_") and
                    not existing_user.get("phone_is_temporary", False) and
                    not existing_user.get("requires_phone_update", False)
                )
                
                requires_phone = not has_permanent_phone
                
                logger.info(f"User {email} requires_phone: {requires_phone}")
                return existing_user, requires_phone
            
            # Create new Google user with unique temp phone
            timestamp = str(int(time.time()))
            unique_id = str(uuid.uuid4()).replace('-', '')[:8]
            temp_phone = f"TEMP_GOOGLE_{timestamp}_{unique_id}"
            ist_time = get_ist_datetime_for_db()

            user_doc = {
                "id": id,
                "name": name,
                "email": email.lower(),
                "phone": temp_phone,
                "phone_is_temporary": True,
                "phone_verified": False,
                "requires_phone_update": True,
                "provider": "google",
                "google_id": google_id,
                "email_verified": True,  # Google emails are pre-verified
                "role": "customer",
                "is_active": True,
                "created_at": ist_time['ist_string']
            }
            
            user_id = await self.db.insert_one("users", user_doc)
            created_user = await self.db.find_one("users", {"_id": ObjectId(user_id)})
            
            logger.info(f"New Google user {email} created with temp phone")
            return created_user, True  # True = requires phone
            
        except Exception as e:
            logger.error(f"Google user creation error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process Google user"
            )