from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ContactSubmission(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    message: str = Field(min_length=1, max_length=5000)


class ContactResponse(BaseModel):
    status: Literal["success"]
    message: str
