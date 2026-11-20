from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

MembershipStatus = Literal["active", "inactive"]
PreferredPosition = Literal["Goalkeeper", "Defender", "Midfielder", "Forward"]


class MemberContact(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    phone: str = Field(min_length=7, max_length=30, pattern=r"^[0-9+().\-\s]+$")
    address: str = Field(min_length=5, max_length=300)
    preferred_position: PreferredPosition

    @field_validator("phone")
    @classmethod
    def validate_phone_digits(cls, value: str) -> str:
        digit_count = sum(character.isdigit() for character in value)
        if not 7 <= digit_count <= 15:
            raise ValueError("Phone number must contain between 7 and 15 digits")
        return value


class MemberCreate(MemberContact):
    name: str = Field(min_length=2, max_length=120)


class MemberApplicationCreate(MemberContact):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    date_of_birth: date | None = None
    consent: bool

    @field_validator("consent")
    @classmethod
    def require_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Consent is required to submit an application")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Date of birth cannot be in the future")
        return value


MemberApplicationStatus = Literal["pending", "approving", "approved", "rejected"]


class MemberApplication(BaseModel):
    application_id: str
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    address: str
    preferred_position: PreferredPosition
    date_of_birth: date | None = None
    image_url: str | None = None
    status: MemberApplicationStatus
    submitted_at: datetime
    consented_at: datetime
    membership_id: str | None = None


class MemberApplicationSubmitted(BaseModel):
    application_id: str
    status: Literal["pending"]


class MemberApplicationSubmittedResponse(BaseModel):
    status: Literal["success"]
    data: MemberApplicationSubmitted


class MemberApplicationsResponse(BaseModel):
    status: Literal["success"]
    data: list[MemberApplication]
    total: int


class MemberApplicationResponse(BaseModel):
    status: Literal["success"]
    data: MemberApplication


class Member(BaseModel):
    membership_id: str
    name: str
    joined_at: datetime
    status: MembershipStatus
    preferred_position: PreferredPosition | None = None
    image_url: str | None = None


class MemberRegistration(BaseModel):
    year: int
    registered_at: datetime


class MemberDetail(Member):
    registrations: list[MemberRegistration] = Field(default_factory=list)


class MemberRegistrationCreate(BaseModel):
    year: int = Field(ge=1900)


class MemberResponse(BaseModel):
    status: Literal["success"]
    data: Member


class MemberDetailResponse(BaseModel):
    status: Literal["success"]
    data: MemberDetail


class MembersResponse(BaseModel):
    status: Literal["success"]
    data: list[Member]
    total: int
