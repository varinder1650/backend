from pydantic import BaseModel

class Category(BaseModel):
    name:str
    image: str = None

class CategoryResponse(Category):
    id: str
    
    class Config:
        populate_by_name = True