from app.services.otp_service import OTPService
from db.db_manager import get_database
import logging
import asyncio

logger = logging.getLogger(__name__)

async def cleanup_expired_otps():
    """Periodic task to clean up expired OTPs"""
    try:
        db = await get_database()
        otp_service = OTPService(db)
        await otp_service.cleanup_expired_otps()
        logger.info("Expired OTPs cleaned up successfully")
    except Exception as e:
        logger.error(f"Error in OTP cleanup task: {e}")
