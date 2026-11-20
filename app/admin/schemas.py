from typing import Literal

from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class AdminSessionResponse(BaseModel):
    status: Literal["success"]
    username: str
