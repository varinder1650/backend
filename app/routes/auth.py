from fastapi import APIRouter, HTTPException, Depends, status, Request, BackgroundTasks
import logging
from dotenv import load_dotenv
import os
from datetime import timedelta, datetime
from app.services.auth_service import AuthService
from app.services.otp_service import OTPService
from app.services.email_service import email_service
from db.db_manager import DatabaseManager, get_database
from schema.user import (
    UserCreate, TokenOut, UserResponse, UserLogin, GoogleLogin, 
    PhoneUpdate, ForgotPasswordRequest, ResetPasswordRequest, 
    UpdateUser, VerifyEmailRequest, VerifyOTPRequest
)
from app.utils.auth import create_refresh_token, get_current_user, create_access_token
from jose import JWTError, jwt
from app.utils.id_generator import get_id_generator
from app.middleware.rate_limiter import rate_limit
from pydantic import BaseModel

id_generator = get_id_generator()
load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter()

# New Pydantic models
class VerifyEmailRequest(BaseModel):
    email: str
    otp: str

class ResendOTPRequest(BaseModel):
    email: str

class VerifyPasswordResetOTP(BaseModel):
    email: str
    otp: str

class ResetPasswordWithOTP(BaseModel):
    email: str
    otp: str
    new_password: str


@router.post("/register")
@rate_limit(max_requests=5, window_seconds=300)
async def register_user(
    user_data: UserCreate, 
    background_tasks: BackgroundTasks,
    db: DatabaseManager = Depends(get_database)
):
    """Register new user and send email verification OTP"""
    try:
        auth_service = AuthService(db)
        otp_service = OTPService(db)
        
        # Check if email already exists
        existing_user = await db.find_one('users', {"email": user_data.email.lower()})
        if existing_user:
            if existing_user.get("email_verified"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )
            else:
                # User exists but not verified, resend OTP
                otp = await otp_service.create_otp(user_data.email, "email_verification")
                background_tasks.add_task(
                    email_service.send_email_verification_otp,
                    user_data.email,
                    user_data.name,
                    otp
                )
                return {
                    "success": True,
                    "message": "Verification code sent to your email",
                    "requires_verification": True,
                    "email": user_data.email
                }
        
        # Create user with unverified status
        custom_id = await id_generator.generate_user_id(user_data.email, "customer")
        result = await auth_service.create_unverified_user(user_data, custom_id)
        
        # Generate and send OTP
        otp = await otp_service.create_otp(user_data.email, "email_verification")
        background_tasks.add_task(
            email_service.send_email_verification_otp,
            user_data.email,
            user_data.name,
            otp
        )
        
        logger.info(f"Registration initiated for {user_data.email}")
        
        return {
            "success": True,
            "message": "Verification code sent to your email",
            "requires_verification": True,
            "email": user_data.email
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration service error"
        )


