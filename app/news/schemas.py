from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NewsCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=180)
    category: str = Field(min_length=2, max_length=50)
    summary: str = Field(min_length=10, max_length=500)
    content: str = Field(min_length=20, max_length=30000)

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        return value.upper()


class NewsImage(BaseModel):
    url: str
    alt: str


class NewsCard(BaseModel):
    slug: str
    title: str
    category: str
    summary: str
    cover_image_url: str
    published_at: datetime


class NewsArticle(NewsCard):
    content: str
    gallery: list[NewsImage] = Field(default_factory=list)


class NewsListResponse(BaseModel):
    status: Literal["success"]
    data: list[NewsCard]
    total: int


class NewsArticleResponse(BaseModel):
    status: Literal["success"]
    data: NewsArticle


class NewsCreatedResponse(BaseModel):
    status: Literal["success"]
    data: NewsArticle
