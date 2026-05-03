from typing import List, Optional, Union
from pydantic import BaseModel, Field

class Image(BaseModel):
    url: str
    thumbnail: str
    public_id: str
    index: int
    is_primary: bool

class CategoryRef(BaseModel):
    id: str = Field(alias="_id")
    name: str

class BrandRef(BaseModel):
    id: str = Field(alias="_id")
    name: str

class PrintableArea(BaseModel):
    x: float = Field(default=0.25, ge=0.0, le=1.0)
    y: float = Field(default=0.20, ge=0.0, le=1.0)
    width: float = Field(default=0.50, ge=0.0, le=1.0)
    height: float = Field(default=0.60, ge=0.0, le=1.0)

class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    price: float = Field(..., gt=0)
    images: Optional[List[Image]] = Field(default_factory=list)
    category: str
    brand: str
    stock: int = Field(default=0, ge=0)
    is_active: bool = True
    keywords: Optional[List[str]] = Field(default_factory=list)
    mockup_template_url: Optional[str] = None
    printable_area: Optional[PrintableArea] = None

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, min_length=1)
    price: Optional[float] = Field(None, gt=0)
    images: Optional[List[Image]] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    stock: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    keywords: Optional[List[str]] = None
    mockup_template_url: Optional[str] = None
    printable_area: Optional[PrintableArea] = None

class ProductInDB(ProductBase):
    pass

class ProductResponse(ProductBase):
    category: Union[CategoryRef, dict]
    brand: Union[BrandRef, dict]