@router.post("/verify-email")
@rate_limit(max_requests=5, window_seconds=300)
async def verify_email(
    verify_data: VerifyEmailRequest,
    db: DatabaseManager = Depends(get_database)
):
    """Verify email with OTP"""
    try:
        otp_service = OTPService(db)
        
        # Verify OTP
        is_valid = await otp_service.verify_otp(
            verify_data.email, 
            verify_data.otp, 
            "email_verification"
        )
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification code"
            )
        
        # Update user as verified
        user = await db.find_one("users", {"email": verify_data.email.lower()})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        await db.update_one(
            "users",
            {"id": user["id"]},
            {"$set": {"email_verified": True, "verified_at": datetime.utcnow()}}
        )
        
        # Create tokens
        access_token = create_access_token(
            data={'sub': str(user['id']), 'role': user['role']},
            exp_time=timedelta(minutes=int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', 30)))
        )
        refresh_token = await create_refresh_token(str(user['id']), db)
        
        # Check if phone is required
        requires_phone = not user.get("phone") or user.get("phone", "").startswith("TEMP_")
        
        logger.info(f"Email verified for {verify_data.email}")
        
        return TokenOut(
            access_token=access_token,
            refresh_token=refresh_token,
            requires_phone=requires_phone,
            token_type="bearer"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Email verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email verification failed"
        )


@router.post("/resend-verification")
@rate_limit(max_requests=3, window_seconds=300)
async def resend_verification(
    resend_data: ResendOTPRequest,
    background_tasks: BackgroundTasks,
    db: DatabaseManager = Depends(get_database)
):
    """Resend email verification OTP"""
    try:
        user = await db.find_one("users", {"email": resend_data.email.lower()})
        if not user:
            # Don't reveal if user exists
            return {"success": True, "message": "Verification code sent if email exists"}
        
        if user.get("email_verified"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already verified"
            )
        
        otp_service = OTPService(db)
        otp = await otp_service.create_otp(resend_data.email, "email_verification")
        
        background_tasks.add_task(
            email_service.send_email_verification_otp,
            resend_data.email,
            user["name"],
            otp
        )
        
        return {"success": True, "message": "Verification code sent to your email"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resend verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resend verification code"
        )

@router.post("/login", response_model=TokenOut)
@rate_limit(max_requests=10, window_seconds=300)
async def login_user(
    request: Request,
    user_data: UserLogin, 
    db: DatabaseManager = Depends(get_database)
):
    """Login user"""
    try:
        print(user_data)
        auth_service = AuthService(db)
        user = await auth_service.authenticate_user(db, user_data.email, user_data.password)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Invalid email or password",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Check if email is verified
        if not user.get("email_verified", False) and user.get("provider") != "google":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email not verified. Please verify your email first."
            )
        
        user_custom_id = str(user['id'])
        
        access_token = create_access_token(
            data={'sub': user_custom_id, 'role': user['role']},
            exp_time=timedelta(minutes=int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', 30)))
        )
        refresh_token = await create_refresh_token(user_custom_id, db)
        
        # ✅ FIXED: Properly check if phone is required
        has_permanent_phone = (
            user.get("phone") and 
            not user.get("phone", "").startswith("TEMP_") and
            not user.get("phone_is_temporary", False) and
            not user.get("requires_phone_update", False)
        )
        
        requires_phone = not has_permanent_phone
        
        logger.info(f"User {user['email']} logged in - requires_phone: {requires_phone}")
        
        return TokenOut(
            access_token=access_token,
            refresh_token=refresh_token,
            requires_phone=requires_phone,
            user = user,
            token_type="bearer"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service error"
        )

@router.post("/google", response_model=TokenOut)
@rate_limit(max_requests=10, window_seconds=300)
async def google_login(
    user_info: GoogleLogin, 
    db: DatabaseManager = Depends(get_database)
):
    """Google OAuth login - no email verification required"""
    try:
        logger.info(f"Google login attempt with data: {user_info.dict()}")
        
        user_data = user_info.user
        email = user_data.get("email")
        name = user_data.get("name")
        google_id = user_data.get("googleId") or user_data.get("id")
        
        logger.info(f"Extracted data - email: {email}, name: {name}, google_id: {google_id}")
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required from Google"
            )
        
        if not name:
            name = email.split('@')[0]
        
        if not google_id:
            google_id = email
        
        auth_service = AuthService(db)
        custom_id = await id_generator.generate_user_id(email, "customer")
        user, requires_phone = await auth_service.create_or_get_google_user(
            email, name, google_id, custom_id
        )
        
        # ✅ Double-check phone requirement
        has_permanent_phone = (
            user.get("phone") and 
            not user.get("phone", "").startswith("TEMP_") and
            not user.get("phone_is_temporary", False) and
            not user.get("requires_phone_update", False)
        )
        
        requires_phone = not has_permanent_phone
        
        user_custom_id = str(user['id'])
        
        access_token = create_access_token(
            data={'sub': user_custom_id, 'role': user.get('role', 'customer')},
            exp_time=timedelta(minutes=int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', 30)))
        )
        refresh_token = await create_refresh_token(user_custom_id, db)
        
        logger.info(f"Google user {email} logged in, requires_phone: {requires_phone}, phone: {user.get('phone', 'None')}")
        
        return TokenOut(
            access_token=access_token,
            refresh_token=refresh_token,
            requires_phone=requires_phone,
            token_type="bearer"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Google authentication failed"
        )
        
@router.post("/phone")
async def update_phone(
    phone_data: PhoneUpdate, 
    current_user=Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
):
    """Update user phone number - marks phone as permanently set"""
    try:
        logger.info(f"Phone update request for user {current_user.id}")
        logger.info(f"Phone data received: {phone_data.phone}")
        
        auth_service = AuthService(db)
        updated_user = await auth_service.update_user_phone_permanently(
            current_user.id, 
            phone_data.phone
        )
        
        logger.info(f"Phone permanently set for user {current_user.id}")
        
        # ✅ Return complete user data
        return {
            "success": True,
            "message": "Phone number updated successfully",
            "user": {
                "id": str(updated_user["id"]),
                "name": updated_user["name"],
                "email": updated_user["email"],
                "phone": updated_user.get("phone"),
                "role": updated_user.get("role", "customer"),
                "is_active": updated_user.get("is_active", True),
                "provider": updated_user.get("provider", "local")
            }
        }
    except HTTPException as e:
        logger.error(f"Phone update HTTP error: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Phone update error: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update phone number: {str(e)}"
        )

@router.post("/forgot-password")
@rate_limit(max_requests=3, window_seconds=3600)
async def forgot_password(
    request: Request,
    forgot_request: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: DatabaseManager = Depends(get_database)
):
    """Send password reset OTP to email"""
    try:
        logger.info(f"Forgot password request for email: {forgot_request.email}")
        
        user = await db.find_one("users", {"email": forgot_request.email.lower().strip()})
        
        if not user:
            # Don't reveal if user exists
            return {
                "success": True,
                "message": "If an account exists, you will receive a reset code"
            }
        
        # Generate and send OTP
        otp_service = OTPService(db)
        otp = await otp_service.create_otp(forgot_request.email, "password_reset")
        
        background_tasks.add_task(
            email_service.send_password_reset_otp,
            forgot_request.email,
            user["name"],
            otp
        )
        
        logger.info(f"Password reset OTP sent to {forgot_request.email}")
        
        return {
            "success": True,
            "message": "If an account exists, you will receive a reset code"
        }
        
    except Exception as e:
        logger.error(f"Forgot password error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process password reset request"
        )


@router.post("/verify-reset-otp")
@rate_limit(max_requests=5, window_seconds=300)
async def verify_reset_otp(
    verify_data: VerifyPasswordResetOTP,
    db: DatabaseManager = Depends(get_database)
):
    """Verify password reset OTP"""
    try:
        otp_service = OTPService(db)
        
        is_valid = await otp_service.verify_otp(
            verify_data.email,
            verify_data.otp,
            "password_reset"
        )
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset code"
            )
        
        return {
            "success": True,
            "message": "Code verified successfully. You can now reset your password."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OTP verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify code"
        )


