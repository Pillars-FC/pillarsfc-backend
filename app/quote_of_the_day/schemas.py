from typing import Literal

from pydantic import BaseModel


class Quote(BaseModel):
    id: int
    quote: str
    author: str
    when: str


class QuoteResponse(BaseModel):
    status: Literal["success"]
    data: Quote
