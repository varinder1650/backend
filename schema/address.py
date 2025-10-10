from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime

class AddressBase(BaseModel):
    label: str = Field(..., min_length=1, max_length=50)
    street: str = Field(..., min_length=1, max_length=200)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=100)
    pincode: str = Field(..., min_length=6, max_length=6)
    landmark: Optional[str] = Field(None, max_length=200)
    mobile_number: str = Field(..., min_length=10, max_length=10, pattern=r'^\d{10}$')
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class AddressCreate(AddressBase):
    pass

class AddressUpdate(BaseModel):
    label: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    landmark: Optional[str] = None
    mobile_number: Optional[str] = Field(None, min_length=10, max_length=10, pattern=r'^\d{10}$')
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class AddressResponse(BaseModel):
    id: str = Field(..., alias="_id")
    user_id: str
    label: str = Field(..., min_length=1, max_length=50)
    street: str = Field(..., min_length=1, max_length=200)
    city: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=1, max_length=100)
    pincode: str = Field(..., min_length=6, max_length=6)
    landmark: Optional[str] = Field(None, max_length=200)
    mobile_number: Optional[str] = Field(None, min_length=10, max_length=10, pattern=r'^\d{10}$')
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_default: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}

class GeocodeRequest(BaseModel):
    address: str

class ReverseGeocodeRequest(BaseModel):
    latitude: float
    longitude: float

class AddressSearchRequest(BaseModel):
    query: str