@router.post("/reset-password")
@rate_limit(max_requests=5, window_seconds=3600)
async def reset_password(
    request: Request,
    reset_request: ResetPasswordWithOTP,
    db: DatabaseManager = Depends(get_database)
):
    """Reset password with verified OTP"""
    try:
        # Verify OTP one more time
        otp_service = OTPService(db)
        is_valid = await otp_service.verify_otp(
            reset_request.email,
            reset_request.otp,
            "password_reset"
        )
        
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset code"
            )
        
        # Validate password
        if len(reset_request.new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters long"
            )
        
        # Update password
        from app.utils.auth import create_pasword_hash
        hashed_password = create_pasword_hash(reset_request.new_password)
        
        user = await db.find_one("users", {"email": reset_request.email.lower()})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        await db.update_one(
            "users",
            {"id": user["id"]},
            {"$set": {
                "hashed_password": hashed_password,
                "password_updated_at": datetime.utcnow()
            }}
        )
        
        logger.info(f"Password reset successful for {reset_request.email}")
        
        return {
            "success": True,
            "message": "Password reset successfully. You can now log in with your new password."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password reset error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset password"
        )


@router.post("/refresh")
@rate_limit(max_requests=20, window_seconds=300)
async def refresh_token(
    refresh_data: dict,
    db: DatabaseManager = Depends(get_database)
):
    """Refresh access token"""
    try:
        refresh_token = refresh_data.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Refresh token required"
            )
        
        # Decode refresh token
        try:
            payload = jwt.decode(
                refresh_token, 
                os.getenv('SECRET_KEY'), 
                algorithms=[os.getenv('ALGORITHM')]
            )
            user_id = payload.get("sub")
            jti = payload.get("jti")
            
        except JWTError as e:
            logger.error(f"JWT decode error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        # Verify refresh token exists and is valid
        stored_token = await db.find_one("refresh_tokens", {
            "user_id": user_id, 
            "jti": jti,
            "expire": {"$gt": datetime.utcnow()}
        })
        
        if not stored_token:
            logger.warning(f"Refresh token not found or expired for user {user_id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token not found or expired"
            )
        
        # Get user
        user = await db.find_one("users", {"id": user_id})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        # Create new access token
        access_token = create_access_token(
            data={'sub': str(user['id']), 'role': user['role']},
            exp_time=timedelta(minutes=int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', 30)))
        )
        
        logger.info(f"Access token refreshed for user {user['id']}")
        
        return {
            "access_token": access_token,
            "token_type": "bearer"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token refresh failed"
        )


@router.post("/logout")
@rate_limit(max_requests=10, window_seconds=60)
async def logout(
    db: DatabaseManager = Depends(get_database),
    current_user=Depends(get_current_user)
):
    """Logout user and revoke refresh tokens"""
    try:
        # Delete all refresh tokens for this user
        await db.delete_many('refresh_tokens', {'user_id': current_user.id})
        
        logger.info(f"User {current_user.id} logged out")
        
        return {
            "success": True,
            "message": "Logged out successfully"
        }
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed"
        )

@router.get("/profile")
async def get_me(
    current_user=Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
):
    """Get current user profile with complete data"""
    try:
        # ✅ Fetch complete user data from database
        user = await db.find_one("users", {"id": current_user.id})
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # ✅ Return complete user profile
        return {
            "id": str(user["id"]),
            "email": user["email"],
            "name": user["name"],
            "phone": user.get("phone") if not user.get("phone", "").startswith("TEMP_") else None,
            "role": user.get("role", "customer"),
            "is_active": user.get("is_active", True),
            "provider": user.get("provider", "local"),
            "email_verified": user.get("email_verified", False),
            "phone_verified": user.get("phone_verified", False),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get profile error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get profile"
        )

@router.put("/profile")
async def update_profile(
    user_info: UpdateUser, 
    db: DatabaseManager = Depends(get_database), 
    current_user=Depends(get_current_user)
):
    """Update user profile"""
    try:
        await db.update_one(
            "users", 
            {"id": current_user.id}, 
            {"$set": {"name": user_info.name}}
        )
        
        updated_user = await db.find_one("users", {"id": current_user.id})
        
        return {
            "success": True,
            "user": {
                "id": str(updated_user["id"]),
                "name": updated_user["name"],
                "email": updated_user["email"],
                "phone": updated_user.get("phone"),
                "role": updated_user.get("role", "customer"),
            }
        }
    except Exception as e:
        logger.error(f"Profile update error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile"
        )

@router.post("/push-token")
async def save_push_token(
    push_token_data: dict,
    current_user = Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
):
    """Save user's Expo push notification token"""
    try:
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.id
        
        from app.utils.get_time import get_ist_datetime_for_db
        current_time = get_ist_datetime_for_db()
        
        await db.update_one(
            "users",
            {"id": user_id},
            {
                "$set": {
                    "expo_push_token": push_token_data.get("push_token"),
                    "push_token_updated_at": current_time['ist']
                }
            }
        )
        
        logger.info(f"✅ Push token saved for user {user_id}")
        return {"message": "Push token saved successfully"}
        
    except Exception as e:
        logger.error(f"Error saving push token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save push token"
        )