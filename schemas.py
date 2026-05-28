from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ConversationOut(BaseModel):
    id: int
    phone: str
    message: str
    category: str
    timestamp: datetime

    class Config:
        orm_mode = True


class OrderOut(BaseModel):
    id: int
    phone: str
    customer_name: Optional[str]
    item: str
    quantity: int
    status: str
    timestamp: datetime

    class Config:
        orm_mode = True
