# from typing import Optional
# from pydantic import BaseModel, EmailStr, Field

# class TokenData(BaseModel):
#     user_id: str

# class User(BaseModel):
#     name : str = Field(...,min_length=1,max_length=100)
#     email: EmailStr
#     phone: Optional[str] = Field(None, min_length=10, max_length=15)  # Made optional
#     address: Optional[str] = None
#     city: Optional[str] = None
#     state: Optional[str] = None
#     pincode: Optional[str] = None
#     role: str = Field(default="customer")
#     is_active: bool = True

# class UserCreate(BaseModel):
#     name: str = Field(..., min_length=1, max_length=100)
#     email: EmailStr
#     password: str = Field(..., min_length=6)
#     phone: Optional[str] = Field(None, min_length=10, max_length=15)  # Made optional
#     role: str = Field(default="customer")

# class UserResponse(User):
#     id: str
#     provider: str

# class TokenOut(BaseModel):
#     access_token: str
#     refresh_token: str
#     requires_phone: bool
#     token_type: str = "bearer"
#     user: Optional[UserResponse] = None

# class UserLogin(BaseModel):
#     email: EmailStr
#     password: str

# class GoogleLogin(BaseModel):
#     googleToken: str
#     user: dict  # This should contain: email, name, googleId, photo (optional)

# class GoogleLoginResponse(BaseModel):
#     email: EmailStr
#     googleId: str
#     name: str
#     photo: Optional[str] = None

# class UserinDB(BaseModel):
#     id: str
#     name: str
#     email: EmailStr
#     role: str
#     is_active: bool

# class TokenResponse(BaseModel):
#     access_token: str
#     token_type: str = "bearer"
#     user: Optional[UserResponse] = None

# class GoogleTokenResponse(BaseModel):
#     access_token: str
#     token_type: str = "bearer"
#     user: Optional[GoogleLoginResponse] = None

# # Phone update model
# class PhoneUpdate(BaseModel):
#     phone: str = Field(..., min_length=10, max_length=15)

# # Refresh token model
# class RefreshTokenRequest(BaseModel):
#     refresh_token: str

# # Forgot password model
# class ForgotPasswordRequest(BaseModel):
#     email: EmailStr

# # Reset password model
# class ResetPasswordRequest(BaseModel):
#     token: str
#     new_password: str = Field(..., min_length=6)

# class UpdateUser(BaseModel):
#     name: str


from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    role: Optional[str] = "customer"

class UserLogin(BaseModel):
    email: EmailStr
    password: str

# class GoogleLogin(BaseModel):
#     googleToken: str
#     user: dict

class GoogleLogin(BaseModel):
    googleToken: str
    user: dict
    
    class Config:
        # Allow any extra fields
        extra = "allow"

class PhoneUpdate(BaseModel):
    phone: str

class VerifyEmailRequest(BaseModel):
    email: EmailStr
    otp: str

class ResendOTPRequest(BaseModel):
    email: EmailStr

class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class VerifyPasswordResetOTP(BaseModel):
    email: EmailStr
    otp: str

class ResetPasswordWithOTP(BaseModel):
    email: EmailStr
    otp: str
    new_password: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class UpdateUser(BaseModel):
    name: str

class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: Optional[str] = None
    role: str = "customer"
    is_active: bool = True
    provider: str = "local"

class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    requires_phone: bool = False
    user: Optional[UserResponse] = None

class UserinDB(BaseModel):
    id: str
    email: str
    role: str
    name: str
    is_active: bool = True