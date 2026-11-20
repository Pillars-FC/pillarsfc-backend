from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr


class EventSubscriptionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr


class EventSubscriptionResponse(BaseModel):
    status: Literal["success"]
    message: str
