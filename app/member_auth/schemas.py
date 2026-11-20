from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class MemberAccountRegistration(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class MemberLoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class MemberEmailVerification(BaseModel):
    token: str = Field(min_length=32, max_length=200)


class MemberAccountMessage(BaseModel):
    status: Literal["success"]
    message: str


class MemberSessionResponse(BaseModel):
    status: Literal["success"]
    membership_id: str
    name: str
