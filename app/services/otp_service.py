import random
import string
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class OTPService:
    def __init__(self, db):
        self.db = db
    
    def generate_otp(self, length: int = 6) -> str:
        """Generate a random OTP"""
        return ''.join(random.choices(string.digits, k=length))
    
    async def create_otp(
        self, 
        email: str, 
        otp_type: str,  # 'email_verification', 'password_reset', 'phone_verification'
        expiry_minutes: int = 10
    ) -> str:
        """Create and store OTP"""
        try:
            otp = self.generate_otp()
            expiry = datetime.utcnow() + timedelta(minutes=expiry_minutes)
            
            otp_doc = {
                "email": email.lower().strip(),
                "otp": otp,
                "type": otp_type,
                "expires_at": expiry,
                "used": False,
                "attempts": 0,
                "created_at": datetime.utcnow()
            }
            
            # Delete any existing unused OTPs for this email and type
            await self.db.delete_many("otps", {
                "email": email.lower().strip(),
                "type": otp_type,
                "used": False
            })
            
            # Insert new OTP
            await self.db.insert_one("otps", otp_doc)
            
            logger.info(f"OTP created for {email} (type: {otp_type})")
            return otp
            
        except Exception as e:
            logger.error(f"Error creating OTP: {e}")
            raise
    
    async def verify_otp(
        self, 
        email: str, 
        otp: str, 
        otp_type: str,
        max_attempts: int = 3
    ) -> bool:
        """Verify OTP"""
        try:
            print(email,otp,otp_type)
            otp_doc = await self.db.find_one("otps", {
                "email": email.lower().strip(),
                "otp": otp,
                "type": otp_type,
                "used": False,
                # "expires_at": {"$gt": datetime.utcnow()}
            })
            print(otp_doc)
            if not otp_doc:
                # Check if OTP exists but wrong/expired
                existing_otp = await self.db.find_one("otps", {
                    "email": email.lower().strip(),
                    "type": otp_type,
                    "used": False
                })
                
                if existing_otp:
                    # Increment attempts
                    attempts = existing_otp.get("attempts", 0) + 1
                    await self.db.update_one(
                        "otps",
                        {"_id": existing_otp["_id"]},
                        {"$set": {"attempts": attempts}}
                    )
                    
                    if attempts >= max_attempts:
                        # Mark as used to prevent further attempts
                        await self.db.update_one(
                            "otps",
                            {"_id": existing_otp["_id"]},
                            {"$set": {"used": True, "blocked_at": datetime.utcnow()}}
                        )
                        logger.warning(f"OTP blocked for {email} due to too many attempts")
                
                return False
            
            # Mark OTP as used
            await self.db.update_one(
                "otps",
                {"_id": otp_doc["_id"]},
                {"$set": {"used": True, "used_at": datetime.utcnow()}}
            )
            
            logger.info(f"OTP verified successfully for {email}")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying OTP: {e}")
            return False
    
    async def cleanup_expired_otps(self):
        """Remove expired OTPs (run periodically)"""
        try:
            result = await self.db.delete_many("otps", {
                "expires_at": {"$lt": datetime.utcnow()}
            })
            logger.info(f"Cleaned up {result} expired OTPs")
        except Exception as e:
            logger.error(f"Error cleaning up OTPs: {e}")