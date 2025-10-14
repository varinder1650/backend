from pydantic_settings import BaseSettings
from typing import Optional
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    # Database settings
    mongo_url: str = os.getenv('MONGO_URI')
    db_name: str = os.getenv('DB_NAME')
    
    # JWT settings
    secret_key: str = os.getenv('SECRET_KEY')
    algorithm: str = os.getenv('ALGORITHM')
    access_token_expire_minutes: int = 1440
    
    # API settings
    api_version: str = "v1"
    
    # Ola Krutrim Maps API
    ola_krutrim_api_key: Optional[str] = None
    
    class Config:
        # Allow extra fields and read from environment variables
        extra = "allow"  # This allows extra fields
        env_file = ".env"
        env_file_encoding = 'utf-8'
        case_sensitive = False
        
        # Environment variable names (optional - pydantic auto-detects)
        fields = {
            'mongo_url': {'env': 'MONGO_URI'},
            'db_name': {'env': 'DB_NAME'},
            'secret_key': {'env': 'SECRET_KEY'},
            'algorithm': {'env': 'ALGORITHM'},
            'access_token_expire_minutes': {'env': 'ACCESS_TOKEN_EXPIRE_MINUTES'},
            'ola_krutrim_api_key': {'env': 'OLA_KRUTRIM_API_KEY'},
        }

# Create settings instance
settings = Settings()

# Also make the Ola Krutrim API key available directly
OLA_KRUTRIM_API_KEY = settings.ola_krutrim_api_key or os.getenv('OLA_KRUTRIM_API_KEY')