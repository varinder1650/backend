# app/utils/validators.py
"""
Input validation and sanitization utilities
Prevents injection attacks and malicious input
"""
import re
from typing import Any, Optional
import bleach
from pydantic import validator
import logging
import os

logger = logging.getLogger(__name__)

class InputValidator:
    """Comprehensive input validation"""
    
    # Regex patterns
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    PHONE_PATTERN = re.compile(r'^\+?1?\d{9,15}$')
    ALPHA_NUMERIC = re.compile(r'^[a-zA-Z0-9]+$')
    SAFE_STRING = re.compile(r'^[a-zA-Z0-9\s\-_.]+$')
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format"""
        if not email or len(email) > 320:
            return False
        return bool(InputValidator.EMAIL_PATTERN.match(email))
    
    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Validate phone number"""
        if not phone:
            return False
        # Remove spaces and dashes
        clean_phone = phone.replace(' ', '').replace('-', '')
        return bool(InputValidator.PHONE_PATTERN.match(clean_phone))
    
    @staticmethod
    def sanitize_string(text: str, max_length: int = 1000) -> str:
        """
        Sanitize string input - remove HTML, scripts, etc.
        Prevents XSS attacks
        """
        if not text:
            return ""
        
        # Truncate to max length
        text = text[:max_length]
        
        # Remove HTML tags and scripts
        clean_text = bleach.clean(
            text,
            tags=[],  # No tags allowed
            attributes={},
            strip=True
        )
        
        return clean_text.strip()
    
    @staticmethod
    def sanitize_html(html: str, allowed_tags: list = None) -> str:
        """
        Sanitize HTML - allow only safe tags
        For user-generated content like reviews
        """
        if not html:
            return ""
        
        if allowed_tags is None:
            allowed_tags = ['p', 'br', 'strong', 'em', 'u', 'a']
        
        allowed_attributes = {
            'a': ['href', 'title']
        }
        
        clean_html = bleach.clean(
            html,
            tags=allowed_tags,
            attributes=allowed_attributes,
            strip=True
        )
        
        return clean_html
    
    @staticmethod
    def sanitize_search_query(query: str) -> str:
        """
        Sanitize search queries to prevent NoSQL injection
        """
        if not query:
            return ""
        
        # Remove special MongoDB operators
        dangerous_patterns = [
            '$where', '$regex', '$ne', '$gt', '$gte', 
            '$lt', '$lte', '$in', '$nin', '$exists'
        ]
        
        sanitized = query
        for pattern in dangerous_patterns:
            sanitized = sanitized.replace(pattern, '')
        
        # Escape regex special characters
        sanitized = re.escape(sanitized)
        
        return sanitized[:200]  # Max 200 chars
    
    @staticmethod
    def validate_quantity(quantity: int, max_quantity: int = 100) -> bool:
        """Validate product quantity"""
        return 1 <= quantity <= max_quantity
    
    @staticmethod
    def validate_price(price: float) -> bool:
        """Validate price value"""
        return 0 < price < 1000000  # Max price 1 million
    
    @staticmethod
    def validate_object_id(obj_id: str) -> bool:
        """Validate MongoDB ObjectId format"""
        if not obj_id or len(obj_id) != 24:
            return False
        return bool(re.match(r'^[a-f0-9]{24}$', obj_id))
    
    @staticmethod
    def validate_custom_id(custom_id: str, pattern: str = None) -> bool:
        """Validate custom ID format (e.g., ORD20250102ABC123)"""
        if not custom_id:
            return False
        
        if pattern:
            return bool(re.match(pattern, custom_id))
        
        # Default: alphanumeric with hyphens
        return bool(re.match(r'^[A-Z0-9\-]+$', custom_id))
    
    @staticmethod
    def validate_file_size(file_size: int, max_size: int = 5242880) -> bool:
        """Validate file size (default 5MB)"""
        return 0 < file_size <= max_size
    
    @staticmethod
    def validate_file_type(mime_type: str, allowed_types: list = None) -> bool:
        """Validate file MIME type"""
        if allowed_types is None:
            allowed_types = ['image/jpeg', 'image/png', 'image/webp']
        
        return mime_type in allowed_types

# Pydantic validators for schemas
def phone_validator(v: str) -> str:
    """Pydantic validator for phone numbers"""
    if not v:
        raise ValueError('Phone number is required')
    
    # Clean phone number
    clean_phone = v.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    
    if not InputValidator.validate_phone(clean_phone):
        raise ValueError('Invalid phone number format')
    
    return clean_phone

def email_validator(v: str) -> str:
    """Pydantic validator for emails"""
    if not v:
        raise ValueError('Email is required')
    
    v = v.lower().strip()
    
    if not InputValidator.validate_email(v):
        raise ValueError('Invalid email format')
    
    return v

def sanitize_text_validator(v: str) -> str:
    """Pydantic validator for text fields"""
    if not v:
        return ""
    
    return InputValidator.sanitize_string(v)

def quantity_validator(v: int) -> int:
    """Pydantic validator for quantity"""
    max_qty = int(os.getenv('MAX_CART_ITEMS_PER_PRODUCT', 100))
    
    if not InputValidator.validate_quantity(v, max_qty):
        raise ValueError(f'Quantity must be between 1 and {max_qty}')
    
    return v