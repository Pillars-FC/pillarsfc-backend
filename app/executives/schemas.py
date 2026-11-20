from typing import Literal

from pydantic import BaseModel


class Executive(BaseModel):
    id: int
    name: str
    position: str
    image: str


class ExecutivesResponse(BaseModel):
    status: Literal["success"]
    data: list[Executive]
