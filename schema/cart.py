from pydantic import BaseModel, Field, validator, ConfigDict
from typing import Optional
from datetime import datetime

class CartRequest(BaseModel):
    productId: str = Field(..., description="Product ID to add to cart")
    quantity: int = Field(..., gt=0, description="Quantity to add")
    
    @validator('productId')
    def validate_product_id(cls, v):
        if not v or not v.strip():
            raise ValueError('Product ID cannot be empty')
        return v.strip()

class UpdateCartItemRequest(BaseModel):
    itemId: str = Field(..., description="Cart item ID to update")
    quantity: int = Field(..., gt=0, description="New quantity")
    
    @validator('itemId')
    def validate_item_id(cls, v):
        if not v or not v.strip():
            raise ValueError('Item ID cannot be empty')
        return v.strip()

class CartItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    id: str
    product: dict
    quantity: int
    added_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
class CartResponse(BaseModel):
    items: list[CartItemResponse] = []
    total_items: Optional[int] = None
    total_amount: Optional[float] = None