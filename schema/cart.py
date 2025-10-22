# schema/cart.py
from pydantic import BaseModel, Field, validator
from typing import Optional
from app.utils.validators import quantity_validator, sanitize_text_validator

class CartRequest(BaseModel):
    productId: str = Field(..., min_length=1, max_length=100)
    quantity: int = Field(..., gt=0, le=100)
    
    # Validators
    _validate_quantity = validator('quantity', allow_reuse=True)(quantity_validator)
    
    @validator('productId')
    def validate_product_id(cls, v):
        if not v or not v.strip():
            raise ValueError('Product ID is required')
        return v.strip()

class UpdateCartItemRequest(BaseModel):
    itemId: str = Field(..., min_length=1, max_length=100)
    quantity: int = Field(..., gt=0, le=100)
    
    _validate_quantity = validator('quantity', allow_reuse=True)(quantity_validator)
    
    @validator('itemId')
    def validate_item_id(cls, v):
        if not v or not v.strip():
            raise ValueError('Item ID is required')
        return v.strip()

class CartItemResponse(BaseModel):
    id: str = Field(alias="_id")
    product: dict
    quantity: int
    available_stock: int
    stock_sufficient: bool
    added_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    class Config:
        populate_by_name = True

class CartResponse(BaseModel):
    items: list[CartItemResponse]
    total_items: int = 0
    total_price: float = 0.0
    
    @validator('total_items', always=True)
    def calculate_total_items(cls, v, values):
        items = values.get('items', [])
        return sum(item.quantity for item in items)
    
    @validator('total_price', always=True)
    def calculate_total_price(cls, v, values):
        items = values.get('items', [])
        return sum(
            item.product.get('price', 0) * item.quantity 
            for item in items
        )