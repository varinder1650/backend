# schema/user.py
from pydantic import BaseModel, Field, validator
from typing import Optional
from app.utils.validators import email_validator, phone_validator, sanitize_text_validator
import re

class UserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=6, max_length=128)
    phone: Optional[str] = Field(None, min_length=10, max_length=15)
    role: str = Field(default="customer")
    
    # Validators
    _validate_email = validator('email', allow_reuse=True)(email_validator)
    _validate_name = validator('name', allow_reuse=True)(sanitize_text_validator)
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        if len(v) > 128:
            raise ValueError('Password too long')
        return v
    
    @validator('phone')
    def validate_phone_optional(cls, v):
        if v:
            return phone_validator(v)
        return v
    
    @validator('role')
    def validate_role(cls, v):
        allowed_roles = ['customer', 'delivery_partner', 'admin']
        if v not in allowed_roles:
            raise ValueError(f'Role must be one of {allowed_roles}')
        return v

class UserLogin(BaseModel):
    email: str
    password: str
    
    _validate_email = validator('email', allow_reuse=True)(email_validator)

class PhoneUpdate(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)
    
    _validate_phone = validator('phone', allow_reuse=True)(phone_validator)

class UpdateUser(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    
    _validate_name = validator('name', allow_reuse=True)(sanitize_text_validator)

class UserinDB(BaseModel):
    id: str
    email: str
    role: str
    name: str
    is_active: bool = True

class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: Optional[str] = None
    role: str
    is_active: bool
    provider: str = "local"
    email_verified: bool = False
    phone_verified: bool = False

class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    requires_phone: bool = False
    user: Optional[UserResponse] = None

class GoogleLogin(BaseModel):
    user: dict
    
    @validator('user')
    def validate_user_data(cls, v):
        required_fields = ['email', 'name']
        for field in required_fields:
            if field not in v:
                raise ValueError(f'{field} is required in user data')
        
        # ✅ Simple email validation without InputValidator
        email = v['email']
        email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        
        if not email_pattern.match(email):
            raise ValueError('Invalid email in Google user data')
        
        return v


class VerifyEmailRequest(BaseModel):
    email: str
    otp: str = Field(..., min_length=6, max_length=6)
    
    _validate_email = validator('email', allow_reuse=True)(email_validator)
    
    @validator('otp')
    def validate_otp(cls, v):
        if not v.isdigit():
            raise ValueError('OTP must contain only digits')
        return v

class VerifyOTPRequest(BaseModel):
    email: str
    otp: str = Field(..., min_length=6, max_length=6)
    
    _validate_email = validator('email', allow_reuse=True)(email_validator)
    
    @validator('otp')
    def validate_otp(cls, v):
        if not v.isdigit():
            raise ValueError('OTP must contain only digits')
        return v

class ForgotPasswordRequest(BaseModel):
    email: str
    
    _validate_email = validator('email', allow_reuse=True)(email_validator)

class ResetPasswordRequest(BaseModel):
    email: str
    otp: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=6, max_length=128)
    
    _validate_email = validator('email', allow_reuse=True)(email_validator)
    
    @validator('otp')
    def validate_otp(cls, v):
        if not v.isdigit():
            raise ValueError('OTP must contain only digits')
        return v
    
    @validator('new_password')
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v