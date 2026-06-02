from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class ConversationOut(BaseModel):
    id: int
    phone: str
    message: str
    category: str
    timestamp: datetime
    channel: Optional[str] = "whatsapp"

    model_config = ConfigDict(from_attributes=True)


class OrderOut(BaseModel):
    id: int
    phone: str
    customer_name: Optional[str]
    item: str
    quantity: int
    status: str
    timestamp: datetime
    channel: Optional[str] = "whatsapp"

    model_config = ConfigDict(from_attributes=True)


class BusinessProfileOut(BaseModel):
    id: int
    user_id: int
    business_name: str
    description: Optional[str]
    category: Optional[str]
    address: Optional[str]
    currency: str = "NGN"
    is_public: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductOut(BaseModel):
    id: int
    business_id: int
    name: str
    description: Optional[str]
    price: Optional[float]
    currency: str = "NGN"
    is_available: bool = True

    model_config = ConfigDict(from_attributes=True)


class PipelineLogOut(BaseModel):
    id: int
    message: str
    category: Optional[str]
    final_reply: Optional[str]
    success: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
