from typing import List, Literal, Optional, Union
from pydantic import BaseModel, Field,ConfigDict
from datetime import datetime
from bson import ObjectId
from schema.products import ProductResponse

class DeliveryAddress(BaseModel):
    name: Optional[str] = None
    street: str
    city: str
    state: str
    pincode: str
    mobile_number: str
    latitude: Optional[float] = 0.0
    longitude: Optional[float] = 0.0

    class Config:
        extra = "ignore"

class ProductOrderItem(BaseModel):
    type: Literal["product"]
    product: str
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)

class PrintServiceData(BaseModel):
    print_type: Optional[str] = "document"
    pages: int = 1
    file_urls: Optional[List[str]] = None
    document_urls: Optional[List[str]] = None
    photo_urls: Optional[List[str]] = None
    copies: int = Field(gt=0)
    color: bool
    paper_size: str
    notes: Optional[str] = ""
    price: float = Field(default=0, ge=0)

    class Config:
        extra = "ignore"

class PrintOrderItem(BaseModel):
    type: Literal["printout"]
    service_data: PrintServiceData

class Dimensions(BaseModel):
    length: Optional[str] = None
    width: Optional[str] = None
    height: Optional[str] = None

    class Config:
        extra = "ignore"

class PorterServiceData(BaseModel):
    pickup_address: DeliveryAddress
    delivery_address: DeliveryAddress
    dimensions: Optional[Dimensions] = None
    weight_category: int
    estimated_distance: float
    estimated_cost: float
    notes: Optional[str] = ""
    is_urgent: bool
    phone: Optional[str] = None
    recipient_name: Optional[str] = None

    class Config:
        extra = "ignore"

class PorterOrderItem(BaseModel):
    type: Literal["porter"]
    service_data: PorterServiceData

class OrderItemResponse(BaseModel):
    product: str
    quantity: int
    price: float

class OrderItemEnhancedResponse(BaseModel):
    product: str
    quantity: int
    price: float
    product_name: Optional[str] = None  # Add product name field
    product_image: Optional[List] = None  # Add product images field

class StatusChange(BaseModel):
    status: str
    changed_at: datetime = Field(default_factory=datetime.utcnow)
    changed_by: str


class UserInfo(BaseModel):
    name: str
    email: str
    phone: str

OrderItem = Union[
    ProductOrderItem,
    PrintOrderItem,
    PorterOrderItem
]

class OrderBase(BaseModel):
    user: Optional[str] = None
    items: List[OrderItem] = Field(..., min_items=1)
    delivery_address: DeliveryAddress
    payment_method: Literal["cod","online"] = "cod"
    delivery: float = Field(default=0, ge=0)
    app_fee: float = Field(default=0, ge=0)
    total_amount: float = Field(gt=0)
    promo_code: Optional[str] = None
    promo_discount: float = Field(default=0, ge=0)
    order_status: str = "preparing"
    status_change_history: List[StatusChange] = []
    delivery_partner: Optional[str] = None
    order_type: str = "mixed"


class OrderCreate(OrderBase):
    tip_amount: Optional[float] = Field(0, ge=0, le=500)
    payment_status: Literal["pending", "paid", "failed"] = "pending"

class OrderUpdate(BaseModel):
    order_status: Optional[str] = None
    payment_status: Optional[str] = None
    status_change_history: Optional[List[StatusChange]] = None
    delivery_partner: Optional[str] = None

class OrderInDB(OrderBase):
    pass

class OrderResponse(BaseModel):
    id: str
    user: str
    user_info: Optional[UserInfo] = None
    items: List[OrderItemResponse]   # product is just ID
    delivery_address: DeliveryAddress
    payment_method: str = "cod"
    subtotal: float
    tax: float = 0
    delivery_charge: float = 0
    app_fee: float = 0
    total_amount: float
    payment_status: str = "pending"
    order_status: str = "pending"
    status_change_history: List[StatusChange] = []
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    delivery_partner: Optional[str] = None
    delivery_partner_info: Optional[UserInfo] = None
    tip_amount: Optional[float] = 0
    payment_method: Optional[str] = "cod"
    payment_status: Optional[str] = "pending"
    payment_transaction_id: Optional[str] = None


class OrderResponseEnhanced(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    user: str
    user_info: Optional[UserInfo] = None
    items: List[OrderItemEnhancedResponse]  # Now includes product_name
    delivery_address: DeliveryAddress
    payment_method: str = "cod"
    subtotal: float
    tax: float = 0
    delivery_charge: float = 0
    app_fee: float = 0
    total_amount: float
    payment_status: str = "pending"
    order_status: str = "pending"
    status_change_history: List[StatusChange] = []
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    delivery_partner: Optional[str] = None
    delivery_partner_info: Optional[UserInfo] = None

class OrderRating(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    review: str = Field(default="", max_length=500)
    order_id: str

class DraftOrderRequest(BaseModel):
    items: list
    delivery_address: DeliveryAddress
    tip_amount: float = 0
    promo_code: Optional[str] = None

class DraftOrderResponse(BaseModel):
    draft_order_id: str
    signature: str
    total_amount: float
    subtotal: float
    delivery_fee: float
    app_fee: float
    tip_amount: float
    discount: float
    expires_at: str

class ConfirmOrderRequest(BaseModel):
    draft_order_id: str
    signature: str
    payment_method: str